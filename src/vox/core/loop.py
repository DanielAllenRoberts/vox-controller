"""The Vox daemon: a small state machine over wake phrases.

IDLE waits (via the configured wake backend) for an activation phrase. The control
label enters CONTROL mode (Dragon-style: transcribe + execute each command until a
sleep phrase). The assistant label enters ASSISTANT mode (one-shot LLM request).
See docs/plan/modes.md.
"""

import os
import subprocess
import sys
import threading
import webbrowser

from dotenv import load_dotenv

from vox import actions, assistant, dispatch, executor, sounds, tts
from vox.audio import capture_utterance, open_mic_stream
from vox.config import CONFIG
from vox.io.console import ConsoleOutput
from vox.stats import Timer, process_stats
from vox.stt.whisper_transcriber import WhisperTranscriber
from vox.wakeword.backends import make_backend, normalize, phrase_match


def _record_turn(role: str, text: str, *, brain=None, kind=None) -> None:
    """Publish one conversation turn to the live dashboard feed (idea #43). Fully guarded:
    the web package is an additive convenience, so a missing/broken vox.web.conversation must
    NEVER break the voice daemon. Ephemeral by design — record_turn writes nothing to disk."""
    if not text or not str(text).strip():
        return
    try:
        from vox.web import conversation
        conversation.record_turn(role, text, brain=brain, kind=kind)
    except Exception:
        pass


def _setting(key: str, fallback):
    """Read a runtime override from the dashboard's settings_store, else fall back to Config.
    Fully guarded (mirrors assistant._setting): if vox.web.settings_store is missing or errors,
    return the fallback so the daemon behaves exactly as before. None from the store means
    'unset' → fallback. This is what lets dashboard toggles take effect on the NEXT relevant
    action without a restart."""
    try:
        from vox.web import settings_store
        val = settings_store.get(key)
        return fallback if val is None else val
    except Exception:
        return fallback


class _Quit(Exception):
    """Raised to exit the whole program by voice."""


class _Restart(Exception):
    """Raised to re-exec the program (pick up code changes) by voice."""


def _start_dashboard(cfg, out) -> None:
    """Launch the embedded dashboard web server in a background daemon thread. Fully guarded:
    a missing or broken vox.web package must NEVER stop the voice daemon (the dashboard is an
    additive convenience). Only runs when cfg.dashboard_enabled."""
    if not getattr(cfg, "dashboard_enabled", False):
        return
    try:
        from vox.web import server
        server.start_in_background(cfg)
        out.emit(f"  [dashboard] http://{cfg.dashboard_host}:{cfg.dashboard_port}  (say \"open dashboard\")")
    except Exception as exc:  # web package missing/broken → log and carry on
        if cfg.debug:
            out.emit(f"  [dashboard] not started: {exc}")


def _start_scheduler(cfg, out) -> None:
    """Start the background scheduler thread (timers / alarms / reminders, idea #16). Fully
    guarded, like _start_dashboard: a missing/broken vox.scheduler must NEVER stop the voice
    daemon. Only runs when cfg.scheduler_enabled."""
    if not getattr(cfg, "scheduler_enabled", True):
        return
    try:
        from vox import scheduler
        if scheduler.start() is not None:
            out.emit("  [scheduler] timers / alarms / reminders armed")
    except Exception as exc:  # scheduler module missing/broken → log and carry on
        if cfg.debug:
            out.emit(f"  [scheduler] not started: {exc}")


def _open_dashboard(cfg, out) -> None:
    """Open the dashboard in its own window (Arc opens external localhost links as a standalone
    'Little Arc' window), reusing an already-open dashboard window/tab so 'open dashboard' never
    stacks. Closing is non-disruptive — actions.close_dashboard presses the window's close button
    via accessibility (no Space-switch). Guarded so a failure can't break the wake loop."""
    url = f"http://{cfg.dashboard_host}:{cfg.dashboard_port}"
    try:
        if actions._focus_dashboard(url):  # reuse the existing dashboard window/tab
            out.emit("🖥  Dashboard already open — focused it.")
            return
        subprocess.run(["open", url], capture_output=True, text=True)  # own window (Arc → Little Arc)
        out.emit(f"🖥  Opening dashboard → {url}")
    except Exception:
        try:  # last-resort fallback to the system default browser
            webbrowser.open(url)
            out.emit(f"🖥  Opening dashboard → {url}")
        except Exception as exc:
            out.emit(f"  [dashboard] couldn't open browser: {exc}")


def _is_quit(text: str, cfg) -> bool:
    return phrase_match(normalize(text), cfg.quit_phrases)


def _is_restart(text: str, cfg) -> bool:
    return phrase_match(normalize(text), cfg.restart_phrases)


def _is_open_dashboard(text: str, cfg) -> bool:
    return phrase_match(normalize(text), cfg.open_dashboard_phrases)


def _is_close_dashboard(text: str, cfg) -> bool:
    return phrase_match(normalize(text), getattr(cfg, "close_dashboard_phrases", ()))


def _is_sleep(text: str, cfg) -> bool:
    t = normalize(text)
    return any(p in t for p in cfg.sleep_phrases)


def _is_abort(text: str, cfg) -> bool:
    t = normalize(text)
    return any(p in t for p in cfg.abort_phrases)


def _is_assistant(text: str, cfg) -> bool:
    t = normalize(text)
    return any(p in t for p in cfg.assistant_phrases)


def _is_control(text: str, cfg) -> bool:
    t = normalize(text)
    return any(p in t for p in cfg.control_phrases)


def _is_dictate(text: str, cfg) -> bool:
    t = normalize(text)
    return any(p in t for p in cfg.dictate_phrases)


_NOISE_WORDS = {"and", "uh", "um", "ah", "oh", "so", "the", "a", "i", "yeah", "yep", "no",
                "okay", "ok", "hmm", "mm", "mhm", "like", "you", "well", "but", "or", "is", "it"}


def _looks_like_noise(text: str) -> bool:
    """Short fragments / fillers — almost always background (a video, chatter). Don't escalate
    these to the LLM."""
    words = normalize(text).split()
    return len(words) <= 1 or all(w in _NOISE_WORDS for w in words)


def _wants_escalation(text: str, cfg) -> bool:
    """Whether an utterance the deterministic parser couldn't handle should reach the brain.
    In "auto" mode (default) everything does. In "keywords" mode it must contain an escalation
    keyword — you opt the brain in by phrasing ("Vox, write me…"), so ambient audio stops tripping
    the LLM (issues.md O7). A pending clarification bypasses this (handled by the caller)."""
    if _setting("escalation_mode", cfg.escalation_mode) != "keywords":
        return True
    t = normalize(text)
    return any(k in t for k in cfg.escalation_keywords)


def _transcribe(transcriber, audio, cfg, out, hotwords: str = "") -> str:
    dur = len(audio) / cfg.sample_rate
    with Timer() as stt:
        text = transcriber.transcribe(audio, hotwords=hotwords)
    cpu, mem = process_stats()
    out.emit(f"  ⏱  audio {dur:.1f}s · stt {stt.seconds:.2f}s "
             f"(rtf {stt.seconds / max(dur, 0.01):.2f}) · cpu {cpu:.0f}% · mem {mem:.0f}MB")
    if cfg.debug:
        out.emit(f"  [debug] heard: {text!r}")
    return text


def _passes_interrupt_gate(audio, text, cfg) -> bool:
    """A mid-call barge-in must be REAL speech, not a blip (loop 1, O7/O8). Require the captured
    audio to be sustained ≥ interrupt_min_seconds AND carry ≥ interrupt_min_words transcribed
    words — mirrors livekit min_interruption_duration/min_interruption_words + pipecat's
    MinWords strategy. Ambient TV/chatter that leaks one short word no longer cancels the call.
    Read via the guarded _setting path so defaults are pure wins and dashboard toggles apply live."""
    min_secs = _setting("interrupt_min_seconds", cfg.interrupt_min_seconds)
    if min_secs and len(audio) / cfg.sample_rate < min_secs:
        return False
    min_words = _setting("interrupt_min_words", cfg.interrupt_min_words)
    if min_words and len(normalize(text).split()) < min_words:
        return False
    return True


def _run_interruptible(work, frames, cfg, transcriber, slow=True):
    """Run work() (a blocking LLM call) on a thread while still listening, so the user can cancel
    it by speaking a stop/sleep/quit/restart phrase (barge-in, idea #19). No echo worries — Vox
    isn't speaking during the call. Returns (result, interrupt): interrupt is None if work
    finished, else 'sleep' | 'quit' | 'restart'. An abandoned call finishes in the background and
    its result is dropped (Python can't kill a thread).

    `slow` marks calls expected to outrun the poll loop (big-brain / vision / compose). When
    interrupt_slow_calls_only is on (default), barge-in is NOT armed for fast calls — those finish
    before the poll fires anyway, so arming there only wastes a capture window and risks a spurious
    cancel (loop 1, part of O8)."""
    arm = _setting("barge_in_enabled", cfg.barge_in_enabled)
    if arm and _setting("interrupt_slow_calls_only", cfg.interrupt_slow_calls_only) and not slow:
        arm = False
    if not arm:
        return work(), None
    box: dict = {}

    def runner():
        try:
            box["result"] = work()
        except Exception as exc:  # callees normally catch their own; don't lose it
            box["error"] = exc

    t = threading.Thread(target=runner, daemon=True)
    t.start()
    while t.is_alive():
        audio = capture_utterance(frames, cfg, listen_timeout=cfg.barge_in_poll_seconds)
        if audio is None:
            continue  # silence — loop and re-check whether work() finished
        text = transcriber.transcribe(audio, hotwords=cfg.command_hotwords)
        if not text:
            continue
        if not _passes_interrupt_gate(audio, text, cfg):
            continue  # too short / too few words → a blip, not a barge-in; keep waiting for work()
        if _is_abort(text, cfg) or _is_sleep(text, cfg):
            return None, "sleep"
        if _is_quit(text, cfg):
            return None, "quit"
        if _is_restart(text, cfg):
            return None, "restart"
        # a clear new command / mode-switch mid-call → cut the LLM off and do THAT instead
        if actions.parse(text) is not None or _is_assistant(text, cfg) or _is_dictate(text, cfg):
            return None, ("redirect", text)
        # anything else (chatter / fuzzy / background) → ignore and keep waiting for work()
    if "error" in box:
        raise box["error"]
    return box.get("result"), None


def _speak_interruptible(spoken, frames, cfg, transcriber, mic):
    """Speak `spoken` while still listening, so the user can talk over the reply (loop 3 / R5).

    Returns (interrupt, text):
      • (None, None)            — the reply finished uninterrupted (the normal case).
      • ("sleep", None)         — a stop/sleep/abort phrase cut the reply → caller goes idle.
      • ("quit"|"restart", None)— those phrases cut the reply → caller raises.
      • ("redirect", text)      — a real new utterance cut the reply → caller handles `text` next.

    tts.speak() runs on a worker thread (it BLOCKS until the phrase finishes). Meanwhile we capture
    utterances and apply the loop-1 _passes_interrupt_gate, so ambient blips don't cut the voice.
    On a gated barge-in we call tts.stop_speaking() to halt Kokoro's streaming player immediately
    and drop the unplayed audio, then return the decision.

    IMPORTANT — HEADPHONES ONLY: Vox has no echo cancellation yet (loop 5 / AEC). On SPEAKERS the
    mic hears the TTS and will interrupt Vox with its own voice. This whole path is gated OFF by
    default (cfg.tts_interruptible) and is only armed for tts_engine=="kokoro" (the only engine
    stop_speaking() can actually halt) — so the default speak path stays byte-for-byte unchanged."""
    done = threading.Event()

    def speaker():
        try:
            tts.speak(spoken)
        finally:
            done.set()

    t = threading.Thread(target=speaker, daemon=True)
    t.start()
    try:
        while not done.is_set():
            audio = capture_utterance(frames, cfg, listen_timeout=cfg.barge_in_poll_seconds)
            if audio is None:
                continue  # silence — keep speaking
            text = transcriber.transcribe(audio, hotwords=cfg.command_hotwords)
            if not text or not _passes_interrupt_gate(audio, text, cfg):
                continue  # blip / too short → not a real barge-in; let the reply continue
            tts.stop_speaking()  # gated, real speech over the reply → cut the voice now
            if _is_abort(text, cfg) or _is_sleep(text, cfg):
                return "sleep", None
            if _is_quit(text, cfg):
                return "quit", None
            if _is_restart(text, cfg):
                return "restart", None
            return "redirect", text  # anything else → handle it as the next turn
        return None, None
    finally:
        done.wait()  # the speak thread BLOCKS to completion; if we cut it, stop_speaking already fired


def _control_mode(frames, cfg, transcriber, out, mic) -> None:
    out.emit(f'● CONTROL MODE — e.g. "open Safari" or "go to GitHub". Say "{cfg.sleep_spoken}" to stop.')
    pending = []  # short clarification memory: when the brain asks a question, the next answer gets context
    redirect = None  # a clear command captured mid-LLM-call, to run instead of the cancelled one
    while True:
        if redirect is not None:
            text, redirect = redirect, None
        else:
            audio = capture_utterance(frames, cfg)
            if audio is None:
                continue  # stay in control mode — only the sleep phrase (or Ctrl+C) exits
            text = _transcribe(transcriber, audio, cfg, out, hotwords=cfg.command_hotwords)
            if not text:
                continue
        if _is_abort(text, cfg):  # emergency stop → straight to idle, whatever mode we're in
            sounds.play(cfg.sound_abort)
            out.emit("🛑 Stopped.")
            return None
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
        # Dashboard open/close also work from CONTROL mode (not just idle) — caught before the
        # generic "open <app>" parser, which would otherwise try to open an app called "dashboard".
        if _is_open_dashboard(text, cfg):
            sounds.play(cfg.sound_dashboard_open)
            _open_dashboard(cfg, out)
            pending = []
            continue
        if _is_close_dashboard(text, cfg):
            sounds.play(cfg.sound_dashboard_close)
            out.emit(f"🖥  {actions.close_dashboard()}")
            pending = []
            continue
        out.emit(f"  you: {text!r}")
        _record_turn("user", text)
        # Shared deterministic layer (vox.dispatch) — ONE place for all three modes: "what app is
        # this", the scheduler (timers/alarms/reminders), then the command parser. acted → a silent
        # "did it" cue; else → a spoken answer/confirmation. None → escalate to the brain below.
        det = dispatch.try_deterministic(text)
        if det is not None:
            acted, msg = det
            if acted:
                out.emit(f"  → {msg}")
            else:
                out.emit(f"  🔊 {msg}")
                tts.speak(msg)
                mic.flush()  # drop our own confirmation TTS the mic caught
            _record_turn("assistant", str(msg), kind="command")
            pending = []  # handled deterministically → drop any pending clarification
        elif not pending and _looks_like_noise(text):  # 1-word/filler → background; don't bug the LLM
            out.emit("  (ignored — too short / background)")
            pending = []
        elif not pending and not _wants_escalation(text, cfg):  # keyword mode: no trigger → don't escalate
            out.emit("  (ignored — no escalation keyword)")
            pending = []
        else:  # unparsed, or the deterministic attempt found no target → let the brain try
            sounds.play(cfg.sound_thinking)  # "thinking…" cue — the LLM can take a moment
            # Control-mode executor is small-brain-first (a quick command translation) — it
            # usually finishes before the poll loop ever captures an utterance, so arm barge-in
            # only when interrupt_slow_calls_only is off (loop 1, O8).
            result, interrupt = _run_interruptible(
                lambda: executor.execute(text, pending), frames, cfg, transcriber, slow=False)
            if interrupt == "quit":
                raise _Quit
            if interrupt == "restart":
                raise _Restart
            if interrupt == "sleep":  # "stop"/"sleep" said mid-call → cancel and go idle
                sounds.play(cfg.sound_sleep)
                out.emit("○ Stopped (cancelled the request).")
                return None
            if isinstance(interrupt, tuple) and interrupt[0] == "redirect":  # new command mid-call
                out.emit(f"  ⤳ cancelled — doing {interrupt[1]!r} instead")
                redirect, pending = interrupt[1], []
                continue
            acted, msg = result
            if acted:
                sounds.play(cfg.sound_oneshot)  # quiet "did it" cue — action-first (#13)
                out.emit(f"  ⚡ {msg}")
                _record_turn("assistant", msg, brain="small", kind="command")
                pending = []
            elif msg:
                shown, spoken = assistant.split_say(msg)
                out.emit(f"  🔊 {shown}")
                _record_turn("assistant", shown, brain="small", kind="reply")
                tts.speak(spoken)
                mic.flush()  # drop our own voice the mic caught while speaking (no self-feedback)
                # brain asked something → remember this exchange so the next answer has context
                pending = (pending + [("user", text), ("assistant", shown)])[-4:] \
                    if shown.rstrip().endswith("?") else []
            else:  # the brain judged it chatter / not meant for Vox → stay silent
                out.emit("  (ignored — sounded like chatter)")
                pending = []


def _assistant_mode(frames, cfg, transcriber, out, mic, return_to=None):
    out.emit('● ASSISTANT MODE — chat with me. Say "stand down" when done.')
    history = []
    expecting_answer = False  # set when the model tags its reply [OPEN] → wait patiently for you
    redirect = None  # an utterance captured mid-reply, to handle instead of the cancelled one
    while True:
        if redirect is not None:
            text, redirect = redirect, None
        else:
            timeout = cfg.assistant_open_timeout_seconds if expecting_answer else cfg.assistant_idle_timeout_seconds
            audio = capture_utterance(frames, cfg,
                                      silence_seconds=cfg.assistant_silence_seconds,
                                      listen_timeout=timeout)
            if audio is None:
                out.emit("  (no reply — back to idle)")
                return return_to
            text = _transcribe(transcriber, audio, cfg, out)
            if not text:
                continue
        if _is_abort(text, cfg):  # emergency stop → straight to idle, whatever mode we're in
            sounds.play(cfg.sound_abort)
            out.emit("🛑 Stopped.")
            return None
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
        if _is_open_dashboard(text, cfg):  # a control command said mid-chat → do it, keep chatting
            sounds.play(cfg.sound_dashboard_open)
            _open_dashboard(cfg, out)
            mic.flush()
            continue
        if _is_close_dashboard(text, cfg):
            sounds.play(cfg.sound_dashboard_close)
            out.emit(f"🖥  {actions.close_dashboard()}")
            mic.flush()
            continue
        # Shared deterministic layer (vox.dispatch) — the SAME "one place" control & one-shot use:
        # "what app is this", the scheduler (timers/alarms/reminders), then a deterministic command.
        # Runs mid-chat so you can act without leaving the conversation.
        det = dispatch.try_deterministic(text)
        if det is not None:
            acted, msg = det
            sounds.play(cfg.sound_oneshot)
            if acted:
                out.emit(f"  ⚡ {msg}")
            else:
                out.emit(f"  🔊 {msg}")
                tts.speak(msg)
            _record_turn("user", text)
            _record_turn("assistant", str(msg), kind="command")
            mic.flush()
            expecting_answer = False
            continue
        # Action intents (write / "make this pretty" / "what's on my screen" / a fuzzy command) →
        # run the executor, so assistant mode has the SAME do-powers as control. Chat-first:
        # only clear action requests reach the executor; everything else falls through to chat.
        if dispatch.looks_like_action(text, cfg):
            sounds.play(cfg.sound_thinking)
            acted, msg = executor.execute(text)
            if acted:
                _record_turn("user", text)
                sounds.play(cfg.sound_oneshot)
                out.emit(f"  ⚡ {msg}")
                _record_turn("assistant", str(msg), brain="small", kind="command")
                mic.flush()
                expecting_answer = False
                continue
            if msg:  # a spoken answer (vision / a short reply)
                _record_turn("user", text)
                shown, spoken = assistant.split_say(msg)
                out.emit(f"  🔊 {shown}")
                _record_turn("assistant", shown, brain="small", kind="reply")
                tts.speak(spoken)
                mic.flush()
                expecting_answer = shown.rstrip().endswith("?")
                continue
            # executor judged it chatter / not an action → fall through to conversational chat
        sounds.play(cfg.sound_send)  # captured → "sending to the AI"
        out.emit(f"  you: {text!r}")
        _record_turn("user", text)
        # Assistant chat is the slow path (full conversational reply, may escalate to the big
        # brain) — worth arming barge-in so a long answer can be cut off (loop 1).
        result, interrupt = _run_interruptible(
            lambda: assistant.respond_turn(text, history), frames, cfg, transcriber, slow=True)
        if interrupt == "quit":
            raise _Quit
        if interrupt == "restart":
            raise _Restart
        if interrupt == "sleep":  # "sleep"/"stop" said while the AI was responding → drop it, go idle
            sounds.play(cfg.sound_sleep)
            out.emit("○ Sleeping.")
            return None
        if isinstance(interrupt, tuple) and interrupt[0] == "redirect":  # new utterance mid-reply
            out.emit(f"  ⤳ switching to {interrupt[1]!r}")
            redirect = interrupt[1]
            continue
        reply, expecting_answer = result  # model tags [OPEN]/[DONE]
        shown, spoken = assistant.split_say(reply)  # brain may pick a shorter spoken version
        history += [("user", text), ("assistant", shown)]
        _record_turn("assistant", shown, brain="small", kind="chat")
        out.emit(f"  🔊 {shown}" + ("  (…your turn)" if expecting_answer else ""))
        # Interruptible speaking (loop 3): only when tts_interruptible is ON *and* the engine is
        # kokoro (the streaming player stop_speaking() can actually halt). HEADPHONES-only — no AEC
        # yet, so on speakers the mic would hear the TTS. OFF by default → the original blocking
        # speak + mic.flush path below, byte-for-byte unchanged.
        if _setting("tts_interruptible", cfg.tts_interruptible) \
                and _setting("tts_engine", cfg.tts_engine) == "kokoro":
            interrupt, spoke_text = _speak_interruptible(spoken, frames, cfg, transcriber, mic)
            mic.flush()  # drop any residual audio captured during/after the reply
            if interrupt == "quit":
                raise _Quit
            if interrupt == "restart":
                raise _Restart
            if interrupt == "sleep":  # talked "stop"/"sleep" over the reply → cancel, go idle
                sounds.play(cfg.sound_sleep)
                out.emit("○ Sleeping.")
                return None
            if interrupt == "redirect":  # talked a new utterance over the reply → handle it next
                out.emit(f"  ⤳ you cut in — handling {spoke_text!r}")
                redirect = spoke_text
                continue
            if not expecting_answer:  # [DONE] → spoke through, exchange is over → back to idle
                out.emit("  ✓ done — back to idle (say \"Hey Vox\" to chat again)")
                return return_to
            continue
        tts.speak(spoken)
        mic.flush()  # drop our own TTS audio so we don't hear ourselves
        if not expecting_answer:  # [DONE] → the exchange reached a stopping point → back to idle
            out.emit("  ✓ done — back to idle (say \"Hey Vox\" to chat again)")
            return return_to


def _dictation_mode(frames, cfg, transcriber, out, return_to=None):
    sounds.play(cfg.sound_dictate_start)
    out.emit('✎ DICTATION — click where you want text, then speak. Say "stop typing" to stop.')
    actions.reset_dictation()  # fresh spacing/capitalization state for this session
    while True:
        audio = capture_utterance(frames, cfg, silence_seconds=cfg.assistant_silence_seconds)
        if audio is None:  # long pause
            if not _setting("dictation_exit_on_silence", cfg.dictation_exit_on_silence):
                continue  # setting: stay in dictation until an explicit "stop typing"
            sounds.play(cfg.sound_dictate_stop)
            out.emit("✎ Stopped typing.")
            return return_to
        text = _transcribe(transcriber, audio, cfg, out)
        if not text:
            continue
        if _is_abort(text, cfg):  # emergency stop → straight to idle, whatever mode we're in
            sounds.play(cfg.sound_abort)
            out.emit("🛑 Stopped.")
            return None
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
        wake = make_backend(cfg, transcriber, out)
    out.emit(f"Models loaded in {load.seconds:.1f}s.  [wake backend: {cfg.wake_backend}]")

    _start_dashboard(cfg, out)  # additive; non-fatal if the web package is missing/broken
    _start_scheduler(cfg, out)  # additive; non-fatal if the scheduler module is missing/broken

    idle_msg = f"Idle. {wake.prompt} (Ctrl+C to quit)"
    out.emit(idle_msg)
    try:
        with open_mic_stream(cfg) as mic:
            frames = mic.frames()
            # _Quit/_Restart are handled INSIDE the `with` (not propagated out) so we never run
            # MicStream.__exit__: PortAudio's Pa_StopStream → CoreAudio DeviceStop can deadlock and
            # wedge the process (the "restart got stuck" hang). os._exit skips that teardown; the OS
            # frees the mic when we exit, so a clean re-open works.
            try:
                while True:
                    label = wake.listen(frames)
                    if label == "quit":
                        raise _Quit
                    if label == "restart":
                        raise _Restart
                    if label == "dashboard":  # "open dashboard" → open the web UI, stay idle
                        sounds.play(cfg.sound_dashboard_open)
                        _open_dashboard(cfg, out)
                        out.emit(idle_msg)
                        continue
                    if label == "close_dashboard":  # "close dashboard" → close its tab in place
                        sounds.play(cfg.sound_dashboard_close)
                        out.emit(f"🖥  {actions.close_dashboard()}")
                        out.emit(idle_msg)
                        continue
                    if label.startswith("do:"):  # one-shot from idle ("Vox, open Safari" / "Vox, write me…")
                        cmd = label[3:]
                        sounds.play(cfg.sound_oneshot)  # quick "got it" cue
                        # Same shared dispatch as control/assistant: deterministic (what-app /
                        # scheduler / command) first, else the executor (write / make-pretty /
                        # vision / fuzzy) — so one-shots cover everything the other modes do.
                        det = dispatch.try_deterministic(cmd)
                        if det is not None:
                            acted, msg = det
                            if acted:
                                out.emit(f"⚡ {cmd!r} → {msg}")
                            else:
                                out.emit(f"  🔊 {msg}")
                                tts.speak(msg)
                                mic.flush()
                        else:
                            sounds.play(cfg.sound_thinking)
                            acted, msg = executor.execute(cmd)
                            if acted:
                                out.emit(f"⚡ {msg}")
                            elif msg:
                                shown, spoken = assistant.split_say(msg)
                                out.emit(f"  🔊 {shown}")
                                tts.speak(spoken)
                                mic.flush()
                        out.emit(idle_msg)
                        continue
                    # A mode may return a follow-on label to chain into the other mode
                    # without dropping to idle. If the assistant was reached *from* control,
                    # it returns to control when done (instead of idling).
                    from_control = False
                    while label in ("control", "assistant", "dictation"):
                        if label == "control":
                            sounds.play(cfg.sound_control)
                            label = _control_mode(frames, cfg, transcriber, out, mic)
                            from_control = label in ("assistant", "dictation")
                        elif label == "assistant":
                            sounds.play(cfg.sound_assistant)
                            label = _assistant_mode(frames, cfg, transcriber, out, mic,
                                                    return_to="control" if from_control else None)
                            from_control = False
                        else:  # dictation
                            label = _dictation_mode(frames, cfg, transcriber, out,
                                                    return_to="control" if from_control else None)
                            from_control = False
                    out.emit(idle_msg)
            except _Restart:
                out.emit("\n↻ Restarting Vox…")
                # Fresh process + hard exit instead of os.execv (which only ran AFTER the mic close,
                # so the deadlock there meant restart never fired). start_new_session detaches it so
                # it survives this process exiting; stdout still goes to the terminal.
                subprocess.Popen([sys.executable, "-m", "vox"], start_new_session=True)
                os._exit(0)
            except (KeyboardInterrupt, _Quit):
                sounds.play(cfg.sound_sleep)
                out.emit("\n👋 Quitting Vox.")
                os._exit(0)  # same reason — don't risk hanging on the mic-stream close on the way out
    except (KeyboardInterrupt, _Quit):  # Ctrl+C during startup (model load / mic open), before the loop
        out.emit("\n👋 Quitting Vox.")


if __name__ == "__main__":
    main()
