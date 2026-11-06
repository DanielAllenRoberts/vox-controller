"""Voice Lab: the user's own recordings, for testing Vox against their real voice and mic.

Synthetic test voices only go so far. A wake-word gate that catches 91% of the macOS `say` voices
says nothing about how the user actually says "vox". The app's Voice Lab page records short clips
of requested phrases; each one is transcribed here with the engine's own Whisper, named after what
was heard, and kept in ``<data>/voice-samples/`` (16 kHz mono WAV + ``index.json``). Evaluation
scripts (``scripts/eval_voice_samples.py``) replay them through wake detection, the idle pre-check,
end-of-turn detection and so on.

Recordings stay on this machine in the data folder, which is gitignored, like everything else there.
"""

from __future__ import annotations

import io
import json
import re
import threading
import time
import uuid
import wave

import numpy as np

from vox.paths import DATA_DIR

DIR = DATA_DIR / "voice-samples"
_INDEX = DIR / "index.json"
_LOCK = threading.Lock()

# What to record, and why. Categories map onto the evaluations that use them.
PROMPTS: list[dict] = [
    {"category": "wake", "text": "Hey Vox", "why": "Wake word recall"},
    {"category": "wake", "text": "Take control", "why": "Wake word recall"},
    {"category": "wake", "text": "Vox, open Safari", "why": "One-shots, the case the quick check misses"},
    {"category": "wake", "text": "Vox, what time is it?", "why": "One-shots"},
    {"category": "wake", "text": "Vox start typing", "why": "Dictation from idle"},
    {"category": "command", "text": "Next tab", "why": "Short commands"},
    {"category": "command", "text": "Click submit", "why": "Short commands"},
    {"category": "command", "text": "Scroll down", "why": "Short commands"},
    {"category": "command", "text": "Point at the export button", "why": "Pointing"},
    {"category": "unfinished", "text": "I want you to open the… (stop mid-sentence)", "why": "End-of-turn detection"},
    {"category": "unfinished", "text": "Can you send an email to… (stop mid-sentence)", "why": "End-of-turn detection"},
    {"category": "finished", "text": "Remind me in ten minutes to stretch.", "why": "End-of-turn detection"},
    {"category": "ambient", "text": "Anything you'd say to someone else in the room", "why": "Must NOT wake Vox"},
    {"category": "ambient", "text": "Talk about your day for a few seconds", "why": "Must NOT wake Vox"},
    {"category": "dictation", "text": "Hello there, I'll see you at three tomorrow.", "why": "Typing accuracy"},
]

_transcriber = None  # set by the daemon (shares its loaded Whisper); lazily created standalone


def use_transcriber(t) -> None:
    global _transcriber
    _transcriber = t


def _get_transcriber():
    global _transcriber
    if _transcriber is None:
        from vox.config import CONFIG
        from vox.stt.whisper_transcriber import WhisperTranscriber
        _transcriber = WhisperTranscriber(CONFIG.whisper_model, CONFIG.whisper_compute_type,
                                          cpu_threads=CONFIG.whisper_cpu_threads)
    return _transcriber


def _read() -> list[dict]:
    try:
        return json.loads(_INDEX.read_text())
    except Exception:
        return []


def _write(items: list[dict]) -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    tmp = _INDEX.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, indent=2))
    tmp.replace(_INDEX)


def _decode_wav(data: bytes) -> np.ndarray:
    """16-bit PCM WAV → int16 mono at 16 kHz (resampled linearly if the recorder used another rate)."""
    with wave.open(io.BytesIO(data)) as w:
        sr, ch, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
        frames = w.readframes(w.getnframes())
    if width != 2:
        raise ValueError("expected 16-bit PCM audio")
    a = np.frombuffer(frames, dtype=np.int16)
    if ch > 1:
        a = a.reshape(-1, ch).mean(axis=1).astype(np.int16)
    if sr != 16000 and a.size:
        n = int(a.size * 16000 / sr)
        a = np.interp(np.linspace(0, a.size, n, endpoint=False), np.arange(a.size), a).astype(np.int16)
    return a


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:48] or "silence"


def add(wav_bytes: bytes, prompt: str = "", category: str = "") -> dict:
    audio = _decode_wav(wav_bytes)
    if audio.size < 1600:
        raise ValueError("recording is too short")
    transcript = (_get_transcriber().transcribe(audio) or "").strip()
    sid = uuid.uuid4().hex[:8]
    name = f"{_slug(transcript)}-{sid}.wav"
    DIR.mkdir(parents=True, exist_ok=True)
    with wave.open(str(DIR / name), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(audio.tobytes())
    entry = {"id": sid, "file": name, "transcript": transcript, "prompt": prompt, "category": category,
             "durationMs": int(audio.size / 16), "created": time.strftime("%Y-%m-%dT%H:%M:%S")}
    with _LOCK:
        items = _read()
        items.append(entry)
        _write(items)
    return entry


def all_samples() -> list[dict]:
    return sorted(_read(), key=lambda e: e.get("created", ""), reverse=True)


def path_of(sid: str):
    e = next((x for x in _read() if x["id"] == sid), None)
    return (DIR / e["file"]) if e else None


def remove(sid: str) -> bool:
    with _LOCK:
        items = _read()
        keep = [x for x in items if x["id"] != sid]
        if len(keep) == len(items):
            return False
        gone = next(x for x in items if x["id"] == sid)
        try:
            (DIR / gone["file"]).unlink(missing_ok=True)
        except Exception:
            pass
        _write(keep)
        return True
