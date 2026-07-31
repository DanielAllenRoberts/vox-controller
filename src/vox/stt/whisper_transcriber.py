"""faster-whisper transcriber. Runs locally (CTranslate2, CPU/int8 on Apple Silicon)."""

import numpy as np
from faster_whisper import WhisperModel


class WhisperTranscriber:
    def __init__(self, model_size: str, compute_type: str, cpu_threads: int = 0):
        # cpu_threads caps CTranslate2's intra-op threads. 0 = its default (≈ all physical cores),
        # which lets idle transcription saturate the machine; a modest cap keeps the system responsive.
        self._model = WhisperModel(model_size, device="cpu", compute_type=compute_type,
                                   cpu_threads=cpu_threads)

    def transcribe(self, audio: np.ndarray, hotwords: str = "") -> str:
        # faster-whisper wants float32 mono in [-1, 1]; mic gives us int16.
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32) / 32768.0
        # hotwords bias recognition toward expected vocabulary (e.g. app/command words).
        # vad_filter drops non-speech (fan noise, silence) BEFORE transcribing — stops
        # Whisper hallucinating words (often the biased hotwords) when you're not speaking.
        segments, _ = self._model.transcribe(audio, language="en", hotwords=hotwords or None,
                                             vad_filter=True)
        text = " ".join(seg.text.strip() for seg in segments).strip()
        # "Learn a word" (idea #54): apply the user's speech-correction dictionary to Whisper's output
        # — fix homophones/proper nouns (clawed→Claude) that a frozen model can't be taught directly.
        # Guarded + lazy: any problem (missing store/module) returns the raw transcript unchanged.
        try:
            from vox import vocab
            text = vocab.apply(text)
        except Exception:
            pass
        return text
