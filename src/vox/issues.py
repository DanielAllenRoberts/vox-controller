"""Issues the user logs by voice ("log an issue: the circle thing didn't work").

Saying it is quicker than writing it down mid-flow, and the moment it happens is when the useful
context exists: what was on screen, what was just said, what Vox just did. All of that is captured
with the user's words. Stored as JSON lines in ``<data>/issues.jsonl``; shown in Vox.app under
Insights → Testing, and read by whoever is fixing things (``GET /api/issues``).
"""

from __future__ import annotations

import json
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


def add(text: str) -> dict:
    entry = {"id": uuid.uuid4().hex[:8], "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
             "text": (text or "").strip(), "status": "open", "context": _context()}
    with _LOCK:
        _FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    return entry


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
