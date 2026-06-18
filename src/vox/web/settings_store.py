"""Runtime settings store for the dashboard bridge.

Foundation skeleton (dashboard iteration 1). A small persisted override layer on
top of the frozen ``Config`` dataclass: the dashboard writes user changes to
``data/settings.json`` and reads merge those over the Config defaults, so a
toggle in the UI takes effect on the next call that reads it (no restart for
runtime-read flags; some, noted in the schema's ``help``, need a restart).

``SCHEMA`` describes every exposed setting (CONTRACT §"Settings exposed") as a
``Setting`` = ``{key, label, group, type, value, options?, help}``. The ``value``
field is filled in live by ``all()`` from the effective value (override → Config).

Public API (CONTRACT): ``SCHEMA`` ; ``get(key)`` ; ``set(key, value)`` ;
``all()`` ; persists ``data/settings.json``.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from ..config import CONFIG

# Runtime store lives under data/ (gitignored). This file is
# src/vox/web/settings_store.py → parents[3] is the repo root.
_DATA_DIR = Path(__file__).resolve().parents[3] / "data"
_STORE = _DATA_DIR / "settings.json"

_LOCK = threading.RLock()

_PROVIDER_OPTIONS = [
    {"value": "claude_sdk", "label": "Claude (subscription / SDK)"},
    {"value": "anthropic", "label": "Anthropic API"},
    {"value": "openai", "label": "OpenAI-compatible (DeepSeek / Ollama / LM Studio)"},
    {"value": "claude_cli", "label": "Claude CLI"},
]

# Schema metadata WITHOUT the live value (value is injected from the effective
# config by ``all()``). Every key maps to a Config attribute of the same name.
_SCHEMA_META: list[dict] = [
    # --- Brains ---
    {
        "key": "small_brain_provider",
        "label": "Small brain provider",
        "group": "Brains",
        "type": "select",
        "options": _PROVIDER_OPTIONS,
        "help": "Fast/cheap brain used for chat and command execution. Restart to apply.",
    },
    {
        "key": "small_brain_model",
        "label": "Small brain model",
        "group": "Brains",
        "type": "text",
        "help": "Model id for the small brain (e.g. deepseek-chat). Restart to apply.",
    },
    {
        "key": "big_brain_provider",
        "label": "Big brain provider",
        "group": "Brains",
        "type": "select",
        "options": _PROVIDER_OPTIONS,
        "help": "Powerful brain the small brain escalates to. Restart to apply.",
    },
    {
        "key": "big_brain_model",
        "label": "Big brain model",
        "group": "Brains",
        "type": "text",
        "help": "Model id for the big brain (e.g. claude-opus-4-8). Restart to apply.",
    },
    {
        "key": "escalate_to_big_brain",
        "label": "Escalate to big brain",
        "group": "Brains",
        "type": "toggle",
        "help": "Let the small brain hand complex turns to the big brain.",
    },
    {
        "key": "escalation_mode",
        "label": "Escalation mode",
        "group": "Brains",
        "type": "select",
        "options": [
            {"value": "auto", "label": "Auto (always escalate)"},
            {"value": "keywords", "label": "Keywords only"},
        ],
        "help": "How control mode decides to hand an utterance to the brain.",
    },
    # --- Behavior ---
    {
        "key": "llm_executor_enabled",
        "label": "LLM executor",
        "group": "Behavior",
        "type": "toggle",
        "help": "On uncertain commands, let the brain run actions instead of just explaining.",
    },
    {
        "key": "screen_vision_enabled",
        "label": "Screen vision",
        "group": "Behavior",
        "type": "toggle",
        "help": "Let the brain screenshot and read the screen on request.",
    },
    {
        "key": "dictation_exit_on_silence",
        "label": "Dictation auto-exit on silence",
        "group": "Behavior",
        "type": "toggle",
        "help": "A long pause auto-exits dictation so it can't get stuck.",
    },
    # --- Voice ---
    {
        "key": "tts_enabled",
        "label": "Voice output (TTS)",
        "group": "Voice",
        "type": "toggle",
        "help": "Speak responses aloud via macOS say.",
    },
    {
        "key": "barge_in_enabled",
        "label": "Barge-in",
        "group": "Voice",
        "type": "toggle",
        "help": "Keep listening during a blocking LLM call so you can cancel it.",
    },
    # --- Debug ---
    {
        "key": "debug",
        "label": "Debug logging",
        "group": "Debug",
        "type": "toggle",
        "help": "Log every transcription in every mode. Verbose.",
    },
]

# Public schema (without live values). Use ``all()`` for values-filled Settings.
SCHEMA: list[dict] = _SCHEMA_META

# Key → schema-meta lookup for validation in set().
_BY_KEY = {m["key"]: m for m in _SCHEMA_META}
# Set of valid keys for guarding set().
_KEYS = set(_BY_KEY)


class SettingError(ValueError):
    """Raised by ``set`` on an unknown key or a value that fails schema validation.

    A ``ValueError`` subclass so callers that only catch ``ValueError`` still work; the
    server maps it to a 4xx with the message.
    """


def _coerce(meta: dict, value):
    """Validate ``value`` against ``meta`` and return the coerced value.

    - ``toggle`` → bool (accepts real bools and the JSON-ish strings "true"/"false").
    - ``select`` → must be one of the declared option values.
    - ``text``   → coerced to str.

    Raises ``SettingError`` with a human-readable message on bad input.
    """
    typ = meta["type"]
    if typ == "toggle":
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.lower() in ("true", "false"):
            return value.lower() == "true"
        raise SettingError(f"{meta['key']} expects a boolean, got {value!r}")
    if typ == "select":
        allowed = [o["value"] for o in meta.get("options", [])]
        if value not in allowed:
            raise SettingError(
                f"{meta['key']} must be one of {allowed}, got {value!r}"
            )
        return value
    if typ == "text":
        if value is None:
            raise SettingError(f"{meta['key']} expects text, got null")
        return str(value)
    # Unknown type in schema → accept as-is (shouldn't happen).
    return value


def _load_overrides() -> dict:
    """Load the persisted override dict (empty if missing/corrupt)."""
    if not _STORE.exists():
        return {}
    try:
        with _STORE.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_overrides(data: dict) -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _STORE.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(_STORE)


def get(key: str):
    """Return the effective value for ``key``: override → Config default.

    Unknown keys fall back to Config's attribute (or None) so callers in
    assistant.py / executor.py can read any flag safely.
    """
    with _LOCK:
        overrides = _load_overrides()
    if key in overrides:
        return overrides[key]
    return getattr(CONFIG, key, None)


def set(key: str, value) -> dict:  # noqa: A001 - matches the contract's API name
    """Validate ``value`` against the schema, persist it as an override, and return
    ``{ok, value}`` (the coerced value).

    Raises ``SettingError`` (a ``ValueError``) for an unknown key or a value that
    fails the schema's type/enum rules — the server maps that to a 4xx with the
    message. Only the validated override is written to ``data/settings.json``.
    """
    meta = _BY_KEY.get(key)
    if meta is None:
        raise SettingError(f"unknown setting key: {key!r}")
    coerced = _coerce(meta, value)
    with _LOCK:
        overrides = _load_overrides()
        overrides[key] = coerced
        _save_overrides(overrides)
    return {"ok": True, "value": coerced}


def all() -> list[dict]:  # noqa: A001 - matches the contract's API name
    """Return the full schema as ``Setting[]`` with live effective values."""
    with _LOCK:
        overrides = _load_overrides()
    out: list[dict] = []
    for meta in _SCHEMA_META:
        key = meta["key"]
        value = overrides[key] if key in overrides else getattr(CONFIG, key, None)
        setting = {
            "key": key,
            "label": meta["label"],
            "group": meta["group"],
            "type": meta["type"],
            "value": value,
            "help": meta["help"],
        }
        if "options" in meta:
            setting["options"] = meta["options"]
        out.append(setting)
    return out
