"""faster-whisper transcriber. Runs locally (CTranslate2, CPU/int8 on Apple Silicon)."""

import numpy as np
from faster_whisper import WhisperModel


class WhisperTranscriber:
    def __init__(self, model_size: str, compute_type: str):
        self._model = WhisperModel(model_size, device="cpu", compute_type=compute_type)

    def transcribe(self, audio: np.ndarray, hotwords: str = "") -> str:
        # faster-whisper wants float32 mono in [-1, 1]; mic gives us int16.
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32) / 32768.0
        # hotwords bias recognition toward expected vocabulary (e.g. app/command words).
        # vad_filter drops non-speech (fan noise, silence) BEFORE transcribing — stops
        # Whisper hallucinating words (often the biased hotwords) when you're not speaking.
        segments, _ = self._model.transcribe(audio, language="en", hotwords=hotwords or None,
                                             vad_filter=True)
        return " ".join(seg.text.strip() for seg in segments).strip()
