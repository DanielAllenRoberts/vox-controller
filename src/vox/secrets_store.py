"""API keys, stored by Vox itself (Settings → Brains → API keys, and the setup flow).

Keys live in ``<data>/secrets.db``: a SQLite file private to this Mac user (0600), under the
gitignored data folder, never in the repo and never returned by the API (the app only learns
WHETHER a key is set). At start-up ``load()`` puts every stored key into the process environment,
so everything that reads ``os.environ`` keeps working.

A one-time import copies keys from an old ``.env`` file into the database, so nobody has to type
them again. After that ``.env`` is not read at all.
"""

from __future__ import annotations

import os
import sqlite3
import threading

from vox.paths import DATA_DIR, ENV_FILE, REPO_ROOT

_DB = DATA_DIR / "secrets.db"
_LOCK = threading.Lock()
# Key names Vox knows about (the import only copies these out of an old .env).
KNOWN = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY", "ELEVENLABS_API_KEY",
         "COMPOSIO_API_KEY", "LOCAL_AI1", "LOCAL_AI1_URL")


def _conn() -> sqlite3.Connection:
    _DB.parent.mkdir(parents=True, exist_ok=True)
    new = not _DB.exists()
    if new:
        _DB.touch(mode=0o600)
    con = sqlite3.connect(_DB)
    con.execute("CREATE TABLE IF NOT EXISTS secret (name TEXT PRIMARY KEY, value TEXT NOT NULL, "
                "updated_at TEXT NOT NULL DEFAULT (datetime('now')))")
    con.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
    os.chmod(_DB, 0o600)
    return con


def get(name: str) -> str:
    with _LOCK, _conn() as con:
        row = con.execute("SELECT value FROM secret WHERE name = ?", (name,)).fetchone()
    return row[0] if row else ""


def put(name: str, value: str) -> None:
    """Save (or, with an empty value, delete) one key, and apply it to this process now."""
    value = (value or "").strip()
    with _LOCK, _conn() as con:
        if value:
            con.execute("INSERT INTO secret (name, value) VALUES (?, ?) ON CONFLICT(name) DO UPDATE "
                        "SET value = excluded.value, updated_at = datetime('now')", (name, value))
        else:
            con.execute("DELETE FROM secret WHERE name = ?", (name,))
    if value:
        os.environ[name] = value
    else:
        os.environ.pop(name, None)


def names() -> list[str]:
    with _LOCK, _conn() as con:
        return [r[0] for r in con.execute("SELECT name FROM secret ORDER BY name")]


def _parse_env(path) -> dict[str, str]:
    out = {}
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip().removeprefix("export ").strip()
            v = v.strip().strip('"').strip("'")
            if k in KNOWN and v:
                out[k] = v
    except OSError:
        pass
    return out


def import_env_once() -> list[str]:
    """Copy keys from an old .env into the database (once). Returns the names copied."""
    with _LOCK, _conn() as con:
        if con.execute("SELECT 1 FROM meta WHERE key = 'env_imported'").fetchone():
            return []
        have = {r[0] for r in con.execute("SELECT name FROM secret")}
        found: dict[str, str] = {}
        for path in (REPO_ROOT / ".env", ENV_FILE):
            for k, v in _parse_env(path).items():
                found.setdefault(k, v)
        copied = [k for k in found if k not in have]
        for k in copied:
            con.execute("INSERT INTO secret (name, value) VALUES (?, ?)", (k, found[k]))
        con.execute("INSERT INTO meta (key, value) VALUES ('env_imported', datetime('now'))")
    return copied


def load() -> list[str]:
    """Start-up: import an old .env once, then put every stored key into the environment.
    Returns the names imported this time (for the log; never the values)."""
    copied = import_env_once()
    with _LOCK, _conn() as con:
        for name, value in con.execute("SELECT name, value FROM secret"):
            os.environ[name] = value
    return copied
