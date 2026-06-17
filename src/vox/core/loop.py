"""The Vox daemon: a small state machine over wake phrases.

IDLE waits (via the configured wake backend) for an activation phrase. The control
label enters CONTROL mode (Dragon-style: transcribe + execute each command until a
sleep phrase). The assistant label enters ASSISTANT mode (one-shot LLM request).
See docs/plan/modes.md.
"""

from vox import actions, assistant
from vox.audio import MicStream, capture_utterance
from vox.config import CONFIG
from vox.io.console import ConsoleOutput
from vox.stats import Timer, process_stats
from vox.stt.whisper_transcriber import WhisperTranscriber
from vox.wakeword.backends import make_backend, normalize


def _is_sleep(text: str, cfg) -> bool:
    t = normalize(text)
    return any(p in t for p in cfg.sleep_phrases)


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
        if _is_sleep(text, cfg):
            out.emit("○ Sleeping.")
            return
        out.emit(f"  you: {text!r}")
        out.emit(f"  → {actions.handle(text)}")


def _assistant_mode(frames, cfg, transcriber, out) -> None:
    out.emit("● ASSISTANT MODE — ask something…")
    audio = capture_utterance(frames, cfg)
    if audio is None:
        out.emit("  (heard nothing — back to idle)")
        return
    text = _transcribe(transcriber, audio, cfg, out)
    if not text:
        out.emit("  (heard nothing — back to idle)")
        return
    if _is_sleep(text, cfg):
        out.emit("○ Sleeping.")
        return
    out.emit(f"  you: {text!r}")
    out.emit(f"  → {assistant.respond(text)}")


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
                if label == "control":
                    _control_mode(frames, cfg, transcriber, out)
                elif label == "assistant":
                    _assistant_mode(frames, cfg, transcriber, out)
                out.emit(idle_msg)
    except KeyboardInterrupt:
        out.emit("\nStopped.")


if __name__ == "__main__":
    main()
