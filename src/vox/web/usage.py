"""Token-usage + cost ledger for the dashboard bridge.

Foundation skeleton (dashboard iteration 1). Records one ``UsageEvent`` per LLM
call, persists them as JSON Lines under ``data/usage.jsonl``, derives summaries,
and fans newly-recorded events out to WebSocket subscribers so the live feed
updates in real time. See ``docs/dashboard/CONTRACT.md`` for the data shapes.

Public API (CONTRACT):
- ``record_usage(provider, model, brain, kind, input_tokens, output_tokens,
  latency_ms) -> dict`` — append + publish a ``UsageEvent``.
- ``recent(limit=100) -> list[UsageEvent]`` — newest first.
- ``summary() -> {totals, byModel, byDay}``.
- ``PRICES`` — $ per 1M tokens, per model (input, output).
- ``subscribe()/unsubscribe()`` — async queue registry the WS route drains.

Everything is additive and defensive: the voice daemon must keep running even if
recording fails, so ``record_usage`` never raises out to its caller.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

# Runtime store lives under data/ (gitignored). This file is src/vox/web/usage.py
# → parents[3] is the repo root.
_DATA_DIR = Path(__file__).resolve().parents[3] / "data"
_STORE = _DATA_DIR / "usage.jsonl"

# One process-wide lock so the voice daemon thread and the API thread never
# interleave partial writes to the JSONL file.
_LOCK = threading.RLock()

# --- Token pricing: $ per 1M tokens (input, output). Approximate + editable. ---
# Keys are matched by exact id first, then by prefix (so dated snapshots like
# "claude-haiku-4-5-20251001" resolve via the "claude-haiku-4-5" entry).
PRICES: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-opus-4-8": (5.00, 25.00),
    "deepseek-chat": (0.27, 1.10),
}

# Providers whose calls run on a flat subscription (Claude Max via the SDK/CLI).
# Their token counts are still recorded, but cost is shown as 0 with a note.
_SUBSCRIPTION_PROVIDERS = frozenset({"claude_sdk", "claude_cli"})


def _price_for(model: str) -> tuple[float, float] | None:
    """Return (input, output) $/1M for ``model``, or None if unknown."""
    if model in PRICES:
        return PRICES[model]
    for key, price in PRICES.items():
        if model.startswith(key):
            return price
    return None


def _cost_usd(provider: str, model: str, input_tokens: int, output_tokens: int) -> float:
    """Compute call cost in USD. Subscription providers cost 0; unknown → 0."""
    if provider in _SUBSCRIPTION_PROVIDERS:
        return 0.0
    price = _price_for(model)
    if price is None:
        return 0.0
    in_rate, out_rate = price
    return round((input_tokens * in_rate + output_tokens * out_rate) / 1_000_000, 6)


# --- Subscriber registry: async queues the WS route drains. ----------------
# A subscriber is an asyncio.Queue living on the API event loop. ``publish`` is
# called from arbitrary threads (the voice daemon), so it schedules the put onto
# each queue's own loop thread-safely.
_subscribers: set[asyncio.Queue] = set()
_sub_lock = threading.Lock()


def subscribe() -> asyncio.Queue:
    """Register and return a new event queue (call from the WS handler)."""
    q: asyncio.Queue = asyncio.Queue(maxsize=1000)
    with _sub_lock:
        _subscribers.add(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    """Drop a subscriber queue (call on WS disconnect)."""
    with _sub_lock:
        _subscribers.discard(q)


def _publish(event: dict) -> None:
    """Fan an event out to every subscriber queue, thread-safely.

    Each queue remembers the loop it was created on (captured lazily here) so a
    put scheduled from the daemon thread lands on the right event loop.
    """
    with _sub_lock:
        subs = list(_subscribers)
    for q in subs:
        loop = getattr(q, "_vox_loop", None)
        try:
            if loop is None or loop.is_closed():
                # No bound loop yet (shouldn't happen post-subscribe) — best effort.
                q.put_nowait(event)
            else:
                loop.call_soon_threadsafe(_safe_put, q, event)
        except Exception:
            # A full/broken queue must never break recording.
            continue


def _safe_put(q: asyncio.Queue, event: dict) -> None:
    try:
        q.put_nowait(event)
    except asyncio.QueueFull:
        pass


def record_usage(
    provider: str,
    model: str,
    brain: str,
    kind: str,
    input_tokens: int,
    output_tokens: int,
    latency_ms: int,
) -> dict:
    """Record one LLM call: build a ``UsageEvent``, persist it, publish it.

    Returns the event dict. Never raises out — usage recording is best-effort and
    must not take down the voice loop.

    ``brain`` is "small"|"big"; ``kind`` is "chat"|"command"|"vision"|"rewrite".
    """
    input_tokens = int(input_tokens or 0)
    output_tokens = int(output_tokens or 0)
    event = {
        "id": uuid.uuid4().hex[:12],
        "ts": datetime.now(timezone.utc).isoformat(),
        "provider": provider,
        "model": model,
        "brain": brain,
        "kind": kind,
        "inputTokens": input_tokens,
        "outputTokens": output_tokens,
        "costUsd": _cost_usd(provider, model, input_tokens, output_tokens),
        "latencyMs": int(latency_ms or 0),
    }
    try:
        with _LOCK:
            _DATA_DIR.mkdir(parents=True, exist_ok=True)
            with _STORE.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception:
        # Persisting failed (disk full, perms) — still publish to the live feed.
        pass
    _publish(event)
    return event


def _read_all() -> list[dict]:
    """Load every event from the JSONL store (oldest first). Tolerates blanks."""
    if not _STORE.exists():
        return []
    out: list[dict] = []
    with _STORE.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def recent(limit: int = 100) -> list[dict]:
    """Return up to ``limit`` most-recent usage events, newest first."""
    with _LOCK:
        events = _read_all()
    events.reverse()  # stored oldest-first → newest-first
    if limit and limit > 0:
        return events[:limit]
    return events


def _day_of(ts: str) -> str:
    """Extract a YYYY-MM-DD day key from an ISO timestamp (fallback: today)."""
    try:
        return datetime.fromisoformat(ts).date().isoformat()
    except (ValueError, TypeError):
        return datetime.now(timezone.utc).date().isoformat()


def summary() -> dict:
    """Aggregate the full ledger into totals + per-model + per-day breakdowns."""
    with _LOCK:
        events = _read_all()

    totals = {"calls": 0, "inputTokens": 0, "outputTokens": 0, "costUsd": 0.0}
    by_model: dict[str, dict] = {}
    by_day: dict[str, dict] = defaultdict(
        lambda: {"costUsd": 0.0, "inputTokens": 0, "outputTokens": 0}
    )

    for e in events:
        inp = int(e.get("inputTokens", 0))
        out = int(e.get("outputTokens", 0))
        cost = float(e.get("costUsd", 0.0))
        totals["calls"] += 1
        totals["inputTokens"] += inp
        totals["outputTokens"] += out
        totals["costUsd"] += cost

        model = e.get("model", "unknown")
        m = by_model.get(model)
        if m is None:
            m = by_model[model] = {
                "model": model,
                "provider": e.get("provider", "unknown"),
                "calls": 0,
                "inputTokens": 0,
                "outputTokens": 0,
                "costUsd": 0.0,
            }
        m["calls"] += 1
        m["inputTokens"] += inp
        m["outputTokens"] += out
        m["costUsd"] += cost

        day = by_day[_day_of(e.get("ts", ""))]
        day["costUsd"] += cost
        day["inputTokens"] += inp
        day["outputTokens"] += out

    totals["costUsd"] = round(totals["costUsd"], 6)
    by_model_list = sorted(by_model.values(), key=lambda m: m["costUsd"], reverse=True)
    for m in by_model_list:
        m["costUsd"] = round(m["costUsd"], 6)
    by_day_list = [
        {"date": d, **{k: (round(v, 6) if k == "costUsd" else v) for k, v in vals.items()}}
        for d, vals in sorted(by_day.items())
    ]

    return {"totals": totals, "byModel": by_model_list, "byDay": by_day_list}
