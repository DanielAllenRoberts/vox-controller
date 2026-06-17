"""Microphone capture. Yields fixed-size int16 frames from the default input device."""

import queue
from collections import deque

import numpy as np
import sounddevice as sd


class MicStream:
    """Streams mono int16 audio frames from the microphone via a callback queue."""

    def __init__(self, sample_rate: int, frame_samples: int, device: int | None = None):
        self._frame_samples = frame_samples
        self._queue: "queue.Queue[np.ndarray]" = queue.Queue()
        self._stream = sd.InputStream(
            samplerate=sample_rate,
            channels=1,
            dtype="int16",
            blocksize=frame_samples,
            device=device,
            callback=self._callback,
        )

    def _callback(self, indata, frames, time_info, status) -> None:
        # indata: shape (frame_samples, 1) int16 — copy out of the driver buffer.
        self._queue.put(indata[:, 0].copy())

    def frames(self):
        """Generator yielding one int16 frame at a time."""
        while True:
            yield self._queue.get()

    def __enter__(self) -> "MicStream":
        self._stream.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stream.stop()
        self._stream.close()


def rms(frame: np.ndarray) -> float:
    return float(np.sqrt(np.mean(frame.astype(np.float32) ** 2)))


def capture_utterance(frames, cfg, silence_seconds=None):
    """Wait for speech onset (keeping a short pre-roll), then record until trailing
    silence. Returns int16 audio, or None if no speech arrives within listen_timeout.

    `silence_seconds` overrides how long a pause ends the utterance (default: cfg value).
    """
    sr, fs = cfg.sample_rate, cfg.frame_samples
    sil = cfg.silence_seconds if silence_seconds is None else silence_seconds
    silence_limit = int(sil * sr / fs)
    max_frames = int(cfg.max_utterance_seconds * sr / fs)
    wait_frames = int(cfg.listen_timeout_seconds * sr / fs)

    pre_roll = deque(maxlen=cfg.preroll_frames)
    waited = 0
    while True:
        frame = next(frames)
        if rms(frame) >= cfg.speech_rms:
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
        if rms(frame) < cfg.speech_rms:
            silent += 1
            if silent >= silence_limit:
                break
        else:
            silent = 0
    return np.concatenate(collected)
