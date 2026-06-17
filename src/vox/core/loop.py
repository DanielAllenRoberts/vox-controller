"""The Vox daemon: a small state machine over wake phrases.

IDLE waits (via the configured wake backend) for an activation phrase. The control
label enters CONTROL mode (Dragon-style: transcribe + execute each command until a
sleep phrase). The assistant label enters ASSISTANT mode (one-shot LLM request).
See docs/plan/modes.md.
"""

import os
import sys

from dotenv import load_dotenv

from vox import actions, assistant, executor, sounds
from vox.audio import MicStream, capture_utterance
from vox.config import CONFIG
from vox.io.console import ConsoleOutput
from vox.stats import Timer, process_stats
from vox.stt.whisper_transcriber import WhisperTranscriber
from vox.wakeword.backends import make_backend, normalize


class _Quit(Exception):
    """Raised to exit the whole program by voice."""


class _Restart(Exception):
    """Raised to re-exec the program (pick up code changes) by voice."""


def _is_quit(text: str, cfg) -> bool:
    t = normalize(text)
    return any(p in t for p in cfg.quit_phrases)


def _is_restart(text: str, cfg) -> bool:
    t = normalize(text)
    return any(p in t for p in cfg.restart_phrases)


def _is_sleep(text: str, cfg) -> bool:
    t = normalize(text)
    return any(p in t for p in cfg.sleep_phrases)


def _is_assistant(text: str, cfg) -> bool:
    t = normalize(text)
    return any(p in t for p in cfg.assistant_phrases)


def _is_control(text: str, cfg) -> bool:
    t = normalize(text)
    return any(p in t for p in cfg.control_phrases)


def _is_dictate(text: str, cfg) -> bool:
    t = normalize(text)
    return any(p in t for p in cfg.dictate_phrases)


def _transcribe(transcriber, audio, cfg, out, hotwords: str = "") -> str:
    dur = len(audio) / cfg.sample_rate
    with Timer() as stt:
        text = transcriber.transcribe(audio, hotwords=hotwords)
    cpu, mem = process_stats()
    out.emit(f"  ⏱  audio {dur:.1f}s · stt {stt.seconds:.2f}s "
             f"(rtf {stt.seconds / max(dur, 0.01):.2f}) · cpu {cpu:.0f}% · mem {mem:.0f}MB")
    return text


def _control_mode(frames, cfg, transcriber, out) -> None:
    out.emit(f'● CONTROL MODE — e.g. "open Safari" or "go to GitHub". Say "{cfg.sleep_spoken}" to stop.')
    while True:
        audio = capture_utterance(frames, cfg)
        if audio is None:
            continue  # stay in control mode — only the sleep phrase (or Ctrl+C) exits
        text = _transcribe(transcriber, audio, cfg, out, hotwords=cfg.command_hotwords)
        if not text:
            continue
        if _is_quit(text, cfg):
            raise _Quit
        if _is_restart(text, cfg):
            raise _Restart
        if _is_sleep(text, cfg):
            sounds.play(cfg.sound_sleep)
            out.emit("○ Sleeping.")
            return None
        if _is_assistant(text, cfg):
            out.emit("→ switching to assistant…")
            return "assistant"
        if _is_dictate(text, cfg):
            out.emit("→ entering dictation…")
            return "dictation"
        out.emit(f"  you: {text!r}")
        if actions.parse(text) is not None:
            out.emit(f"  → {actions.handle(text)}")
        else:  # uncertain → hand to the executor (fast model w/ Vox's tools): it acts, or replies
            acted, msg = executor.execute(text)
            if acted:
                sounds.play(cfg.sound_oneshot)  # quiet "did it" cue — action-first (#13)
                out.emit(f"  ⚡ {msg}")
            else:
                out.emit(f"  🔊 {msg}")


def _assistant_mode(frames, cfg, transcriber, out, return_to=None):
    out.emit('● ASSISTANT MODE — chat with me. Say "stand down" when done.')
    history = []
    expecting_answer = False  # set when the model tags its reply [OPEN] → wait patiently for you
    while True:
        timeout = cfg.assistant_open_timeout_seconds if expecting_answer else cfg.listen_timeout_seconds
        audio = capture_utterance(frames, cfg,
                                  silence_seconds=cfg.assistant_silence_seconds,
                                  listen_timeout=timeout)
        if audio is None:
            out.emit("  (no reply — back to idle)")
            return return_to
        text = _transcribe(transcriber, audio, cfg, out)
        if not text:
            continue
        if _is_quit(text, cfg):
            raise _Quit
        if _is_restart(text, cfg):
            raise _Restart
        if _is_sleep(text, cfg):
            sounds.play(cfg.sound_sleep)
            out.emit("○ Sleeping.")
            return None
        if _is_control(text, cfg):
            out.emit("→ switching to control…")
            return "control"
        sounds.play(cfg.sound_send)  # captured → "sending to the AI"
        out.emit(f"  you: {text!r}")
        reply, expecting_answer = assistant.respond_turn(text, history)  # model tags [OPEN]/[DONE]
        history += [("user", text), ("assistant", reply)]
        out.emit(f"  🔊 {reply}" + ("  (…your turn)" if expecting_answer else ""))


def _dictation_mode(frames, cfg, transcriber, out, return_to=None):
    sounds.play(cfg.sound_dictate_start)
    out.emit('✎ DICTATION — click where you want text, then speak. Say "stop typing" to stop.')
    while True:
        audio = capture_utterance(frames, cfg, silence_seconds=cfg.assistant_silence_seconds)
        if audio is None:  # long pause
            if not cfg.dictation_exit_on_silence:
                continue  # setting: stay in dictation until an explicit "stop typing"
            sounds.play(cfg.sound_dictate_stop)
            out.emit("✎ Stopped typing.")
            return return_to
        text = _transcribe(transcriber, audio, cfg, out)
        if not text:
            continue
        if _is_quit(text, cfg):
            raise _Quit
        if _is_restart(text, cfg):
            raise _Restart
        if "stop typing" in normalize(text) or _is_sleep(text, cfg):
            sounds.play(cfg.sound_dictate_stop)
            out.emit("✎ Stopped typing.")
            return return_to
        actions.dictate(text)
        out.emit(f"  typed: {text!r}")


def main() -> None:
    cfg = CONFIG
    load_dotenv()  # load ANTHROPIC_API_KEY etc. from .env
    out = ConsoleOutput(cfg.log_file)

    out.emit(f"Loading {cfg.assistant_name}… (first run downloads models)")
    with Timer() as load:
        transcriber = WhisperTranscriber(cfg.whisper_model, cfg.whisper_compute_type)
        wake = make_backend(cfg, transcriber)
    out.emit(f"Models loaded in {load.seconds:.1f}s.  [wake backend: {cfg.wake_backend}]")

    idle_msg = f"Idle. {wake.prompt} (Ctrl+C to quit)"
    out.emit(idle_msg)
    try:
        with MicStream(cfg.sample_rate, cfg.frame_samples, cfg.input_device) as mic:
            frames = mic.frames()
            while True:
                label = wake.listen(frames)
                if label == "quit":
                    raise _Quit
                if label == "restart":
                    raise _Restart
                if label.startswith("do:"):  # one-shot command from idle ("Vox, open Safari")
                    cmd = label[3:]
                    sounds.play(cfg.sound_oneshot)  # quick "got it" cue
                    out.emit(f"⚡ {cmd!r} → {actions.handle(cmd)}")
                    out.emit(idle_msg)
                    continue
                # A mode may return a follow-on label to chain into the other mode
                # without dropping to idle. If the assistant was reached *from* control,
                # it returns to control when done (instead of idling).
                from_control = False
                while label in ("control", "assistant", "dictation"):
                    if label == "control":
                        sounds.play(cfg.sound_control)
                        label = _control_mode(frames, cfg, transcriber, out)
                        from_control = label in ("assistant", "dictation")
                    elif label == "assistant":
                        sounds.play(cfg.sound_assistant)
                        label = _assistant_mode(frames, cfg, transcriber, out,
                                                return_to="control" if from_control else None)
                        from_control = False
                    else:  # dictation
                        label = _dictation_mode(frames, cfg, transcriber, out,
                                                return_to="control" if from_control else None)
                        from_control = False
                out.emit(idle_msg)
    except (KeyboardInterrupt, _Quit):
        sounds.play(cfg.sound_sleep)
        out.emit("\n👋 Quitting Vox.")
    except _Restart:
        out.emit("\n↻ Restarting Vox…")
        os.execv(sys.executable, [sys.executable, "-m", "vox"])


if __name__ == "__main__":
    main()
