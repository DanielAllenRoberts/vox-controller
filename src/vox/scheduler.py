"""Vox-owned scheduler: timers, alarms, and reminders (idea #16).

ONE unified "scheduled job" model covers all three — they differ only in how the
time is expressed, whether they recur, and how they announce when they fire. Vox
owning the jobs is what lets the dashboard *show and cancel everything in one
place* (the feature the user asked for). On top of that, a job can OPTIONALLY be
mirrored to **Apple Reminders** (AppleScript-scriptable + iCloud-synced) so it
also goes off on the phone — default OFF, guarded.

Storage: ``data/reminders.json`` (gitignored, like the other ``data/*.json``
stores). A job is::

    {id, kind: "timer"|"alarm"|"reminder", text, fire_at (ISO local),
     recurrence: null|"daily"|"weekdays"|"weekly", created_at, enabled}

Engine: a background thread (the voice loop is synchronous, so firing lives off
it). It wakes every ~``scheduler_poll_seconds``, fires due jobs per the output
policy below, then deletes a one-shot or rolls a recurring job to its next
occurrence. Persisted to disk so it survives a restart; on startup, recently-
overdue one-shots (< ~1h) fire once with a "While you were away — …" prefix and
older ones are dropped; recurring jobs just resume.

Output policy (the per-kind default; the firing function takes them all the same
way so they stay configurable):
  • reminder → SPEAK, personalised with the user's name from core memory if we
    have it ("Hey <name>, reminding you to <text>"), plus a soft sound.
  • timer    → SOUND only (a short "timer's up" chime).
  • alarm    → BOTH a sound and a spoken line.

Everything here is GUARDED: the thread never raises out (a bad job, a TTS hiccup,
a disk error are all swallowed) so the scheduler can never take down the daemon.
``parse_and_create`` is deterministic-first for the obvious shapes; it returns a
human result string for the voice layer to speak, or None when nothing matched.
"""

from __future__ import annotations

import re
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from vox.config import CONFIG

# Runtime store lives under data/ (gitignored). This file is
# src/vox/scheduler.py → parents[2] is the repo root.
_DATA_DIR = Path(__file__).resolve().parents[2] / "data"
_STORE = _DATA_DIR / "reminders.json"

_LOCK = threading.RLock()

# Singleton background thread (started once from the daemon).
_THREAD: "_SchedulerThread | None" = None

# Weekday names → datetime.weekday() index (Mon=0). Used by "every <weekday> at …".
_WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}

VALID_KINDS = ("timer", "alarm", "reminder")
VALID_RECURRENCE = (None, "daily", "weekdays", "weekly")


# --- Persistence -----------------------------------------------------------
# Stored shape: {"jobs": [Job, ...]}. fire_at / created_at are ISO LOCAL strings
# (naive, no tz) so relative parsing ("in 20 min") anchors to datetime.now().

def _now() -> datetime:
    return datetime.now()


def _iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat()


def _parse_iso(s) -> datetime | None:
    if not isinstance(s, str) or not s.strip():
        return None
    try:
        return datetime.fromisoformat(s.strip())
    except ValueError:
        return None


def _clean_job(j) -> dict | None:
    """Coerce a loaded entry to a valid Job dict, or None if unusable."""
    if not isinstance(j, dict):
        return None
    jid = j.get("id")
    kind = j.get("kind")
    if not isinstance(jid, str) or not jid:
        return None
    if kind not in VALID_KINDS:
        return None
    if _parse_iso(j.get("fire_at")) is None:
        return None
    rec = j.get("recurrence")
    if rec not in VALID_RECURRENCE:
        rec = None
    return {
        "id": jid,
        "kind": kind,
        "text": str(j.get("text") or ""),
        "fire_at": j["fire_at"],
        "recurrence": rec,
        "created_at": j.get("created_at") or _iso(_now()),
        "enabled": bool(j.get("enabled", True)),
    }


def _load() -> list[dict]:
    if not _STORE.exists():
        return []
    try:
        import json
        with _STORE.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []
    raw = data.get("jobs") if isinstance(data, dict) else data
    if not isinstance(raw, list):
        return []
    return [c for c in (_clean_job(j) for j in raw) if c is not None]


def _save(jobs: list[dict]) -> None:
    import json
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _STORE.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump({"jobs": jobs}, f, ensure_ascii=False, indent=2)
    tmp.replace(_STORE)


# --- The user's name (for personalised reminders) --------------------------

def _user_name() -> str:
    """Best-effort first name from core memory, for "Hey <name>, …". "" if unknown.

    Scans core bullets for "my name is X" / "I'm X" / "call me X". Fully guarded —
    a missing/odd memory store just yields "" and reminders go generic."""
    try:
        from vox import memory
        for entry in memory.core():
            t = (entry.get("text") or "").lower()
            m = re.search(r"(?:name is|i am|i'm|call me|named)\s+([a-z][a-z'\-]+)", t)
            if m:
                return m.group(1).capitalize()
    except Exception:
        pass
    return ""


# --- Output policy: announce a fired job -----------------------------------

def _announce(job: dict, *, prefix: str = "") -> None:
    """Fire a job per the output policy. Reads cfg sounds + tts.speak, fully guarded.

    ``prefix`` (e.g. "While you were away — ") is prepended to the spoken line for
    a one-shot that fired late on startup."""
    from vox import sounds, tts
    kind = job.get("kind")
    text = (job.get("text") or "").strip()
    spoken = ""
    if kind == "reminder":
        name = _user_name()
        body = text or "this is your reminder"
        spoken = f"{prefix}Hey {name}, reminding you to {body}." if name \
            else f"{prefix}Reminding you to {body}."
        sound, times = getattr(CONFIG, "sound_reminder", ""), 1
    elif kind == "alarm":
        spoken = f"{prefix}Alarm{f' — {text}' if text else ''}."
        sound = getattr(CONFIG, "sound_alarm", "") or getattr(CONFIG, "sound_timer", "")
        times = max(1, int(getattr(CONFIG, "sound_alarm_repeat", 4)))
    else:  # timer → a couple of chimes, no spoken line by default.
        sound, times = getattr(CONFIG, "sound_timer", ""), 2
    try:
        if sound:
            sounds.play_n(sound, times)
    except Exception:
        pass
    try:
        if spoken:
            tts.speak(spoken)
    except Exception:
        pass


# --- Recurrence: advance a fired recurring job to its next occurrence -------

def _advance(dt: datetime, recurrence: str) -> datetime:
    """Next fire time for a recurring job after it fired at ``dt`` (same time-of-day)."""
    if recurrence == "weekly":
        return dt + timedelta(days=7)
    if recurrence == "weekdays":
        nxt = dt + timedelta(days=1)
        while nxt.weekday() >= 5:  # skip Sat/Sun
            nxt += timedelta(days=1)
        return nxt
    return dt + timedelta(days=1)  # daily (default)


# --- CRUD (server + voice) -------------------------------------------------

def list_jobs() -> list[dict]:
    """All scheduled jobs, soonest first (CONTRACT GET /api/reminders)."""
    with _LOCK:
        jobs = _load()
    return sorted(jobs, key=lambda j: j.get("fire_at") or "")


def create_job(kind: str, text: str = "", *, fire_at: datetime | str | None = None,
               recurrence: str | None = None, enabled: bool = True) -> dict:
    """Create + persist a job. ``fire_at`` is a datetime or ISO-local string.

    Optionally mirrors to Apple Reminders when the config toggle is on (default
    OFF). Returns the stored Job dict."""
    if kind not in VALID_KINDS:
        raise ValueError(f"unknown kind: {kind!r}")
    dt = fire_at if isinstance(fire_at, datetime) else _parse_iso(fire_at)
    if dt is None:
        raise ValueError("fire_at is required")
    if recurrence not in VALID_RECURRENCE:
        recurrence = None
    job = {
        "id": uuid.uuid4().hex[:12],
        "kind": kind,
        "text": (text or "").strip(),
        "fire_at": _iso(dt),
        "recurrence": recurrence,
        "created_at": _iso(_now()),
        "enabled": bool(enabled),
    }
    with _LOCK:
        jobs = _load()
        jobs.append(job)
        _save(jobs)
    if kind == "reminder":
        mirror_to_apple_reminders(job["text"], dt)  # guarded; no-op unless toggled on
    return job


def cancel_job(job_id) -> bool:
    """Cancel (delete) the job with ``job_id``. True if one was removed."""
    job_id = "" if job_id is None else str(job_id)
    if not job_id:
        return False
    with _LOCK:
        jobs = _load()
        kept = [j for j in jobs if j["id"] != job_id]
        removed = len(kept) < len(jobs)
        if removed:
            _save(kept)
    return removed


def cancel_matching(text: str) -> int:
    """Cancel jobs matching a voice phrase ("cancel my timer", "cancel the 3pm reminder").

    A bare kind word ("timer"/"alarm"/"reminder") cancels all of that kind; any
    other words must appear in the job's text. Returns how many were cancelled."""
    t = (text or "").lower()
    kind = next((k for k in VALID_KINDS if k in t), None)
    # Words to match against job text, minus the command/kind filler.
    filler = {"cancel", "clear", "delete", "remove", "my", "the", "a", "all", "stop",
              "timer", "timers", "alarm", "alarms", "reminder", "reminders", "to"}
    words = [w for w in re.findall(r"[a-z0-9]+", t) if w not in filler]
    with _LOCK:
        jobs = _load()
        keep, killed = [], 0
        for j in jobs:
            kind_ok = kind is None or j["kind"] == kind
            text_ok = not words or all(w in (j.get("text") or "").lower() for w in words)
            if kind_ok and text_ok:
                killed += 1
            else:
                keep.append(j)
        if killed:
            _save(keep)
    return killed


# --- Time parsing (deterministic-first) ------------------------------------

_UNIT_SECONDS = {"second": 1, "minute": 60, "hour": 3600}

# Whisper transcribes spoken numbers as WORDS ("two minutes", not "2 minutes"), so the digit-based
# time regexes below missed almost every spoken reminder. _digitize() converts number words to
# digits first. (NOTE: "a"/"an" are handled separately — only when they directly precede a time
# unit — so "set A timer" isn't mangled into "set 1 timer".)
_NUM_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
    "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
_NUM_RE = re.compile(r"\b(" + "|".join(_NUM_WORDS) + r")(?:[\s-]+(" + "|".join(_NUM_WORDS) + r"))?\b")
_RE_A_UNIT = re.compile(r"\b(?:a|an)\s+(seconds?|minutes?|hours?|secs?|mins?|hrs?)\b")


def _digitize(t: str) -> str:
    """Replace spoken number words with digits: "two minutes"→"2 minutes", "twenty-five"→"25",
    "in a minute"→"in 1 minute" (the a/an form only right before a time unit)."""
    def repl(m):
        a = _NUM_WORDS[m.group(1)]
        if m.group(2):
            b = _NUM_WORDS[m.group(2)]
            if a in (20, 30, 40, 50, 60, 70, 80, 90) and 1 <= b <= 9:
                return str(a + b)        # "twenty five" → 25
            return f"{a} {b}"            # two unrelated numbers → keep both
        return str(a)
    return _RE_A_UNIT.sub(r"1 \1", _NUM_RE.sub(repl, t))


_RE_TIMER = re.compile(
    r"\b(?:set\s+(?:a|an)\s+)?timer\s+for\s+(\d+)\s*(seconds?|minutes?|hours?|secs?|mins?|hrs?)\b")
# Capture the task EITHER before "in" ("remind me to X in 5 min") OR after the unit
# ("remind me in 5 min to X") — both are natural and Whisper produces both orders.
_RE_REMIND_IN = re.compile(
    r"\bremind\s+me\s+(?:to\s+(.+?)\s+)?in\s+(\d+)\s*(seconds?|minutes?|hours?|secs?|mins?|hrs?)\b"
    r"(?:\s+to\s+(.+))?")
_RE_REMIND_AT = re.compile(
    r"\bremind\s+me\s+(?:to\s+(.+?)\s+)?at\s+(\d{1,2})(?::(\d{2}))?\s*([ap]\.?m\.?)?(?:\s+to\s+(.+?))?$")
# `(?:for|at)+` (not just one) tolerates "alarm for at 8am" left behind after a day word like
# "tomorrow" is stripped from "set an alarm for tomorrow at 8am".
_RE_ALARM_AT = re.compile(
    r"\b(?:set\s+(?:an|a)\s+)?alarm\s+(?:(?:for|at)\s+)+(\d{1,2})(?::(\d{2}))?\s*([ap]\.?m\.?)?(?:\s+to\s+(.+?))?$")
_RE_EVERY = re.compile(
    r"\bevery\s+(day|weekday|weekdays|week|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b")
# A day qualifier ("tomorrow", "tonight", "this evening", "on Monday") that shifts the at-time to
# another day. Captured + stripped so the at-time regexes see a clean "... at 8am".
_RE_DAY = re.compile(
    r"\b(tomorrow|tonight|today|this\s+(?:morning|afternoon|evening|night)|"
    r"(?:on\s+|next\s+)?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday))\b")


def _unit_base(unit: str) -> str:
    u = unit.rstrip("s")
    return {"sec": "second", "min": "minute", "hr": "hour"}.get(u, u)


def _next_clock(hour: int, minute: int, ampm: str | None, *,
                offset_days: int | None = None, evening: bool = False) -> datetime | None:
    """The datetime matching H:MM (am/pm optional). With ``offset_days`` set (from a day word like
    "tomorrow"), it's that many days from today; otherwise the NEXT occurrence (today if still
    ahead, else tomorrow). ``evening`` (from "tonight"/"this evening") defaults a bare 1–11 to pm.
    Returns None on an invalid clock value."""
    ap = (ampm or "").replace(".", "").lower()
    if not ap and evening and 1 <= hour <= 11:
        ap = "pm"  # "tonight at 8" → 8pm
    if ap == "pm" and hour < 12:
        hour += 12
    elif ap == "am" and hour == 12:
        hour = 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    now = _now()
    base = now + timedelta(days=offset_days) if offset_days is not None else now
    target = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:  # already past (e.g. "today at 8" said at noon) → roll a day
        target += timedelta(days=1)
    return target


def _day_offset(t: str) -> tuple[int | None, bool, str]:
    """Find a day qualifier ("tomorrow", "tonight", "this evening", "on Monday") and return
    ``(offset_days, is_evening, text_without_that_phrase)``; ``(None, False, t)`` if there's none."""
    m = _RE_DAY.search(t)
    if not m:
        return None, False, t
    phrase = m.group(1)
    stripped = " ".join((t[:m.start()] + " " + t[m.end():]).split())
    evening = ("evening" in phrase) or ("night" in phrase) or (phrase == "tonight")
    if phrase == "tomorrow":
        return 1, evening, stripped
    if phrase in ("today", "tonight") or phrase.startswith("this"):
        return 0, evening, stripped
    for name, idx in _WEEKDAYS.items():
        if name in phrase:
            return ((idx - _now().weekday()) % 7 or 7), evening, stripped  # next such weekday
    return None, False, t


def _recurrence_from(text: str) -> str | None:
    """Map an "every …" phrase to a recurrence, or None."""
    m = _RE_EVERY.search(text)
    if not m:
        return None
    word = m.group(1)
    if word in ("day",):
        return "daily"
    if word in ("weekday", "weekdays"):
        return "weekdays"
    if word in ("week",) or word in _WEEKDAYS:
        return "weekly"
    return None


def parse_and_create(text: str) -> str | None:
    """Parse a scheduler utterance and create the job; return a human result line.

    Deterministic-first for the obvious shapes:
      • "(set a )?timer for N seconds|minutes|hours"          → timer (relative)
      • "remind me (to X )?in N minutes|hours"                → reminder (relative)
      • "remind me (to X )?at H[:MM][ ]?(am|pm)?( to X)?"     → reminder (absolute)
      • "(set an )?alarm for|at H[:MM][ ]?(am|pm)?( to X)?"   → alarm (absolute)
    An "every day|weekday|<weekday> at …" phrase sets recurrence on the at-time
    forms. Returns None when nothing matched (the caller then escalates / ignores)."""
    if not text or not text.strip():
        return None
    t = _digitize(" ".join(text.lower().split()))  # spoken number words → digits first
    recurrence = _recurrence_from(t)
    # Strip the "every <day>" span so the at-time regexes see a clean "remind me at H…"
    # ("remind me every day at 9 am" → "remind me at 9 am"); recurrence is already captured.
    if recurrence:
        t = " ".join(_RE_EVERY.sub(" ", t).split())
    # A day word ("tomorrow", "tonight", "on Friday") shifts the at-time; strip it so the at-time
    # regexes see a clean phrase. (Recurring jobs already say "every …", so skip the day word there.)
    offset_days, evening = (None, False)
    if not recurrence:
        offset_days, evening, t = _day_offset(t)

    # timer for N <unit> — sound-only countdown.
    m = _RE_TIMER.search(t)
    if m:
        n, unit = int(m.group(1)), _unit_base(m.group(2))
        fire = _now() + timedelta(seconds=n * _UNIT_SECONDS[unit])
        create_job("timer", "", fire_at=fire)
        return f"Timer set for {n} {unit}{'s' if n != 1 else ''}."

    # remind me (to X) in N <unit> (to X) — relative reminder; task may be before "in" or after.
    m = _RE_REMIND_IN.search(t)
    if m:
        body = (m.group(1) or m.group(4) or "").strip()
        n, unit = int(m.group(2)), _unit_base(m.group(3))
        fire = _now() + timedelta(seconds=n * _UNIT_SECONDS[unit])
        create_job("reminder", body, fire_at=fire)
        when = f"in {n} {unit}{'s' if n != 1 else ''}"
        return f"I'll remind you to {body} {when}." if body else f"I'll remind you {when}."

    # remind me (to X) at H:MM (am/pm) (to X) — absolute reminder.
    m = _RE_REMIND_AT.search(t)
    if m:
        fire = _next_clock(int(m.group(2)), int(m.group(3) or 0), m.group(4),
                           offset_days=offset_days, evening=evening)
        if fire is not None:
            body = (m.group(1) or m.group(5) or "").strip()
            create_job("reminder", body, fire_at=fire, recurrence=recurrence)
            return _confirm("reminder", body, fire, recurrence)

    # (set an) alarm for|at H:MM (am/pm) (to X) — absolute alarm.
    m = _RE_ALARM_AT.search(t)
    if m:
        fire = _next_clock(int(m.group(1)), int(m.group(2) or 0), m.group(3),
                           offset_days=offset_days, evening=evening)
        if fire is not None:
            body = (m.group(4) or "").strip()
            create_job("alarm", body, fire_at=fire, recurrence=recurrence)
            return _confirm("alarm", body, fire, recurrence)

    return None


def _confirm(kind: str, body: str, fire: datetime, recurrence: str | None) -> str:
    """Human confirmation line for an at-time job."""
    when = fire.strftime("%-I:%M %p").lower() if hasattr(fire, "strftime") else _iso(fire)
    day = ""
    if not recurrence and hasattr(fire, "date"):
        delta = (fire.date() - _now().date()).days
        if delta == 1:
            day = " tomorrow"
        elif delta > 1:
            day = fire.strftime(" on %A")
    every = {"daily": " every day", "weekdays": " every weekday", "weekly": " every week"}.get(
        recurrence or "", "")
    label = "reminder" if kind == "reminder" else "alarm"
    tail = f" to {body}" if body else ""
    return f"{label.capitalize()} set for {when}{day}{every}{tail}."


def summary() -> str:
    """A short spoken summary of active jobs ("what are my timers/reminders")."""
    jobs = list_jobs()
    if not jobs:
        return "You have no timers, alarms, or reminders set."
    parts = []
    for j in jobs[:6]:
        when = _parse_iso(j["fire_at"])
        clock = when.strftime("%-I:%M %p").lower() if when else "?"
        txt = (j.get("text") or "").strip()
        parts.append(f"a {j['kind']} at {clock}" + (f" to {txt}" if txt else ""))
    head = f"You have {len(jobs)} scheduled: " if len(jobs) > 1 else "You have "
    return head + ("; ".join(parts)) + "."


# --- Apple Reminders mirror (optional, default OFF) ------------------------

def mirror_to_apple_reminders(text: str, fire_at: datetime) -> bool:
    """Mirror a reminder into Apple Reminders so it ALSO fires on the phone (iCloud-
    synced). Only runs when ``apple_reminders_mirror`` is on (default OFF). Fully
    guarded — any AppleScript/osascript failure is swallowed and returns False so a
    mirror attempt can never break job creation. Returns True on a successful mirror."""
    if not getattr(CONFIG, "apple_reminders_mirror", False):
        return False
    try:
        from vox import actions
        name = (text or "Reminder").replace('"', "'")
        when = fire_at.strftime("%-m/%-d/%Y %-I:%M:%S %p")
        script = (
            'tell application "Reminders"\n'
            f'  make new reminder with properties {{name:"{name}", '
            f'remind me date:date "{when}"}}\n'
            'end tell'
        )
        ok, _out = actions._osa(script)
        return ok
    except Exception:
        return False


# --- Background thread: start / stop ---------------------------------------

class _SchedulerThread(threading.Thread):
    """Wakes every ~poll seconds and fires due jobs. Guarded so it never crashes the
    daemon — every tick is wrapped, a bad job is dropped rather than raised."""

    def __init__(self, poll_seconds: float):
        super().__init__(name="vox-scheduler", daemon=True)
        self._poll = max(1.0, float(poll_seconds))
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        _catch_up()  # fire/clear recently-overdue one-shots once at startup
        while not self._stop.wait(self._poll):
            try:
                _tick()
            except Exception:
                pass  # a bad tick must never take down the thread / daemon


def _tick() -> None:
    """Fire every due+enabled job; roll recurring ones, delete fired one-shots."""
    now = _now()
    with _LOCK:
        jobs = _load()
        changed = False
        for job in list(jobs):
            if not job.get("enabled", True):
                continue
            fire = _parse_iso(job["fire_at"])
            if fire is None or fire > now:
                continue
            _announce(job)
            if job.get("recurrence"):
                nxt = _advance(fire, job["recurrence"])
                while nxt <= now:  # don't replay missed recurrences; catch up to the future
                    nxt = _advance(nxt, job["recurrence"])
                job["fire_at"] = _iso(nxt)
            else:
                jobs.remove(job)
            changed = True
        if changed:
            _save(jobs)


# Window for firing a one-shot that came due while Vox was off (else it's stale).
_CATCHUP_WINDOW = timedelta(hours=1)


def _catch_up() -> None:
    """At startup: fire one-shots overdue by < ~1h once (prefixed "While you were
    away — "), drop older one-shots, and roll any overdue recurring jobs forward."""
    now = _now()
    with _LOCK:
        jobs = _load()
        keep, changed = [], False
        for job in jobs:
            fire = _parse_iso(job["fire_at"])
            if fire is None:
                changed = True
                continue
            if fire > now:  # still in the future → resume untouched
                keep.append(job)
                continue
            if job.get("recurrence"):  # overdue recurring → roll to its next future time
                nxt = _advance(fire, job["recurrence"])
                while nxt <= now:
                    nxt = _advance(nxt, job["recurrence"])
                job["fire_at"] = _iso(nxt)
                keep.append(job)
                changed = True
                continue
            # overdue one-shot
            if job.get("enabled", True) and now - fire < _CATCHUP_WINDOW:
                _announce(job, prefix="While you were away — ")
            changed = True  # dropped (fired-late or stale) either way
        if changed:
            _save(keep)


def start() -> "_SchedulerThread | None":
    """Start the background scheduler thread (idempotent). Returns the thread, or
    None if disabled / already running. Fully guarded — a failure to start must
    never break the daemon."""
    global _THREAD
    if not getattr(CONFIG, "scheduler_enabled", True):
        return None
    if _THREAD is not None and _THREAD.is_alive():
        return _THREAD
    try:
        _THREAD = _SchedulerThread(getattr(CONFIG, "scheduler_poll_seconds", 5.0))
        _THREAD.start()
        return _THREAD
    except Exception:
        return None


def stop() -> None:
    """Signal the background thread to stop (best-effort; it's a daemon thread)."""
    global _THREAD
    if _THREAD is not None:
        try:
            _THREAD.stop()
        except Exception:
            pass
        _THREAD = None
