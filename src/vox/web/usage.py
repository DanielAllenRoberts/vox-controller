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
import os
import threading
import time
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
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


def is_subscription_call(provider: str, input_tokens, output_tokens) -> bool:
    """True when a call carries no billable token counts — a flat-subscription
    provider, or any provider that didn't expose tokens (both → cost 0, and the
    dashboard renders 'subscription' rather than a misleading 0-token row)."""
    return provider in _SUBSCRIPTION_PROVIDERS or (
        input_tokens is None and output_tokens is None
    )


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

    ``input_tokens``/``output_tokens`` may be ``None`` when the provider didn't
    expose token counts (SDK/CLI subscription calls). Each field is kept as
    ``null`` when its own value is ``None`` (independent of the other), and
    ``costUsd`` is 0 for subscription/unknown-token calls, so the dashboard can
    render them as subscription calls rather than misleading 0-token requests.
    """
    # A token count is kept as null when the provider didn't expose it (None),
    # so the dashboard renders "subscription"/unknown rather than a misleading 0.
    # Both fields are handled symmetrically: each preserves its own None and
    # coerces to int otherwise, independent of the other.
    in_tok = None if input_tokens is None else int(input_tokens or 0)
    out_tok = None if output_tokens is None else int(output_tokens or 0)
    cost = _cost_usd(provider, model, int(in_tok or 0), int(out_tok or 0))
    event = {
        "id": uuid.uuid4().hex[:12],
        "ts": datetime.now(timezone.utc).isoformat(),
        "provider": provider,
        "model": model,
        "brain": brain,
        "kind": kind,
        "inputTokens": in_tok,
        "outputTokens": out_tok,
        "costUsd": cost,
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
        inp = int(e.get("inputTokens") or 0)   # None (subscription) → 0 for totals
        out = int(e.get("outputTokens") or 0)
        cost = float(e.get("costUsd") or 0.0)
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


# --- Cost budget -------------------------------------------------------------
# Month-to-date spend vs an optional monthly budget (settings_store key
# ``monthly_budget_usd``). Fully guarded + None-safe: a missing/garbage budget,
# an unreadable settings store, or a corrupt ledger all degrade to "no budget"
# rather than raising. The voice daemon never calls this, but the dashboard does.


def _budget_usd() -> float:
    """Read the monthly budget (USD) from the settings store, guarded.

    Returns 0.0 when the setting is unset, blank, non-numeric, negative, or the
    settings store can't be imported/read — i.e. "no budget" is the safe default.
    """
    try:
        from . import settings_store  # lazy: keep usage.py importable standalone

        raw = settings_store.get("monthly_budget_usd")
    except Exception:
        return 0.0
    if raw is None:
        return 0.0
    try:
        val = float(str(raw).strip())
    except (TypeError, ValueError):
        return 0.0
    return val if val > 0 else 0.0


def _month_key(ts: str) -> str:
    """Extract a YYYY-MM month key from an ISO timestamp (fallback: this month)."""
    try:
        return datetime.fromisoformat(ts).strftime("%Y-%m")
    except (ValueError, TypeError):
        return datetime.now(timezone.utc).strftime("%Y-%m")


def _month_to_date_cost() -> float:
    """Sum ``costUsd`` over events in the current UTC calendar month. Guarded."""
    this_month = datetime.now(timezone.utc).strftime("%Y-%m")
    try:
        with _LOCK:
            events = _read_all()
    except Exception:
        return 0.0
    total = 0.0
    for e in events:
        if _month_key(e.get("ts", "")) == this_month:
            try:
                total += float(e.get("costUsd") or 0.0)
            except (TypeError, ValueError):
                continue
    return round(total, 6)


def budget_status() -> dict:
    """Month-to-date spend vs the configured monthly budget.

    Returns ``{budgetUsd, spentUsd, remainingUsd, percent, state}`` where:
    - ``budgetUsd``    — the monthly budget (0.0 when unset / no budget).
    - ``spentUsd``     — month-to-date total cost from the ledger.
    - ``remainingUsd`` — ``budgetUsd - spentUsd`` (0.0 when no budget).
    - ``percent``      — 0-100 share of budget spent (0.0 when no budget).
    - ``state``        — "none" (no budget) | "ok" | "warn" (>=80%) | "over" (>=100%).

    Fully guarded + None-safe: any failure degrades to the no-budget shape.
    """
    budget = _budget_usd()
    spent = _month_to_date_cost()
    if budget <= 0:
        return {
            "budgetUsd": 0.0,
            "spentUsd": spent,
            "remainingUsd": 0.0,
            "percent": 0.0,
            "state": "none",
        }
    percent = round(min(max(spent / budget * 100, 0.0), 100.0), 2)
    raw_percent = spent / budget * 100
    if raw_percent >= 100:
        state = "over"
    elif raw_percent >= 80:
        state = "warn"
    else:
        state = "ok"
    return {
        "budgetUsd": round(budget, 6),
        "spentUsd": spent,
        "remainingUsd": round(budget - spent, 6),
        "percent": percent,
        "state": state,
    }


# --- Dev seed (visual QA only) ----------------------------------------------
# Guarded sample data so the Token Usage page renders during local QA. Never
# runs in normal operation: only when VOX_DEV_SEED=1, and only if the store has
# no real data yet (so it can't pollute a live ledger).

_DEV_SEED_EVENTS = [
    # (provider, model, brain, kind, in, out, latencyMs, days_ago, hour)
    ("openai", "deepseek-chat", "small", "chat", 1840, 320, 900, 3, 9),
    ("openai", "deepseek-chat", "small", "command", 2210, 96, 1100, 3, 14),
    ("anthropic", "claude-haiku-4-5", "small", "chat", 980, 410, 1300, 2, 10),
    ("openai", "deepseek-chat", "small", "rewrite", 3120, 540, 1500, 2, 11),
    ("claude_sdk", "claude-opus-4-8", "big", "chat", None, None, 4200, 2, 16),
    ("anthropic", "claude-haiku-4-5", "small", "vision", 1600, 180, 2100, 1, 8),
    ("openai", "deepseek-chat", "small", "chat", 760, 240, 850, 1, 12),
    ("claude_sdk", "claude-opus-4-8", "big", "command", None, None, 5300, 1, 15),
    ("anthropic", "claude-opus-4-8", "big", "chat", 5400, 1280, 6100, 1, 18),
    ("openai", "deepseek-chat", "small", "chat", 1320, 300, 940, 0, 9),
    ("anthropic", "claude-haiku-4-5", "small", "command", 1180, 220, 1050, 0, 13),
    ("claude_sdk", "claude-opus-4-8", "big", "chat", None, None, 4800, 0, 17),
]


def maybe_seed_dev() -> int:
    """Seed ~12 realistic sample events when ``VOX_DEV_SEED=1``. Returns the
    number of events written (0 if seeding is off or the store already has data).

    Fully guarded — any failure is swallowed; seeding is a QA convenience and
    must never affect startup or a real ledger.
    """
    if os.environ.get("VOX_DEV_SEED") != "1":
        return 0
    try:
        with _LOCK:
            if _read_all():
                return 0  # real data present — don't pollute it
            _DATA_DIR.mkdir(parents=True, exist_ok=True)
            now = datetime.now(timezone.utc)
            written = 0
            with _STORE.open("a", encoding="utf-8") as f:
                for prov, model, brain, kind, inp, out, lat, days_ago, hour in _DEV_SEED_EVENTS:
                    ts = (now - timedelta(days=days_ago)).replace(
                        hour=hour, minute=0, second=0, microsecond=0
                    )
                    sub = is_subscription_call(prov, inp, out)
                    in_tok = None if sub and inp is None else int(inp or 0)
                    out_tok = None if sub and out is None else int(out or 0)
                    event = {
                        "id": uuid.uuid4().hex[:12],
                        "ts": ts.isoformat(),
                        "provider": prov,
                        "model": model,
                        "brain": brain,
                        "kind": kind,
                        "inputTokens": in_tok,
                        "outputTokens": out_tok,
                        "costUsd": _cost_usd(prov, model, int(in_tok or 0), int(out_tok or 0)),
                        "latencyMs": lat,
                    }
                    f.write(json.dumps(event, ensure_ascii=False) + "\n")
                    written += 1
            return written
    except Exception:
        return 0
