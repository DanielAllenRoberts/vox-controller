"""Learn mis-heard words in the background, from repeated failures.

Speech-to-text keeps writing some names wrong ("amituba" for a label on screen), so the same request
fails again and again. This watches every turn (``note_turn``, called from the voice loop). When
two requests fail within a few minutes, a background brain call looks at what was heard, what Vox
answered, what worked just before/after and the labels that were on screen, and decides whether a
word was mis-heard. If it's sure, the fix goes into the correction dictionary (``vocab``: "when you
hear X, write Y"), which applies to every transcript from then on. Vox shows a bubble saying what
it learned; Vocabulary in Vox.app lists it and can remove it.

Conservative on purpose, because a vocab entry rewrites ALL speech including dictation: the heard
phrase must appear in a failed request, must not be a single ordinary word or a phrase of only
everyday words (either would corrupt normal typing), and at most two are learned per look. Off with the ``mishear_learning``
setting. Fully guarded: nothing here may break the voice loop.
"""

from __future__ import annotations

import re
import threading
import time
from collections import deque

_LOCK = threading.Lock()
_turns: deque = deque(maxlen=24)        # (ts, heard, reply, failed)
_labels: list[str] = []                 # the last on-screen labels the click picker saw
_last_user: tuple[float, str] | None = None
_last_run = 0.0
_running = False

WINDOW = 300          # two failures within 5 minutes trigger a look
COOLDOWN = 180        # at most one look every 3 minutes
_FAILED = re.compile(r"(?i)what did you want me to do|i couldn'?t (?:find|map|see|click)|did you mean|"
                     r"not sure how to do that|no (?:app|tab|window) (?:called|matching)|"
                     r"my brain didn'?t answer|there aren'?t any")
_LEARN = re.compile(r"^\s*LEARN:\s*(.+?)\s*=>\s*(.+?)\s*$", re.I | re.M)
_WORDS: set[str] | None = None
_COMMON = set("""a an the and or but if then so to of in on at by for with from up down out over into
onto off about it its it's this that these those my your our their his her me you we they i he she
is are was were be been am do does did have has had can could will would should may might must not no
yes please just now here there what which who where when why how all some any more less very go get
got make made take put set let say said see look show find open close click press tap select choose
pick start stop play pause next back new one two three last first other same right left top bottom
page tab window app button link menu file screen thing things""".split())


def _setting(key: str, fallback):
    try:
        from vox.web import settings_store
        val = settings_store.get(key)
        return fallback if val is None else val
    except Exception:
        return fallback


def _dbg(msg: str) -> None:
    try:
        from vox import assistant
        assistant._dbg("[mishear]", msg)
    except Exception:
        pass


def _english() -> set[str]:
    global _WORDS
    if _WORDS is None:
        try:
            with open("/usr/share/dict/words", encoding="utf-8", errors="ignore") as f:
                _WORDS = {w.strip().lower() for w in f if w.strip()}
        except OSError:
            _WORDS = set()
    return _WORDS


def note_labels(labels) -> None:
    """The click picker's view of the screen, kept as evidence for the next look."""
    global _labels
    try:
        with _LOCK:
            _labels = [str(x)[:80] for x in list(labels)[:120]]
    except Exception:
        pass


def note_turn(role: str, text: str) -> None:
    """Every conversation turn. A user line followed by a failure reply counts as a failure."""
    global _last_user
    try:
        text = str(text or "").strip()
        if not text:
            return
        now = time.time()
        with _LOCK:
            if role == "user":
                _last_user = (now, text)
                return
            if not _last_user or now - _last_user[0] > 120:
                return
            heard = _last_user[1]
            _last_user = None
            failed = bool(_FAILED.search(text))
            _turns.append((now, heard, text[:160], failed))
            recent_fails = [t for t in _turns if t[3] and now - t[0] <= WINDOW]
            due = (failed and len(recent_fails) >= 2 and not _running and now - _last_run >= COOLDOWN)
        if due and _setting("mishear_learning", True):
            _start()
    except Exception:
        pass


def _start() -> None:
    global _running, _last_run
    with _LOCK:
        if _running:
            return
        _running, _last_run = True, time.time()
        turns, labels = list(_turns), list(_labels)
    threading.Thread(target=_look, args=(turns, labels), name="vox-mishear", daemon=True).start()


_SYSTEM = (
    "You review a voice assistant's recent requests to find MIS-HEARD WORDS. The user speaks; local "
    "speech-to-text writes it down, sometimes wrongly (a name or label turned into a sound-alike "
    "word or gibberish). Some requests FAILED. Decide whether a failure happened because a specific "
    "word or name was mis-heard, using the evidence: what the user said, what Vox answered, what "
    "worked just before or after (a rephrase that worked is strong evidence), and the labels that "
    "were on screen.\n"
    "Only when you're confident, reply with one line per fix:\n"
    "LEARN: <the mis-heard word or phrase, copied exactly from a failed request> => <what it should be>\n"
    "Rules: the heard part is 1-4 words, copied verbatim; the fix is the real word/name as it would "
    "appear on screen. Never 'fix' ordinary English words (that would corrupt the user's typing), "
    "never rewrite a whole request, and don't guess: if the failure had another cause (the thing "
    "wasn't on screen, an error, an unclear request), reply exactly NONE. At most two LEARN lines."
)


def _prompt(turns, labels, known) -> str:
    lines = []
    for ts, heard, reply, failed in turns[-14:]:
        mark = "FAILED" if failed else "ok"
        lines.append(f"[{time.strftime('%H:%M:%S', time.localtime(ts))}] {mark}  user: {heard!r}  →  vox: {reply!r}")
    out = "Recent requests (oldest first):\n" + "\n".join(lines)
    if labels:
        out += "\n\nLabels on screen at the last click attempt:\n" + "\n".join(f"  - {l}" for l in labels[:80])
    if known:
        out += "\n\nCorrections already learned (don't repeat): " + ", ".join(known[:40])
    return out


def _acceptable(heard: str, write: str, failed_texts: list[str], known: set[str]) -> str | None:
    """Why a suggested fix is rejected, or None when it's safe to learn."""
    words = re.findall(r"[a-z']+", heard.lower())
    if not words or len(words) > 4 or not write.strip():
        return "wrong shape"
    if heard.strip().lower() == write.strip().lower():
        return "no change"
    if heard.lower() in known:
        return "already learned"
    pat = re.compile(r"\b" + re.escape(heard) + r"\b", re.I)
    if not any(pat.search(t) for t in failed_texts):
        return "not in a failed request"
    # A vocab entry rewrites every transcript, dictation included. One ordinary word ("pose" → "pause")
    # would change normal writing all the time, so never. A PHRASE of real words that is an unusual
    # combination ("see grid" → "Sigrid", "fair burn lab") is fine: that exact phrase rarely means
    # anything else. Phrases of only everyday words and command verbs ("click on") are refused.
    eng = _english()
    if len(words) == 1 and eng and words[0].strip("'") in eng:
        return "an ordinary English word (would corrupt dictation)"
    if all(w.strip("'") in _COMMON for w in words):
        return "only everyday words (would corrupt dictation)"
    return None


def _look(turns, labels) -> None:
    global _running
    try:
        from vox import assistant, vocab
        known_entries = vocab.list_entries()
        known = {e["heard"].lower() for e in known_entries}
        reply = assistant.complete(_prompt(turns, labels, sorted(known)), system=_SYSTEM, brain="big",
                                   kind="mishear", prompt="mishear")
        if assistant.failed(reply):
            _dbg(f"brain failed: {reply[:100]!r}")
            return
        failed_texts = [t[1] for t in turns if t[3]]
        learned = []
        for heard, write in _LEARN.findall(reply)[:2]:
            heard, write = heard.strip().strip("'\""), write.strip().strip("'\"")
            why = _acceptable(heard, write, failed_texts, known)
            if why:
                _dbg(f"rejected {heard!r} → {write!r}: {why}")
                continue
            vocab.add(heard, write, learned=True)
            known.add(heard.lower())
            learned.append((heard, write))
            _dbg(f"LEARNED {heard!r} → {write!r}")
        if not learned:
            _dbg(f"nothing to learn ({reply.strip()[:80]!r})")
            return
        msg = "; ".join(f"“{h}” now means “{w}”" for h, w in learned)
        try:
            from vox import bubble
            bubble.show(f"I learned a word: {msg}. Say it again and it should work. "
                        "(Remove it in Vocabulary if that's wrong.)", source="Vox")
        except Exception:
            pass
    except Exception as exc:
        _dbg(f"error: {exc}")
    finally:
        with _LOCK:
            _running = False
