"""Clicking an agent in the menu bar switches to the terminal tab it's running in.

Vox walks from the agent's MCP server up to its ``claude`` process, takes that process's tty and
the terminal app hosting it, and asks the app (Ghostty or Terminal) to bring that tab forward.

Runs under pytest, or standalone without it:  .venv/bin/python tests/test_agent_focus.py
Nothing is focused: the process table and osascript are faked.
"""

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from vox import agents  # noqa: E402

_ORIGINALS = {}

# pid → (ppid, tty, command), like `ps -o ppid=,tty=,comm=`
GHOSTTY_TREE = {
    500: (400, "ttys015", "/opt/homebrew/bin/python3"),
    400: (300, "ttys015", "claude"),
    300: (200, "ttys015", "-/bin/zsh"),
    200: (100, "ttys015", "/usr/bin/login"),
    100: (1, "??", "/Applications/Ghostty.app/Contents/MacOS/ghostty"),
}


def setup_function(_fn=None):
    _ORIGINALS.update(path=agents._PATH, ps=agents._ps, osa=agents._osascript, alive=agents._alive)
    agents._PATH = Path(tempfile.mkdtemp()) / "agents.json"
    agents._alive = lambda pid: True


def teardown_function(_fn=None):
    agents._PATH = _ORIGINALS["path"]
    agents._ps = _ORIGINALS["ps"]
    agents._osascript = _ORIGINALS["osa"]
    agents._alive = _ORIGINALS["alive"]


def _plant(name: str, pid: int) -> None:
    data = agents._read()
    data[name.lower()] = {"name": name, "pid": pid, "cwd": "/work", "registered_at": "2026-11-21 10:00:00"}
    agents._write(data)


def _fake(tree: dict, ran: list, result: tuple = (True, "")):
    agents._ps = lambda pid: tree.get(pid)
    agents._osascript = lambda script: ran.append(script) or result


def test_terminal_for_finds_the_claude_tty_and_host_app():
    _fake(GHOSTTY_TREE, [])
    _plant("Jeff", 500)
    assert agents.terminal_for("Jeff") == ("Ghostty", "/dev/ttys015")


def test_an_app_bundled_python_is_not_mistaken_for_the_terminal():
    tree = dict(GHOSTTY_TREE)
    tree[500] = (400, "ttys015", "/opt/homebrew/Cellar/python@3.12/3.12.13_2/Frameworks/Python.framework/"
                                 "Versions/3.12/Resources/Python.app/Contents/MacOS/Python")
    _fake(tree, [])
    _plant("Jeff", 500)
    assert agents.terminal_for("Jeff") == ("Ghostty", "/dev/ttys015")


def test_focus_asks_ghostty_for_the_tab_with_that_tty():
    ran = []
    _fake(GHOSTTY_TREE, ran)
    _plant("Jeff", 500)
    assert agents.focus("Jeff") == (True, "")
    [script] = ran
    assert 'tell application "Ghostty"' in script
    assert '"/dev/ttys015"' in script
    assert "select tab" in script and "focus" in script


def test_focus_works_in_terminal_app_too():
    tree = dict(GHOSTTY_TREE)
    tree[100] = (1, "??", "/System/Applications/Utilities/Terminal.app/Contents/MacOS/Terminal")
    ran = []
    _fake(tree, ran)
    _plant("Jeff", 500)
    assert agents.focus("Jeff") == (True, "")
    assert 'tell application "Terminal"' in ran[0] and '"/dev/ttys015"' in ran[0]


def test_focus_explains_an_unsupported_terminal():
    tree = dict(GHOSTTY_TREE)
    tree[100] = (1, "??", "/Applications/Warp.app/Contents/MacOS/stable")
    ran = []
    _fake(tree, ran)
    _plant("Jeff", 500)
    ok, why = agents.focus("Jeff")
    assert not ok and "Warp" in why
    assert ran == []


def test_focus_explains_an_unknown_agent():
    _fake(GHOSTTY_TREE, [])
    ok, why = agents.focus("Nobody")
    assert not ok and "Nobody" in why


def test_focus_reports_when_the_tab_is_gone():
    _fake(GHOSTTY_TREE, [], result=(False, "no tab"))
    _plant("Jeff", 500)
    assert agents.focus("Jeff")[0] is False


def test_api_focus():
    from fastapi.testclient import TestClient
    from vox.web.server import create_app
    ran = []
    _fake(GHOSTTY_TREE, ran)
    _plant("Jeff", 500)
    r = TestClient(create_app()).post("/api/agents/Jeff/focus", json={},
                                      headers={"content-type": "application/json"})
    assert r.json() == {"ok": True, "error": ""}
    assert len(ran) == 1


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            setup_function()
            try:
                fn()
            finally:
                teardown_function()
            print("ok", name)
