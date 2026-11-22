"""When Vox is quit, agents stay quiet.

vox-speak runs inside each agent's own process, so it used to speak (and pop notification cards)
whether or not Vox was running. Quitting Vox, say before going away from the Mac, didn't stop
agents talking to an empty room. Now speak / announce_done / notify first check that Vox's engine
answers on its local API, and when it doesn't they do nothing and tell the agent why.

"Running" means Vox's own /api/status answered: another program on the same port doesn't count.

Runs under pytest, or standalone without it:  .venv/bin/python tests/test_quiet_when_vox_quit.py
"""

import importlib.util
import json
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from vox import running  # noqa: E402


def _serve(body: bytes, status: int = 200) -> HTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_running_when_vox_answers():
    server = _serve(json.dumps({"running": True, "mode": "idle", "pid": 123}).encode())
    try:
        assert running.vox_running(port=server.server_port) is True
    finally:
        server.shutdown()


def test_not_running_when_nothing_listens():
    assert running.vox_running(port=_free_port()) is False


def test_not_running_when_something_else_has_the_port():
    server = _serve(b"<html>not vox</html>")
    try:
        assert running.vox_running(port=server.server_port) is False
    finally:
        server.shutdown()


def _speak_server():
    spec = importlib.util.spec_from_file_location("vox_speak_server_quit", ROOT / "mcp" / "vox_speak_server.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod._play_cue = lambda: None
    return mod


def _with_vox(up: bool):
    """Pretend Vox is (or isn't) running; returns what tried to speak or show."""
    from vox import bubble, tts
    calls = []
    saved = (running.vox_running, tts.speak_with, bubble.show)
    running.vox_running = lambda *a, **kw: up
    tts.speak_with = lambda text, **kw: calls.append(("spoke", text))
    bubble.show = lambda text, **kw: calls.append(("shown", text)) or "card"

    def restore():
        running.vox_running, tts.speak_with, bubble.show = saved
    return calls, restore


def test_speak_and_notify_do_nothing_when_vox_is_quit():
    server = _speak_server()
    calls, restore = _with_vox(False)
    try:
        replies = [server.speak("tests pass"), server.announce_done("done"), server.notify("tests pass")]
    finally:
        restore()
    assert calls == []
    for reply in replies:
        assert "Vox isn't running" in reply


def test_speak_and_notify_work_when_vox_is_running():
    server = _speak_server()
    calls, restore = _with_vox(True)
    try:
        server.speak("tests pass")
        server.notify("tests pass")
    finally:
        restore()
    assert [kind for kind, _ in calls] == ["spoke", "shown"]


if __name__ == "__main__":
    for name, test in [(k, v) for k, v in dict(globals()).items() if k.startswith("test_")]:
        test()
        print("ok  ", name)
