"""Live daemon state shared between the voice loop and the bridge (ideas #68).

Two things live here:

* **Typed input.** ``submit(text)`` queues text that the voice loop "hears" exactly as if it had
  been spoken. ``capture_utterance`` checks the queue every frame and hands back a ``TypedUtterance``
  (a 1-sample int16 array carrying ``.text``). The transcriber passes it straight through, so typed
  text reaches every path speech does (wake phrases, one-shots, the command DB, the executor,
  learning, the conversation feed) with no second code path to drift.
* **Mode / pause.** The loop publishes which mode it's in, so ``/api/status`` and the menu bar
  can show it. ``paused`` stops the mic being treated as speech. Typed input still works while paused.
* **The on-screen indicator feed.** ``hud(...)`` pushes "listening" / "heard" / "state" events to
  Vox.app the instant they happen, so it can show what Vox is hearing. Nothing is stored.
"""

from __future__ import annotations

import queue
import threading
import time

import numpy as np


class TypedUtterance(np.ndarray):
    """An "utterance" that was typed, not spoken. Behaves like (silent) audio everywhere else."""

    text: str = ""


def _make(text: str) -> TypedUtterance:
    arr = np.zeros(1, dtype=np.int16).view(TypedUtterance)
    arr.text = text
    return arr


def is_typed(audio) -> bool:
    return isinstance(audio, TypedUtterance)


_typed: "queue.Queue[str]" = queue.Queue(maxsize=32)


def submit(text: str) -> bool:
    text = (text or "").strip()
    if not text:
        return False
    try:
        _typed.put_nowait(text)
        return True
    except queue.Full:
        return False


def take() -> TypedUtterance | None:
    try:
        return _make(_typed.get_nowait())
    except queue.Empty:
        return None


# --- mode / pause ---------------------------------------------------------------------------
_lock = threading.Lock()
_mode = "starting"
_mode_since = time.time()
paused = False


def set_mode(mode: str) -> None:
    global _mode, _mode_since
    with _lock:
        changed = mode != _mode
        if changed:
            _mode, _mode_since = mode, time.time()
    if changed:
        hud("state")


def mode() -> tuple[str, float]:
    with _lock:
        return _mode, _mode_since


# Hold-to-talk (ideas #69.1): set while the user holds the talk key in Vox.app. capture_utterance
# starts recording the moment it goes True (no wake word, no volume threshold) and stops when it
# goes False. `last_capture_ptt` tells the wake backend the last utterance was deliberate, so from
# idle it runs as a one-shot without the "vox" prefix.
_ptt_held = False
_ptt_since = 0.0
# Words said straight after "hey vox" in the same breath; assistant mode answers them first.
wake_remainder = ""
last_capture_ptt = False
# A press longer than this is a lost "release" (an app quit mid-hold, a dropped request), not a
# person talking. Expire it, or every later capture would run in hold-to-talk mode forever.
PTT_MAX_HOLD = 300.0


def set_ptt(held: bool) -> None:
    global _ptt_held, _ptt_since
    _ptt_held, _ptt_since = bool(held), time.time()


def ptt_down() -> bool:
    global _ptt_held
    if _ptt_held and time.time() - _ptt_since > PTT_MAX_HOLD:
        _ptt_held = False
    return _ptt_held


def set_paused(value: bool) -> None:
    global paused
    paused = bool(value)
    hud("state")


# --- on-screen indicator feed -------------------------------------------------------------------
# Vox.app's corner indicator subscribes over /api/hud/stream. Events: {"type": "listening", "on"}
# while an utterance is being captured, {"type": "heard", "text", "ignored"} with what was
# recognised, and {"type": "state"} when the mode or pause changes (the app re-reads /api/status).
# Each subscriber is (event loop, asyncio queue); the voice loop publishes from its own thread.
_hud_subs: list = []


def hud_subscribe(loop, q) -> None:
    _hud_subs.append((loop, q))


def hud_unsubscribe(q) -> None:
    _hud_subs[:] = [s for s in _hud_subs if s[1] is not q]


def _hud_put(q, event: dict) -> None:
    try:
        q.put_nowait(event)
    except Exception:  # a full queue drops the event; the indicator is never worth blocking for
        pass


def hud(kind: str, **fields) -> None:
    """Publish an indicator event. Never raises: the voice loop must not depend on anyone watching."""
    event = {"type": kind, **fields}
    for loop, q in list(_hud_subs):
        try:
            loop.call_soon_threadsafe(_hud_put, q, event)
        except Exception:
            pass


# --- stop button --------------------------------------------------------------------------------
# The ⏹ button in Vox.app (menu bar + Home). One press stops whatever Vox is doing right now: the
# reply it's speaking, a brain call it's waiting on, an agent run. It's a timestamp, not a latch, so
# work that started BEFORE the press sees it and work that starts after doesn't.
_stopped_at = 0.0


def request_stop() -> list[str]:
    """Stop what's in flight. Returns what was actually stopped (for the log and the API reply)."""
    global _stopped_at
    _stopped_at = time.time()
    stopped = []
    try:
        from vox import tts
        if tts.is_speaking():
            stopped.append("speech")
        tts.stop_speaking()
    except Exception:
        pass
    try:
        from vox import agent
        if agent.abort():
            stopped.append("agent")
    except Exception:
        pass
    return stopped


def stopped_since(t: float) -> bool:
    """True if the stop button was pressed after time ``t`` (when the caller's work began)."""
    return _stopped_at >= t
