"""The live mic meter: the audio module records each frame's loudness and /api/mic/level reports it
on the shared 0-1 scale, with the speech threshold marked on the same scale."""

import queue
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from vox import audio  # noqa: E402
from vox.web.server import create_app  # noqa: E402


def test_level_tracks_the_latest_frame():
    q = queue.Queue(maxsize=4)
    audio._put_latest(q, np.full(1280, 1000, dtype=np.int16))
    lv = audio.level()
    assert abs(lv["rms"] - 1000) < 1
    assert lv["age"] < 1


def test_endpoint_reports_live_level_and_threshold():
    q = queue.Queue(maxsize=4)
    client = TestClient(create_app())
    audio._put_latest(q, np.full(1280, 3000, dtype=np.int16))   # about -21 dBFS: clearly speech
    loud = client.get("/api/mic/level").json()
    audio._put_latest(q, np.zeros(1280, dtype=np.int16))         # silence
    quiet = client.get("/api/mic/level").json()
    assert loud["live"] and quiet["live"]
    assert 0 < loud["threshold"] < 1
    assert loud["level"] > loud["threshold"] > quiet["level"] == 0.0


def test_no_audio_means_not_live():
    audio._level["at"] = 0.0
    r = TestClient(create_app()).get("/api/mic/level").json()
    assert r == {**r, "live": False, "level": 0.0}


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print("ok ", name)
    print(f"{len(tests)} passed")
