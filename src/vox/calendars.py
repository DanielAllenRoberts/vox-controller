"""Read the Mac's calendars (EventKit): every account added to macOS (iCloud, Google, Exchange…).

Used by routines ("every weekday at 7, tell me what's on my calendar") and by the brain when asked
what's on. Read-only. Calendar access is granted to Vox.app (Settings → Permissions → Calendar);
the engine it launches inherits it. Without access every call returns None plus a reason, and
nothing prompts from here: the prompt belongs to the app, where the user expects it.
"""

from __future__ import annotations

from datetime import datetime, timedelta

_FULL_ACCESS = 3   # EKAuthorizationStatusFullAccess (== the old "authorized")
_STORE = None


def status() -> str:
    """"granted" | "not_asked" | "denied" | "unavailable"."""
    try:
        import EventKit
    except Exception:
        return "unavailable"
    s = int(EventKit.EKEventStore.authorizationStatusForEntityType_(EventKit.EKEntityTypeEvent))
    return {0: "not_asked", _FULL_ACCESS: "granted"}.get(s, "denied")


def why_not() -> str:
    if _last_error:
        return f"I couldn't read your Google Calendar through Composio: {_last_error}"
    return {"not_asked": "I don't have access to your calendar yet. Add your Composio API key (Settings → Brains → API keys) for Google Calendar, or allow the Mac's Calendar in Settings → Permissions.",
            "denied": "Calendar access is turned off for Vox. Turn it on in System Settings → Privacy & Security → Calendars.",
            "unavailable": "I can't read calendars on this Mac."}.get(status(), "")


_last_error = ""


def events(start: datetime, end: datetime) -> list[dict] | None:
    """Events overlapping [start, end) from every source Vox can read (the Mac's Calendar app and,
    with a Composio key, Google Calendar through Composio), soonest first. None if no source could be
    read."""
    global _last_error
    _last_error = ""
    found, any_ok = [], False
    mac = _mac_events(start, end)
    if mac is not None:
        found += mac
        any_ok = True
    try:
        from vox import composio
        if composio.configured():
            found += composio.calendar_events(start, end)
            any_ok = True
    except Exception as exc:
        _last_error = str(exc)
    if not any_ok:
        return None
    seen, out = set(), []
    for e in sorted(found, key=lambda x: (not x["all_day"], x["start"])):
        key = (e["title"].strip().lower(), e["start"].strftime("%Y-%m-%d %H:%M"))
        if key not in seen:   # the same Google event seen through both sources
            seen.add(key)
            out.append(e)
    return out


def _mac_events(start: datetime, end: datetime) -> list[dict] | None:
    """Events from the Mac's Calendar app (EventKit). None without access."""
    global _STORE
    if status() != "granted":
        return None
    try:
        import EventKit
        from Foundation import NSDate
        if _STORE is None:
            _STORE = EventKit.EKEventStore.alloc().init()
        pred = _STORE.predicateForEventsWithStartDate_endDate_calendars_(
            NSDate.dateWithTimeIntervalSince1970_(start.timestamp()),
            NSDate.dateWithTimeIntervalSince1970_(end.timestamp()), None)
        out = []
        for e in _STORE.eventsMatchingPredicate_(pred) or []:
            s = datetime.fromtimestamp(e.startDate().timeIntervalSince1970())
            f = datetime.fromtimestamp(e.endDate().timeIntervalSince1970())
            out.append({"title": str(e.title() or "(no title)"), "start": s, "end": f,
                        "all_day": bool(e.isAllDay()), "location": str(e.location() or ""),
                        "calendar": str(e.calendar().title() if e.calendar() else "")})
        out.sort(key=lambda x: (not x["all_day"], x["start"]))
        return out
    except Exception:
        return None


def day(offset: int = 0) -> list[dict] | None:
    """Events for today (0), tomorrow (1), …"""
    d0 = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=offset)
    return events(d0, d0 + timedelta(days=1))


def describe(offset: int = 0, label: str | None = None) -> str:
    """Prompt text: one line per event, or why it can't be read."""
    evs = day(offset)
    label = label or {0: "Today", 1: "Tomorrow"}.get(offset, f"In {offset} days")
    if evs is None:
        return f"[Calendar] {why_not()}"
    if not evs:
        return f"[Calendar · {label}] Nothing scheduled."
    lines = []
    for e in evs[:25]:
        when = "all day" if e["all_day"] else f"{e['start']:%H:%M}–{e['end']:%H:%M}"
        where = f" @ {e['location']}" if e["location"] else ""
        lines.append(f"  {when}  {e['title']}{where}  ({e['calendar']})")
    return f"[Calendar · {label}]\n" + "\n".join(lines)
