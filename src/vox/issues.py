"""Issues the user logs by voice ("log an issue: the circle thing didn't work"), and the ones Vox
logs by itself whenever it tells you it couldn't do something (``note_cant``).

Saying it is quicker than writing it down mid-flow, and the moment it happens is when the useful
context exists: what was on screen, what was just said, what Vox just did. All of that is captured
with the user's words. Stored as JSON lines in ``<data>/issues.jsonl``; shown in Vox.app under
Insights → Testing, and read by whoever is fixing things (``GET /api/issues``).
"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid

from vox.paths import DATA_DIR

_FILE = DATA_DIR / "issues.jsonl"
_LOCK = threading.Lock()


def _context() -> dict:
    ctx: dict = {}
    try:
        from vox import actions
        ctx["app"] = actions.frontmost_app()
        ctx["recentActions"] = actions.recent_actions_block() or ""
    except Exception:
        pass
    try:
        from vox.web import conversation
        turns = conversation.recent(8) or []
        ctx["recentTurns"] = [f"{t.get('role')}: {t.get('text')}" for t in reversed(turns)]
    except Exception:
        pass
    ctx["recentLog"] = _recent_log()
    return ctx


_LOG_MARKERS = ("heard", "you:", "you (typed)", "decision=", "⚡", "🔊", "[learn]", "click", "→")


def _recent_log(n: int = 25) -> list[str]:
    """The last few meaningful lines of vox.log: what was heard and decided just before the issue.
    Unlike the conversation feed (in memory, emptied by every restart), the log survives."""
    try:
        from vox.config import CONFIG
        with open(CONFIG.log_file, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 60_000))
            tail = f.read().decode("utf-8", "replace").splitlines()[1:]
        keep = [ln.strip()[:300] for ln in tail if any(m in ln for m in _LOG_MARKERS)
                and not ln.lstrip().startswith(("[debug][prompt", "[user]", "[assistant]"))]
        return keep[-n:]
    except Exception:
        return []


def add(text: str, **extra) -> dict:
    entry = {"id": uuid.uuid4().hex[:8], "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
             "text": (text or "").strip(), "status": "open", **extra, "context": _context()}
    with _LOCK:
        _FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    return entry


# --- logged by Vox itself: things it couldn't do ----------------------------------------------
# Every time Vox answers with "I can't…" / "I couldn't…", that's a gap: a missing command or tool,
# something it couldn't see, a prompt that led it astray, a brain that didn't answer. Each one is
# saved with the same context as a spoken issue (what was said, what Vox did, the log around it), so
# the list can be read later and the gaps closed. Entries carry ``"source": "auto"``.
_CANT = re.compile(
    r"^\W*(?:sorry\W+)?(?:i\s+(?:can(?:'|’)?t|cannot|couldn(?:'|’)?t|could not|don(?:'|’)?t know how|"
    r"don(?:'|’)?t have|wasn(?:'|’)?t able|am not able|(?:'|’)?m not able|am unable)|i(?:'|’)m (?:not able|unable)|"
    r"couldn(?:'|’)?t|can(?:'|’)?t|unable to|my brain didn(?:'|’)?t answer|that(?:'|’)?s not something i can)\b", re.I)

# What the brain said it would have needed (the first half of its CANT: line), for the next note.
missing_hint = ""
_last_cant: tuple[str, float] = ("", 0.0)


def is_cant(reply: str) -> bool:
    return bool(_CANT.match(reply or ""))


def note_cant(heard: str, reply: str) -> None:
    """Log that Vox couldn't do ``heard`` (it answered ``reply``). Returns at once: the context is
    gathered and written on a background thread so the spoken reply isn't held up. The same request
    failing again within ten minutes is logged once."""
    global missing_hint, _last_cant
    missing, missing_hint = missing_hint, ""
    key = " ".join((heard or "").lower().split())
    if not key or (key == _last_cant[0] and time.time() - _last_cant[1] < 600):
        return
    _last_cant = (key, time.time())

    def write():
        try:
            add(f"Couldn't do: \u201C{heard.strip()}\u201D", source="auto", heard=heard.strip(),
                reply=(reply or "").strip()[:400], missing=missing)
        except Exception:
            pass

    threading.Thread(target=write, daemon=True).start()


def _all_raw() -> list[dict]:
    try:
        return [json.loads(line) for line in _FILE.read_text(encoding="utf-8").splitlines() if line.strip()]
    except Exception:
        return []


def all_issues() -> list[dict]:
    return sorted(_all_raw(), key=lambda e: e.get("ts", ""), reverse=True)


def set_status(iid: str, status: str, note: str | None = None) -> dict:
    if status not in ("open", "fixed", "wontfix"):
        raise ValueError("status must be open, fixed or wontfix")
    with _LOCK:
        items = _all_raw()
        hit = next((e for e in items if e.get("id") == iid), None)
        if hit is None:
            raise KeyError(iid)
        hit["status"] = status
        if note is not None:
            hit["note"] = note.strip()
        tmp = _FILE.with_suffix(".tmp")
        tmp.write_text("".join(json.dumps(e) + "\n" for e in items), encoding="utf-8")
        tmp.replace(_FILE)
    return hit
