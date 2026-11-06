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

from vox.paths import DATA_DIR

import json
import threading
import uuid

# Runtime store lives under data/ (gitignored) — see vox/paths.py.
_DATA_DIR = DATA_DIR
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
    app = r.get("app")
    return {"id": rid, "text": text, "enabled": bool(r.get("enabled", True)),
            "app": app.strip() if isinstance(app, str) and app.strip() else None}


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


def add_rule(text, app=None) -> dict:
    """Create and persist a new rule (``enabled`` defaults True). Returns the Rule.

    ``text`` is required; raises ``ValueError`` (→ 400) if blank.
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("rule 'text' is required")
    app = app.strip() if isinstance(app, str) and app.strip() else None
    rule = {"id": uuid.uuid4().hex[:12], "text": text, "enabled": True, "app": app}
    with _LOCK:
        rules = _load_rules()
        rules.append(rule)
        _save_rules(rules)
    return rule


_UNSET = object()


def update_rule(rid, text=None, enabled=None, app=_UNSET, **_ignored) -> dict:
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
                if app is not _UNSET:
                    rule["app"] = app.strip() if isinstance(app, str) and app.strip() else None
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


def enabled_rules_text(app: str | None = None) -> str:
    """Return the enabled rules as a short block, or "" if none: every rule for everywhere, plus
    the rules for ``app`` (the app in front) under their own heading. Rules for other apps are left
    out, which is the point of app notes: each app's quirks reach the prompt only when that app is
    in front, instead of every app's list riding along on every call.

    What ``assistant.py`` and the command router inject into the system prompt. Never raises."""
    try:
        with _LOCK:
            rules = [r for r in _load_rules() if r.get("enabled") and r["text"].strip()]
        lines = [f"- {r['text'].strip()}" for r in rules if not r.get("app")]
        here = [r for r in rules if r.get("app") and app and r["app"].lower() == app.lower()]
        if here:
            lines.append(f"While {app} is in front:")
            lines += [f"- {r['text'].strip()}" for r in here]
        return "\n".join(lines)
    except Exception:
        return ""
