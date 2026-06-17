"""Output channel interface. Console now; voice (TTS) and others slot in later (M2/M3)."""

from typing import Protocol


class OutputSink(Protocol):
    def emit(self, text: str) -> None:
        """Deliver a line of output to the user."""
        ...
