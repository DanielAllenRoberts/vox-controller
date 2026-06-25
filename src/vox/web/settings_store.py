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
    {"value": "local_ai", "label": "Local AI (your own GPU / endpoint)"},
    {"value": "claude_cli", "label": "Claude CLI"},
]

# Common model ids per provider — shared by the small + big brain model dropdowns. Pick the one
# that matches the brain's provider. (For provider "local_ai" the model comes from local_ai_model
# in config; the Gemma entry here is just so the value displays.) Set an exotic model in config.py.
_MODEL_OPTIONS = [
    {"value": "claude-haiku-4-5-20251001", "label": "Claude Haiku 4.5 — fast (Claude / Anthropic)"},
    {"value": "claude-sonnet-4-6", "label": "Claude Sonnet 4.6 (Claude / Anthropic)"},
    {"value": "claude-opus-4-8", "label": "Claude Opus 4.8 — deep (Claude / Anthropic)"},
    {"value": "deepseek-v4-flash", "label": "DeepSeek V4 Flash — fast (OpenAI-compatible API)"},
    {"value": "deepseek-v4-pro", "label": "DeepSeek V4 Pro — capable (OpenAI-compatible API)"},
    {"value": "google/gemma-4-e4b", "label": "Gemma E4B — your local model (Local AI)"},
]

# Kokoro voice choices — shared by the system voice (kokoro_voice) and the MCP voice
# (mcp_kokoro_voice). 54 voices exist; this is the common English subset.
_KOKORO_VOICE_OPTIONS = [
    {"value": "af_heart", "label": "af_heart — US ♀ (warm, default)"},
    {"value": "af_bella", "label": "af_bella — US ♀"},
    {"value": "af_nicole", "label": "af_nicole — US ♀ (soft)"},
    {"value": "af_sarah", "label": "af_sarah — US ♀"},
    {"value": "af_sky", "label": "af_sky — US ♀"},
    {"value": "af_kore", "label": "af_kore — US ♀"},
    {"value": "am_michael", "label": "am_michael — US ♂"},
    {"value": "am_adam", "label": "am_adam — US ♂"},
    {"value": "am_onyx", "label": "am_onyx — US ♂ (deep)"},
    {"value": "am_puck", "label": "am_puck — US ♂"},
    {"value": "am_fenrir", "label": "am_fenrir — US ♂"},
    {"value": "bf_emma", "label": "bf_emma — UK ♀"},
    {"value": "bf_isabella", "label": "bf_isabella — UK ♀"},
    {"value": "bm_george", "label": "bm_george — UK ♂"},
    {"value": "bm_daniel", "label": "bm_daniel — UK ♂"},
    {"value": "bm_fable", "label": "bm_fable — UK ♂"},
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
        "type": "select",
        "options": _MODEL_OPTIONS,
        "help": "Model for the small brain — pick one that matches the provider above. Applies on "
                "the next reply. (Need a model not listed? Set small_brain_model in config.py.)",
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
        "type": "select",
        "options": _MODEL_OPTIONS,
        "help": "Model for the big brain — pick one that matches the provider above. Applies on the "
                "next reply. (Need a model not listed? Set big_brain_model in config.py.)",
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
        "help": "Let the brain read the screen on request ('what's on my screen?').",
    },
    {
        "key": "screen_vision_mode",
        "label": "Screen vision source",
        "group": "Behavior",
        "type": "select",
        "options": [
            {"value": "auto", "label": "Auto — AX tree first, screenshot fallback"},
            {"value": "axtree", "label": "AX tree only (no screenshot)"},
            {"value": "screenshot", "label": "Screenshot only"},
        ],
        "help": "How Vox reads the screen. The AX tree is token-light structured text; a screenshot "
                "is a vision-model image. 'AX tree only' tests the tree in isolation. Applies on the "
                "next request.",
    },
    {
        "key": "dictation_exit_on_silence",
        "label": "Dictation auto-exit on silence",
        "group": "Behavior",
        "type": "toggle",
        "help": "A long pause auto-exits dictation so it can't get stuck.",
    },
    {
        "key": "memory_autocapture",
        "label": "Auto-capture memories",
        "group": "Behavior",
        "type": "toggle",
        "default": True,  # not a Config field — schema is the source of truth (daemon defaults on too)
        "help": "Let Vox save memories on its own — durable facts to core, "
                "session notes to daily — and recall them in later turns. "
                "Off means memories are only what you add by hand.",
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
    {
        "key": "tts_engine",
        "label": "TTS engine",
        "group": "Voice",
        "type": "select",
        "options": [
            {"value": "say", "label": "macOS say (zero-install)"},
            {"value": "kokoro", "label": "Kokoro (local neural, ~353MB download)"},
        ],
        "help": "Voice synthesis backend. Applies live; Kokoro lazy-downloads on first use and falls back to say on any error.",
    },
    {
        "key": "kokoro_voice",
        "label": "Kokoro voice",
        "group": "Voice",
        "type": "select",
        "default": "af_heart",
        "options": _KOKORO_VOICE_OPTIONS,
        "help": "Kokoro voice (used when TTS engine is Kokoro). Applies live on the next reply. 54 voices exist incl. other languages — set kokoro_voice in config.py for one not listed.",
    },
    {
        "key": "tts_interruptible",
        "label": "Interruptible speaking",
        "group": "Voice",
        "type": "toggle",
        "help": "Talk over Vox to cut it off mid-reply. Kokoro-only, and HEADPHONES-only until AEC lands (else the mic hears itself). Applies live.",
    },
    {
        "key": "turn_detection",
        "label": "Turn detection",
        "group": "Voice",
        "type": "select",
        "options": [
            {"value": "vad", "label": "Fixed silence (VAD)"},
            {"value": "smart_turn", "label": "Smart turn (local ONNX model)"},
        ],
        "help": "How the end of your utterance is decided. smart_turn lazy-downloads an ~8MB model. May need a Vox restart to take effect.",
    },
    {
        "key": "audio_aec",
        "label": "Echo cancellation (AEC)",
        "group": "Voice",
        "type": "toggle",
        "default": False,  # not a Config field yet — schema is the source of truth (daemon defaults off)
        "help": "Acoustic echo cancellation so the mic ignores Vox's own voice on speakers. May need a Vox restart to take effect.",
    },
    {
        "key": "interrupt_slow_calls_only",
        "label": "Barge-in on slow calls only",
        "group": "Voice",
        "type": "toggle",
        "help": "Only arm barge-in for slow (big-brain/vision/compose) calls, avoiding spurious cancels on fast ones. Applies live.",
    },
    {
        "key": "interrupt_min_words",
        "label": "Barge-in min words",
        "group": "Voice",
        "type": "text",
        "help": "Whole number: a barge-in must transcribe at least this many words to count. Applies live.",
    },
    {
        "key": "interrupt_min_seconds",
        "label": "Barge-in min seconds",
        "group": "Voice",
        "type": "text",
        "help": "Decimal seconds: captured audio must be at least this long to count as a barge-in. Applies live.",
    },
    # --- MCP voice --- the vox-speak MCP heads-up voice, kept separate from the system voice
    # above so the IDE assistant sounds different from Vox. Reload the MCP server in your editor
    # to pick up changes (it reads these at speak-time).
    {
        "key": "mcp_tts_engine",
        "label": "MCP TTS engine",
        "group": "MCP voice",
        "type": "select",
        "options": [
            {"value": "system", "label": "Follow system engine"},
            {"value": "say", "label": "macOS say (zero-install)"},
            {"value": "kokoro", "label": "Kokoro (local neural)"},
        ],
        "help": "Engine for the vox-speak MCP's voice. 'Follow system' matches the TTS engine above; 'Kokoro' lazy-downloads on first use and falls back to say on any error. Reload the MCP server to apply.",
    },
    {
        "key": "mcp_tts_voice",
        "label": "MCP say voice",
        "group": "MCP voice",
        "type": "text",
        "help": "macOS `say` voice for the MCP heads-up (e.g. Samantha, Karen, Daniel, Alex). Kept distinct from the system voice. Reload the MCP server to apply.",
    },
    {
        "key": "mcp_kokoro_voice",
        "label": "MCP Kokoro voice",
        "group": "MCP voice",
        "type": "select",
        "options": _KOKORO_VOICE_OPTIONS,
        "help": "Kokoro voice for the MCP when its engine is Kokoro (or 'Follow system' resolves to Kokoro). Reload the MCP server to apply.",
    },
    {
        "key": "mcp_speak_cue",
        "label": "MCP speak cue sound",
        "group": "MCP voice",
        "type": "text",
        "help": "Path to a short sound played just before the vox-speak MCP speaks, so a spoken heads-up doesn't come out of nowhere. Blank to disable. Reload the MCP server to apply.",
    },
    # --- Cost ---
    {
        "key": "monthly_budget_usd",
        "label": "Monthly budget (USD)",
        "group": "Cost",
        "type": "text",
        "help": "Monthly spend budget in USD; 0 = no budget.",
    },
    # --- Commands (app/site-scoped command DB, idea #36) ---
    {
        "key": "command_db_enabled",
        "label": "App-scoped command DB",
        "group": "Commands",
        "type": "toggle",
        "help": "Resolve voice commands from the per-app command database (in front of the built-in "
                "parser), so the same words can do different things depending on the focused app. "
                "Off = built-in commands only. Applies live — no restart.",
    },
    {
        "key": "command_db_log",
        "label": "Log command DB activity",
        "group": "Commands",
        "type": "toggle",
        "help": "Write every command-DB query, per-app load, and resolution to vox.log. Restart to apply.",
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
    meta = _BY_KEY.get(key)
    return getattr(CONFIG, key, meta.get("default") if meta else None)


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
        value = overrides[key] if key in overrides else getattr(CONFIG, key, meta.get("default"))
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
