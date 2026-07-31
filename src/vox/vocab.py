"""Speech-correction dictionary — the local "learn a word" (idea #54).

Whisper is a frozen model; we can't teach it new words. Instead this applies a user-editable
REPLACEMENT MAP to Whisper's OUTPUT text — "when you hear X, write Y" (e.g. ``clawed`` → ``Claude``).
Deterministic, instant, fully local; it never touches the model. Matching is **word-boundary** and
**case-insensitive** so "clawed"→"Claude" fixes the word without mangling "clawedness"; the replacement
is written verbatim (the user controls its casing). Longer phrases win over shorter ones
("clawed code" beats "clawed").

Stored as ``data/vocab.json`` (``{"entries": [{id, heard, write, enabled}]}``), loaded into memory and
compiled into one regex. ``apply(text)`` runs right after STT (``whisper_transcriber``) so dictation,
commands and chat all see corrected text. The dashboard edits the SAME in-process module state, so a
change takes effect on the next utterance with no restart. Fully guarded: a missing/corrupt store or
any error returns the text unchanged (exactly today's behaviour).
"""

from __future__ import annotations

import json
import re
import threading
import uuid
from pathlib import Path

# Runtime store lives under data/ (gitignored). This file is src/vox/vocab.py → parents[2] is root.
_DATA_DIR = Path(__file__).resolve().parents[2] / "data"
_STORE = _DATA_DIR / "vocab.json"

_LOCK = threading.RLock()
_LOADED = False
_ENTRIES: list[dict] = []          # [{id, heard, write, enabled}]
_PATTERN: re.Pattern | None = None  # compiled alternation of all enabled "heard" phrases
_MAP: dict[str, str] = {}          # lowercased heard → write


# --- persistence + compilation ------------------------------------------------------------------

def _clean(e) -> dict | None:
    if not isinstance(e, dict):
        return None
    heard = str(e.get("heard", "")).strip()
    write = str(e.get("write", "")).strip()
    if not heard:
        return None
    return {
        "id": str(e.get("id") or uuid.uuid4().hex[:8]),
        "heard": heard,
        "write": write,
        "enabled": bool(e.get("enabled", True)),
    }


def _load() -> None:
    global _LOADED, _ENTRIES
    if _LOADED:
        return
    entries: list[dict] = []
    try:
        if _STORE.exists():
            data = json.loads(_STORE.read_text(encoding="utf-8"))
            raw = data.get("entries") if isinstance(data, dict) else None
            for e in raw or []:
                c = _clean(e)
                if c:
                    entries.append(c)
    except Exception:
        entries = []
    _ENTRIES = entries
    _recompile()
    _LOADED = True


def _save() -> None:
    try:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = _STORE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"entries": _ENTRIES}, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(_STORE)
    except Exception:
        pass  # a failed save must never break the edit or the voice loop


def _recompile() -> None:
    """Rebuild the compiled matcher from the enabled entries. Longest phrases first so a multi-word
    rule wins over a single-word one; \\b boundaries keep it whole-word."""
    global _PATTERN, _MAP
    enabled = [(e["heard"], e["write"]) for e in _ENTRIES if e.get("enabled", True) and e["heard"]]
    _MAP = {h.lower(): w for h, w in enabled}
    if not enabled:
        _PATTERN = None
        return
    alts = sorted((re.escape(h) for h, _ in enabled), key=len, reverse=True)
    try:
        _PATTERN = re.compile(r"\b(" + "|".join(alts) + r")\b", re.IGNORECASE)
    except re.error:
        _PATTERN = None


# --- the hot path -------------------------------------------------------------------------------

def apply(text: str) -> str:
    """Apply the correction map to a transcript. Guarded — returns ``text`` unchanged on any problem."""
    try:
        with _LOCK:
            _load()
            if not _PATTERN or not text:
                return text
            return _PATTERN.sub(lambda m: _MAP.get(m.group(0).lower(), m.group(0)), text)
    except Exception:
        return text


# --- CRUD (used by the dashboard bridge; mutates in-memory state so edits apply live) -------------

def list_entries() -> list[dict]:
    with _LOCK:
        _load()
        return [dict(e) for e in _ENTRIES]


def add(heard: str, write: str) -> dict:
    """Add a correction. Raises ValueError if ``heard`` is blank. ``write`` may be empty (deletes the
    heard word). If ``heard`` already exists (case-insensitive), its ``write`` is updated instead."""
    heard = (heard or "").strip()
    write = (write or "").strip()
    if not heard:
        raise ValueError("'heard' is required")
    with _LOCK:
        _load()
        for e in _ENTRIES:  # de-dupe by heard (case-insensitive) → update rather than duplicate
            if e["heard"].lower() == heard.lower():
                e["write"] = write
                e["enabled"] = True
                _recompile()
                _save()
                return dict(e)
        entry = {"id": uuid.uuid4().hex[:8], "heard": heard, "write": write, "enabled": True}
        _ENTRIES.append(entry)
        _recompile()
        _save()
        return dict(entry)


def update(entry_id: str, *, heard=None, write=None, enabled=None) -> dict | None:
    with _LOCK:
        _load()
        target = next((e for e in _ENTRIES if e["id"] == str(entry_id)), None)
        if target is None:
            return None
        if heard is not None:
            if not str(heard).strip():
                raise ValueError("'heard' cannot be blank")
            target["heard"] = str(heard).strip()
        if write is not None:
            target["write"] = str(write).strip()
        if enabled is not None:
            target["enabled"] = bool(enabled)
        _recompile()
        _save()
        return dict(target)


def remove(entry_id: str) -> bool:
    with _LOCK:
        _load()
        before = len(_ENTRIES)
        _ENTRIES[:] = [e for e in _ENTRIES if e["id"] != str(entry_id)]
        removed = len(_ENTRIES) < before
        if removed:
            _recompile()
            _save()
        return removed


# --- CLI: quick manual test ----------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 3 and sys.argv[1] == "--try":
        add("clawed", "Claude")
        add("clawed code", "Claude Code")
        print("entries:", list_entries())
        print(f"  {sys.argv[2]!r} → {apply(sys.argv[2])!r}")
    else:
        print("entries:", list_entries())
        print('try:  python -m vox.vocab --try "open clawed code please"')
