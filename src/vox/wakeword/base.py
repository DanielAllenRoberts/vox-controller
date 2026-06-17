"""Wake-word detector interface. Implementations are swappable behind this Protocol."""

from typing import Protocol

import numpy as np


class WakeWordDetector(Protocol):
    def detect(self, frame: np.ndarray) -> bool:
        """Return True if the wake word fired on this audio frame."""
        ...

    def reset(self) -> None:
        """Clear internal state after a trigger."""
        ...
