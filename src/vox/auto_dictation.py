"""Auto dictation: inside CONTROL mode, speech in a text field is typed unless it is clearly a command.

Dragon's "Dictation & Commands" mode, for Vox. The design, the evidence and the build order are in
``docs/plan/research/command-vs-dictation.md`` §3; this module is that decision procedure:

  L0  hard floor (sleep / quit / abort / mode phrases) — stays in ``core/loop.py``, always wins.
  L1  explicit overrides — "Vox, …" forces a command; "literally …" forces text (``actions.dictate``).
  L2  focus probe — ``ax.focused_text_target()``. Not an editable field → control mode as today.
  L3  in a text field, a COMMAND only when the WHOLE utterance is an exact command, and a
      DESTRUCTIVE one only with the "Vox," prefix — otherwise Vox asks first.
  L4  everything else is TYPED, and pushed onto a chunk history so it can be taken back.
  L5  the LLM is never on the typing path. It's reachable only through "Vox, …" or by saying
      "that was a command" after a chunk was typed.

Off by default (``auto_dictation``). Every decision writes one greppable ``[auto]`` line to vox.log.
Nothing here can make plain control mode worse: with the setting off, or AX unavailable, or no text
field focused, ``route`` hands the utterance straight back to the normal control path untouched.
"""

from __future__ import annotations

import re
import time
from collections import deque
from dataclasses import dataclass, field

# --- risk tiers ------------------------------------------------------------------------------
# What a command costs if it fires on words you meant to type. `safe` moves you somewhere you can
# come straight back from. `edit` changes text, and ⌘Z puts it back. `destructive` loses something:
# the tab holding your half-written message, the page you were typing into, or whatever an
# unspecified click/keypress does. Anything not listed is treated as destructive — a new intent
# should have to earn its way into the cheaper tiers.
SAFE, EDIT, DESTRUCTIVE = "safe", "edit", "destructive"

RISK: dict[str, str] = {
    "navigate": SAFE, "navigate_new": SAFE, "search": SAFE,
    "tab": SAFE, "tab_arrow": SAFE, "tab_index": SAFE,
    "window": SAFE, "window_move": SAFE, "window_index": SAFE,
    "desktop_move": SAFE, "desktop_index": SAFE,
    "profile": SAFE, "profile_move": SAFE, "app_cycle": SAFE, "sidebar": SAFE,
    "scroll": SAFE, "point": SAFE,
    # Grammar phrases the PARSER doesn't own — show/hide clickable (dispatch's overlay) and the
    # spent dictation-control phrases. A closed, curated set with nothing destructive in it.
    "vox_control": SAFE,
    # Leaving the page you're typing on. ⌘W closes the tab with your draft in it; ⌘R reloads it away;
    # "back" (⌘[) navigates away from a form. The research tiers navigation `safe`, but these three
    # take the text field WITH them, which is the one thing auto mode exists to protect.
    "close_tab": DESTRUCTIVE, "reload": DESTRUCTIVE, "back": DESTRUCTIVE,
    # Open-ended: "click send", "press enter", "set …" do whatever the target does.
    "click": DESTRUCTIVE, "right_click": DESTRUCTIVE, "double_click": DESTRUCTIVE,
    "drag": DESTRUCTIVE, "set_value": DESTRUCTIVE, "press": DESTRUCTIVE,
}

# Return SENDS in a chat app. dictate() maps "enter"/"send"/"submit" to a real Return, so in these
# apps a stray one posts a half-written message. The research says keep it (it's how you send by
# voice) but log it as destructive, so the trial data shows how often it misfires.
CHAT_APPS = {"slack", "messages", "discord", "whatsapp", "telegram", "signal", "microsoft teams",
             "teams", "messenger", "zoom", "beeper"}
_RETURN_WORDS = {"enter", "return", "send", "submit"}


def risk_tier(intent: str | None) -> str:
    """The tier for a command intent. Unknown → destructive (fail-safe)."""
    return RISK.get(intent or "", DESTRUCTIVE)


def _norm(text: str) -> str:
    """Same normalisation as wakeword.backends.normalize / command_store.normalize."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", (text or "").lower())).strip()


# --- in-dictation edit words -------------------------------------------------------------------
# A mirror of the whole-utterance edit words ``actions.dictate`` acts on instead of typing. They're
# checked FIRST in a text field: "enter" and "new line" are also on the Vosk grammar, and if they
# reached control dispatch they'd be swallowed as spent dictation-control phrases. tests/ pins this
# list against dictate() so the two can't drift silently.
_EDIT_EXACT = {
    "new line", "newline", "next line", "new paragraph", "enter", "return", "send", "submit",
    "backspace", "delete", "delete that", "tab key",
    "delete line", "delete the line", "delete this line", "delete the current line",
    "delete current line", "delete a line",
    "delete paragraph", "delete the paragraph", "delete this paragraph", "delete a paragraph",
    "undo", "undo that", "undo it", "redo", "redo that", "redo it",
}
_EDIT_WORDS_RE = re.compile(r"(?:delete|remove|scratch|erase)\s+(?:the\s+)?(?:last\s+)?(?:\w+\s+)?words?")


def edit_word(text: str) -> str | None:
    """The edit word this utterance is (normalised), or None. Repeats ("enter enter") collapse the way
    dictate() collapses them."""
    t = _norm(text)
    if t in _EDIT_EXACT or _EDIT_WORDS_RE.fullmatch(t):
        return t
    for w in _EDIT_EXACT:
        if re.fullmatch(rf"{re.escape(w)}(?:\s+{re.escape(w)})+", t):
            return w
    return None


def edit_tier(word: str, app: str | None) -> str:
    """Return-in-a-chat-app is destructive (it sends); every other edit word is ⌘Z-reversible."""
    if word in _RETURN_WORDS and (app or "").strip().lower() in CHAT_APPS:
        return DESTRUCTIVE
    return EDIT


# --- L1: the "Vox, …" prefix -------------------------------------------------------------------
# Only the name itself and its two common spellings. The idle one-shot also accepts "box"/"fox"
# (wakeword.backends._oneshot), but there an utterance has to start the wake path to matter; in a
# text field "Fox news reported…" is ordinary dictation, so a mishear here must fall to TYPING, the
# reversible side. Leading filler is tolerated exactly as the one-shot does.
_PREFIX_RE = re.compile(r"^(?:(?:um|uh|er|ah|oh|so|okay|ok|well|and|now|hey)\s+)*(?:vox|vocks|vaux)\s+(.+)$")


def strip_vox_prefix(text: str) -> str | None:
    """The command after a leading "Vox, …", or None when there's no prefix. The prefix is
    DETECTED on normalised text but the command is cut from the ORIGINAL, so punctuation the command
    needs survives ("Vox, go to github.com" → "go to github.com", not "go to github com")."""
    if _PREFIX_RE.match(_norm(text)) is None:
        return None
    m = re.match(r"\s*(?:(?:um|uh|er|ah|oh|so|okay|ok|well|hey|and)[\s,.!?]+)*(?:vox|vocks|vaux|fox|box)\b[\s,.:!?-]*(.*)$",
                 text or "", re.I | re.S)
    return (m.group(1).strip().rstrip(".!?,;") if m else "") or None


# --- L3: exact command lookup --------------------------------------------------------------------

def exact_command(text: str, app: str | None = None, extra_phrases=()) -> dict | None:
    """Is the WHOLE utterance an exact command? Returns ``{intent, arg, phrase, source, via}`` or None.

    Two sources, both whole-utterance only:
      • the command DB in text-context mode (``command_cache.resolve(text_context=True)``): exact
        equality, no `contains` slack, no regex, ≤5 words, no learned command still on probation;
      • the closed set of parser phrases the Vosk grammar already enumerates (scroll / page / reload /
        "switch <app>" / "open <app>" / show clickable …). The PARSER itself is regex `search`, so
        "I'll go back to that later" parses as `back` — that's why only enumerated phrases count.
    Learned commands are never allowed to be destructive from a text context (research §3): such a
    hit is dropped here, and the words are typed instead."""
    t = _norm(text)
    if not t:
        return None
    hit = None
    try:
        from vox import command_cache
        r = command_cache.resolve(t, app=app, actions_only=True, text_context=True)
        if r is not None:
            hit = {"intent": r.get("intent"), "arg": r.get("arg"), "phrase": r.get("phrase"),
                   "source": r.get("_source") or "builtin", "via": "db"}
    except Exception:
        hit = None
    if hit is None:
        known = {_norm(p) for p in (extra_phrases or ())}
        if t in known:
            try:
                from vox import actions
                parsed = actions.parse(t)
            except Exception:
                parsed = None
            hit = {"intent": parsed[0] if parsed else "vox_control", "arg": parsed[1] if parsed else None,
                   "phrase": t, "source": "builtin", "via": "grammar"}
    if hit is not None and hit["source"] == "learned" and risk_tier(hit["intent"]) == DESTRUCTIVE:
        return None
    return hit


# --- L4: typed-chunk history (Talon's phrase_history) ------------------------------------------

@dataclass
class Chunk:
    spoken: str            # what was said (what "that was a command" re-runs)
    pasted: str            # exactly what went into the field, leading space included
    pid: int | None
    element: object = None  # the AXUIElement it went into
    at: float = field(default_factory=time.monotonic)


_HISTORY: deque = deque(maxlen=20)
_MAX_DIRECT_DELETE = 200   # longer than this → ⌘Z (also the AX peek length, so we can verify it)


def record(spoken: str, pasted: str, target: dict | None) -> None:
    if pasted:
        _HISTORY.append(Chunk(spoken, pasted, (target or {}).get("pid"), (target or {}).get("element")))


def clear_history() -> None:
    _HISTORY.clear()


def reset() -> None:
    """Forget the chunk history and any unanswered confirmation — on entering control mode, so a
    "yes" in a NEW session can't fire a question asked in the last one."""
    global _CONFIRM
    _HISTORY.clear()
    _CONFIRM = None


def last_chunk() -> Chunk | None:
    return _HISTORY[-1] if _HISTORY else None


def _same_element(a, b) -> bool:
    if a is None or b is None:
        return False
    try:
        return bool(a == b)  # pyobjc → isEqual: → CFEqual on AXUIElementRefs
    except Exception:
        return False


def scratch_plan(chunk: Chunk, target: dict | None) -> str:
    """How to take ``chunk`` back out, given what has focus NOW. Returns
    "delete" (backspace exactly len(chunk.pasted)), "undo" (⌘Z), or "refuse".

    Deleting by length is only right if the cursor is still sitting right after the chunk. When the
    field's text is readable we CHECK that; when it isn't, the same element is the best evidence we
    have. Anything else gets ⌘Z, which in most apps is exactly one paste. We refuse outright when the
    app changed: ⌘Z there would undo something in a different app."""
    if target is None or target.get("pid") is None or target.get("pid") != chunk.pid:
        return "refuse"
    n = len(chunk.pasted)
    before = target.get("before")
    if before is not None:
        return "delete" if n <= _MAX_DIRECT_DELETE and before.endswith(chunk.pasted) else "undo"
    if n <= _MAX_DIRECT_DELETE and _same_element(target.get("element"), chunk.element):
        return "delete"
    return "undo"


def _backspace(n: int) -> None:
    from vox import actions
    actions._osa('tell application "System Events"\n'
                 f'repeat {int(n)} times\nkey code 51\nend repeat\nend tell')


def _undo() -> None:
    from vox import actions
    actions._osa('tell application "System Events" to keystroke "z" using {command down}')


def scratch_that(probe=None, backspace=_backspace, undo=_undo) -> tuple[str, Chunk | None]:
    """Take the last typed chunk back out. Returns (method, chunk): method is "delete" / "undo" /
    "refuse" / "empty". The chunk is popped unless refused, so repeating walks back one at a time."""
    if not _HISTORY:
        return "empty", None
    chunk = _HISTORY[-1]
    if probe is None:
        from vox import ax
        probe = lambda: ax.focused_text_target(max_age=0)  # noqa: E731 - fresh read: we're about to delete
    try:
        target = probe()
    except Exception:
        target = None
    plan = scratch_plan(chunk, target)
    if plan == "refuse":
        return plan, chunk
    if plan == "delete":
        backspace(len(chunk.pasted))
    else:
        undo()
    _HISTORY.pop()
    # Put the running spacing/caps state back to how it stood after the chunk BEFORE this one, for
    # fields we can't peek into (a readable field re-primes itself before the next chunk anyway).
    try:
        from vox import actions
        prev = last_chunk()
        if prev is not None and _same_element(prev.element, chunk.element):
            actions.prime_dictation(prev.pasted)
        else:
            actions.reset_dictation()
    except Exception:
        pass
    return plan, chunk


# --- pending confirmation for a destructive command ---------------------------------------------
_CONFIRM: dict | None = None    # {"text", "tier", "at"}
_CONFIRM_TTL = 20.0
_YES = re.compile(r"^(?:yes|yeah|yep|yup|sure|do it|go ahead|ok|okay|confirm|please|correct)(?:\s+please)?$")
_NO = re.compile(r"^(?:no|nope|nah|don t|do not|cancel|stop|never mind|nevermind)(?:\s+thanks)?$")


def ask_confirm(command: str, tier: str) -> str:
    """Hold ``command`` until the next utterance says yes. Returns the question to speak."""
    global _CONFIRM
    _CONFIRM = {"text": command, "tier": tier, "at": time.monotonic()}
    return f"{command[:1].upper()}{command[1:]}?"


def _take_confirm(text: str) -> tuple[str, dict] | None:
    """("yes"|"no"|"other", pending) when a confirmation is waiting, else None. Always consumes it:
    a question Vox asked is answered by the very next utterance or not at all."""
    global _CONFIRM
    pending, _CONFIRM = _CONFIRM, None
    if pending is None or time.monotonic() - pending["at"] > _CONFIRM_TTL:
        return None
    t = _norm(text)
    return ("yes" if _YES.match(t) else "no" if _NO.match(t) else "other"), pending


# --- the decision ---------------------------------------------------------------------------------

@dataclass
class Route:
    kind: str           # text | command | confirm | scratch | recall | ignore
    text: str           # what to type, or the command to dispatch
    reason: str
    tier: str = ""


_SCRATCH = {"scratch that", "nope that", "scratch", "strike that"}
_RECALL = {"that was a command", "that s a command", "that was meant to be a command", "do that instead"}
_FILLER = {"and", "uh", "um", "ah", "oh", "so", "the", "a", "i", "yeah", "yep", "no", "okay", "ok",
           "hmm", "mm", "mhm", "like", "you", "well", "but", "or", "is", "it"}


def decide(text: str, target: dict | None, *, app: str | None = None, pending: bool = False,
           overlay_active: bool = False, extra_phrases=()) -> Route:
    """Route one utterance. Pure apart from the confirmation it consumes — every side effect is the
    caller's. ``target`` is ``ax.focused_text_target()`` (None = AX unavailable)."""
    t = _norm(text)
    conf = _take_confirm(text)
    if conf is not None:
        answer, held = conf
        if answer == "yes":
            return Route("command", held["text"], "confirmed", held["tier"])
        if answer == "no":
            return Route("ignore", held["text"], "confirmation declined")
        # anything else: the question lapses and this utterance is routed on its own merits

    # History commands work wherever you are; scratch_that itself refuses if the app changed.
    if t in _SCRATCH:
        return Route("scratch", "", "history")
    if t in _RECALL:
        return Route("recall", "", "history")

    # L1: "Vox, …" is a command, wherever focus is. In a text field a destructive one still needs
    # the exact phrase; anything looser ("Vox, close the tab please") is asked about first.
    cmd = strip_vox_prefix(text)
    if cmd is not None:
        if target is not None and target.get("editable"):
            hit = exact_command(cmd, app, extra_phrases)
            if hit is not None:
                return Route("command", cmd, f"vox prefix + exact '{hit['phrase']}'", risk_tier(hit["intent"]))
            try:
                from vox import actions
                parsed = actions.parse(cmd)
            except Exception:
                parsed = None
            if parsed is not None and risk_tier(parsed[0]) == DESTRUCTIVE:
                return Route("confirm", cmd, f"vox prefix, {parsed[0]} not exact", DESTRUCTIVE)
        return Route("command", cmd, "vox prefix")

    # L2: only an editable, non-secure field is a typing context.
    if target is None:
        return Route("command", text, "no AX")
    if target.get("secure"):
        return Route("command", text, "secure field")
    if not target.get("editable"):
        return Route("command", text, "not a text field")
    if pending:
        return Route("command", text, "answering Vox's question")
    if overlay_active:
        return Route("command", text, "numbered overlay is up")

    # L3: in a text field.
    if re.match(r"(?i)^\s*literally\s+\S", text or ""):
        return Route("text", text, "literally")
    word = edit_word(text)
    if word is not None:
        return Route("text", text, f"edit word '{word}'", edit_tier(word, app))
    hit = exact_command(text, app, extra_phrases)
    if hit is not None:
        tier = risk_tier(hit["intent"])
        if tier == DESTRUCTIVE:
            return Route("confirm", t, f"exact '{hit['phrase']}' ({hit['intent']}) without the Vox prefix", tier)
        return Route("command", text, f"exact '{hit['phrase']}' via {hit['via']}", tier)

    # L4: type it — unless it's pure filler, which in a hot mic is the room, not you.
    words = t.split()
    if not words or all(w in _FILLER for w in words):
        return Route("ignore", text, "filler")
    return Route("text", text, "no exact command")


def whole_utterance(text: str, phrases) -> bool:
    """Is the WHOLE utterance one of ``phrases``? The loop's floor matches mode phrases as
    substrings ("see you later" anywhere → sleep), which is right when everything you say is for Vox
    but means dictating "see you later" into an email drops Vox to sleep. In a text field the floor
    uses this instead (research §3, L0: "whole-utterance only")."""
    t = _norm(text)
    t2 = t.replace(" ", "")
    return any(t == _norm(p) or t2 == _norm(p).replace(" ", "") for p in (phrases or ()))


# --- the effectful half (called from core/loop.py's control mode) ---------------------------------

def probe() -> dict | None:
    """The focus target for this utterance (``ax.focused_text_target()``), or None when AX can't
    answer — which the router treats as "not a text field", i.e. plain control mode."""
    try:
        from vox import ax
        return ax.focused_text_target()
    except Exception:
        return None


def describe(target: dict | None, app: str | None) -> str:
    """One `[auto] focus` line. Never includes field contents."""
    if target is None:
        return "  [auto] focus: AX unavailable → control"
    return (f"  [auto] focus {app or '?'}: editable={target.get('editable')} "
            f"role={target.get('role') or '-'}{'/' + target['subrole'] if target.get('subrole') else ''} "
            f"secure={target.get('secure')} peek={'yes' if target.get('before') is not None else 'no'} "
            f"({target.get('ms', 0):.1f}ms)")


def route(text: str, target: dict | None, *, out, speak, pending=False, extra_phrases=()) -> str | None:
    """Act on one control-mode utterance under auto dictation. Returns None when it was handled here
    (typed / scratched / asked / ignored), or the command text the normal control path should run."""
    from vox import actions
    app = None
    try:
        from vox import command_cache
        app = command_cache.current_app()
    except Exception:
        pass
    try:
        from vox import overlay
        overlay_active = bool(overlay.is_active())
    except Exception:
        overlay_active = False
    out.emit(describe(target, app))
    r = decide(text, target, app=app, pending=pending, overlay_active=overlay_active,
               extra_phrases=extra_phrases)
    secret = bool(target and target.get("secure"))
    shown = "<secure field — not logged>" if secret else repr(r.text)

    if r.kind == "command":
        out.emit(f"  [auto] command {shown} reason={r.reason}" + (f" tier={r.tier}" if r.tier else ""))
        return r.text
    if r.kind == "confirm":
        q = ask_confirm(r.text, r.tier)
        out.emit(f"  [auto] confirm {r.text!r} tier={r.tier} reason={r.reason} → asking {q!r}")
        speak(q)
        return None
    if r.kind == "ignore":
        out.emit(f"  [auto] ignored {shown} reason={r.reason}")
        return None
    if r.kind == "scratch":
        method, chunk = scratch_that()
        out.emit(f"  [auto] scratch → {method}" + (f" {chunk.pasted!r} ({len(chunk.pasted)} chars)" if chunk else ""))
        if method == "refuse":
            speak("You've moved to another app, so I left it.")
        elif method == "empty":
            speak("Nothing to scratch.")
        return None
    if r.kind == "recall":
        method, chunk = scratch_that()
        if chunk is None or method == "refuse":
            out.emit(f"  [auto] recall → nothing to recall ({method})")
            speak("You've moved to another app, so I left it." if method == "refuse" else "Nothing to recall.")
            return None
        out.emit(f"  [auto] recall → scratched via {method}, running {chunk.spoken!r} as a command")
        return chunk.spoken

    # TEXT. Prime spacing/capitals from the field itself when we can read it; otherwise keep the
    # running state, but start fresh when the text is going into a different field than last time.
    before = target.get("before") if target else None
    prev = last_chunk()
    if before is not None:
        actions.prime_dictation(before)
    elif prev is None or not _same_element(prev.element, (target or {}).get("element")):
        actions.reset_dictation()
    pasted = actions.dictate(r.text)
    if pasted:
        record(r.text, pasted, target)
        out.emit(f"  [auto] typed {r.text!r} → {app or '?'} {target.get('role') if target else ''} "
                 f"reason={r.reason}")
    else:
        # An edit key moved the cursor or changed the text, so "delete the last chunk by length"
        # would no longer delete the right characters. Forget the history rather than guess.
        clear_history()
        out.emit(f"  [auto] edit {r.text!r} reason={r.reason}" + (f" tier={r.tier}" if r.tier else ""))
    return None
