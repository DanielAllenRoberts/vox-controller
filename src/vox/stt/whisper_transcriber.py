"""faster-whisper transcriber. Runs locally (CTranslate2 on the CPU; float32 on Apple Silicon)."""

import re

import numpy as np
from faster_whisper import WhisperModel


def _regurgitated(text: str, hotwords: str, run: int = 3) -> bool:
    """True when the transcript contains ``run``+ words that follow each other IN THE SAME ORDER as
    the hotword list ("amazon netflix calculator terminal…"). That's Whisper reading back its own
    biasing prompt on near-silence, not something anyone says, so the whole transcript is dropped."""
    order = (hotwords or "").lower().split()
    if len(order) < run:
        return False
    pos = {w: i for i, w in enumerate(order)}
    words = re.findall(r"[a-z0-9']+", text.lower())
    streak = 1
    for a, b in zip(words, words[1:]):
        streak = streak + 1 if (a in pos and b in pos and pos[b] == pos[a] + 1) else 1
        if streak >= run:
            return True
    return False


class WhisperTranscriber:
    def __init__(self, model_size: str, compute_type: str, cpu_threads: int = 0, beam_size: int = 1):
        # cpu_threads caps CTranslate2's intra-op threads. 0 = its default (≈ all physical cores),
        # which lets idle transcription saturate the machine; a modest cap keeps the system responsive.
        self._model = WhisperModel(model_size, device="cpu", compute_type=compute_type,
                                   cpu_threads=cpu_threads)
        self._beam_size = beam_size

    def transcribe(self, audio: np.ndarray, hotwords: str = "") -> str:
        from vox import runtime
        if runtime.is_typed(audio):  # typed to Vox (ideas #68): nothing to recognise
            return audio.text
        # faster-whisper wants float32 mono in [-1, 1]; mic gives us int16.
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32) / 32768.0
        # hotwords bias recognition toward expected vocabulary (e.g. app/command words).
        # vad_filter drops non-speech (fan noise, silence) BEFORE transcribing — stops
        # Whisper hallucinating words (often the biased hotwords) when you're not speaking.
        # temperature=0.0: faster-whisper's default fallback list re-decodes up to 5 more times when
        # output looks like garbage — exactly what idle noise and mumbling produce, so the worst case
        # landed on audio we throw away. condition_on_previous_text=False: each utterance stands alone.
        segments, _ = self._model.transcribe(audio, language="en", hotwords=hotwords or None,
                                             vad_filter=True, beam_size=self._beam_size,
                                             temperature=0.0, condition_on_previous_text=False)
        text = " ".join(seg.text.strip() for seg in segments).strip()
        if hotwords and _regurgitated(text, hotwords):
            return ""
        # "Learn a word" (idea #54): apply the user's speech-correction dictionary to Whisper's output
        # — fix homophones/proper nouns (clawed→Claude) that a frozen model can't be taught directly.
        # Guarded + lazy: any problem (missing store/module) returns the raw transcript unchanged.
        try:
            from vox import vocab
            text = vocab.apply(text)
        except Exception:
            pass
        return text
