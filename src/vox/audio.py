"""Microphone capture. Yields fixed-size int16 frames from the default input device."""

import queue

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
