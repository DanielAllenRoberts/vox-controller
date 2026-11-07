"""Routines: scheduled requests that Vox CARRIES OUT, not just says.

A routine is a scheduler job of kind "routine" whose text is a request, e.g. every weekday at 7:00
"tell me what's on my calendar and the weather", or every day at 9 "check my calendar and board and
tell me what to work on". When it fires (``scheduler._announce`` → ``run``), Vox either

* does it, when the request is a command ("open my email", "play music"), through the same path as
  speech, or
* briefs you: gathers what the request asks about (calendar, weather, board, reminders) and has the
  brain turn it into a short spoken update. Missing access (no calendar permission) is said, not hidden.

Later (ideas #71 / the agent board): routines that hand the request to a background agent.
"""

from __future__ import annotations

import re
import threading

# Editable on the Prompts page (vox.prompts REGISTRY "routine").
_SYSTEM = (
    "Deliver a ROUTINE the user scheduled earlier. "
    "Below is the request and fresh information gathered for it just now (calendar, weather, board, "
    "reminders, the time). Write exactly what Vox will SAY out loud: a short, natural spoken briefing, "
    "usually 2 to 5 sentences. No lists, bullets, markdown or emoji. Say times naturally ('at nine', "
    "'half past two'). Use only the information given; never invent events or numbers. If something "
    "couldn't be read (for example no calendar access), say so in one short clause and carry on with "
    "the rest. When asked what to work on, pick the most important one to three things using deadlines, "
    "the calendar and what's in Doing, and say why briefly. If the request needs a fact that isn't "
    "given and could be looked up on the web, reply with ONLY:  WEB: <the question>"
)

_WEATHER = re.compile(r"\b(weather|rain|raining|temperature|forecast|cold|hot|warm|umbrella|sunny|wind)\b")
_CALENDAR = re.compile(r"\b(calendar|meetings?|schedule|agenda|events?|appointments?|what'?s on|busy|free|"
                       r"diary|work on|plan|day ahead|today|tomorrow)\b")
_BOARD = re.compile(r"\b(board|tasks?|to ?dos?|work on|priorit\w*|should i|doing|deadlines?)\b")
_REMINDERS = re.compile(r"\breminders?\b")
_TOMORROW = re.compile(r"\btomorrow\b")
_AGENTS = re.compile(r"\b(?:my agents|coding agents?|the \w+ agent|agents? (?:for|to) |ask (?:the|my) .*agent)")
_ACTION = re.compile(r"^(?:please\s+)?(open|go to|launch|start|play|pause|resume|close|quit|switch|move|"
                     r"turn|set|mute|unmute|show|hide|click|press|type|search)\b")


def gather(request: str) -> str:
    """The context a briefing request needs, as prompt text."""
    t = request.lower()
    parts = []
    try:
        from vox import actions
        parts.append(actions._now_line())
    except Exception:
        pass
    if _CALENDAR.search(t):
        try:
            from vox import calendars
            parts.append(calendars.describe(0))
            if _TOMORROW.search(t):
                parts.append(calendars.describe(1))
        except Exception:
            parts.append("[Calendar] couldn't be read.")
    if _WEATHER.search(t):
        try:
            from vox import web_search
            place = web_search._weather_place(t) or web_search._home()
            w = web_search.weather(place) if place else None
            parts.append(f"[Weather · {place or 'unknown place'}] {w or 'could not be fetched.'}")
        except Exception:
            parts.append("[Weather] couldn't be fetched.")
    if _BOARD.search(t):
        try:
            from vox import actions
            b = actions.board_block()
            if b:
                parts.append(b)
        except Exception:
            pass
    if _REMINDERS.search(t):
        try:
            from vox import scheduler
            parts.append("[Reminders] " + scheduler.summary())
        except Exception:
            pass
    return "\n\n".join(p for p in parts if p)


_CAL_QUESTION = re.compile(r"\b(calendar|meetings?|agenda|appointments?|what'?s on (?:today|tomorrow|my)|"
                           r"am i (?:busy|free)|my (?:day|schedule))\b")


def calendar_context(text: str) -> str:
    """Calendar lines for an ordinary question that's about the calendar ("what's on today?",
    "do I have meetings tomorrow?"), else "". Used by both brains' prompts."""
    t = (text or "").lower()
    if not _CAL_QUESTION.search(t):
        return ""
    try:
        from vox import calendars
        out = calendars.describe(0)
        if _TOMORROW.search(t):
            out += "\n" + calendars.describe(1)
        return out
    except Exception:
        return ""


def _briefing(request: str) -> str:
    from vox import assistant, prompts
    context = gather(request)
    message = f"Routine request: {request}\n\n{context}"
    system = prompts.system("routine")   # the core prompt adds the user's name
    reply = assistant.complete(message, None, brain="small", system=system, prompt="routine").strip()
    if reply.upper().startswith("WEB:"):
        try:
            from vox import web_search
            found = web_search.answer(reply[4:].strip() or request)
        except Exception:
            found = "The web couldn't be reached."
        reply = assistant.complete(f"{message}\n\n[Looked up on the web]\n{found}", None, brain="small",
                                   system=system + "\n\nDon't ask for another lookup.", prompt="routine").strip()
    return reply


def _do(request: str) -> str:
    """A command routine: the deterministic parser first, else the brain's router (as if spoken)."""
    from vox import actions, executor
    if actions.parse(request) is not None:
        return actions.run(request)
    _acted, msg = executor.execute(request)
    return msg


def is_action(request: str) -> bool:
    try:
        from vox import actions
        if actions.parse(request) is not None:
            return True
    except Exception:
        pass
    return bool(_ACTION.match(request.strip().lower()))


def run(job: dict, *, speak: bool = True) -> str:
    """Carry out a routine now. Returns what was said (also spoken, put in the conversation feed and
    in short-term memory)."""
    request = (job.get("text") or "").strip()
    if not request:
        return ""
    try:
        if _AGENTS.search(request.lower()):   # "ask my agents for an update", "have the getprice agent run the tests"
            from vox import team
            said = team.ceo(request)
        else:
            said = _do(request) if is_action(request) else _briefing(request)
    except Exception as exc:
        said = f"Your routine '{request}' didn't work: {exc}"
    said = (said or "").strip()
    spoken = said
    try:
        from vox import assistant
        said, spoken = assistant.split_say(said)   # the brain may give a shorter spoken version
    except Exception:
        pass
    try:
        from vox import working_memory
        working_memory.note_did(f"ran the scheduled routine {request!r}")
        if said:
            working_memory.note_reply(said)
    except Exception:
        pass
    try:
        from vox.web import conversation
        conversation.record_turn("assistant", said or f"Ran your routine: {request}", brain="small", kind="routine")
    except Exception:
        pass
    if speak and spoken:
        try:
            from vox import tts
            tts.speak(spoken)
        except Exception:
            pass
    return said


def run_in_background(job: dict) -> None:
    """Fire-and-forget for the scheduler thread: a briefing takes seconds and must not hold up other
    jobs firing."""
    threading.Thread(target=run, args=(dict(job),), name="vox-routine", daemon=True).start()
