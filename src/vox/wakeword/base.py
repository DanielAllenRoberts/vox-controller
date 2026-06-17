"""Wake-word detector interface. Implementations are swappable behind this Protocol."""

from typing import Protocol

import numpy as np


class WakeWordDetector(Protocol):
    def fired(self, frame: np.ndarray) -> str | None:
        """Return the name of the phrase that fired on this frame, or None."""
        ...

    def scores(self, frame: np.ndarray) -> dict[str, float]:
        """Return the confidence score for each loaded phrase."""
        ...

    def reset(self) -> None:
        """Clear internal state after a trigger."""
        ...
