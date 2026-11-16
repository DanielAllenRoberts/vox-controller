"""Overnight memory tidy ("dream", ideas #28): once a day, pick up lasting facts the day missed.

In the moment the chat brain only saves a fact when it notices one. Once a day (first scheduler tick
after 03:00, so a Mac asleep at 3 a.m. catches up when it wakes) this reads what the user said over
the last day (``working_memory``) plus the daily notes, asks the small brain for durable facts about
the PERSON, and saves each through ``assistant._save_core``: the same path as live capture, so a
fact that replaces an old one updates it and a repeat isn't stored twice. How-to notes and tasks are
filtered out exactly as in live capture. Off with the ``memory_dream`` setting.
"""

from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime, timedelta

from vox.paths import DATA_DIR

_STATE = DATA_DIR / "dream.json"
_RUNNING = threading.Lock()
_HOUR = 3

_SYSTEM = (
    "You tidy a voice assistant's long-term memory overnight. Below is what the user said to the "
    "assistant over the last day, and the day's notes. List the DURABLE facts about the PERSON worth "
    "remembering for months: who they are, the people in their life, where they live and work, "
    "health, strong preferences, important dates, ongoing projects. NOT tasks, reminders, one-off "
    "plans, how to operate the assistant, or anything about what's on their screen. Write each as one "
    "line 'FACT: The user …' in plain words. If there's nothing lasting, reply NONE. Never invent."
)


def _setting(key: str, fallback):
    try:
        from vox.web import settings_store
        val = settings_store.get(key)
        return fallback if val is None else val
    except Exception:
        return fallback


def _last_run() -> str:
    try:
        return json.loads(_STATE.read_text()).get("last", "")
    except Exception:
        return ""


def _mark(day: str, found: int) -> None:
    try:
        _STATE.parent.mkdir(parents=True, exist_ok=True)
        _STATE.write_text(json.dumps({"last": day, "facts": found, "at": time.strftime("%Y-%m-%dT%H:%M:%S")}))
    except Exception:
        pass


def material(hours: float = 24) -> str:
    """What the user said in the last ``hours`` and the daily notes for today and yesterday."""
    parts = []
    try:
        from vox import working_memory
        said = [e["text"] for e in working_memory.recent(minutes=hours * 60, limit=400) if e.get("who") == "user"]
        if said:
            parts.append("[What the user said]\n" + "\n".join(f"- {t}" for t in said))
    except Exception:
        pass
    try:
        from vox import memory
        today = datetime.now().date()
        notes = []
        for d in (today - timedelta(days=1), today):
            notes += [e["text"] for e in memory.daily(d.isoformat())]
        if notes:
            parts.append("[Daily notes]\n" + "\n".join(f"- {t}" for t in notes))
    except Exception:
        pass
    return "\n\n".join(parts)


def run() -> list[str]:
    """Do one tidy now. Returns the facts it saved (or updated)."""
    text = material()
    if len(text) < 40:
        return []
    from vox import assistant
    try:
        raw = assistant.complete(text[-20000:], None, brain="small", system=_SYSTEM, kind="memory",
                                 prompt="memory_dream").strip()
    except Exception:
        return []
    facts = [m.group(1).strip() for m in re.finditer(r"(?im)^\s*FACT:\s*(.+)$", raw)]
    saved = []
    for f in facts[:20]:
        if assistant._core_ok(f):
            assistant._save_core(f)   # updates a replaced fact, skips a repeat
            saved.append(f)
    assistant._dbg("[dream]", f"{len(saved)} lasting fact(s) from the last day: {saved}")
    return saved


def maybe_run() -> None:
    """Called from the scheduler tick: run once a day after 03:00, in the background."""
    if not _setting("memory_dream", True):
        return
    now = datetime.now()
    today = now.date().isoformat()
    if now.hour < _HOUR or _last_run() == today:
        return
    if not _RUNNING.acquire(blocking=False):
        return
    _mark(today, 0)   # claim the day first: a failure shouldn't retry every tick

    def work():
        try:
            _mark(today, len(run()))
        finally:
            _RUNNING.release()

    threading.Thread(target=work, name="vox-dream", daemon=True).start()
