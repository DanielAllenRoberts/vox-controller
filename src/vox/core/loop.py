"""The Vox daemon: a small state machine over wake phrases.

IDLE listens for activation phrases. The control phrase enters CONTROL mode
(Dragon-style: transcribe + execute each command until a sleep phrase). The
assistant phrase enters ASSISTANT mode (one-shot LLM request). See docs/plan/modes.md.
"""

from collections import deque

import numpy as np

from vox import actions, assistant
from vox.audio import MicStream
from vox.config import CONFIG
from vox.io.console import ConsoleOutput
from vox.stats import Timer, process_stats
from vox.stt.whisper_transcriber import WhisperTranscriber
from vox.wakeword.openwakeword_detector import OpenWakeWordDetector


def _rms(frame: np.ndarray) -> float:
    return float(np.sqrt(np.mean(frame.astype(np.float32) ** 2)))


def _listen_utterance(frames, cfg):
    """Wait for speech onset, then record until trailing silence.

    Returns an int16 array, or None if no speech arrives within listen_timeout.
    """
    sr, fs = cfg.sample_rate, cfg.frame_samples
    silence_limit = int(cfg.silence_seconds * sr / fs)
    max_frames = int(cfg.max_utterance_seconds * sr / fs)
    wait_frames = int(cfg.listen_timeout_seconds * sr / fs)

    pre_roll = deque(maxlen=cfg.preroll_frames)
    waited = 0
    while True:
        frame = next(frames)
        if _rms(frame) >= cfg.speech_rms:
            break
        pre_roll.append(frame)
        waited += 1
        if waited >= wait_frames:
            return None

    collected = list(pre_roll) + [frame]
    silent = 0
    while len(collected) < max_frames:
        frame = next(frames)
        collected.append(frame)
        if _rms(frame) < cfg.speech_rms:
            silent += 1
            if silent >= silence_limit:
                break
        else:
            silent = 0
    return np.concatenate(collected)


def _is_sleep(text: str, cfg) -> bool:
    t = text.lower()
    return any(p in t for p in cfg.sleep_phrases)


def _transcribe(transcriber, audio, cfg, out) -> str:
    dur = len(audio) / cfg.sample_rate
    with Timer() as stt:
        text = transcriber.transcribe(audio)
    cpu, mem = process_stats()
    out.emit(f"  ⏱  audio {dur:.1f}s · stt {stt.seconds:.2f}s "
             f"(rtf {stt.seconds / max(dur, 0.01):.2f}) · cpu {cpu:.0f}% · mem {mem:.0f}MB")
    return text


def _control_mode(frames, cfg, transcriber, out) -> None:
    out.emit(f'● CONTROL MODE — commands like "open Safari". Say "{cfg.sleep_spoken}" to stop.')
    while True:
        audio = _listen_utterance(frames, cfg)
        if audio is None:
            continue  # stay in control mode — only the sleep phrase (or Ctrl+C) exits
        text = _transcribe(transcriber, audio, cfg, out)
        if not text:
            continue
        if _is_sleep(text, cfg):
            out.emit("○ Sleeping.")
            return
        out.emit(f"  you: {text!r}")
        out.emit(f"  → {actions.handle(text)}")


def _assistant_mode(frames, cfg, transcriber, out) -> None:
    out.emit("● ASSISTANT MODE — ask something…")
    audio = _listen_utterance(frames, cfg)
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
        detector = OpenWakeWordDetector([cfg.control_wake, cfg.assistant_wake], cfg.wake_threshold)
        transcriber = WhisperTranscriber(cfg.whisper_model, cfg.whisper_compute_type)
    out.emit(f"Models loaded in {load.seconds:.1f}s.")

    idle_msg = (f'Idle. Say "{cfg.control_spoken}" for control, '
                f'"{cfg.assistant_spoken}" for the assistant. (Ctrl+C to quit)')
    out.emit(idle_msg)
    try:
        with MicStream(cfg.sample_rate, cfg.frame_samples, cfg.input_device) as mic:
            frames = mic.frames()
            for frame in frames:
                fired = detector.fired(frame)
                if fired is None:
                    continue
                detector.reset()
                if fired == cfg.control_wake:
                    _control_mode(frames, cfg, transcriber, out)
                else:
                    _assistant_mode(frames, cfg, transcriber, out)
                out.emit(idle_msg)
    except KeyboardInterrupt:
        out.emit("\nStopped.")


if __name__ == "__main__":
    main()
