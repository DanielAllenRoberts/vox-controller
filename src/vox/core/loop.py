"""M0 loop: wait for the wake word, capture an utterance, transcribe, print it.

No actions yet — opening apps and intent parsing arrive in M1+. The components
(wake word, STT, output) sit behind interfaces so they can be swapped later.
"""

import numpy as np

from vox.audio import MicStream
from vox.config import CONFIG
from vox.io.console import ConsoleOutput
from vox.stats import Timer, process_stats
from vox.stt.whisper_transcriber import WhisperTranscriber
from vox.wakeword.openwakeword_detector import OpenWakeWordDetector


def _record_utterance(frames, cfg) -> np.ndarray:
    """Collect frames after a wake trigger until a short silence or the max cap."""
    collected: list[np.ndarray] = []
    silent = 0
    max_frames = int(cfg.max_utterance_seconds * cfg.sample_rate / cfg.frame_samples)
    silence_limit = int(cfg.silence_seconds * cfg.sample_rate / cfg.frame_samples)

    for _ in range(max_frames):
        frame = next(frames)
        collected.append(frame)
        rms = float(np.sqrt(np.mean(frame.astype(np.float32) ** 2)))
        if rms < cfg.silence_rms:
            silent += 1
            if silent >= silence_limit and len(collected) > silence_limit:
                break
        else:
            silent = 0

    return np.concatenate(collected) if collected else np.zeros(0, dtype=np.int16)


def main() -> None:
    cfg = CONFIG
    out = ConsoleOutput()

    out.emit(f"Loading {cfg.assistant_name}… (first run downloads models)")
    with Timer() as load:
        detector = OpenWakeWordDetector(cfg.wake_word_model, cfg.wake_threshold)
        transcriber = WhisperTranscriber(cfg.whisper_model, cfg.whisper_compute_type)
    out.emit(f"Models loaded in {load.seconds:.1f}s.")

    out.emit(f'{cfg.assistant_name} is listening — say "{cfg.wake_word_spoken}", then speak. (Ctrl+C to quit)')
    try:
        with MicStream(cfg.sample_rate, cfg.frame_samples, cfg.input_device) as mic:
            frames = mic.frames()
            for frame in frames:
                if not detector.detect(frame):
                    continue
                detector.reset()
                out.emit("→ wake word detected, listening…")
                audio = _record_utterance(frames, cfg)
                audio_dur = len(audio) / cfg.sample_rate
                with Timer() as stt:
                    text = transcriber.transcribe(audio)
                cpu, mem = process_stats()
                out.emit(f"You said: {text!r}" if text else "(heard nothing)")
                rtf = stt.seconds / max(audio_dur, 0.01)
                out.emit(f"  ⏱  audio {audio_dur:.1f}s · stt {stt.seconds:.2f}s "
                         f"(rtf {rtf:.2f}) · cpu {cpu:.0f}% · mem {mem:.0f}MB")
    except KeyboardInterrupt:
        out.emit("\nStopped.")


if __name__ == "__main__":
    main()
