"""Coding agents run on auto, Vox never reads a command aloud, and voices queue."""

import asyncio
import threading
import time

import pytest

from vox import speech_lock, team, tts
from vox.config import CONFIG


def _decide(monkeypatch, tmp_path, tool, inp, auto=True):
    """'allow', or 'ask' if the policy would have stopped for the user."""
    asked = []

    def ask(agent, what):
        asked.append(what)
        ev = threading.Event()
        ev.set()
        return {"event": ev, "allow": False}

    monkeypatch.setattr(team, "_ask_user", ask)
    monkeypatch.setattr(team, "_update", lambda *a, **k: None)
    monkeypatch.setattr(team, "_log", lambda *a, **k: None)
    monkeypatch.setattr(team, "_setting", lambda key, fb: auto if key == "team_auto_mode" else fb)
    asyncio.run(team._policy("tester", tmp_path)(tool, inp, None))
    return "ask" if asked else "allow"


@pytest.mark.parametrize("cmd", [
    "cd /somewhere/app && swift build 2>&1 | tail -25",
    'python -c "import ast; print(1)"',
    "git checkout -b feature 2>&1 | tail -2",
    "git add -A && git commit -q -m x",
    "npm install",
])
def test_auto_runs_ordinary_commands_without_asking(monkeypatch, tmp_path, cmd):
    assert _decide(monkeypatch, tmp_path, "Bash", {"command": cmd}) == "allow"


@pytest.mark.parametrize("cmd", ["git push origin main", "cd x && git  push", "sudo rm -rf /", "npm publish",
                                 "gh pr merge 3"])
def test_auto_still_asks_before_what_cannot_be_undone(monkeypatch, tmp_path, cmd):
    assert _decide(monkeypatch, tmp_path, "Bash", {"command": cmd}) == "ask"


def test_auto_edits(monkeypatch, tmp_path):
    assert _decide(monkeypatch, tmp_path, "Edit", {"file_path": str(tmp_path / "a.py")}) == "allow"
    assert _decide(monkeypatch, tmp_path, "Write", {"file_path": "/tmp/scratch.txt"}) == "allow"
    assert _decide(monkeypatch, tmp_path, "Edit", {"file_path": "/etc/hosts"}) == "ask"


def test_auto_off_asks_like_before(monkeypatch, tmp_path):
    assert _decide(monkeypatch, tmp_path, "Bash", {"command": "npm install"}, auto=False) == "ask"
    assert _decide(monkeypatch, tmp_path, "Bash", {"command": "git status"}, auto=False) == "allow"


def test_the_command_is_shown_but_never_spoken(monkeypatch):
    from vox import bubble, working_memory
    from vox.web import conversation
    said, shown = [], []
    monkeypatch.setattr(team, "_update", lambda *a, **k: None)
    monkeypatch.setattr(team, "_setting", lambda key, fb: fb)
    monkeypatch.setattr(team, "_approvals", [])
    monkeypatch.setattr(working_memory, "note_did", lambda *a, **k: None)
    monkeypatch.setattr(conversation, "record_turn", lambda *a, **k: {})
    monkeypatch.setattr(bubble, "show", lambda text, **k: shown.append(text))
    monkeypatch.setattr(tts, "speak", said.append)
    team._ask_user("docs agent", "run `git push origin main`")
    assert said == ["docs agent needs your okay to proceed."]
    assert "git push origin main" in shown[0]


def test_queue_outlasts_a_long_message():
    # At 15 s / 30 s any spoken message over ~40 words was talked over by the next speaker.
    assert CONFIG.speech_queue_max_hold >= 90
    assert CONFIG.speech_queue_timeout > CONFIG.speech_queue_max_hold


def test_second_speaker_waits_and_chime_waits_its_turn(monkeypatch, tmp_path):
    monkeypatch.setattr(speech_lock, "_LOCK_PATH", tmp_path / "speaking.lock")
    monkeypatch.setattr(speech_lock, "_setting", lambda key, fb: fb)
    monkeypatch.setattr(speech_lock, "paused", lambda: False)
    order = []
    monkeypatch.setattr(tts, "_speak_with_now", lambda text, **k: order.append(("words", time.monotonic())))
    started = threading.Event()

    def first():
        with speech_lock.hold("first"):
            started.set()
            time.sleep(0.6)
            order.append(("first done", time.monotonic()))

    t = threading.Thread(target=first)
    t.start()
    started.wait(2)
    tts.speak_with("hello", label="second", before=lambda: order.append(("chime", time.monotonic())))
    t.join()
    assert [o[0] for o in order] == ["first done", "chime", "words"]
