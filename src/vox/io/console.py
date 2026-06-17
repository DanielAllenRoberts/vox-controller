"""Console output sink — prints to the terminal and tees to a log file."""

import time


class ConsoleOutput:
    def __init__(self, log_path: str = "") -> None:
        self._log = open(log_path, "a", buffering=1) if log_path else None

    def emit(self, text: str) -> None:
        print(text, flush=True)
        if self._log:
            self._log.write(f"{time.strftime('%H:%M:%S')} {text}\n")
