"""Registry of named agents — so you can tell who is talking.

From ``docs/plan/named-agents.md`` (idea #39): you run several CLIs at once and give each a name —
"David", "Greg" — and from then on each announcement says which one it came from. The doc's insight
is that **agents name themselves**: rather than a central config guessing which terminal is which,
the agent calls ``register_agent("David")`` on its own MCP server, which knows its own process.

This module holds the registry file and its accessors, and the routing half: ``send()`` gets your
voice back *into* David's session through Claude Code's own cross-session messaging (no tmux needed —
see the section at the bottom). The pane id is still captured; it costs nothing.

Each MCP server is spawned per client, so one process = one agent, and ``$TMUX_PANE`` is inherited
from the CLI that launched it.
"""

from __future__ import annotations

from vox.paths import DATA_DIR

import json
import os
import random
import time

_PATH = DATA_DIR / "agents.json"


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
    explicit_voice = "kokoroVoice" in meta

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
        if not explicit_voice:
            entry["kokoroVoice"] = _voice_for(data, clean.lower())
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


# --- a voice of its own --------------------------------------------------------------------------
# A name only helps once it's been said. Giving each agent its own voice means you know who's
# talking from the first word, and get better at it the more you hear them. Picked at random when
# the agent registers, from the voices no other running agent has, and never Vox's own voice.

def voice_pool() -> list[str]:
    """The Kokoro voices agents are given (the same English set the voice settings offer)."""
    from vox.web.settings_store import _KOKORO_VOICE_OPTIONS
    return [o["value"] for o in _KOKORO_VOICE_OPTIONS]


def _system_voice() -> str:
    """Vox's own Kokoro voice, which no agent should sound like."""
    try:
        from vox.web import settings_store
        return settings_store.get("kokoro_voice") or "af_heart"
    except Exception:
        return "af_heart"


def _alive(pid: int) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, just not ours
    return True


def _voice_for(data: dict, key: str) -> str:
    """The voice for the agent registering as ``key``. Re-registering from the same process keeps
    its voice; otherwise a random one that no other live agent is using, falling back to any voice
    but Vox's own once they're all taken."""
    prior = data.get(key) or {}
    if prior.get("pid") == os.getpid() and prior.get("kokoroVoice"):
        return prior["kokoroVoice"]
    pool = [v for v in voice_pool() if v != _system_voice()]
    taken = {e.get("kokoroVoice") for k, e in data.items()
             if k != key and _alive(int(e.get("pid") or 0))}
    free = [v for v in pool if v not in taken]
    return random.choice(free or pool)


# --- updates: what each agent has said, for the menu bar's Agents list ----------------------------
# vox-speak's spoken lines and silent notices, and approval requests from the Claude Code hook, are
# kept as JSON lines. Each carries the pid of the agent that sent it, so a later session reusing a
# name starts clean. Trimmed to the newest _UPDATES_KEEP once it doubles.

_UPDATES = DATA_DIR / "agent_updates.jsonl"
_UPDATES_KEEP = 300


def add_update(name: str, text: str, kind: str) -> None:
    """Record that registered agent ``name`` said ``text``. ``kind``: spoke / notice / approval.
    Unknown names are ignored: the list only shows agents that registered."""
    entry = get(name)
    text = " ".join((text or "").split())
    if entry is None or not text:
        return
    row = {"at": time.time(), "name": entry["name"], "pid": entry.get("pid"), "kind": kind,
           "text": text[:400]}
    _UPDATES.parent.mkdir(parents=True, exist_ok=True)
    with open(_UPDATES, "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")
    _trim_updates()


def _trim_updates() -> None:
    try:
        lines = _UPDATES.read_text(encoding="utf-8").splitlines()
    except Exception:
        return
    if len(lines) <= _UPDATES_KEEP * 2:
        return
    tmp = _UPDATES.with_suffix(".jsonl.tmp")
    tmp.write_text("\n".join(lines[-_UPDATES_KEEP:]) + "\n", encoding="utf-8")
    os.replace(tmp, _UPDATES)


def _read_updates() -> list[dict]:
    try:
        rows = _UPDATES.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    out = []
    for line in rows:
        try:
            out.append(json.loads(line))
        except Exception:
            continue  # a half-written line from a concurrent append
    return out


def live_agents(limit: int = 5) -> list[dict]:
    """The registered agents whose process is still running, each with its newest ``limit``
    updates (newest first). Agents with the most recent news come first."""
    updates = _read_updates()
    out = []
    for e in _read().values():
        pid = int(e.get("pid") or 0)
        if not _alive(pid):
            continue
        mine = [u for u in updates
                if str(u.get("name", "")).lower() == e["name"].lower() and u.get("pid") == pid]
        mine.reverse()
        out.append({
            "name": e["name"],
            "folder": os.path.basename(str(e.get("cwd", "")).rstrip("/")),
            "cwd": e.get("cwd", ""),
            "kokoroVoice": e.get("kokoroVoice", ""),
            "registeredAt": e.get("registered_at", ""),
            "updates": mine[:limit],
        })
    out.sort(key=lambda a: a["updates"][0]["at"] if a["updates"] else 0, reverse=True)
    return out


def name_for(session_id: str = "", cwd: str = "") -> str:
    """Which named agent a Claude Code hook came from. Hooks carry the session id and working
    directory but not a name; an MCP server registers its name with its own cwd, so a cwd shared by
    exactly one registered agent identifies it. The answer is remembered against the session id so
    later hooks from that session resolve even if a second agent registers in the same folder."""
    data = _read()
    if session_id:
        for e in data.values():
            if session_id in e.get("sessions", []):
                return e["name"]
    # Only live agents: entries left by sessions that have ended would otherwise make every folder
    # they ran in ambiguous, and the hook would fall back to "An agent".
    matches = [e for e in data.values()
               if cwd and e.get("cwd") == cwd and _alive(int(e.get("pid") or 0))]
    if len(matches) != 1:
        return ""
    entry = matches[0]
    if session_id:
        entry["sessions"] = (entry.get("sessions", []) + [session_id])[-20:]
        data[entry["name"].lower()] = entry
        try:
            _write(data)
        except Exception:
            pass
    return entry["name"]


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


# --- talking back: deliver a message into a registered agent's terminal session ------------------
#
# Claude Code sessions on one Mac can message each other (``ListAgents`` / ``SendMessage``, over a
# per-session Unix socket that never leaves the machine). An idle session wakes and starts a turn; a
# busy one reads it between tool calls. The socket's wire format isn't documented, so rather than
# speak it ourselves Vox runs a throwaway headless ``claude -p`` whose only tool is SendMessage.
# No tmux, no typing into the terminal, no focus steal. ~10 s per message.
#
# The registry knows the agent's MCP-server pid; the session is the ``claude`` process above it,
# and ``claude agents --json`` names that session (e.g. "myproject-05").

def _claude_bin() -> str | None:
    import shutil
    path = shutil.which("claude")
    if path:
        return path
    home = os.path.expanduser("~/.local/bin/claude")  # the native installer; the daemon's PATH may lack it
    return home if os.path.exists(home) else None


def _claude_pid(pid: int) -> int | None:
    """The ``claude`` process that ``pid`` (an agent's MCP server) runs under, walking up parents."""
    import subprocess
    for _ in range(8):
        try:
            out = subprocess.run(["ps", "-o", "ppid=,comm=", "-p", str(pid)], capture_output=True,
                                 text=True, timeout=3).stdout.strip()
        except Exception:
            return None
        ppid, _, comm = out.partition(" ")
        if not ppid.isdigit():
            return None
        if os.path.basename(comm.strip()) == "claude":
            return pid
        pid = int(ppid)
        if pid <= 1:
            return None
    return None


def session_for(name: str) -> dict | None:
    """The live Claude Code session behind a registered agent: ``claude agents --json``'s entry
    (``name``, ``status``, ``sessionId``, ``pid``), or None if it's gone or can't be found."""
    import subprocess
    entry = get(name)
    exe = _claude_bin()
    if not entry or not exe:
        return None
    cpid = _claude_pid(int(entry.get("pid") or 0))
    if not cpid:
        return None
    try:
        out = subprocess.run([exe, "agents", "--json"], capture_output=True, text=True, timeout=15,
                             stdin=subprocess.DEVNULL).stdout
        return next((s for s in json.loads(out) if s.get("pid") == cpid and s.get("name")), None)
    except Exception:
        return None


def send(name: str, text: str, timeout: float = 90) -> tuple[bool, str]:
    """Deliver ``text`` from the user into registered agent ``name``'s terminal session.
    Returns (delivered, what to tell the user). Never raises."""
    import subprocess
    entry = get(name)
    if not entry:
        return False, f"There's no registered agent called {name!r}."
    shown = entry.get("name", name)
    session = session_for(name)
    if session is None:
        return False, f"I can't find {shown}'s Claude Code session any more. Is it still open?"
    body = (text or "").strip().replace("</msg>", "</ msg>")
    if not body:
        return False, f"What should I tell {shown}?"
    prompt = (f'Use the SendMessage tool exactly once to send the text between the <msg> tags to the '
              f'session named "{session["name"]}". Send it verbatim: do not summarise, shorten, '
              f'reword or add anything. Then reply with the single word SENT, or FAILED and the reason.\n'
              f'<msg>Message from the user, sent by voice through Vox:\n\n{body}</msg>')
    from vox.assistant import SUBSCRIPTION_ENV
    try:
        r = subprocess.run(
            [_claude_bin() or "claude", "-p", prompt, "--allowedTools", "SendMessage", "--model", "haiku",
             "--strict-mcp-config", "--setting-sources", "", "--name", "vox"],
            capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL,
            cwd=str(DATA_DIR), env={**os.environ, **SUBSCRIPTION_ENV})
    except subprocess.TimeoutExpired:
        return False, f"Sending to {shown} timed out."
    except Exception as e:
        return False, f"I couldn't send to {shown}: {e}"
    if "SENT" in (r.stdout or "") and "FAILED" not in (r.stdout or ""):
        state = session.get("status") or ""
        when = "It's mid-task, so it'll read it between steps." if state == "busy" else ""
        return True, f"Sent to {shown}. {when}".strip()
    why = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()
    return False, f"I couldn't get that to {shown}: {why[-1][:160] if why else 'no reply'}"
