"""Wake backend interface — pluggable wake-word detection. See vox/wakeword/backends.py."""

from typing import Protocol


class WakeBackend(Protocol):
    prompt: str  # human-readable hint of what to say, shown when idle

    def listen(self, frames) -> str:
        """Block, pulling audio frames, until an activation phrase fires.

        Return a logical label such as 'control' or 'assistant'.
        """
        ...
