"""Console output sink."""


class ConsoleOutput:
    def emit(self, text: str) -> None:
        print(text, flush=True)
