"""Registry of named agents — so you can tell who is talking.

From ``docs/plan/named-agents.md`` (idea #39): you run several CLIs at once and give each a name —
"David", "Greg" — and from then on each announcement says which one it came from. The doc's insight
is that **agents name themselves**: rather than a central config guessing which terminal is which,
the agent calls ``register_agent("David")`` on its own MCP server, which knows its own process.

This module is only the identity half — the registry file and its accessors. The routing half
(getting your voice back *into* David's session via ``tmux send-keys``) is stage 1 of that doc and
isn't built; the pane id is captured here anyway because it costs nothing now and is exactly what
that stage needs.

Each MCP server is spawned per client, so one process = one agent, and ``$TMUX_PANE`` is inherited
from the CLI that launched it.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

# src/vox/agents.py → parents[2] is the repo root, matching settings_store's convention.
_PATH = Path(__file__).resolve().parents[2] / "data" / "agents.json"


def _read() -> dict:
    try:
        with open(_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}  # missing or corrupt → an empty registry, never an error


def _write(data: dict) -> None:
    """Atomic replace, so a crash mid-write can't leave a truncated registry."""
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _PATH.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, _PATH)


def register(name: str, **meta) -> dict:
    """Record ``name`` as this process's agent identity and return the stored entry.

    Re-registering the same name overwrites it — an agent restarting in a new pane should take the
    name over rather than leave a stale entry pointing at a dead process. Serialised with an
    exclusive lock because several MCP servers can register at the same time.
    """
    clean = " ".join((name or "").split())
    if not clean:
        raise ValueError("an agent name can't be empty")

    entry = {
        "name": clean,
        "pid": os.getpid(),
        "tmux_pane": os.environ.get("TMUX_PANE", ""),
        "cwd": os.getcwd(),
        "registered_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    entry.update(meta)

    _PATH.parent.mkdir(parents=True, exist_ok=True)
    fh = None
    try:
        import fcntl
        fh = open(_PATH.with_suffix(".json.lock"), "a+")
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
    except Exception:
        fh = None  # no flock here → accept the small race rather than fail to register
    try:
        data = _read()
        data[clean.lower()] = entry
        _write(data)
    finally:
        if fh is not None:
            try:
                import fcntl as _f
                _f.flock(fh.fileno(), _f.LOCK_UN)
                fh.close()
            except Exception:
                pass
    return entry


def get(name: str) -> dict | None:
    """The registry entry for ``name`` (case-insensitive), or None."""
    return _read().get(" ".join((name or "").split()).lower())


def all_agents() -> list[dict]:
    """Every registered agent, newest registration first."""
    return sorted(_read().values(), key=lambda e: e.get("registered_at", ""), reverse=True)


def unregister(name: str) -> bool:
    """Drop ``name`` from the registry. Returns True if it was there."""
    key = " ".join((name or "").split()).lower()
    data = _read()
    if key not in data:
        return False
    del data[key]
    _write(data)
    return True
