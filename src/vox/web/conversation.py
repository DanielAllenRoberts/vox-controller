"""Live, EPHEMERAL conversation feed for the dashboard (idea #43).

A purely in-RAM ring buffer of conversation turns (your utterances, the brain's
replies, any command that ran), fanned out to WebSocket subscribers so a
Conversation dashboard page can render the running session like a standard AI
chat. **Nothing is written to disk** — persistence stays the tiered memory; this
module is a window onto what's happening *right now*, not a store.

Mirrors ``usage.py`` exactly: a process-wide subscriber registry of asyncio
queues bound to the API event loop, a thread-safe ``publish`` (the voice daemon
calls ``record_turn`` from its own thread), and ``_safe_put`` that drops on a
full queue rather than ever breaking recording.

Public API:
- ``record_turn(role, text, *, brain=None, kind=None) -> dict`` — append + publish a turn.
- ``recent(limit=100) -> list[dict]`` — newest first (the live RAM buffer).
- ``subscribe()/unsubscribe()`` — async queue registry the WS route drains.
- ``SESSION_ID`` — id created at process start so concurrent sessions are distinguishable.

Everything is additive and defensive: ``record_turn`` never raises out to its
caller, so the voice loop is never taken down by the conversation feed.
"""

from __future__ import annotations

import asyncio
import threading
import uuid
from collections import deque
from datetime import datetime, timezone

# A session id created at process start so concurrent sessions (two daemons, or a
# restart) are distinguishable on the page. Stamped onto every turn.
SESSION_ID = uuid.uuid4().hex[:12]

# In-RAM ring buffer of recent turns (oldest → newest). Bounded so a long session
# can't grow unbounded; the page only ever needs the tail. NO disk backing.
_BUFFER: deque[dict] = deque(maxlen=300)
_LOCK = threading.Lock()


# --- Subscriber registry: async queues the WS route drains. ----------------
# A subscriber is an asyncio.Queue living on the API event loop. ``publish`` is
# called from arbitrary threads (the voice daemon), so it schedules the put onto
# each queue's own loop thread-safely. Mirrors usage.py.
_subscribers: set[asyncio.Queue] = set()
_sub_lock = threading.Lock()


def subscribe() -> asyncio.Queue:
    """Register and return a new turn queue (call from the WS handler)."""
    q: asyncio.Queue = asyncio.Queue(maxsize=1000)
    with _sub_lock:
        _subscribers.add(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    """Drop a subscriber queue (call on WS disconnect)."""
    with _sub_lock:
        _subscribers.discard(q)


def _publish(turn: dict) -> None:
    """Fan a turn out to every subscriber queue, thread-safely.

    Each queue remembers the loop it was created on (set by the WS route) so a
    put scheduled from the daemon thread lands on the right event loop.
    """
    with _sub_lock:
        subs = list(_subscribers)
    for q in subs:
        loop = getattr(q, "_vox_loop", None)
        try:
            if loop is None or loop.is_closed():
                q.put_nowait(turn)
            else:
                loop.call_soon_threadsafe(_safe_put, q, turn)
        except Exception:
            # A full/broken queue must never break recording.
            continue


def _safe_put(q: asyncio.Queue, turn: dict) -> None:
    try:
        q.put_nowait(turn)
    except asyncio.QueueFull:
        pass


def record_turn(role: str, text: str, *, brain: str | None = None, kind: str | None = None) -> dict:
    """Record one conversation turn: build it, buffer it, publish it.

    Returns the turn dict. Never raises out — recording is best-effort and must
    not take down the voice loop.

    ``role`` is "user"|"assistant". ``brain`` is the replying brain
    ("small"|"big") on assistant turns, else None. ``kind`` tags the turn
    ("chat"|"command"|"reply"|…) so the page can render a command inline.
    """
    turn = {
        "id": uuid.uuid4().hex[:12],
        "session": SESSION_ID,
        "ts": datetime.now(timezone.utc).isoformat(),
        "role": role,
        "text": text if isinstance(text, str) else str(text),
        "brain": brain,
        "kind": kind,
    }
    try:
        with _LOCK:
            _BUFFER.append(turn)
    except Exception:
        pass
    _publish(turn)
    return turn


def recent(limit: int = 100) -> list[dict]:
    """Return up to ``limit`` most-recent turns from the RAM buffer, newest first."""
    with _LOCK:
        turns = list(_BUFFER)
    turns.reverse()  # buffered oldest-first → newest-first
    if limit and limit > 0:
        return turns[:limit]
    return turns
