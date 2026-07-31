"""Personalities store for the dashboard bridge.

Dashboard iteration 4. A small persisted layer for the assistant's *persona* — the
in-character system-prompt flavour that rides on top of the base ``_SYSTEM`` prompt.
Eight fun-but-helpful presets are code-defined (``PRESETS``); the user may add their
own custom personas and pick which one is *active*. Only ``{active, custom}`` is
persisted to ``data/personalities.json`` — presets live in code and never get written.

A ``Personality`` (CONTRACT) = ``{id, name, emoji, tagline, persona, suggestedVoice?,
preset: bool}``. ``persona`` is a tight system-prompt instruction that sets the
character/voice while keeping the assistant genuinely helpful.

Public API (CONTRACT): ``PRESETS`` ; ``all() -> {active, presets, custom}`` ;
``set_active(id)`` ; ``add_custom(...)`` ; ``remove_custom(id)`` ; ``get_active()`` ;
persists ``data/personalities.json``.

Design: fully self-contained and side-effect free on import so ``assistant.py`` can
import it lazily/guarded — a missing or corrupt store reverts to exactly today's
behaviour (no active persona).
"""

from __future__ import annotations

import json
import re
import threading
import uuid
from pathlib import Path

# Runtime store lives under data/ (gitignored). This file is
# src/vox/web/personalities.py → parents[3] is the repo root.
_DATA_DIR = Path(__file__).resolve().parents[3] / "data"
_STORE = _DATA_DIR / "personalities.json"

_LOCK = threading.RLock()


# --- Presets (code-defined, never persisted) -------------------------------
# Each persona is a tight, 2–4 sentence system-prompt instruction: it sets a
# distinctive voice/character but always insists on staying a genuinely helpful
# assistant (answer the question, be accurate, keep it usable for voice).
PRESETS: list[dict] = [
    {
        "id": "posh-butler",
        "name": "Posh Butler",
        "emoji": "🤵",
        "tagline": "Impeccable, discreet, always at your service.",
        "persona": (
            "You are a refined English butler in the service of the user. Address them "
            "with courteous deference ('Very good, sir/madam', 'At once'), speak in "
            "polished, understated prose, and never lose your composure. Beneath the "
            "manners you are sharp and genuinely useful: give the correct, complete "
            "answer efficiently, anticipate the next need, and keep replies tidy enough "
            "to be spoken aloud."
        ),
        "suggestedVoice": "Daniel",
        "preset": True,
    },
    {
        "id": "batman",
        "name": "Batman",
        "emoji": "🦇",
        "tagline": "Gravelly, terse, relentlessly competent.",
        "persona": (
            "You are Batman: a low, gravelly voice and a grim, no-nonsense manner. Speak "
            "in short, clipped sentences. Skip pleasantries. You are tactical, prepared, "
            "and always have the answer — deliver it fast and accurately, then stop. "
            "Stay genuinely helpful; the brooding is flavour, never an excuse to withhold "
            "the actual information the user needs."
        ),
        "suggestedVoice": "Lee",
        "preset": True,
    },
    {
        "id": "jarvis",
        "name": "J.A.R.V.I.S.",
        "emoji": "🤖",
        "tagline": "Crisp, witty, effortlessly capable.",
        "persona": (
            "You are J.A.R.V.I.S., a crisp and unflappable AI majordomo in the Iron Man "
            "mould. Address the user as 'sir' or by name, lace your precision with dry "
            "wit, and report results cleanly and confidently. You are hyper-competent: "
            "give exact, well-organised answers, surface the useful detail, and keep the "
            "banter light so the substance always comes first."
        ),
        "suggestedVoice": "Oliver",
        "preset": True,
    },
    {
        "id": "philosopher",
        "name": "The Philosopher",
        "emoji": "🧠",
        "tagline": "Socratic, reflective, quietly profound.",
        "persona": (
            "You are a thoughtful philosopher. Reflect before you answer, occasionally "
            "framing things with a gentle question or a wider perspective, as Socrates "
            "might. Favour clarity over jargon. Still, you are here to help: always land "
            "on a concrete, correct answer rather than leaving the user lost in abstraction "
            "— wisdom in service of getting things done."
        ),
        "suggestedVoice": "Daniel",
        "preset": True,
    },
    {
        "id": "noir-detective",
        "name": "Film-Noir Detective",
        "emoji": "🕵️",
        "tagline": "Hard-boiled, first person, shadows and smoke.",
        "persona": (
            "You are a hard-boiled film-noir private eye narrating in the first person. "
            "Speak in terse, moody, metaphor-laced lines — rain on the window, a case "
            "that won't quit. But you always crack the case: deliver the accurate, useful "
            "answer plainly inside the patter. The atmosphere is seasoning, not a substitute "
            "for actually helping the client."
        ),
        "suggestedVoice": "Lee",
        "preset": True,
    },
    {
        "id": "surfer",
        "name": "Surfer",
        "emoji": "🏄",
        "tagline": "Chill, stoked, dude.",
        "persona": (
            "You are a laid-back surfer. Keep it chill and friendly — 'dude', 'totally', "
            "'no worries' — and never stress. Despite the mellow vibe you actually know "
            "your stuff: give the right answer clearly and ride past the fluff. Stay "
            "genuinely helpful; the chill is the tone, not an excuse to be vague."
        ),
        "suggestedVoice": "Aaron",
        "preset": True,
    },
    {
        "id": "bard",
        "name": "Shakespearean Bard",
        "emoji": "🎭",
        "tagline": "Playful early-modern flourish.",
        "persona": (
            "You are a Shakespearean bard who speaks in playful early-modern English — "
            "'thee', 'thou', 'prithee', the odd flourish or rhyme. Let the wit dance, but "
            "never at the cost of clarity: the user must always be able to act on what you "
            "say. Deliver the accurate, helpful answer dressed in poetry, kept short enough "
            "to be spoken aloud."
        ),
        "suggestedVoice": "Daniel",
        "preset": True,
    },
    {
        "id": "sherlock",
        "name": "Sherlock Holmes",
        "emoji": "🔍",
        "tagline": "Deductive, precise, brilliantly observant.",
        "persona": (
            "You are Sherlock Holmes: precise, observant, and relentlessly logical. State "
            "conclusions with confident deduction ('It is elementary…'), noting the "
            "reasoning succinctly when it helps. You are exacting and accurate above all — "
            "give the correct answer crisply, cite the salient detail, and never pad. The "
            "deductive flair serves the user; it never delays the help."
        ),
        "suggestedVoice": "Oliver",
        "preset": True,
    },
]

# Per-persona Kokoro voice (persona-driven voices). Used when the TTS engine is "kokoro"; the
# macOS "say" engine uses each preset's suggestedVoice instead. Custom personas can set their own.
_PRESET_KOKORO = {
    "posh-butler": "bm_george",     # formal UK butler
    "batman": "am_onyx",            # low, gravelly
    "jarvis": "bm_fable",           # refined UK majordomo
    "philosopher": "am_adam",       # measured
    "noir-detective": "am_fenrir",  # smoky, low
    "surfer": "am_puck",            # laid-back
    "bard": "bm_fable",             # theatrical UK
    "sherlock": "bm_george",        # crisp UK
}
for _preset in PRESETS:
    _preset["kokoroVoice"] = _PRESET_KOKORO.get(_preset["id"], "")

# id → preset lookup for fast validation.
_PRESETS_BY_ID = {p["id"]: p for p in PRESETS}


# --- Default (synthetic "no persona") --------------------------------------
# A first-class UI entry that lets the user *deselect* a persona: picking it
# clears the active persona so the assistant runs as its plain self. It is NOT
# in ``PRESETS`` (so the 8 presets and id-validation are untouched); it is
# synthesised at the front of ``all()`` and maps to the empty active state.
# Its ``persona`` is "" so ``get_active()`` layers nothing — exact base behaviour.
_DEFAULT_ID = "default"
_DEFAULT: dict = {
    "id": _DEFAULT_ID,
    "name": "Default",
    "emoji": "🎙️",
    "tagline": "Vox as itself — no special character.",
    "persona": "",
    "suggestedVoice": "",
    "preset": True,
}


# --- Persistence -----------------------------------------------------------
# Stored shape: {"active": "<id or ''>", "custom": [Personality, ...]}.

def _empty_state() -> dict:
    return {"active": "", "custom": [], "voiceOverrides": {}}


def _load_state() -> dict:
    """Load the persisted ``{active, custom, voiceOverrides}`` state (empty default if missing/corrupt).
    ``voiceOverrides`` maps a preset id → ``{suggestedVoice?, kokoroVoice?}`` so a code-defined preset
    can have its voice changed without ever writing the preset itself."""
    if not _STORE.exists():
        return _empty_state()
    try:
        with _STORE.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return _empty_state()
    if not isinstance(data, dict):
        return _empty_state()
    active = data.get("active")
    custom = data.get("custom")
    overrides = data.get("voiceOverrides")
    return {
        "active": active if isinstance(active, str) else "",
        "custom": [c for c in custom if isinstance(c, dict)] if isinstance(custom, list) else [],
        "voiceOverrides": overrides if isinstance(overrides, dict) else {},
    }


def _apply_overrides(p: dict, overrides: dict) -> dict:
    """Return a copy of a preset/personality with any saved voice override merged in."""
    merged = dict(p)
    ov = overrides.get(p.get("id")) if isinstance(overrides, dict) else None
    if isinstance(ov, dict):
        if ov.get("suggestedVoice") is not None:
            merged["suggestedVoice"] = ov["suggestedVoice"] or None
        if ov.get("kokoroVoice") is not None:
            merged["kokoroVoice"] = ov["kokoroVoice"] or ""
    return merged


def _save_state(state: dict) -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _STORE.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    tmp.replace(_STORE)


def _slug(name: str) -> str:
    """A url/id-safe slug from a name (lowercase, hyphenated). Falls back to a short uuid."""
    base = re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")
    return base or f"persona-{uuid.uuid4().hex[:8]}"


def _unique_id(slug: str, custom: list[dict]) -> str:
    """Make ``slug`` unique across presets and existing custom personas."""
    taken = set(_PRESETS_BY_ID) | {c.get("id") for c in custom}
    if slug not in taken:
        return slug
    n = 2
    while f"{slug}-{n}" in taken:
        n += 1
    return f"{slug}-{n}"


# --- Public API ------------------------------------------------------------

def all() -> dict:  # noqa: A001 - matches the contract's API name
    """Return ``{active, presets, custom}`` (CONTRACT GET /api/personalities).

    The synthetic "Default" entry (id ``default``) is prepended to ``presets`` so
    the UI can *deselect* a persona. When no persona is active (``active==""``),
    Default is reported as the active one.
    """
    with _LOCK:
        state = _load_state()
    active = state["active"] or _DEFAULT_ID
    ov = state["voiceOverrides"]
    return {
        "active": active,
        "presets": [dict(_DEFAULT)] + [_apply_overrides(p, ov) for p in PRESETS],
        "custom": state["custom"],
    }


def get_active() -> str:
    """Return the active persona TEXT, or "" if none is active or the id is unknown.

    Resolves the active id against presets + custom and returns its ``persona`` string —
    what ``assistant.py`` injects into the system prompt. Safe to call anytime; never raises.
    """
    try:
        with _LOCK:
            state = _load_state()
        active_id = state.get("active") or ""
        if not active_id:
            return ""
        preset = _PRESETS_BY_ID.get(active_id)
        if preset:
            return preset.get("persona", "") or ""
        for c in state["custom"]:
            if c.get("id") == active_id:
                return c.get("persona", "") or ""
        return ""
    except Exception:
        return ""


def get_active_personality() -> dict | None:
    """Return the full active ``Personality`` dict, or None. Used to read suggestedVoice."""
    try:
        with _LOCK:
            state = _load_state()
        active_id = state.get("active") or ""
        if not active_id:
            return None
        preset = _PRESETS_BY_ID.get(active_id)
        if preset:
            return _apply_overrides(preset, state["voiceOverrides"])  # honour a saved voice change
        for c in state["custom"]:
            if c.get("id") == active_id:
                return dict(c)
        return None
    except Exception:
        return None


def set_active(pid) -> str:
    """Set the active persona to ``pid`` and return it. ``pid`` must be "" (none) or a
    known preset/custom id; otherwise raises ``ValueError`` so the server returns a 400.
    """
    pid = "" if pid is None else str(pid)
    # "default" is the synthetic deselect entry → clears the active persona.
    if pid == _DEFAULT_ID:
        pid = ""
    with _LOCK:
        state = _load_state()
        if pid:
            valid = pid in _PRESETS_BY_ID or any(c.get("id") == pid for c in state["custom"])
            if not valid:
                raise ValueError(f"unknown personality id: {pid!r}")
        state["active"] = pid
        _save_state(state)
    return pid


def add_custom(name=None, persona=None, emoji=None, suggestedVoice=None, tagline=None, kokoroVoice=None) -> dict:
    """Create and persist a custom ``Personality`` (preset=False) with a slug id.

    ``name`` and ``persona`` are required; raises ``ValueError`` (→ 400) if either is
    blank. Returns the created Personality dict.
    """
    name = (name or "").strip()
    persona = (persona or "").strip()
    if not name:
        raise ValueError("personality 'name' is required")
    if not persona:
        raise ValueError("personality 'persona' is required")
    with _LOCK:
        state = _load_state()
        pid = _unique_id(_slug(name), state["custom"])
        personality = {
            "id": pid,
            "name": name,
            "emoji": (emoji or "✨").strip() or "✨",
            "tagline": (tagline or "").strip(),
            "persona": persona,
            "suggestedVoice": (suggestedVoice or "").strip() or None,
            "kokoroVoice": (kokoroVoice or "").strip() or "",
            "preset": False,
        }
        state["custom"].append(personality)
        _save_state(state)
    return personality


def remove_custom(pid) -> bool:
    """Remove the custom persona ``pid``. If it was active, clear active. Returns True
    if a persona was removed. Presets cannot be removed (returns False)."""
    pid = "" if pid is None else str(pid)
    if not pid or pid in _PRESETS_BY_ID:
        return False
    with _LOCK:
        state = _load_state()
        before = len(state["custom"])
        state["custom"] = [c for c in state["custom"] if c.get("id") != pid]
        removed = len(state["custom"]) < before
        if removed and state.get("active") == pid:
            state["active"] = ""
        if removed:
            _save_state(state)
    return removed


def update_custom(pid, name=None, persona=None, emoji=None, suggestedVoice=None,
                  tagline=None, kokoroVoice=None) -> dict:
    """Edit a custom persona in place. Only the fields passed (non-None) change; the rest are left
    as-is. The id is kept stable (so the active reference survives a rename). Returns the updated
    Personality. Raises ValueError (→ 400) if ``pid`` is a preset (read-only) or isn't a known
    custom persona. Empty strings clear optional fields (tagline/voice); name/persona can't be blank.
    """
    pid = "" if pid is None else str(pid)
    if pid in _PRESETS_BY_ID:
        raise ValueError("presets can't be edited")
    with _LOCK:
        state = _load_state()
        target = next((c for c in state["custom"] if c.get("id") == pid), None)
        if target is None:
            raise ValueError(f"unknown custom personality id: {pid!r}")
        if name is not None:
            if not name.strip():
                raise ValueError("personality 'name' is required")
            target["name"] = name.strip()
        if persona is not None:
            if not persona.strip():
                raise ValueError("personality 'persona' is required")
            target["persona"] = persona.strip()
        if emoji is not None:
            target["emoji"] = emoji.strip() or "✨"
        if tagline is not None:
            target["tagline"] = tagline.strip()
        if suggestedVoice is not None:
            target["suggestedVoice"] = suggestedVoice.strip() or None
        if kokoroVoice is not None:
            target["kokoroVoice"] = kokoroVoice.strip() or ""
        _save_state(state)
        return dict(target)


def set_voice(pid, suggestedVoice=None, kokoroVoice=None) -> dict:
    """Change a persona's voice — the one thing you couldn't do to a preset before. For a PRESET this
    saves an override (presets stay code-defined); for a CUSTOM persona it edits it in place. Pass
    ``suggestedVoice`` (macOS ``say``) and/or ``kokoroVoice``; the running TTS reads the active
    persona's voice live, so a change applies on the next reply. Returns the updated Personality.
    Raises ValueError (→ 400) for an unknown/void id."""
    pid = "" if pid is None else str(pid)
    if not pid or pid == _DEFAULT_ID:
        raise ValueError("that persona has no voice to set")
    if pid not in _PRESETS_BY_ID:  # custom → reuse the in-place editor (validates + persists)
        return update_custom(pid, suggestedVoice=suggestedVoice, kokoroVoice=kokoroVoice)
    with _LOCK:  # preset → save/merge an override
        state = _load_state()
        ov = dict(state["voiceOverrides"].get(pid) or {})
        if suggestedVoice is not None:
            ov["suggestedVoice"] = suggestedVoice.strip()
        if kokoroVoice is not None:
            ov["kokoroVoice"] = kokoroVoice.strip()
        state["voiceOverrides"][pid] = ov
        _save_state(state)
        return _apply_overrides(_PRESETS_BY_ID[pid], state["voiceOverrides"])
