"""faster-whisper transcriber. Runs locally (CTranslate2, CPU/int8 on Apple Silicon)."""

import numpy as np
from faster_whisper import WhisperModel


class WhisperTranscriber:
    def __init__(self, model_size: str, compute_type: str):
        self._model = WhisperModel(model_size, device="cpu", compute_type=compute_type)

    def transcribe(self, audio: np.ndarray) -> str:
        # faster-whisper wants float32 mono in [-1, 1]; mic gives us int16.
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32) / 32768.0
        segments, _ = self._model.transcribe(audio, language="en")
        return " ".join(seg.text.strip() for seg in segments).strip()
