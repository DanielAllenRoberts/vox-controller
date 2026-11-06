"""Every prompt Vox sends, in one place, viewable and editable from Vox.app.

The defaults stay in the code next to the logic that depends on them (the router prompt lists the
directives the executor parses, for example). An edit made in the app is stored in
``<data>/prompts.json`` and wins over the default until it's reset. The user can edit prompts here (and
so can a developer helping them); Vox itself has no way to, by design.

``recent()`` also keeps the last calls that were actually sent (full system prompt with its dynamic
blocks, the message, the reply), so you can see exactly what the model got.
"""

from __future__ import annotations

import collections
import importlib
import json
import threading
import time

from vox.paths import DATA_DIR

_STORE = DATA_DIR / "prompts.json"
_LOCK = threading.Lock()

# name, title, what it's for, module, attribute holding the default
REGISTRY: list[tuple[str, str, str, str, str]] = [
    ("router", "Command router",
     "Turns anything the command parser didn't recognise into one Vox action (click, open, type, "
     "remind, board, point…) or a short spoken reply. The most-used prompt.", "vox.executor", "_SYSTEM"),
    ("chat", "Conversation",
     "Vox's personality and rules when you're chatting (after \"Hey Vox\"). Your personality, "
     "rules, memories and the clock are added underneath it.", "vox.assistant", "_SYSTEM"),
    ("edit", "Rewrite selected text",
     "\"Make this more formal\", \"fix the spelling\": rewrites the text you've selected.", "vox.executor", "_EDIT_SYSTEM"),
    ("look", "Answer about the screen",
     "\"What does this say?\": answers from the text Vox can read on screen.", "vox.executor", "_LOOK_AXTREE_SYSTEM"),
    ("click_pick", "Pick what to click",
     "When \"click X\" doesn't match a button exactly: picks the right one from the list on screen.",
     "vox.executor", "_CLICK_PICK_SYSTEM"),
    ("click_vision", "Find it in a screenshot",
     "Last resort for clicking and pointing: finds the thing on a numbered screenshot. Keep the "
     "{target} and {n} placeholders.", "vox.executor", "_CLICK_VISION_PROMPT"),
    ("agent", "Screen agent",
     "Multi-step tasks done by looking at the screen and acting, step by step.", "vox.agent", "_SYSTEM"),
]
_NAMES = {r[0] for r in REGISTRY}


def _overrides() -> dict:
    try:
        return json.loads(_STORE.read_text())
    except Exception:
        return {}


def default(name: str) -> str:
    _n, _t, _d, mod, attr = next(r for r in REGISTRY if r[0] == name)
    return getattr(importlib.import_module(mod), attr)


def get(name: str) -> str:
    """The prompt to use: the user's edit if there is one, else the default."""
    text = _overrides().get(name)
    return text if isinstance(text, str) and text.strip() else default(name)


def put(name: str, text: str) -> dict:
    if name not in _NAMES:
        raise KeyError(name)
    if not (text or "").strip():
        raise ValueError("a prompt can't be empty")
    with _LOCK:
        o = _overrides()
        o[name] = text
        _STORE.parent.mkdir(parents=True, exist_ok=True)
        _STORE.write_text(json.dumps(o, indent=2))
    return describe(name)


def reset(name: str) -> dict:
    if name not in _NAMES:
        raise KeyError(name)
    with _LOCK:
        o = _overrides()
        o.pop(name, None)
        _STORE.write_text(json.dumps(o, indent=2))
    return describe(name)


def describe(name: str) -> dict:
    n, title, what, _m, _a = next(r for r in REGISTRY if r[0] == name)
    o = _overrides().get(name)
    return {"name": n, "title": title, "description": what, "text": get(n), "default": default(n),
            "edited": isinstance(o, str) and bool(o.strip())}


def all_prompts() -> list[dict]:
    return [describe(r[0]) for r in REGISTRY]


# --- what was actually sent ----------------------------------------------------------------------
_RECENT: collections.deque = collections.deque(maxlen=60)


def record(prompt: str, brain: str, model: str, system: str, message: str, reply: str) -> None:
    _RECENT.append({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "prompt": prompt, "brain": brain,
                    "model": model, "system": (system or "")[:40_000],
                    "message": (message or "")[:20_000], "reply": (reply or "")[:8_000]})


def recent(prompt: str | None = None, limit: int = 10) -> list[dict]:
    rows = [r for r in reversed(_RECENT) if prompt is None or r["prompt"] == prompt]
    return rows[:limit]
