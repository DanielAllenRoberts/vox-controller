"""Live daemon state shared between the voice loop and the bridge (ideas #68).

Two things live here:

* **Typed input.** ``submit(text)`` queues text that the voice loop "hears" exactly as if it had
  been spoken. ``capture_utterance`` checks the queue every frame and hands back a ``TypedUtterance``
  (a 1-sample int16 array carrying ``.text``). The transcriber passes it straight through, so typed
  text reaches every path speech does (wake phrases, one-shots, the command DB, the executor,
  learning, the conversation feed) with no second code path to drift.
* **Mode / pause.** The loop publishes which mode it's in, so ``/api/status`` and the menu bar
  can show it. ``paused`` stops the mic being treated as speech. Typed input still works while paused.
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
        if mode != _mode:
            _mode, _mode_since = mode, time.time()


def mode() -> tuple[str, float]:
    with _lock:
        return _mode, _mode_since


# Hold-to-talk (ideas #69.1): set while the user holds the talk key in Vox.app. capture_utterance
# starts recording the moment it goes True (no wake word, no volume threshold) and stops when it
# goes False. `last_capture_ptt` tells the wake backend the last utterance was deliberate, so from
# idle it runs as a one-shot without the "vox" prefix.
_ptt_held = False
_ptt_since = 0.0
last_capture_ptt = False
# A press longer than this is a lost "release" (an app quit mid-hold, a dropped request), not a
# person talking. Expire it, or every later capture would run in hold-to-talk mode forever.
PTT_MAX_HOLD = 90.0


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
