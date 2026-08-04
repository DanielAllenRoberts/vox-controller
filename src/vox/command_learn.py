"""Command learning — the policy layer over the command DB's write path (idea #24 / #14).

Full design: ``docs/plan/command-learning/``. The short version:

  **Learn the action, cluster the phrases, promote on evidence, decay on silence.**

``command_store`` is a dumb data layer; EVERY judgment call lives here, in one file, so the rules are
auditable in one place and testable without a database.

**Phase 2 — promotion is live.** Every LLM-resolved action is observed, gated, and counted; once an
action clears the bar (N clean hits in a rolling window) it is saved as a real command and resolves
instantly and for free from then on. ``learning_mode`` (``auto`` / ``suggest`` / ``off``) governs
whether it saves on its own; ``remember that`` / ``forget that`` are the explicit overrides.

The safety comes from being easy to reverse rather than hard to trigger: a newly learned command is on
**probation** and deletes itself if it doesn't get used, one "no" retires it, and a correction can
re-point it. So promotion is deliberately eager — a wrong guess costs days, a missed one costs
permanent friction.

Everything is guarded: this is an additive observer bolted onto the voice loop, and a bug in it must
never be able to break a command the user actually said.
"""

from __future__ import annotations

import re

from vox import command_store

# Intents we may EVER learn — a positive allowlist, not a blocklist, so a newly added intent is
# unlearnable until someone deliberately opts it in. Deliberately excludes: compose/rewrite/dictation
# (the arg IS free-text content and never repeats), LOOK/CHAT (questions aren't replayable actions),
# and the whole mode/system control plane (sleep/quit/restart — a mis-fired learned row there is
# unrecoverable). See docs/plan/command-learning/01-promotion.md.
LEARNABLE_INTENTS = {
    "navigate", "navigate_new", "tab", "tab_arrow", "tab_index",
    "window", "window_move", "window_index", "desktop_move", "desktop_index",
    "profile", "profile_move", "app_cycle", "sidebar", "click",
}

# Intents whose action doesn't depend on what's focused: opening an app or a URL does the same thing
# from anywhere. Learning those per-app made "open logic" a separate candidate in every app it was
# said from (seen in real shadow data: two candidates for one action), each needing its own three
# hits. They learn GLOBALLY instead. Everything else — click, tab, window, sidebar — is meaningless
# outside the app it was said in and stays app-scoped, which keeps a bad learn's blast radius small.
GLOBAL_INTENTS = {"navigate", "navigate_new", "app_cycle"}

# Words stripped from the edges of a heard phrase before it's stored (doc 02).
_FILLER = r"(?:please|can you|could you|would you|just|for me|now|vox|hey|um|uh|ok|okay)"
_FILLER_RE = re.compile(rf"^(?:{_FILLER}\s+)+|(?:\s+{_FILLER})+$", re.I)

_MAX_ARG_WORDS = 6
_MAX_ARG_CHARS = 60

# The last observed action, so the NEXT utterance can be read as a negative signal ("no" / a re-say).
# Consumed after one utterance — a rejection has to be immediate to mean anything.
_pending: dict | None = None
# The same action, but kept until the next one replaces it: "remember that" / "forget that" / "when I
# say X I mean Y" all refer back to it, and those must survive the check_negative sweep that every
# utterance triggers (otherwise saying "remember that" would itself clear what you meant to save).
_last: dict | None = None


def _setting(key: str, fallback):
    """Live dashboard override, else the fallback. Mirrors dispatch/assistant — fully guarded."""
    try:
        from vox.web import settings_store
        val = settings_store.get(key)
        if val is not None:
            return val
    except Exception:
        pass
    return fallback


def mode() -> str:
    """``off`` | ``suggest`` | ``auto``. Default ``auto``: learning shouldn't hand the user a queue of
    admin — it should just get faster on its own. Safe because a wrong guess expires (probation, doc
    03) and one correction retires it. ``suggest`` queues for approval; ``off`` disables writing."""
    return str(_setting("learning_mode", "auto"))


def should_confirm(cand: dict, *, phrase: str = "", label: str = "") -> tuple[bool, str]:
    """Should Vox ASK before saving this one, rather than just doing it?

    Two triggers. (1) ``learning_confirm`` is on — the user wants to vet every command. (2) The
    mapping is a LEAP: the words and the thing it resolved to share almost nothing, which is the
    signature of a lucky guess rather than a understood request ("open the thing" → some button whose
    label has no word in common). Everything else saves silently — the point is not to create work.
    """
    if _setting("learning_confirm", False):
        return True, "confirm-every-command is on"
    return False, ""


def looks_like_a_leap(phrase: str, label: str) -> bool:
    """Do the words and the thing they resolved to share nothing? The signature of a lucky guess.

    This used to WITHHOLD the save on thin evidence. It no longer does. Under the eager model a
    command is saved on first hearing precisely so it's usable immediately, which makes "minimal
    evidence" the normal case rather than a warning sign — withholding then blocked the common good
    case ("refresh page" → reload share no letters, yet it's exactly right) and left the user saying
    a phrase that visibly did nothing. Probation is the safety net instead: an unproven command that
    isn't used enough deletes itself, and one "no" retires it on the spot. Kept as a LOG signal, so
    odd mappings are still greppable while the trial runs."""
    return bool(phrase and label and not _shares_a_word(phrase, label))


def _shares_a_word(phrase: str, label: str, threshold: float = 0.6) -> bool:
    """Does any word in ``phrase`` resemble any word in ``label``?

    Fuzzy on purpose. Exact set-overlap fails the two cases that matter most here: inflections
    ("alexs" vs "Alex") and the sound-alikes this whole click path exists to handle ("alec" →
    "Alex"). Both are perfectly good mappings and must not trigger a confirmation prompt."""
    import difflib
    pw = command_store.normalize(phrase).split()
    lw = command_store.normalize(label).split()
    for a in pw:
        for b in lw:
            if difflib.SequenceMatcher(None, a, b).ratio() >= threshold:
                return True
    return False


def clean_phrase(text: str) -> str:
    """Normalize + strip edge filler, so 'Hey Vox, could you open Alex's chat please?' and
    'open alexs chat' cluster as the same phrase (doc 02)."""
    t = command_store.normalize(text or "")
    # normalize() strips the apostrophe, so "Alex's" arrives as "alex s" — re-join it, or the same
    # request typed two ways would sit in the candidate as two different phrases.
    t = re.sub(r"\b(\w+) s\b", r"\1s", t)
    prev = None
    while t and t != prev:  # repeat: filler often stacks ("hey vox please …")
        prev = t
        t = _FILLER_RE.sub("", t).strip()
    return t


def is_learnable(intent: str, arg: str | None, *, confidence: float | None = None) -> tuple[bool, str]:
    """The gate from doc 01. Returns ``(ok, reason)`` — the reason is recorded either way, so
    "why didn't it learn that?" is always answerable."""
    if not intent:
        return False, "no intent"
    if intent not in LEARNABLE_INTENTS:
        return False, f"intent {intent!r} is not learnable"
    if confidence is not None and confidence < 0.6:
        return False, f"low STT confidence ({confidence:.2f})"
    a = (arg or "").strip()
    if a:
        if len(a) > _MAX_ARG_CHARS or len(a.split()) > _MAX_ARG_WORDS:
            return False, "arg looks like free text, not an identifier"
        if "\n" in a or re.search(r"[?!]", a):
            return False, "arg reads as a sentence, not an identifier"
        # A bare '.' is NOT sentence punctuation here: `navigate` args are usually URLs or filenames
        # (github.com, notes.md), and rejecting every dot rejected the single most common thing worth
        # learning — caught by real shadow data ("open go proxies" → a URL, refused). Only treat a dot
        # as prose when the arg also has spaces, since identifiers don't.
        if "." in a and " " in a:
            return False, "arg reads as a sentence, not an identifier"
        if re.fullmatch(r"[\d\s:/-]+", a):
            return False, "arg is numeric / date-like"
    return True, "ok"


def clears_bar(cand: dict) -> tuple[bool, str]:
    """Has this candidate earned promotion? N clean hits inside a ROLLING window (doc 01).

    Deliberately NOT "spread across N calendar days": three uses this afternoon is a real habit, and
    making someone wait for tomorrow to get the benefit is the kind of friction that makes a feature
    feel dead. Eager promotion is safe because a wrong guess expires — see probation in doc 03.

    The guard against learning your own mistakes (saying it three times because it didn't work) is the
    negative-signal path, which is the accurate detector for that: a correction walks the candidate
    back and enough corrections block it outright. ``window_hits`` also ignores negated rows entirely.
    """
    if cand.get("blocked"):
        return False, "blocked"
    max_neg = int(_setting("learning_max_negatives", 3))
    if int(cand.get("negative_count") or 0) >= max_neg:
        return False, f"{cand['negative_count']} negative signals"
    min_hits = int(_setting("learning_min_hits", 3))
    window = float(_setting("learning_window_days", 2))
    # window_hits (clean, in-window) when the caller could compute it; else the lifetime count.
    hits = int(cand.get("window_hits", cand.get("hit_count") or 0))
    if hits < min_hits:
        return False, f"{hits}/{min_hits} hits in {window:g}d"
    return True, f"{hits} hits in {window:g}d"


def _context_id(conn, app: str | None, intent: str = "") -> int | None:
    """The context to learn into: global for focus-independent intents (see ``GLOBAL_INTENTS``),
    else the focused app's. App-scoping is the default by design (doc 02) — a bad learn can then only
    misfire in the one app it came from.

    The context is CREATED on demand: only 'Arc' is seeded, so without this everything learned in
    Slack/Cursor/anywhere else would be keyed to the *global* context — the opposite of app-scoped,
    and it would quietly make every candidate's action key wrong. An empty context is inert (it holds
    no commands), so creating one costs nothing but gets the scoping right from the first observation.
    """
    if app and intent not in GLOBAL_INTENTS:
        for c in command_store.list_contexts(conn):
            if c["kind"] == "app" and (c["match_value"] or "").lower() == app.lower():
                return c["id"]
        try:
            cid = command_store._ensure_context(conn, "app", app, app, 10)  # priority 10 = app > global
            conn.commit()
            return cid
        except Exception:
            pass  # couldn't create it → fall back to global rather than lose the observation
    for c in command_store.list_contexts(conn):
        if c["kind"] == "global":
            return c["id"]
    return None


def observe(heard: str, intent: str, arg: str | None, *, app: str | None = None,
            success: bool = True, confidence: float | None = None, log=None) -> dict | None:
    """The single entry point, called after the LLM executor acts.

    Applies the never-learn gate, then either notes that an EXISTING command already covers this
    action (so the phrase would become an alias) or upserts a candidate and counts the hit. Returns a
    summary dict for logging, or None when nothing was recorded.

    SHADOW MODE: this never creates or edits a command. Fully guarded — any failure is swallowed,
    because an observer must never break the action the user actually asked for.
    """
    global _pending, _last
    try:
        if mode() == "off" or not success:
            return None
        ok, why = is_learnable(intent, arg, confidence=confidence)
        phrase = clean_phrase(heard)
        if not phrase:
            return None
        conn = command_store.connect()
        try:
            ctx_id = _context_id(conn, app, intent)
            if ctx_id is None:
                return None
            scoped_app = app if intent not in GLOBAL_INTENTS else None
            ctx_label = scoped_app or "global"
            if not ok:
                command_store.log_resolution(
                    conn, heard=phrase, context_kind="app" if scoped_app else "global",
                    context_value=scoped_app, intent=intent, arg=arg, resolved_by="llm",
                    success=success, confidence=confidence)
                if log:
                    log(f"  [learn] {phrase!r} → {intent} — not learnable ({why})")
                return {"learnable": False, "reason": why}

            # Does a command for this ACTION already exist? Then the words are an alias, never a
            # second command — this is what stops "send Alex a message" / "open Alex's chat"
            # becoming two rows (doc 02).
            existing = command_store.find_by_action(conn, ctx_id, intent, arg)
            cand = command_store.note_candidate(
                conn, context_id=ctx_id, intent=intent, arg=arg, phrase=phrase)
            command_store.log_resolution(
                conn, heard=phrase, context_kind="app" if scoped_app else "global",
                context_value=scoped_app, command_id=existing["id"] if existing else None,
                intent=intent, arg=arg, resolved_by="llm", success=success,
                confidence=confidence, candidate_id=cand["id"])
            cand["window_hits"] = command_store.window_hits(
                conn, cand["id"], float(_setting("learning_window_days", 2)))
            ready, bar = clears_bar(cand)
            _pending = {"candidate_id": cand["id"], "phrase": phrase,
                        "command_id": existing["id"] if existing else None}
            _last = {"candidate_id": cand["id"], "phrase": phrase, "intent": intent, "arg": arg,
                     "app": scoped_app, "context_id": ctx_id,
                     "command_id": existing["id"] if existing else None}

            # An action we already have a command for → the words are a new ALIAS, never a new row.
            if existing is not None:
                added = command_store.attach_phrase(conn, existing["id"], phrase)
                if log:
                    log(f"  [learn] {phrase!r} → {intent} — "
                        f"{'new alias on' if added else 'already covered by'} command "
                        f"#{existing['id']} [{ctx_label}]")
                return {"learnable": True, "candidate_id": cand["id"], "alias_of": existing["id"],
                        "added_phrase": added}

            if not ready:
                if log:
                    log(f"  [learn] {phrase!r} → {intent}{'/' + arg if arg else ''} — "
                        f"candidate #{cand['id']} ({bar}) [{ctx_label}]")
                return {"learnable": True, "candidate_id": cand["id"], "would_promote": False,
                        "bar": bar}

            m = mode()
            ask, why = should_confirm(cand, phrase=phrase, label=arg or intent)
            if m != "auto" or ask:
                # Not saving on our own: either the user wants to approve everything, the mapping is
                # a leap on thin evidence, or we're in suggest mode. It stays a candidate, and
                # "remember that" promotes it on the spot.
                if log:
                    log(f"  [learn] {phrase!r} → {intent}{'/' + arg if arg else ''} — ready ({bar}) "
                        f"but NOT saved: {why or m + ' mode'}. Say \"remember that\" to keep it.")
                return {"learnable": True, "candidate_id": cand["id"], "would_promote": True,
                        "awaiting": why or m, "bar": bar}

            cmd_id = command_store.promote(conn, cand["id"], reason="threshold")
            _last["command_id"] = cmd_id
            _refresh_cache()
            if log:
                uses = int(_setting("learning_probation_uses", 2))
                odd = " ⚠ words don't resemble the target" if looks_like_a_leap(
                    phrase, arg or intent) else ""
                log(f"  [learn] ✅ SAVED {phrase!r} → {intent}{'/' + arg if arg else ''} "
                    f"as command #{cmd_id} [{ctx_label}] — usable now, 1/{uses} uses to "
                    f"cement{odd}")
            return {"learnable": True, "candidate_id": cand["id"], "promoted": cmd_id, "bar": bar}
        finally:
            conn.close()
    except Exception:
        return None  # an observer must never break the voice loop


def note_db_hit(command_id: int, phrase: str, *, intent: str = "", arg: str | None = None,
                app: str | None = None) -> None:
    """A command resolved straight from the DB. Remember it as the last action so a following "no"
    can retire it — otherwise a learned command that does the wrong thing has no way to be corrected,
    which is the failure mode that makes people stop trusting the whole feature."""
    global _pending, _last
    p = command_store.normalize(phrase)
    _pending = {"candidate_id": None, "phrase": p, "command_id": command_id}
    _last = {"candidate_id": None, "phrase": p, "command_id": command_id,
             "intent": intent, "arg": arg, "app": app, "context_id": None}


def _refresh_cache() -> None:
    """Make a just-written command live without a restart (the §6a load-point-3 path)."""
    try:
        from vox import command_cache
        command_cache.refresh()
    except Exception:
        pass


# --- the explicit paths: you telling Vox what to keep ---------------------------------------------
# These outrank every statistic. A deliberate "remember that" is far better evidence than three
# accidental repetitions, and it's the only way to capture something you use weekly but never thrice
# in two days.

def remember_that(log=None) -> str | None:
    """"remember that" / "save that as a command" → promote the last action NOW, bar bypassed.
    Returns a short spoken confirmation, or None if there's nothing to save."""
    if _last is None:
        return None
    try:
        conn = command_store.connect()
        try:
            if _last.get("command_id"):
                return "I already know that one."
            cmd_id = command_store.promote(conn, _last["candidate_id"], reason="explicit")
            if cmd_id is None:
                return None
            _last["command_id"] = cmd_id
        finally:
            conn.close()
        _refresh_cache()
        if log:
            log(f"  [learn] ✅ SAVED on request: {_last['phrase']!r} → {_last['intent']} "
                f"(command #{cmd_id})")
        return f"Saved — I'll remember {_last['phrase']!r}."
    except Exception:
        return None


def forget_that(log=None) -> str | None:
    """"forget that" / "unlearn that" → retire the command behind the last action and block it from
    being re-learned for a while (else the next three uses would just bring it straight back)."""
    if _last is None or not _last.get("command_id"):
        return None
    try:
        conn = command_store.connect()
        try:
            ok = command_store.retire(conn, _last["command_id"], delete=True, block_days=30)
        finally:
            conn.close()
        if not ok:
            return "That one's built in — I can't unlearn it."
        _refresh_cache()
        if log:
            log(f"  [learn] 🗑  FORGOT command #{_last['command_id']} ({_last['phrase']!r}) "
                f"— blocked from re-learning for 30 days")
        _last["command_id"] = None
        return f"Forgotten — {_last['phrase']!r} won't do that any more."
    except Exception:
        return None


def remap_last(intent: str, arg: str | None, log=None) -> str | None:
    """"when I say X, I actually mean Y" → re-point the last learned command at a new action, keeping
    its phrases. Only touches learned rows; builtin/user commands stay untouchable (doc 04)."""
    if _last is None or not _last.get("command_id"):
        return None
    ok, _ = is_learnable(intent, arg)
    if not ok:
        return None
    try:
        conn = command_store.connect()
        try:
            was = command_store.remap(conn, _last["command_id"], intent, arg)
        finally:
            conn.close()
        if was is None:
            return "That one's built in — I can't change it."
        _refresh_cache()
        _last.update(intent=intent, arg=arg)
        if log:
            log(f"  [learn] ✏️  REMAPPED command #{_last['command_id']} ({_last['phrase']!r}): "
                f"{was['intent']}/{was['arg']} → {intent}/{arg}")
        return f"Got it — {_last['phrase']!r} now means {intent} {arg or ''}".strip() + "."
    except Exception:
        return None


_NEGATIVE = ("no", "nope", "not that", "wrong", "that's wrong", "thats wrong", "undo", "cancel",
             "stop", "never mind", "nevermind", "not what i meant", "go back")


def check_negative(text: str, log=None) -> bool:
    """Read the utterance that FOLLOWS an observed action: an explicit rejection — or simply saying
    the same thing again, which means the first attempt didn't do what was wanted — walks the
    candidate back (doc 01). Called once per utterance; consumes the pending action either way."""
    global _pending
    pend, _pending = _pending, None
    if pend is None or not text:
        return False
    t = command_store.normalize(text)
    repeated = bool(t) and t == pend["phrase"]
    if not (repeated or any(t == n or t.startswith(n + " ") for n in _NEGATIVE)):
        return False
    try:
        conn = command_store.connect()
        try:
            row = (conn.execute("SELECT id FROM command_log WHERE candidate_id=? "
                                "ORDER BY id DESC LIMIT 1", (pend["candidate_id"],)).fetchone()
                   if pend.get("candidate_id") else None)
            if row:
                command_store.mark_negated(conn, row["id"])  # owns the candidate walk-back
            elif pend.get("candidate_id"):  # no evidence row → walk the candidate back directly
                conn.execute("UPDATE command_candidate SET negative_count = negative_count + 1, "
                             "hit_count = MAX(0, hit_count - 1) WHERE id=?", (pend["candidate_id"],))
                conn.commit()
            # If a LEARNED command did this, one "no" retires it on the spot. A learned command doing
            # the wrong thing is worse than no command, and the user's rejection is a far more direct
            # signal than the consecutive-failure counter (which is for targets that vanished).
            if pend.get("command_id") and command_store.retire(
                    conn, pend["command_id"], delete=False, block_days=7):
                demoted = pend["command_id"]
                _refresh_cache()
                if log:
                    log(f"  [learn] ⛔ command #{demoted} did the wrong thing → disabled "
                        f"(one correction is enough)")
        finally:
            conn.close()
        if log:
            log(f"  [learn] negative signal ({'re-said' if repeated else text!r}) → "
                f"candidate #{pend['candidate_id']} walked back")
        return True
    except Exception:
        return False
