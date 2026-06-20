"""Unified command dispatch — the ONE place every mode routes an utterance through for its
DETERMINISTIC capabilities, so a capability added here works in one-shot, control AND assistant
mode at once (the user's "all commands from one place" goal; per-mode *prompting* stays separate).

``try_deterministic(text)`` runs, in order:
  1. a quick spoken query — "what app is this?" (instant, no LLM),
  2. the scheduler — timers / alarms / reminders (create · cancel · read-back),
  3. the deterministic command parser (``actions``).
It returns ``(acted, message)`` — ``acted=True`` for a silent "did it" action (the mode plays a
cue + shows the result), ``acted=False`` for a spoken answer/confirmation (the mode speaks it) —
or ``None`` when nothing deterministic matched (the mode then escalates to the LLM: the executor
for control/one-shot, or chat for assistant).

``looks_like_action(text, cfg)`` is the cheap action-intent gate assistant mode uses to decide
whether a non-command utterance should try the executor (compose / rewrite / vision / fuzzy
command) before falling through to conversational chat — so chat stays chat-first.
"""

from __future__ import annotations

from vox import actions
from vox.wakeword.backends import normalize


# --- "what app is this?" — instant, spoken, no LLM ----------------------------

def _is_what_app(t: str) -> bool:
    """True for "what app is this", "what app am I on/looking at", "which app is this"."""
    if "app" in t and ("what" in t or "which" in t) and any(
            w in t for w in ("this", "am i", "i on", "i in", "looking at", "current", "open", "using")):
        return True
    return "what" in t and "looking at" in t  # "what am I looking at"


# --- scheduler (timers / alarms / reminders) ----------------------------------

def _is_schedule_query(t: str) -> bool:
    return ("what" in t or "list" in t or "any" in t or "do i have" in t) \
        and any(k in t for k in ("timer", "alarm", "reminder", "schedule"))


def _is_schedule_cancel(t: str) -> bool:
    return any(c in t for c in ("cancel", "clear", "delete", "remove")) \
        and any(k in t for k in ("timer", "alarm", "reminder"))


def _scheduler(text: str, t: str) -> tuple[bool, str] | None:
    """Route a scheduler utterance (query / cancel / create). Guarded — returns None on any
    problem so the caller falls back to the LLM. ``parse_and_create`` is the create gate (it
    returns None for a non-scheduler phrase)."""
    try:
        from vox import scheduler
        if _is_schedule_query(t):
            return (False, scheduler.summary())
        if _is_schedule_cancel(t):
            n = scheduler.cancel_matching(text)
            return (False, f"Cancelled {n} {'item' if n == 1 else 'items'}." if n
                    else "Nothing matched to cancel.")
        msg = scheduler.parse_and_create(text)
        if msg:
            return (False, msg)
    except Exception:
        pass
    return None


# --- the shared deterministic layer -------------------------------------------

def try_deterministic(text: str) -> tuple[bool, str] | None:
    """Shared deterministic capabilities, tried in order. ``(acted, message)`` or ``None``.

    acted=True  → a silent action ran (mode plays a "did it" cue + shows the result).
    acted=False → a spoken answer/confirmation (mode speaks it).
    None        → nothing matched; the mode escalates to the LLM.
    """
    if not text or not text.strip():
        return None
    t = normalize(text)

    if _is_what_app(t):
        app = actions.frontmost_app()
        return (False, f"You're looking at {app}." if app else "I can't tell which app is focused.")

    sched = _scheduler(text, t)
    if sched is not None:
        return sched

    if actions.parse(text) is not None:
        result = actions.handle(text)
        if result is not None and not actions.failed(result):
            return (True, result)
    return None


# --- assistant action-intent gate ---------------------------------------------

# Normalized-safe substrings that signal the user wants an ACTION (compose / rewrite / vision / a
# command / a timer) rather than conversation — so assistant mode tries the executor before
# falling to chat. A false positive degrades gracefully: the executor just returns a chat reply.
# (normalize() strips apostrophes, so use "what s on" forms, and bare "screen"/"look at" for vision.)
_ACTION_HINTS = (
    "write", "compose", "draft", "rewrite", "make this", "make it", "fix this", "fix the",
    "clean this", "summarize", "summarise", "screen", "look at", "read this", "read the",
    "what can you see", "what do you see", "open ", "go to", "search", "switch",
    " tab", "window", "desktop", "remind", "timer", "alarm", "what app",
    "click", "press ", "tap ", "select ",
)


def looks_like_action(text: str, cfg=None) -> bool:
    """Cheap gate: does this look like an action request (vs conversation)? Assistant mode uses it
    to decide whether to try the executor before chatting. Includes the configured
    escalation_keywords so it's user-tunable."""
    t = " " + normalize(text) + " "
    hints = set(_ACTION_HINTS)
    try:
        hints.update(h for h in (getattr(cfg, "escalation_keywords", ()) or ()) if h and h != "vox")
    except Exception:
        pass
    return any(h in t for h in hints)
