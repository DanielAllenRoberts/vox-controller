"""Short-term (working) memory: what was just said and done, across every mode.

Why this exists (seen live 2026-11-07): "add a card for X" → "move it to Doing" moved a DIFFERENT
card, and "clear my board" → "now put them all back" got "which ones?". Each request from idle runs
as a fresh one-shot with no history, and the only record of past actions (``command_log``) holds
app/site commands, not board changes, replies or web answers. So the brain couldn't resolve "it",
"them" or "put it back".

This keeps a short rolling timeline of
  • ``user``  what the user said or typed,
  • ``vox``   what Vox said back,
  • ``did``   what Vox actually changed, in detail (card ids, titles, columns, what was deleted),
and renders the recent part as a prompt block for BOTH brains. Persisted to a small JSON file so a
restart (frequent while developing) doesn't wipe it. Everything is guarded: a failure here must
never break the voice loop.
"""

from __future__ import annotations

import json
import threading
import time
from collections import deque

from vox.paths import DATA_DIR

_STORE = DATA_DIR / "working_memory.json"
_LOCK = threading.Lock()
_MAX_EVENTS = 400                # kept on disk / in RAM (prompts only ever see the last 30 min)
_KEEP_SECONDS = 26 * 3600        # a day, so the overnight memory tidy (vox.dream) can read it
_events: deque | None = None


def _load() -> deque:
    global _events
    if _events is None:
        try:
            raw = json.loads(_STORE.read_text())
            _events = deque((e for e in raw if isinstance(e, dict)), maxlen=_MAX_EVENTS)
        except Exception:
            _events = deque(maxlen=_MAX_EVENTS)
    return _events


def _save(ev: deque) -> None:
    try:
        _STORE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _STORE.with_suffix(".tmp")
        tmp.write_text(json.dumps(list(ev)))
        tmp.replace(_STORE)
    except Exception:
        pass


def note(who: str, text: str) -> None:
    """Append one event. ``who`` is "user" | "vox" | "did"."""
    text = " ".join(str(text or "").split())
    if not text:
        return
    try:
        with _LOCK:
            ev = _load()
            now = time.time()
            # The same line twice in a row (a turn recorded by two paths) is one event.
            if ev and ev[-1].get("who") == who and ev[-1].get("text") == text and now - ev[-1].get("ts", 0) < 5:
                return
            ev.append({"ts": now, "who": who, "text": text[:600]})
            while ev and now - ev[0].get("ts", now) > _KEEP_SECONDS:
                ev.popleft()
            _save(ev)
    except Exception:
        pass


def note_user(text: str) -> None:
    note("user", text)


def note_reply(text: str) -> None:
    note("vox", text)


def note_did(text: str) -> None:
    note("did", text)


def recent(minutes: float = 30, limit: int = 24) -> list[dict]:
    """Events from the last ``minutes``, oldest first, at most ``limit``."""
    try:
        with _LOCK:
            ev = list(_load())
    except Exception:
        return []
    cutoff = time.time() - minutes * 60
    return [e for e in ev if e.get("ts", 0) >= cutoff][-limit:]


def _ago(ts: float) -> str:
    s = max(0, int(time.time() - ts))
    if s < 60:
        return "just now"
    m = s // 60
    return f"{m} min ago" if m < 60 else f"{m // 60} h ago"


def block(minutes: float = 30, limit: int = 24, max_chars: int = 3500) -> str:
    """The recent timeline as prompt text, or "" when there's nothing recent."""
    events = recent(minutes, limit)
    if not events:
        return ""
    label = {"user": "User said", "vox": "You said", "did": "You did"}
    lines = [f"  {_ago(e['ts'])} · {label.get(e.get('who'), e.get('who'))}: {e.get('text', '')}" for e in events]
    body = "\n".join(lines)
    while len(body) > max_chars and len(lines) > 4:   # drop the oldest first
        lines.pop(0)
        body = "\n".join(lines)
    return ("[Recent conversation and what you did (oldest first). This is your short-term memory. "
            "Use it to work out what 'it', 'that', 'them', 'those', 'the one I just added', 'undo "
            "that' or 'put them back' refer to: usually the most recent matching thing here. If "
            "something here was deleted, it can be brought back. Don't ask the user to repeat "
            "something that is listed here.]\n" + body)


def clear() -> None:
    try:
        with _LOCK:
            ev = _load()
            ev.clear()
            _save(ev)
    except Exception:
        pass
