"""Agents speak through Vox's engine instead of loading their own voice model.

vox-speak used to call vox.tts.speak_with in its own process, so every agent session that had
spoken loaded its own Kokoro model and ONNX Runtime and kept them for the life of the session:
about 1 GB per Claude session, on top of the copy Vox already holds. Now vox-speak POSTs the text to
Vox's /api/speak, and Vox's one model does the speaking. Only when Vox doesn't answer does it fall
back to speaking in-process, as before.

Runs under pytest, or standalone without it:  .venv/bin/python tests/test_speak_via_vox.py
No audio plays: speak_with is faked.
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

from vox import speak_client, tts  # noqa: E402

JSON = {"content-type": "application/json"}


def _fake_speak_with(calls, result=True):
    def fake(text, **kw):
        calls.append((text, kw))
        return result
    return fake


def _api(calls, result=True):
    from fastapi.testclient import TestClient
    from vox.web.server import create_app
    tts.speak_with = _fake_speak_with(calls, result)
    return TestClient(create_app())


_ORIGINAL = tts.speak_with


def teardown_function(_=None):
    tts.speak_with = _ORIGINAL


def test_api_speak_uses_vox_tts_with_the_agents_voice():
    calls = []
    r = _api(calls).post("/api/speak", headers=JSON, json={
        "text": "Jeff here, tests pass", "label": "Jeff", "engine": "kokoro",
        "kokoroVoice": "am_adam", "sayVoice": "Samantha", "rate": 0, "dropIfPaused": True})
    assert r.json() == {"ok": True, "spoken": True}
    (text, kw), = calls
    assert text == "Jeff here, tests pass"
    assert kw["label"] == "Jeff" and kw["kokoro_voice"] == "am_adam" and kw["engine"] == "kokoro"
    assert kw["say_voice"] == "Samantha" and kw["rate"] is None and kw["drop_if_paused"] is True


def test_api_speak_reports_a_line_dropped_by_a_pause():
    r = _api([], result=False).post("/api/speak", headers=JSON, json={"text": "hi", "dropIfPaused": True})
    assert r.json() == {"ok": True, "spoken": False}


def test_api_speak_rejects_empty_text():
    calls = []
    r = _api(calls).post("/api/speak", headers=JSON, json={"text": "  "})
    assert r.status_code == 400 and calls == []


def _serve(reply: dict | None, seen: list) -> HTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            seen.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(reply).encode())

        def log_message(self, *a):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_client_sends_the_line_to_vox():
    seen = []
    server = _serve({"ok": True, "spoken": True}, seen)
    try:
        assert speak_client.speak_via_vox("hi", label="Jeff", kokoro_voice="am_adam",
                                          drop_if_paused=True, port=server.server_port) is True
    finally:
        server.shutdown()
    assert seen[0]["text"] == "hi" and seen[0]["label"] == "Jeff"
    assert seen[0]["kokoroVoice"] == "am_adam" and seen[0]["dropIfPaused"] is True


def test_client_reports_a_dropped_line():
    server = _serve({"ok": True, "spoken": False}, [])
    try:
        assert speak_client.speak_via_vox("hi", port=server.server_port) is False
    finally:
        server.shutdown()


def test_client_returns_none_when_vox_does_not_answer():
    assert speak_client.speak_via_vox("hi", port=_free_port()) is None


def _speak_server():
    spec = importlib.util.spec_from_file_location("vox_speak_server_via", ROOT / "mcp" / "vox_speak_server.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod._play_cue = lambda: None
    return mod


def test_vox_speak_hands_the_line_to_vox_and_loads_no_model():
    server = _speak_server()
    sent, local = [], []
    saved = speak_client.speak_via_vox
    speak_client.speak_via_vox = lambda text, **kw: sent.append((text, kw)) or True
    tts.speak_with = _fake_speak_with(local)
    try:
        reply = server._say("tests pass", "", 0)
    finally:
        speak_client.speak_via_vox = saved
    assert local == [], "the MCP process must not synthesize speech itself when Vox answers"
    assert sent and sent[0][0].endswith("tests pass") and "spoke aloud" in reply


def test_vox_speak_falls_back_to_speaking_itself_when_vox_is_down():
    server = _speak_server()
    local = []
    saved = speak_client.speak_via_vox
    speak_client.speak_via_vox = lambda text, **kw: None
    tts.speak_with = _fake_speak_with(local)
    try:
        server._say("tests pass", "", 0)
    finally:
        speak_client.speak_via_vox = saved
    assert len(local) == 1


if __name__ == "__main__":
    for name, test in [(k, v) for k, v in dict(globals()).items() if k.startswith("test_")]:
        try:
            test()
            print("ok  ", name)
        finally:
            teardown_function()
