"""Pausing speech doesn't stockpile agents' messages for later.

Pause used to hold every new utterance until resume. With several agents working, each one's
updates queued up behind the pause, then all played back to back the moment it lifted (on resume,
or by itself after PAUSE_MAX). Now an agent message that is asked for while speech is paused, or
whose turn was still to come when the pause began, is dropped instead of queued, and the speak tool
returns at once rather than blocking the agent. The utterance that was playing when you paused
still carries on from its sentence when you resume. Callers that don't opt in (Vox's voice preview)
wait out a pause as before.

Runs under pytest, or standalone without it:  .venv/bin/python tests/test_paused_speech.py
No audio plays: the engine call is faked.
"""

import importlib.util
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from vox import speech_lock, tts  # noqa: E402

ENGINES = ("_speak_say", "_speak_kokoro", "_speak_kokoro_streaming")
_saved: dict = {}
spoken: list = []


def setup_function(_=None):
    d = Path(tempfile.mkdtemp())
    for name in ("_LOCK_PATH", "_PAUSE_PATH", "_STOP_PATH"):
        _saved[name] = getattr(speech_lock, name)
    speech_lock._LOCK_PATH = d / "speaking.lock"
    speech_lock._PAUSE_PATH = d / "speech.pause"
    speech_lock._STOP_PATH = d / "speech.stop"
    spoken.clear()
    for name in ENGINES:   # the audio engines, below the pause handling in _speak_with_now
        _saved[name] = getattr(tts, name)
        setattr(tts, name, lambda text, **kw: spoken.append(text) or True)


def teardown_function(_=None):
    for name, value in _saved.items():
        setattr(speech_lock if name.endswith("_PATH") else tts, name, value)
    _saved.clear()


def _in_thread(fn):
    out = {}
    t = threading.Thread(target=lambda: out.setdefault("result", fn()), daemon=True)
    t.start()
    return t, out


def test_speaks_normally_when_not_paused():
    assert tts.speak_with("build done", drop_if_paused=True) is True
    assert spoken == ["build done"]


def test_dropped_at_once_when_asked_while_paused():
    speech_lock.set_paused(True)
    cue = []
    started = time.monotonic()
    assert tts.speak_with("build done", drop_if_paused=True, before=lambda: cue.append(1)) is False
    assert time.monotonic() - started < 0.5, "the agent must not be blocked while speech is paused"
    assert spoken == [] and cue == []


def test_dropped_when_pause_starts_while_waiting_its_turn():
    holding, release = threading.Event(), threading.Event()

    def someone_speaking():
        with speech_lock.hold("Nora"):
            holding.set()
            release.wait(5)

    threading.Thread(target=someone_speaking, daemon=True).start()
    holding.wait(2)
    waiter, out = _in_thread(lambda: tts.speak_with("tests pass", label="Silas", drop_if_paused=True))
    time.sleep(0.2)
    speech_lock.set_paused(True)   # you pause while Nora is talking; Silas is queued behind her
    time.sleep(0.2)
    speech_lock.set_paused(False)  # resume: Nora finishes...
    release.set()
    waiter.join(3)
    assert not waiter.is_alive()
    assert out.get("result") is False and spoken == [], "...but Silas's queued line must not follow"


def test_without_opting_in_a_pause_is_waited_out():
    speech_lock.set_paused(True)
    waiter, out = _in_thread(lambda: tts.speak_with("preview"))
    time.sleep(0.3)
    assert spoken == []
    speech_lock.set_paused(False)
    waiter.join(3)
    assert spoken == ["preview"] and out.get("result") is True


def _speak_server():
    spec = importlib.util.spec_from_file_location("vox_speak_server_paused", ROOT / "mcp" / "vox_speak_server.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_vox_speak_tells_the_agent_it_was_not_spoken():
    server = _speak_server()
    server._play_cue = lambda: None
    speech_lock.set_paused(True)
    reply = server._say("tests pass", "", 0)
    assert spoken == []
    assert "paused" in reply and "spoke aloud" not in reply


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for test in tests:
        setup_function()
        try:
            test()
            print("ok  ", test.__name__)
        finally:
            teardown_function()
