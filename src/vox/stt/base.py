"""Speech-to-text interface. Implementations are swappable behind this Protocol."""

from typing import Protocol

import numpy as np


class Transcriber(Protocol):
    def transcribe(self, audio: np.ndarray) -> str:
        """Transcribe a mono 16 kHz int16 audio buffer to text."""
        ...
