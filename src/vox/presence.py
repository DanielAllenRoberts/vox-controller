"""Is the user at the Mac? (ideas #60: reminders that wait until you're there.)

Away = the screen is locked, or there's been no keyboard/mouse input AND nothing said or typed to
Vox for ``reminder_away_minutes``. Talking to Vox counts as being here: someone using it by voice
alone never touches the keyboard. Guarded: if it can't tell, it says "here", so nothing is held.
"""

from __future__ import annotations

import time


def _setting(key: str, fallback):
    try:
        from vox.web import settings_store
        val = settings_store.get(key)
        return fallback if val is None else val
    except Exception:
        return fallback


def idle_seconds() -> float:
    """Seconds since the last keyboard/mouse/trackpad input (0 if unknown)."""
    try:
        import Quartz
        return float(Quartz.CGEventSourceSecondsSinceLastEventType(
            Quartz.kCGEventSourceStateHIDSystemState, Quartz.kCGAnyInputEventType))
    except Exception:
        return 0.0


def screen_locked() -> bool:
    try:
        import Quartz
        d = Quartz.CGSessionCopyCurrentDictionary()
        return bool(d and d.get("CGSSessionScreenIsLocked"))
    except Exception:
        return False


def _last_spoke() -> float:
    """Seconds since the user last said or typed something to Vox (inf if never)."""
    try:
        from vox import working_memory
        said = [e for e in working_memory.recent(minutes=120, limit=400) if e.get("who") == "user"]
        return time.time() - said[-1]["ts"] if said else float("inf")
    except Exception:
        return float("inf")


def away() -> bool:
    if screen_locked():
        return True
    limit = float(_setting("reminder_away_minutes", 5) or 5) * 60
    return idle_seconds() > limit and _last_spoke() > limit
