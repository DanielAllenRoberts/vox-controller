"""What your named Claude sessions have said, for the Agents list in Vox's menu bar panel.

Each spoken line and silent notice from vox-speak, and each approval request, is kept as an update
against the agent that sent it. The menu shows the agents that are still running, newest update
first. An earlier session that used the same name doesn't leak its updates into the new one.

Runs under pytest, or standalone without it:  .venv/bin/python tests/test_agent_updates.py
Nothing is spoken or shown: the registry lives in a temp folder and TTS/bubbles are faked.
"""

import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from vox import agents  # noqa: E402

_ORIGINALS = {}


def setup_function(_fn=None):
    tmp = Path(tempfile.mkdtemp())
    _ORIGINALS.update(path=agents._PATH, updates=agents._UPDATES, system=agents._system_voice)
    agents._PATH = tmp / "agents.json"
    agents._UPDATES = tmp / "agent_updates.jsonl"
    agents._system_voice = lambda: "af_heart"


def teardown_function(_fn=None):
    agents._PATH = _ORIGINALS["path"]
    agents._UPDATES = _ORIGINALS["updates"]
    agents._system_voice = _ORIGINALS["system"]


def _dead_pid() -> int:
    p = subprocess.Popen(["true"])
    p.wait()
    return p.pid


def _plant(name: str, pid: int, cwd: str = "/work/getprice") -> None:
    data = agents._read()
    data[name.lower()] = {"name": name, "pid": pid, "cwd": cwd, "kokoroVoice": "am_adam",
                          "registered_at": "2026-11-21 10:00:00"}
    agents._write(data)


def test_live_agents_lists_running_sessions_with_newest_update_first():
    agents.register("Jeff")
    agents.add_update("Jeff", "Tests pass.", "spoke")
    agents.add_update("Jeff", "Needs your OK to push the branch.", "approval")
    [jeff] = agents.live_agents()
    assert jeff["name"] == "Jeff"
    assert [u["text"] for u in jeff["updates"]] == ["Needs your OK to push the branch.", "Tests pass."]
    assert jeff["updates"][0]["kind"] == "approval"


def test_ended_sessions_are_not_listed():
    _plant("Ghost", _dead_pid())
    _plant("Gary", os.getppid())
    assert [a["name"] for a in agents.live_agents()] == ["Gary"]


def test_a_new_session_reusing_a_name_starts_with_no_updates():
    _plant("Gary", _dead_pid())
    agents.add_update("Gary", "old session's news", "spoke")
    _plant("Gary", os.getppid())
    [gary] = agents.live_agents()
    assert gary["updates"] == []


def test_updates_for_unknown_agents_are_ignored():
    agents.add_update("Nobody", "hello", "spoke")
    assert agents.live_agents() == []


def test_folder_is_the_last_part_of_the_working_directory():
    _plant("Gary", os.getppid(), cwd="/Users/me/getprice/")
    assert agents.live_agents()[0]["folder"] == "getprice"


def test_the_log_is_trimmed_so_it_cannot_grow_forever():
    agents.register("Jeff")
    for i in range(agents._UPDATES_KEEP * 2 + 5):
        agents.add_update("Jeff", f"update {i}", "spoke")
    lines = agents._UPDATES.read_text().splitlines()
    assert len(lines) <= agents._UPDATES_KEEP * 2
    assert agents.live_agents(limit=1)[0]["updates"][0]["text"].endswith(str(agents._UPDATES_KEEP * 2 + 4))


def _speak_server():
    spec = importlib.util.spec_from_file_location("vox_speak_server_updates", ROOT / "mcp" / "vox_speak_server.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_vox_speak_records_what_a_named_agent_says_and_shows():
    from vox import bubble, tts
    server = _speak_server()
    originals = (tts.speak_with, bubble.show)
    tts.speak_with = lambda text, **kw: None
    bubble.show = lambda text, **kw: True
    try:
        server.register_agent("Jeff")
        server._say("Tests pass.", "", 0)
        server.notify("PR is open.")
    finally:
        tts.speak_with, bubble.show = originals
    kinds = [(u["kind"], u["text"]) for u in agents.live_agents()[0]["updates"]]
    assert kinds == [("notice", "PR is open."), ("spoke", "Tests pass.")]


def test_api_lists_live_agents():
    from fastapi.testclient import TestClient
    from vox.web.server import create_app
    agents.register("Jeff")
    agents.add_update("Jeff", "Tests pass.", "spoke")
    body = TestClient(create_app()).get("/api/agents").json()
    assert body["agents"][0]["name"] == "Jeff"
    assert body["agents"][0]["updates"][0]["text"] == "Tests pass."


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            setup_function()
            try:
                fn()
            finally:
                teardown_function()
            print("ok", name)
