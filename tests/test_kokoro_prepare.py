"""Kokoro voices are downloaded (~350 MB) on first use. Setup's voice step starts that download when it
opens and shows progress, and a preview never queues silently behind it.

Runs under pytest, or standalone without it:  .venv/bin/python tests/test_kokoro_prepare.py
Nothing is downloaded or spoken: the download, the model and the speaker are faked.
"""

import dataclasses
import sys
import threading
import time
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vox import onboarding, tts  # noqa: E402

_ORIGINALS = {}


def setup_function(_fn=None):
    _ORIGINALS.update(ensure=tts._ensure_file, speak=tts.speak_with, config=tts.CONFIG,
                      kokoro_mod=sys.modules.get("kokoro_onnx"))


def teardown_function(_fn=None):
    tts._ensure_file = _ORIGINALS["ensure"]
    tts.speak_with = _ORIGINALS["speak"]
    tts.CONFIG = _ORIGINALS["config"]
    if _ORIGINALS["kokoro_mod"] is None:
        sys.modules.pop("kokoro_onnx", None)
    else:
        sys.modules["kokoro_onnx"] = _ORIGINALS["kokoro_mod"]
    tts._KOKORO = None
    tts._KOKORO_PREP.update(state="idle", downloaded_bytes=0, error="")


class _FakeKokoro:
    def __init__(self, model_path, voices_path):
        self.paths = (model_path, voices_path)


def _reset(downloads, gate=None, fail=None):
    """Fresh Kokoro state with a fake download. `gate` holds the download open until set."""
    tts._KOKORO = None
    tts._KOKORO_PREP.update(state="idle", downloaded_bytes=0, error="")
    sys.modules["kokoro_onnx"] = types.SimpleNamespace(Kokoro=_FakeKokoro)
    tts.CONFIG = dataclasses.replace(_ORIGINALS["config"], kokoro_threads=0)

    def fake_ensure(url, name, progress=None):
        downloads.append(name)
        if progress is not None:
            progress(1024 * 1024)
        if gate is not None:
            gate.wait(5)
        if fail is not None:
            raise fail
        return f"/fake/{name}"

    tts._ensure_file = fake_ensure


def _wait_for(state, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if tts.kokoro_status()["state"] == state:
            return True
        time.sleep(0.01)
    return False


def test_prepare_reports_downloading_then_ready():
    gate = threading.Event()
    _reset([], gate=gate)
    tts.prepare_kokoro()
    assert _wait_for("downloading")
    assert tts.kokoro_status()["downloadedMB"] >= 1
    gate.set()
    assert _wait_for("ready")


def test_prepare_twice_downloads_each_file_once():
    gate = threading.Event()
    downloads = []
    _reset(downloads, gate=gate)
    tts.prepare_kokoro()
    tts.prepare_kokoro()
    gate.set()
    assert _wait_for("ready")
    assert sorted(downloads) == ["kokoro-v1.0.onnx", "voices-v1.0.bin"]


def test_prepare_reports_a_failed_download():
    _reset([], fail=OSError("network down"))
    tts.prepare_kokoro()
    assert _wait_for("error")
    assert "network down" in tts.kokoro_status()["error"]


def test_preview_does_not_queue_speech_while_voices_download():
    gate = threading.Event()
    spoken = []
    _reset([], gate=gate)
    tts.speak_with = lambda text, **kw: spoken.append(text)
    result = onboarding.preview("kokoro", "af_heart")
    assert result["ready"] is False
    assert result["state"] == "downloading"
    gate.set()
    assert _wait_for("ready")
    time.sleep(0.1)
    assert spoken == []


def test_preview_speaks_once_voices_are_ready():
    spoken = []
    _reset([])
    tts.prepare_kokoro()
    assert _wait_for("ready")
    done = threading.Event()
    tts.speak_with = lambda text, **kw: (spoken.append(kw.get("kokoro_voice")), done.set())
    result = onboarding.preview("kokoro", "af_bella")
    assert result["ready"] is True
    assert done.wait(2)
    assert spoken == ["af_bella"]



def test_api_reports_status_and_preview_readiness():
    from fastapi.testclient import TestClient
    from vox.web.server import create_app

    gate = threading.Event()
    _reset([], gate=gate)
    client = TestClient(create_app())
    json_headers = {"content-type": "application/json"}
    assert client.get("/api/voices/kokoro").json()["state"] == "idle"
    assert client.post("/api/voices/kokoro/prepare", json={}, headers=json_headers).json()["state"] in ("loading", "downloading")
    preview = client.post("/api/voices/preview", json={"engine": "kokoro", "voice": "af_heart"}, headers=json_headers).json()
    assert preview["ok"] is True and preview["ready"] is False
    gate.set()
    assert _wait_for("ready")
    assert client.get("/api/voices/kokoro").json()["state"] == "ready"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            setup_function()
            try:
                fn()
            finally:
                teardown_function()
            print("ok", name)
