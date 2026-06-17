"""The Vox daemon: a small state machine over wake phrases.

IDLE waits (via the configured wake backend) for an activation phrase. The control
label enters CONTROL mode (Dragon-style: transcribe + execute each command until a
sleep phrase). The assistant label enters ASSISTANT mode (one-shot LLM request).
See docs/plan/modes.md.
"""

from vox import actions, assistant, sounds
from vox.audio import MicStream, capture_utterance
from vox.config import CONFIG
from vox.io.console import ConsoleOutput
from vox.stats import Timer, process_stats
from vox.stt.whisper_transcriber import WhisperTranscriber
from vox.wakeword.backends import make_backend, normalize


class _Quit(Exception):
    """Raised to exit the whole program by voice."""


def _is_quit(text: str, cfg) -> bool:
    t = normalize(text)
    return any(p in t for p in cfg.quit_phrases)


def _is_sleep(text: str, cfg) -> bool:
    t = normalize(text)
    return any(p in t for p in cfg.sleep_phrases)


def _is_assistant(text: str, cfg) -> bool:
    t = normalize(text)
    return any(p in t for p in cfg.assistant_phrases)


def _is_control(text: str, cfg) -> bool:
    t = normalize(text)
    return any(p in t for p in cfg.control_phrases)


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
        if _is_sleep(text, cfg):
            sounds.play(cfg.sound_sleep)
            out.emit("○ Sleeping.")
            return None
        if _is_assistant(text, cfg):
            out.emit("→ switching to assistant…")
            return "assistant"
        out.emit(f"  you: {text!r}")
        out.emit(f"  → {actions.handle(text)}")


def _assistant_mode(frames, cfg, transcriber, out):
    out.emit("● ASSISTANT MODE — ask something…")
    audio = capture_utterance(frames, cfg, silence_seconds=cfg.assistant_silence_seconds)
    if audio is None:
        sounds.play(cfg.sound_sleep)
        out.emit("  (heard nothing — back to idle)")
        return None
    text = _transcribe(transcriber, audio, cfg, out)
    if not text:
        sounds.play(cfg.sound_sleep)
        out.emit("  (heard nothing — back to idle)")
        return None
    if _is_quit(text, cfg):
        raise _Quit
    if _is_sleep(text, cfg):
        sounds.play(cfg.sound_sleep)
        out.emit("○ Sleeping.")
        return None
    if _is_control(text, cfg):
        out.emit("→ switching to control…")
        return "control"
    sounds.play(cfg.sound_send)  # prompt captured → "sending to the AI"
    out.emit(f"  you: {text!r}")
    out.emit(f"  → {assistant.respond(text)}")
    return None


def main() -> None:
    cfg = CONFIG
    out = ConsoleOutput()

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
                # A mode may return a follow-on label to chain directly into the other
                # mode (e.g. "Hey Vox" while in control) without dropping to idle.
                while label in ("control", "assistant"):
                    if label == "control":
                        sounds.play(cfg.sound_control)
                        label = _control_mode(frames, cfg, transcriber, out)
                    else:
                        sounds.play(cfg.sound_assistant)
                        label = _assistant_mode(frames, cfg, transcriber, out)
                out.emit(idle_msg)
    except (KeyboardInterrupt, _Quit):
        sounds.play(cfg.sound_sleep)
        out.emit("\n👋 Quitting Vox.")


if __name__ == "__main__":
    main()
