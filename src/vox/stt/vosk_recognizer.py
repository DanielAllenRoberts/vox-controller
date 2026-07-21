"""Vosk grammar-constrained command recognition — the "fast lane" (idea #53).

Whisper transcribes free-form (open vocabulary) and we string-match commands *after* the fact; if it
mis-hears the key word the match is already lost. Vosk grammar flips this: we hand it the CURRENT
command phrases (from the command DB) and it may only output one of them (or ``[unk]``). Ambiguous
audio snaps to the nearest real command, it's fast (it searches ~50 phrases, not all of English),
and it runs on a tiny ~50 MB model. Anything it can't match (``[unk]``) falls straight through to
Whisper — the two-lane design.

LAZY + GUARDED: vosk and the model load only when the fast lane is enabled and ``recognize()`` is
called; ANY problem (package missing, model download failure, out-of-vocabulary phrase, inference
error) raises ``VoskUnavailable`` so the caller falls back to Whisper. The daemon must run with or
without it.

Note (lexicon): grammar phrases can only use words already in Vosk's model lexicon. A command with an
out-of-vocabulary proper noun (an app name it doesn't know) simply won't match → it returns None and
that command takes the Whisper lane. That degradation is fine and expected.
"""

from __future__ import annotations

import contextlib
import json
import os

_MODEL = None      # cached vosk.Model
_LANG = "en-us"    # the small lookahead model that supports grammar
_REC = None        # cached KaldiRecognizer (reused across utterances for one grammar)
_REC_KEY = None    # (grammar_json, sample_rate) the cached recognizer was built with


class VoskUnavailable(Exception):
    """Raised when Vosk / its model can't load or run, so the caller falls back to Whisper."""


@contextlib.contextmanager
def _silence_c_stderr():
    """Swallow Vosk's C++ stderr at the fd level — it prints an 'Ignoring word missing in vocabulary'
    WARNING for every out-of-vocab command word each time a grammar is built. Guarded: if the fd
    dance fails, just run without suppression."""
    try:
        saved, devnull = os.dup(2), os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, 2)
    except Exception:
        yield
        return
    try:
        yield
    finally:
        try:
            os.dup2(saved, 2)
            os.close(saved)
            os.close(devnull)
        except Exception:
            pass


def _default_model_dir():
    """A downloaded Vosk model under ~/.cache/vox/vosk/ (where the setup download puts it), or None."""
    import glob
    import os
    base = os.path.expanduser("~/.cache/vox/vosk")
    for h in sorted(glob.glob(os.path.join(base, "vosk-model-*"))):
        if os.path.isdir(os.path.join(h, "conf")):  # a real vosk model dir (has conf/model.conf)
            return h
    return None


def _get_model(model_path: str = "", log=None):
    """Load (once) the Vosk model. ``model_path`` wins; else auto-find one under ~/.cache/vox/vosk/;
    else fall back to Vosk's auto-download by lang (needs a live cert on alphacephei.com). Raises
    VoskUnavailable on any problem."""
    global _MODEL
    if _MODEL is not None:
        return _MODEL
    try:
        import vosk
    except Exception as exc:
        raise VoskUnavailable(f"vosk not installed: {exc}") from exc
    path = model_path or _default_model_dir()
    try:
        vosk.SetLogLevel(-1)  # silence Vosk's very chatty internal C++ logging
        if path:
            if log:
                log(f"  [vosk] loading model from {path}")
            _MODEL = vosk.Model(path)
        else:
            if log:
                log("  [vosk] no local model found; trying auto-download by lang…")
            _MODEL = vosk.Model(lang=_LANG)
        if log:
            log("  [vosk] model ready")
    except Exception as exc:
        raise VoskUnavailable(
            f"vosk model unavailable ({exc}) — download a model and set vosk_model_path, "
            "or place it under ~/.cache/vox/vosk/") from exc
    return _MODEL


def _pcm_bytes(audio) -> bytes:
    """A mono 16-bit PCM byte string from an int16 (or float [-1,1]) numpy buffer — what Vosk wants."""
    import numpy as np
    a = np.asarray(audio)
    if a.ndim > 1:
        a = a.reshape(-1)
    if np.issubdtype(a.dtype, np.floating):
        a = np.clip(a * 32768.0, -32768, 32767).astype(np.int16)
    elif a.dtype != np.int16:
        a = a.astype(np.int16)
    return a.tobytes()


def recognize(audio, phrases, sample_rate: int = 16000, model_path: str = "", log=None) -> dict | None:
    """Constrain recognition to ``phrases`` and run the utterance through Vosk.

    Returns ``{text, conf, raw}`` for a CLEAN command match (``text`` is the original phrase, so the
    caller feeds it downstream exactly like a Whisper transcript), or ``None`` when Vosk returns
    ``[unk]`` / no clean match (→ the caller uses Whisper). Raises ``VoskUnavailable`` on a
    load/inference problem so the caller falls back."""
    phrase_list = [p.strip() for p in phrases if p and p.strip()]
    if not phrase_list:
        return None
    global _REC, _REC_KEY
    model = _get_model(model_path, log)
    try:
        from vosk import KaldiRecognizer
        by_lower: dict[str, str] = {}
        for p in phrase_list:
            by_lower.setdefault(p.lower(), p)  # first spelling wins; Vosk emits lowercase
        grammar = json.dumps(list(by_lower.keys()) + ["[unk]"])
        key = (grammar, float(sample_rate))
        if _REC is not None and _REC_KEY == key:
            rec = _REC          # same grammar (same app context) → reuse, no rebuild / no re-warn
            rec.Reset()
        else:
            with _silence_c_stderr():  # OOV warnings fire here only — once per grammar, then swallowed
                rec = KaldiRecognizer(model, float(sample_rate), grammar)
            rec.SetWords(True)
            _REC, _REC_KEY = rec, key
            if log:
                log(f"  [vosk] grammar compiled + cached: {len(by_lower)} phrases")
        rec.AcceptWaveform(_pcm_bytes(audio))
        res = json.loads(rec.FinalResult())
    except Exception as exc:
        raise VoskUnavailable(f"vosk recognize failed: {exc}") from exc
    raw = (res.get("text") or "").strip()
    # Vosk emits `[unk]` tokens for the breath/silence/noise around the command (e.g. "[unk] next
    # tab"). Strip them, then require what's left to be EXACTLY one of our phrases: a real command
    # with a bit of surrounding noise still matches, but a non-command (mostly `[unk]`) does not.
    cleaned = " ".join(w for w in raw.split() if w != "[unk]").strip().lower()
    if not cleaned or cleaned not in by_lower:
        return None  # [unk] / no clean grammar match → Whisper lane
    words = [w for w in (res.get("result") or []) if w.get("word") not in (None, "[unk]")]
    confs = [float(w.get("conf", 1.0)) for w in words]
    conf = round(sum(confs) / len(confs), 3) if confs else 1.0
    return {"text": by_lower[cleaned], "raw": raw, "conf": conf}
