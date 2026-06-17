"""Lightweight compute instrumentation: timing + process CPU/memory.

Used to track how much compute each stage takes so we can optimize over time.
(Real package-power in watts needs `sudo powermetrics` — a separate opt-in tool.)
"""

import time

import psutil

_proc = psutil.Process()
_proc.cpu_percent(interval=None)  # prime the CPU% counter (first call is always 0.0)


class Timer:
    """Context manager measuring wall-clock seconds: `with Timer() as t: ...; t.seconds`."""

    def __enter__(self) -> "Timer":
        self._start = time.monotonic()
        self.seconds = 0.0
        return self

    def __exit__(self, *exc) -> None:
        self.seconds = time.monotonic() - self._start


def process_stats() -> tuple[float, float]:
    """Return (cpu_percent_since_last_call, resident_memory_mb) for this process."""
    return _proc.cpu_percent(interval=None), _proc.memory_info().rss / 1e6
