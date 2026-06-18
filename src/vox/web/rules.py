"""Behavior-rules store for the dashboard bridge.

Dashboard iteration 5. A small persisted layer for the user's custom *behavior
rules* — short standing instructions ("always answer in metric", "never use
emoji", "keep replies under two sentences") that the assistant layers on top of
its base system prompt. Each rule can be toggled on/off without deleting it.

A ``Rule`` (CONTRACT) = ``{id, text, enabled}``. ``id`` is a short uuid string so
it survives as the ``{rid}`` path param in PATCH/DELETE. The whole list is
persisted to ``data/rules.json``.

Public API (CONTRACT): ``list_rules() -> Rule[]`` ; ``add_rule(text) -> Rule`` ;
``update_rule(id, **fields)`` (text and/or enabled) ; ``remove_rule(id) -> bool`` ;
plus ``enabled_rules_text()`` — the enabled rule texts joined into a short block
for the assistant to inject (empty string when none). Persists ``data/rules.json``.

Design: fully self-contained and side-effect free on import so ``assistant.py``
can import it lazily/guarded — a missing or corrupt store reverts to exactly
today's behaviour (no extra rules layered on).
"""

from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path

# Runtime store lives under data/ (gitignored). This file is
# src/vox/web/rules.py → parents[3] is the repo root.
_DATA_DIR = Path(__file__).resolve().parents[3] / "data"
_STORE = _DATA_DIR / "rules.json"

_LOCK = threading.RLock()


# --- Persistence -----------------------------------------------------------
# Stored shape: {"rules": [Rule, ...]}, where Rule = {id, text, enabled}.

def _clean_rule(r) -> dict | None:
    """Coerce a loaded entry to a valid ``Rule`` dict, or None if unusable."""
    if not isinstance(r, dict):
        return None
    rid = r.get("id")
    text = r.get("text")
    if not isinstance(rid, str) or not rid:
        return None
    if not isinstance(text, str):
        return None
    return {"id": rid, "text": text, "enabled": bool(r.get("enabled", True))}


def _load_rules() -> list[dict]:
    """Load the persisted rules list (empty default if missing/corrupt)."""
    if not _STORE.exists():
        return []
    try:
        with _STORE.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []
    raw = data.get("rules") if isinstance(data, dict) else data
    if not isinstance(raw, list):
        return []
    out = []
    for r in raw:
        cleaned = _clean_rule(r)
        if cleaned is not None:
            out.append(cleaned)
    return out


def _save_rules(rules: list[dict]) -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _STORE.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump({"rules": rules}, f, ensure_ascii=False, indent=2)
    tmp.replace(_STORE)


# --- Public API ------------------------------------------------------------

def list_rules() -> list[dict]:
    """Return all rules as ``Rule[]`` (CONTRACT GET /api/rules)."""
    with _LOCK:
        return _load_rules()


def add_rule(text) -> dict:
    """Create and persist a new rule (``enabled`` defaults True). Returns the Rule.

    ``text`` is required; raises ``ValueError`` (→ 400) if blank.
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("rule 'text' is required")
    rule = {"id": uuid.uuid4().hex[:12], "text": text, "enabled": True}
    with _LOCK:
        rules = _load_rules()
        rules.append(rule)
        _save_rules(rules)
    return rule


def update_rule(rid, text=None, enabled=None, **_ignored) -> dict:
    """Update a rule's ``text`` and/or ``enabled``. Returns the updated Rule.

    Only the provided fields change; unknown kwargs are ignored so an over-eager
    request body can't break it. Raises ``ValueError`` (→ 400) on an unknown id or
    a blank ``text``.
    """
    rid = "" if rid is None else str(rid)
    with _LOCK:
        rules = _load_rules()
        for rule in rules:
            if rule["id"] == rid:
                if text is not None:
                    new_text = str(text).strip()
                    if not new_text:
                        raise ValueError("rule 'text' cannot be blank")
                    rule["text"] = new_text
                if enabled is not None:
                    rule["enabled"] = bool(enabled)
                _save_rules(rules)
                return rule
    raise ValueError(f"unknown rule id: {rid!r}")


def remove_rule(rid) -> bool:
    """Remove the rule ``rid``. Returns True if a rule was removed."""
    rid = "" if rid is None else str(rid)
    if not rid:
        return False
    with _LOCK:
        rules = _load_rules()
        before = len(rules)
        kept = [r for r in rules if r["id"] != rid]
        removed = len(kept) < before
        if removed:
            _save_rules(kept)
    return removed


def enabled_rules_text() -> str:
    """Return the enabled rule texts as a short bulleted block, or "" if none.

    What ``assistant.py`` injects into the system prompt. Safe to call anytime;
    never raises — any failure returns "" so the daemon behaves as today.
    """
    try:
        with _LOCK:
            rules = _load_rules()
        lines = [f"- {r['text'].strip()}" for r in rules if r.get("enabled") and r["text"].strip()]
        return "\n".join(lines)
    except Exception:
        return ""
