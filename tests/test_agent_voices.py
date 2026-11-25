"""Each named agent gets its own voice, so you learn who's talking by ear, not only by the name.

When an agent registers, it is given a random Kokoro voice that no other running agent is using and
that isn't Vox's own voice. vox-speak then speaks in it. Agents whose process has gone don't hold on
to a voice, and don't confuse which agent a hook came from.

Runs under pytest, or standalone without it:  .venv/bin/python tests/test_agent_voices.py
Nothing is spoken: the registry lives in a temp folder and TTS is faked.
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
    _ORIGINALS.update(path=agents._PATH, system=agents._system_voice)
    agents._PATH = Path(tempfile.mkdtemp()) / "agents.json"
    agents._system_voice = lambda: "af_heart"


def teardown_function(_fn=None):
    agents._PATH = _ORIGINALS["path"]
    agents._system_voice = _ORIGINALS["system"]


def _dead_pid() -> int:
    p = subprocess.Popen(["true"])
    p.wait()
    return p.pid


def _plant(name: str, pid: int, voice: str, cwd: str = "/work") -> None:
    data = agents._read()
    data[name.lower()] = {"name": name, "pid": pid, "cwd": cwd, "kokoroVoice": voice,
                          "registered_at": "2026-11-21 10:00:00"}
    agents._write(data)


def test_register_gives_a_voice_that_is_not_voxs_own():
    entry = agents.register("Jeff")
    assert entry["kokoroVoice"] in agents.voice_pool()
    assert entry["kokoroVoice"] != "af_heart"


def test_running_agents_never_share_a_voice():
    pool = [v for v in agents.voice_pool() if v != "af_heart"]
    for i, voice in enumerate(pool[:-1]):
        _plant(f"agent{i}", os.getppid(), voice)  # a live process
    assert agents.register("Jeff")["kokoroVoice"] == pool[-1]


def test_a_dead_agent_frees_its_voice():
    pool = [v for v in agents.voice_pool() if v != "af_heart"]
    for i, voice in enumerate(pool[:-1]):
        _plant(f"agent{i}", os.getppid(), voice)
    _plant("ghost", _dead_pid(), pool[-1])
    assert agents.register("Jeff")["kokoroVoice"] == pool[-1]


def test_reregistering_in_the_same_process_keeps_the_voice():
    first = agents.register("Jeff")["kokoroVoice"]
    for _ in range(5):
        assert agents.register("Jeff")["kokoroVoice"] == first


def test_name_for_ignores_agents_whose_process_has_gone():
    _plant("Ghost", _dead_pid(), "am_adam", cwd="/work")
    _plant("Gary", os.getppid(), "bm_george", cwd="/work")
    assert agents.name_for("session-1", "/work") == "Gary"


def _speak_server():
    spec = importlib.util.spec_from_file_location("vox_speak_server_test", ROOT / "mcp" / "vox_speak_server.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_vox_speak_talks_in_the_agents_own_voice():
    from vox import tts
    server = _speak_server()
    heard = []
    original = tts.speak_with
    tts.speak_with = lambda text, **kw: heard.append(kw.get("kokoro_voice"))
    try:
        server.register_agent("Jeff")
        server._say("tests pass", "", 0)
    finally:
        tts.speak_with = original
    assert heard == [agents.get("Jeff")["kokoroVoice"]]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            setup_function()
            try:
                fn()
            finally:
                teardown_function()
            print("ok", name)
