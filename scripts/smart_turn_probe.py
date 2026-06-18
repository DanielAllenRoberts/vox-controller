"""Verification probe for the smart-turn end-of-turn detector (voice-upgrade loop 4).

Generates a clearly-COMPLETE and a clearly-INCOMPLETE spoken clip with macOS `say`, runs
vox.turn_detector on each, and prints P(complete). Optionally cross-checks the pure-numpy
Whisper log-mel features against transformers' WhisperFeatureExtractor if it's importable.

Run:  uv run python scripts/smart_turn_probe.py
"""

import os
import subprocess
import tempfile
import wave

import numpy as np

from vox import turn_detector as td


def _say_to_16k(text: str) -> np.ndarray:
    """Render `text` via macOS `say` and return mono int16 @ 16 kHz."""
    aiff = tempfile.mktemp(suffix=".aiff")
    wav = tempfile.mktemp(suffix=".wav")
    try:
        subprocess.run(["say", "-o", aiff, text], check=True, capture_output=True)
        # afconvert to 16 kHz mono 16-bit PCM wav
        subprocess.run(
            ["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1", aiff, wav],
            check=True, capture_output=True,
        )
        with wave.open(wav, "rb") as w:
            frames = w.readframes(w.getnframes())
        return np.frombuffer(frames, dtype="<i2").astype(np.int16)
    finally:
        for p in (aiff, wav):
            if os.path.exists(p):
                os.remove(p)


def _cross_check_features(audio_int16: np.ndarray) -> None:
    try:
        from transformers import WhisperFeatureExtractor
    except Exception:
        print("  (transformers not installed — skipping feature cross-check)")
        return
    a = td._to_mono_float(audio_int16, 16000)
    if a.size > td.MAX_SAMPLES:
        a = a[-td.MAX_SAMPLES:]
    fe = WhisperFeatureExtractor(chunk_length=8)
    ref = fe(a, sampling_rate=16000, return_tensors="np", padding="max_length",
             max_length=8 * 16000, truncation=True, do_normalize=True).input_features[0]
    mine = td._prepare_input(audio_int16, 16000)[0]
    print(f"  feature cross-check vs transformers: max|Δ| = {np.abs(ref - mine).max():.2e}, "
          f"shapes {ref.shape} vs {mine.shape}")


COMPLETE = "What time is it right now?"
INCOMPLETE = "So I was thinking that maybe we could possibly go and"


def main() -> None:
    print(f"model: {td._MODEL_REPO}/{td._MODEL_FILE}  →  {td._model_path()}")
    for label, text in (("COMPLETE  ", COMPLETE), ("INCOMPLETE", INCOMPLETE)):
        audio = _say_to_16k(text)
        p = td.probability_complete(audio, 16000)
        dur = len(audio) / 16000
        print(f"[{label}] {text!r}  ({dur:.1f}s)  →  P(complete) = {p:.4f}  "
              f"({'COMPLETE' if p >= 0.5 else 'INCOMPLETE'})")
        _cross_check_features(audio)


if __name__ == "__main__":
    main()
