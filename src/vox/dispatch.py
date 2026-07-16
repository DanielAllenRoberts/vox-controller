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

import re

from vox import actions
from vox.config import CONFIG
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


# --- command DB (app/site-scoped commands, idea #36) --------------------------

def _db_enabled() -> bool:
    """Is the DB resolver on? Read through the dashboard's settings override (so it flips live,
    no restart) with the frozen Config default as the floor. Guarded → default on any error."""
    try:
        from vox.web import settings_store
        val = settings_store.get("command_db_enabled")
        if val is not None:
            return bool(val)
    except Exception:
        pass
    return bool(getattr(CONFIG, "command_db_enabled", False))


def _command_db(text: str) -> tuple[bool, str] | None:
    """Consult the command DB (in-memory cache) for a context-scoped ACTION command, in front of the
    regex parser. Returns ``(True, result)`` when one ran cleanly, else ``None`` (→ fall through to
    the parser / LLM). Gated by ``command_db_enabled`` (default off) and fully guarded — a cache
    problem can never break dispatch. Mode/system phrases are excluded (``actions_only``) so the
    control plane stays in the loop's hardcoded floor (§8a)."""
    if not _db_enabled():
        return None
    try:
        from vox import command_cache
        app = command_cache.current_app()
        r = command_cache.resolve(text, app=app, actions_only=True)
        if r is None:
            if getattr(CONFIG, "debug", False):
                command_cache.log(f"  [cmddb] resolve {text!r} [app={app}] → no match (→ parser/LLM)")
            return None
        result = actions.run_intent(r["intent"], r.get("arg") or "")
        ok = result is not None and not actions.failed(result)
        arg = f" {r['arg']!r}" if r.get("arg") else ""
        command_cache.log(f"  [cmddb] resolve {text!r} [app={app}] → {r['intent']}{arg} "
                          f"via {r['context']} '{r['phrase']}'  ⇒ {'ran' if ok else 'FAILED → fall through'}")
        return (True, result) if ok else None
    except Exception:
        return None  # any cache/dispatch error → behave exactly as if the DB weren't there


# --- numbered clickable-element overlay (idea #52) ----------------------------
# "show clickable" / "click link" / "click button" → draw numbered badges on every clickable element;
# then a spoken number → press it + hide. Runs BEFORE the parser so "click <N>" during the overlay
# doesn't get read as "click the control labelled N". Silent (acted=True) on both show and click, so
# the flow never speaks — that both keeps it snappy and dodges the TTS→mic-stall (audio -10863) that
# would otherwise garble the number you say next. Fully guarded: any AppKit/AX problem falls back to
# naming the targets aloud, so it degrades instead of breaking.

_SHOW_CLICKABLE_PHRASES = ("show clickable", "show clickables", "click link", "click button",
                           "show numbers", "show links", "show clickable items", "show clickables")

_ONES = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
         "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
         "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
         "eighty": 80, "ninety": 90}


def _has_phrase(t: str, phrase: str) -> bool:
    """Whole-phrase (word-boundary) match, so 'click link' doesn't fire on 'click linkedin'."""
    return f" {phrase} " in f" {t} "


def _words_to_int(s: str) -> int | None:
    """Parse a spelled-out number 1–99 (e.g. 'twenty one'), or None."""
    s = s.strip().replace("-", " ")
    parts = [p for p in s.split() if p]
    if len(parts) == 1:
        return _ONES.get(parts[0], _TENS.get(parts[0]))
    if len(parts) == 2 and parts[0] in _TENS and parts[1] in _ONES and _ONES[parts[1]] < 10:
        return _TENS[parts[0]] + _ONES[parts[1]]
    return None


def _parse_click_number(t: str) -> int | None:
    """The number the user said while the overlay is up — a digit anywhere ('click 14', '14'), else a
    spelled-out number after stripping filler words. Returns a 1-based number, or None."""
    m = re.search(r"\b(\d{1,3})\b", t)
    if m:
        n = int(m.group(1))
        return n if n >= 1 else None
    body = re.sub(r"\b(click|press|tap|select|choose|hit|number|item|option|the|on|that|please|go|to)\b",
                  " ", t)
    n = _words_to_int(re.sub(r"\s+", " ", body).strip())
    return n if (n is not None and n >= 1) else None


def _overlay(text: str, t: str) -> tuple[bool, str] | None:
    """Handle the numbered-overlay flow. Returns (acted, msg), or None to fall through. Guarded."""
    try:
        from vox import ax, overlay
    except Exception:
        return None

    if overlay.is_active():
        n = _parse_click_number(t)
        overlay.hide()  # ANY utterance dismisses the overlay
        if n is not None:
            res = ax.click_index(n - 1)  # spoken 1-based → 0-based index
            if res and res[0] == "clicked":
                return (True, f"clicked #{n} ({res[1]})")
            if res and res[0] == "press_failed":
                return (True, f"found #{n} ({res[1]}) but couldn't press it")
            return (True, f"no #{n} on screen")
        if any(c in t for c in ("cancel", "never mind", "nevermind", "hide", "escape", "forget it")):
            return (True, "hidden")
        return None  # not a number/cancel → overlay dismissed; handle the utterance normally

    if any(_has_phrase(t, p) for p in _SHOW_CLICKABLE_PHRASES):
        try:
            items = ax.targets_with_frames()
        except Exception:
            items = None
        if not items:
            return (False, "I can't see anything clickable here.")
        try:
            overlay.show(items)
        except Exception:  # overlay couldn't draw → fall back to naming them (still useful)
            names = ", ".join(i["label"] for i in items[:10])
            return (False, f"I can click: {names}. Say the one you want.")
        return (True, f"showing {len(items)} clickable targets — say a number")
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

    ov = _overlay(text, t)  # numbered clickable overlay (idea #52) — before the parser
    if ov is not None:
        return ov

    if _is_what_app(t):
        app = actions.frontmost_app()
        return (False, f"You're looking at {app}." if app else "I can't tell which app is focused.")

    sched = _scheduler(text, t)
    if sched is not None:
        return sched

    db = _command_db(text)  # app/site-scoped commands, in front of the regex parser (gated; off by default)
    if db is not None:
        return db

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
