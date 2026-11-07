"""Vox's agent team (Paperclip-inspired): Vox → a CEO that manages → worker agents in your projects.

Each worker is a real Claude Code session (Claude Agent SDK, on the user's Claude login) running in
one project folder, so it reads that project's CLAUDE.md. It keeps its session between tasks
(``resume``), so "ask the GetPrice agent if it's done" continues the same conversation.

* ``start(folder, task, name=None)``: create (or reuse) the agent for a folder and give it a task.
* ``message(name, text)``: ask an idle agent something and get its answer; a busy one gets it queued.
* ``status()`` / ``get(name)``: who's working on what, and their latest update.
* ``ceo(request)``: the router's AGENTS: directive. A Claude session with tools over the above
  (list, start, message, stop) works out what the user meant and answers in a sentence or two.

What a worker may do without asking (``_can_use_tool``): read anything; edit files inside its own
folder; run read-only and test/build commands. Anything else (installing, deleting, pushing, other
folders) waits for the user: Vox says "The GetPrice agent wants to run `npm install`. Allow it?" and
the run pauses until "yes"/"no" (``answer``). No screen control.

State: ``<data>/team.json``; each agent's transcript: ``<data>/team/<name>.jsonl``.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import threading
import time
from pathlib import Path

from vox.paths import DATA_DIR

_STATE = DATA_DIR / "team.json"
_LOGS = DATA_DIR / "team"
_LOCK = threading.RLock()
_threads: dict[str, threading.Thread] = {}
_clients: dict[str, object] = {}            # name → live ClaudeSDKClient (for stop)
_inbox: dict[str, list[str]] = {}           # messages for a busy agent, delivered after its turn
_approvals: list[dict] = []                 # pending {"id","agent","what","event","allow"}

_READ_TOOLS = {"Read", "Glob", "Grep", "LS", "WebSearch", "WebFetch", "TodoWrite", "NotebookRead",
               "TodoRead", "Task", "ExitPlanMode"}
_EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
_SAFE_CMD = re.compile(
    r"^\s*(?:git\s+(?:status|diff|log|show|branch|blame|rev-parse|ls-files)\b|ls\b|cat\b|head\b|tail\b|"
    r"grep\b|rg\b|find\b|pwd\b|wc\b|echo\b|which\b|tree\b|"
    r"(?:npm|pnpm|yarn|bun)\s+(?:test|run\s+(?:test|lint|build|typecheck|check))\b|"
    r"(?:uv\s+run\s+)?(?:python3?\s+-m\s+)?pytest\b|make\s+(?:test|lint|check|build)\b|"
    r"cargo\s+(?:test|check|build|clippy)\b|go\s+(?:test|build|vet)\b|swift\s+(?:build|test)\b|"
    r"(?:npx\s+)?tsc\b|ruff\s+check\b|eslint\b)")
_CHAINING = re.compile(r"[;&`]|\|\||>|<|\$\(")


def _setting(key: str, fallback):
    try:
        from vox.web import settings_store
        val = settings_store.get(key)
        return fallback if val is None else val
    except Exception:
        return fallback


# --- state ---------------------------------------------------------------------------------------

def _load() -> dict:
    try:
        d = json.loads(_STATE.read_text())
        return d if isinstance(d, dict) else {"agents": []}
    except Exception:
        return {"agents": []}


def _save(d: dict) -> None:
    _STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=2))
    tmp.replace(_STATE)


def _update(name: str, **fields) -> dict | None:
    hit = None
    with _LOCK:
        d = _load()
        for a in d["agents"]:
            if a["name"] == name:
                a.update(fields, updated_at=time.time())
                _save(d)
                hit = dict(a)
                break
    if hit is not None and ("status" in fields):
        _card_follow(hit)   # the Agents board shows it in Working / Needs you / Done
    return hit


def status() -> list[dict]:
    """Every agent: name, folder, status (idle/working/waiting/stopped/error/terminal), task, last update.
    Includes the user's own Claude Code sessions that registered with Vox (``vox.agents``) as
    status "terminal": shown, but Vox can't message them yet."""
    with _LOCK:
        out = _load()["agents"]
    pend = {p["agent"]: p["what"] for p in _approvals}
    for a in out:
        a["waitingFor"] = pend.get(a["name"], "")
    return out + _terminal_agents({_key(a["name"]) for a in out})


def _terminal_agents(skip: set) -> list[dict]:
    try:
        from vox import agents as registry
        rows = []
        for e in registry.all_agents():
            pid = int(e.get("pid") or 0)
            try:
                os.kill(pid, 0)          # still running?
            except Exception:
                continue
            if _key(e.get("name", "")) in skip:
                continue
            rows.append({"name": e.get("name", "?"), "folder": e.get("cwd", ""), "status": "terminal",
                         "task": "", "external": True, "waitingFor": "",
                         "last_update": f"Running in your terminal since {e.get('registered_at', '?')}."})
        return rows
    except Exception:
        return []


def get(name: str) -> dict | None:
    want = _key(name)
    agents = status()
    return (next((a for a in agents if _key(a["name"]) == want), None)
            or next((a for a in agents if want and (want in _key(a["name"]) or _key(a["name"]) in want)), None))


def _key(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", re.sub(r"\b(?:the|agent|my)\b", "", (s or "").lower()))


def transcript(name: str, limit: int = 200) -> list[dict]:
    try:
        lines = (_LOGS / f"{_key(name)}.jsonl").read_text().splitlines()[-limit:]
        return [json.loads(ln) for ln in lines if ln.strip()]
    except Exception:
        return []


def _log(name: str, kind: str, text: str) -> None:
    try:
        _LOGS.mkdir(parents=True, exist_ok=True)
        with open(_LOGS / f"{_key(name)}.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.time(), "kind": kind, "text": text[:4000]}) + "\n")
    except Exception:
        pass


# --- the Agents board: one card per task, moved as the agent works --------------------------------
AGENTS_BOARD = "Agents"
_COLUMN = {"working": "Working", "waiting": "Needs you", "error": "Needs you", "stopped": "Done", "idle": "Done"}


def _board_conn():
    from vox import board_store
    conn = board_store.build()
    if board_store.resolve_board(conn, AGENTS_BOARD) is None:
        board_store.create_board(conn, AGENTS_BOARD, ["Working", "Needs you", "Done"])
    return conn


def _new_card(name: str, task: str, folder: Path) -> int | None:
    try:
        from vox import board_store
        conn = _board_conn()
        try:
            title = task.strip().splitlines()[0][:90] or "Task"
            card = board_store.add_card(conn, "Working", title, f"{name} · {folder.name}\n\n{task.strip()}",
                                        [name], AGENTS_BOARD)
            return card["id"]
        finally:
            conn.close()
    except Exception:
        return None


def _card_follow(agent: dict) -> None:
    """Keep the agent's current card in the column that matches its status, with its latest update."""
    cid = agent.get("card_id")
    if not cid:
        return
    try:
        from vox import board_store
        conn = _board_conn()
        try:
            card = board_store._card_row(conn, int(cid))
            if card is None:
                return
            board_store.move_card(conn, int(cid), _COLUMN.get(agent.get("status", ""), "Working"),
                                  board=AGENTS_BOARD)
            upd = (agent.get("last_update") or "").strip()
            if upd and agent.get("status") in ("idle", "error", "waiting", "stopped"):
                head = card["body"].split("\n\nLatest:")[0]
                board_store.update_card(conn, int(cid), body=f"{head}\n\nLatest: {upd[-500:]}")
        finally:
            conn.close()
    except Exception:
        pass


# --- folders -------------------------------------------------------------------------------------

def projects_root() -> Path:
    return Path(os.path.expanduser(str(_setting("team_projects_root", "~/Repos") or "~/Repos")))


def find_folder(spoken: str) -> Path | None:
    """A project folder by its spoken name ("get price" → …/getprice), up to three levels under the
    projects root. An absolute or ~ path is taken as given if it exists."""
    s = (spoken or "").strip()
    if s.startswith(("/", "~")):
        p = Path(os.path.expanduser(s))
        return p if p.is_dir() else None
    want = re.sub(r"[^a-z0-9]", "", re.sub(r"\b(?:the|my|folder|project|repo)\b", "", s.lower()))
    if not want:
        return None
    root = projects_root()
    best: Path | None = None
    for depth in range(1, 4):
        for p in sorted(root.glob("/".join(["*"] * depth))):
            if p.is_dir() and not p.name.startswith(".") and re.sub(r"[^a-z0-9]", "", p.name.lower()) == want:
                return p
            if best is None and p.is_dir() and want in re.sub(r"[^a-z0-9]", "", p.name.lower()):
                best = p
    return best


# --- permissions ---------------------------------------------------------------------------------

def _inside(path: str, folder: Path) -> bool:
    try:
        return Path(os.path.expanduser(path)).resolve().is_relative_to(folder.resolve())
    except Exception:
        return False


def _ask_user(agent: str, what: str) -> dict:
    """Queue a yes/no for the user and say it out loud. Returns the pending entry."""
    entry = {"id": f"{time.time():.6f}", "agent": agent, "what": what, "event": threading.Event(), "allow": False}
    with _LOCK:
        _approvals.append(entry)
    _update(agent, status="waiting")
    _announce(agent, f"wants to {what}. Should it go ahead?")
    return entry


def pending_approval() -> dict | None:
    with _LOCK:
        return _approvals[0] if _approvals else None


def answer(allow: bool, agent: str | None = None) -> str:
    """The user's yes/no to the oldest waiting request (or that agent's)."""
    with _LOCK:
        hit = next((p for p in _approvals if not agent or _key(p["agent"]) == _key(agent)), None)
        if hit is None:
            return "Nothing's waiting for your OK."
        _approvals.remove(hit)
    hit["allow"] = bool(allow)
    hit["event"].set()
    return f"Okay, {hit['agent']} can go ahead." if allow else f"Okay, I've told {hit['agent']} not to."


def _policy(agent: str, folder: Path):
    async def can_use_tool(tool, inp, _ctx):
        from claude_agent_sdk.types import PermissionResultAllow, PermissionResultDeny
        what = None
        if tool in _READ_TOOLS or tool.startswith("mcp__"):
            return PermissionResultAllow()
        if tool in _EDIT_TOOLS:
            path = inp.get("file_path") or inp.get("notebook_path") or ""
            if _inside(path, folder):
                return PermissionResultAllow()
            what = f"edit {path}, outside its folder"
        elif tool == "Bash":
            cmd = str(inp.get("command", "")).strip()
            if _SAFE_CMD.match(cmd) and not _CHAINING.search(cmd):
                return PermissionResultAllow()
            what = f"run `{cmd[:160]}`"
        else:
            what = f"use {tool}"
        entry = _ask_user(agent, what)
        loop = asyncio.get_running_loop()
        answered = await loop.run_in_executor(None, entry["event"].wait, 1800)
        _update(agent, status="working")
        if answered and entry["allow"]:
            _log(agent, "approved", what)
            return PermissionResultAllow()
        _log(agent, "denied", what)
        return PermissionResultDeny(message="The user said no (or didn't answer). Don't retry it; carry on "
                                            "without it or explain what you need.")
    return can_use_tool


# --- talking -------------------------------------------------------------------------------------

def _announce(agent: str, text: str) -> None:
    """Tell the user something from an agent: a bubble, and speech unless replies are muted."""
    line = f"{agent} {text}" if text.startswith(("wants", "is ", "has ")) else f"{agent}: {text}"
    try:
        from vox import working_memory
        working_memory.note_did(f"agent update: {line}")
    except Exception:
        pass
    try:
        from vox.web import conversation
        conversation.record_turn("assistant", line, brain="agent", kind="agent")
    except Exception:
        pass
    try:
        from vox import bubble
        bubble.show(line, source=agent)
    except Exception:
        pass
    if _setting("team_speak_updates", True):
        try:
            from vox import tts
            tts.speak(line)
        except Exception:
            pass


_WORKER_SYSTEM = (
    "You are {name}, one of the user's coding agents, working in the project at {folder}. Vox, their "
    "voice assistant, manages you and passes on what they say. Work the way you normally would in "
    "this project (follow its CLAUDE.md). Keep going until the task is done or you're blocked. You "
    "may read anything and edit files in this folder; other actions ask the user first, so don't "
    "work around a refusal. When you finish, or need the user, end with 2–3 plain sentences that Vox "
    "will read out: what you did, what's left, or exactly what you need. No markdown in that ending."
)


async def _turn(name: str, folder: Path, prompt: str, session_id: str | None) -> tuple[str, str | None]:
    from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ClaudeSDKClient, ResultMessage, TextBlock
    opts = ClaudeAgentOptions(
        cwd=str(folder), setting_sources=["project"], resume=session_id or None,
        system_prompt={"type": "preset", "preset": "claude_code",
                       "append": _WORKER_SYSTEM.format(name=name, folder=folder)},
        can_use_tool=_policy(name, folder),
        max_turns=int(_setting("team_max_turns", 200) or 200))
    last_text, new_session = "", session_id
    async with ClaudeSDKClient(options=opts) as client:
        _clients[name] = client
        try:
            await client.query(prompt)
            async for msg in client.receive_response():
                if isinstance(msg, AssistantMessage):
                    texts = [b.text for b in msg.content if isinstance(b, TextBlock)]
                    if texts:
                        last_text = " ".join(texts).strip()
                        _log(name, "said", last_text)
                        _update(name, last_update=last_text[-600:])
                    for b in msg.content:
                        if type(b).__name__ == "ToolUseBlock":
                            _log(name, "tool", f"{b.name} {json.dumps(b.input)[:300]}")
                elif isinstance(msg, ResultMessage):
                    new_session = msg.session_id or new_session
        finally:
            _clients.pop(name, None)
    return last_text, new_session


def _run(name: str, prompt: str) -> None:
    a = get(name)
    if a is None:
        return
    folder = Path(a["folder"])
    _update(name, status="working")
    _log(name, "user", prompt)
    try:
        text, sid = asyncio.run(_turn(name, folder, prompt, a.get("session_id")))
        _update(name, status="idle", session_id=sid, last_update=(text or "")[-600:])
        if text:
            _announce(name, _ending(text))
    except Exception as exc:
        _update(name, status="error", last_update=f"Stopped with an error: {exc}"[:600])
        _announce(name, f"stopped with an error: {str(exc)[:160]}")
    finally:
        with _LOCK:
            queued = _inbox.pop(name, [])
            _threads.pop(name, None)
        if queued:   # messages that arrived mid-task
            _spawn(name, "Messages from the user while you were working:\n" + "\n".join(f"- {m}" for m in queued))


def _ending(text: str) -> str:
    """The last few sentences: what the agent wrote for Vox to read."""
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return " ".join(parts[-3:])[:500]


def _spawn(name: str, prompt: str) -> None:
    t = threading.Thread(target=_run, args=(name, prompt), name=f"vox-team-{_key(name)}", daemon=True)
    with _LOCK:
        _threads[name] = t
    t.start()


def busy(name: str) -> bool:
    with _LOCK:
        t = _threads.get(name)
    return bool(t and t.is_alive())


# --- what the CEO (and the app) call -------------------------------------------------------------

def start(folder: str, task: str, name: str | None = None) -> str:
    path = find_folder(folder)
    if path is None:
        return f"I couldn't find a project folder called {folder!r} under {projects_root()}."
    name = (name or f"{path.name} agent").strip()
    with _LOCK:
        d = _load()
        existing = next((a for a in d["agents"] if _key(a["name"]) == _key(name)), None)
        if existing is None:
            d["agents"].append({"name": name, "folder": str(path), "status": "idle", "session_id": None,
                                "task": task, "last_update": "", "created_at": time.time(),
                                "updated_at": time.time()})
        else:
            existing.update(task=task, folder=str(path), updated_at=time.time())
        _save(d)
    if busy(name):
        _inbox.setdefault(name, []).append(task)
        return f"{name} is busy; it'll pick this up next."
    _update(name, card_id=_new_card(name, task, path))
    _spawn(name, task)
    return f"Started {name} in {path.name}."


def message(name: str, text: str, wait: float = 90) -> str:
    """Pass something to an agent. Idle: run it and wait up to ``wait`` s for the answer. Busy: queue it
    and report what it's doing now."""
    a = get(name)
    if a is None:
        return f"There's no agent called {name!r}."
    if a.get("external"):
        return (f"{a['name']} runs in your terminal ({a.get('folder', '')}), so I can't message it yet. "
                f"I can start a Vox agent in that folder instead.")
    if busy(a["name"]):
        _inbox.setdefault(a["name"], []).append(text)
        upd = a.get("last_update") or "no update yet"
        return f"{a['name']} is working on {a.get('task') or 'its task'}. Latest: {upd[-300:]} (I've passed your message on.)"
    _spawn(a["name"], text)
    t = _threads.get(a["name"])
    if t:
        t.join(wait)
    if busy(a["name"]):
        return f"{a['name']} is on it; it'll report back when done."
    return (get(a["name"]) or {}).get("last_update") or "No answer."


def stop(name: str) -> str:
    a = get(name)
    if a is None:
        return f"There's no agent called {name!r}."
    client = _clients.get(a["name"])
    if client is None:
        _update(a["name"], status="idle")
        return f"{a['name']} wasn't working on anything."
    try:
        fut = asyncio.run_coroutine_threadsafe(client.interrupt(), asyncio.get_event_loop())  # best effort
        fut.cancel()
    except Exception:
        pass
    _update(a["name"], status="stopped")
    return f"Asked {a['name']} to stop."


def remove(name: str) -> bool:
    with _LOCK:
        d = _load()
        rest = [a for a in d["agents"] if _key(a["name"]) != _key(name)]
        if len(rest) == len(d["agents"]):
            return False
        d["agents"] = rest
        _save(d)
    return True


# --- the CEO -------------------------------------------------------------------------------------

_CEO_SYSTEM = (
    "You are the CEO of the user's coding agents, working for Vox, their voice assistant. The user "
    "spoke a request about their agents. Use your tools: list_agents to see who exists and what they're "
    "doing; start_agent to create an agent in a project folder (by the folder's name, e.g. 'getprice') "
    "with a clear task; message_agent to ask an agent something or give it new instructions; "
    "stop_agent to stop one. Pick the agent the user means from its name or folder. Then reply with "
    "what Vox should SAY: one to three short spoken sentences, no markdown. When you pass on an agent's "
    "own answer, say it in first person as that agent ('It's the GetPrice agent: I've fixed…')."
)


def ceo(request: str) -> str:
    try:
        from claude_agent_sdk import (AssistantMessage, ClaudeAgentOptions, ClaudeSDKClient, TextBlock,
                                      create_sdk_mcp_server, tool)
    except Exception as exc:
        return f"The agent system needs the Claude Agent SDK ({exc})."

    def _txt(s: str) -> dict:
        return {"content": [{"type": "text", "text": s}]}

    @tool("list_agents", "Every agent: name, folder, status, task and latest update.", {})
    async def list_agents(_args):
        rows = status()
        if not rows:
            return _txt("No agents yet. Projects root: " + str(projects_root()))
        return _txt("\n".join(f"- {a['name']} [{a['status']}] folder={a['folder']} task={a.get('task','')!r} "
                              f"latest={a.get('last_update','')[-300:]!r}"
                              + (f" WAITING FOR USER: {a['waitingFor']}" if a.get("waitingFor") else "")
                              for a in rows))

    @tool("start_agent", "Start (or reuse) an agent in a project folder with a task.",
          {"folder": str, "task": str, "name": str})
    async def start_agent(args):
        return _txt(await asyncio.to_thread(start, args["folder"], args["task"], args.get("name") or None))

    @tool("message_agent", "Send an agent a question or instruction; returns its answer, or what it's busy with.",
          {"name": str, "text": str})
    async def message_agent(args):
        return _txt(await asyncio.to_thread(message, args["name"], args["text"], 90))

    @tool("stop_agent", "Stop an agent's current work.", {"name": str})
    async def stop_agent(args):
        return _txt(stop(args["name"]))

    server = create_sdk_mcp_server("team", tools=[list_agents, start_agent, message_agent, stop_agent])

    async def go():
        from vox import prompts
        system = prompts.system("chat").split("YOUR TASK NOW:")[0] + "YOUR TASK NOW:\n" + _CEO_SYSTEM
        opts = ClaudeAgentOptions(mcp_servers={"team": server}, system_prompt=system, setting_sources=[],
                                  tools=[], max_turns=12, strict_mcp_config=True,
                                  allowed_tools=["mcp__team__list_agents", "mcp__team__start_agent",
                                                 "mcp__team__message_agent", "mcp__team__stop_agent"])
        said = ""
        async with ClaudeSDKClient(options=opts) as client:
            await client.query(request)
            async for msg in client.receive_response():
                if isinstance(msg, AssistantMessage):
                    t = " ".join(b.text for b in msg.content if isinstance(b, TextBlock)).strip()
                    said = t or said
        return said

    try:
        return asyncio.run(asyncio.wait_for(go(), 240)) or "Done."
    except asyncio.TimeoutError:
        return "The agents are taking a while; I'll tell you when they report back."
    except Exception as exc:
        return f"I couldn't reach the agents: {str(exc)[:160]}"
