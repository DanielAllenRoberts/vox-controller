"""Pausing the mic really lets go of it.

A paused mic used to stay open with its frames thrown away. On Bluetooth headphones that kept them
in hands-free (call) mode, which is low-quality audio for everything else, and macOS kept showing
the orange mic dot. Now pausing closes the input stream and the loop is fed silence at the normal
rate (so typed input and the stall watchdog behave as before). Unpausing, or holding the talk key
while paused, opens it again.

Runs under pytest, or standalone without it:  .venv/bin/python tests/test_mic_pause_release.py
No audio device is touched: sounddevice's InputStream is faked.
"""

import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np  # noqa: E402

from vox import audio, runtime  # noqa: E402

FS = 160   # samples per frame: 10 ms at 16 kHz, so the tests run fast
SR = 16000


class FakeStream:
    """Stands in for sd.InputStream: once started, delivers a loud frame every 10 ms."""
    opened: list = []

    def __init__(self, callback=None, **kw):
        self.callback, self.closed, self.started = callback, False, False
        FakeStream.opened.append(self)

    def start(self):
        self.started = True
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while self.started and not self.closed:
            self.callback(np.full((FS, 1), 1000, dtype=np.int16), FS, None, None)
            time.sleep(0.01)

    def abort(self):
        self.started = False

    def close(self):
        self.closed = True


_ORIGINALS = {}


def setup_function(_fn=None):
    _ORIGINALS.update(stream=audio.sd.InputStream, term=audio.sd._terminate, init=audio.sd._initialize,
                      ptt=runtime.ptt_down, paused=runtime.paused)
    audio.sd.InputStream = FakeStream
    audio.sd._terminate = audio.sd._initialize = lambda: None
    FakeStream.opened = []
    runtime.paused = False
    runtime.ptt_down = lambda: False


def teardown_function(_fn=None):
    audio.sd.InputStream = _ORIGINALS["stream"]
    audio.sd._terminate = _ORIGINALS["term"]
    audio.sd._initialize = _ORIGINALS["init"]
    runtime.ptt_down = _ORIGINALS["ptt"]
    runtime.paused = _ORIGINALS["paused"]


def _until(cond, timeout=2.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def _pump(frames, cond, timeout=2.0) -> bool:
    """Keep pulling frames, as the daemon's loop does, until ``cond()`` holds."""
    end = time.time() + timeout
    while time.time() < end:
        next(frames)
        if cond():
            return True
    return False


def _mic():
    mic = audio.MicStream(SR, FS, release_grace=0.05)
    mic.__enter__()
    return mic, mic.frames()


def _open_streams():
    return [s for s in FakeStream.opened if s.started and not s.closed]


def test_pausing_closes_the_stream_and_yields_silence():
    mic, frames = _mic()
    assert next(frames).max() == 1000            # live mic
    runtime.paused = True
    assert _pump(frames, lambda: _until(lambda: _open_streams() == [], timeout=0.05))  # mic let go
    frame = next(frames)
    assert frame.max() == 0 and len(frame) == FS  # silence, same shape


def test_paused_frames_keep_the_normal_rhythm():
    mic, frames = _mic()
    runtime.paused = True
    next(frames)
    t = time.monotonic()
    for _ in range(10):
        next(frames)
    assert 0.07 <= time.monotonic() - t <= 0.5    # ~10 ms each: neither a busy loop nor a stall


def test_unpausing_opens_the_mic_again():
    mic, frames = _mic()
    runtime.paused = True
    assert _pump(frames, lambda: _until(lambda: _open_streams() == [], timeout=0.05))
    runtime.paused = False
    assert _until(lambda: next(frames).max() == 1000)
    assert len(_open_streams()) == 1


def test_holding_the_talk_key_while_paused_opens_the_mic():
    mic, frames = _mic()
    runtime.paused = True
    assert _pump(frames, lambda: _until(lambda: _open_streams() == [], timeout=0.05))
    runtime.ptt_down = lambda: True
    assert _until(lambda: next(frames).max() == 1000)
    runtime.ptt_down = lambda: False
    assert _pump(frames, lambda: _until(lambda: _open_streams() == [], timeout=0.05))  # let go again


def test_a_paused_mic_never_counts_as_stalled():
    mic, frames = _mic()
    runtime.paused = True
    end = time.monotonic() + 3.5                   # longer than the 3 s stall timeout
    while time.monotonic() < end:
        next(frames)                               # must not raise MicStreamDead or log a stall
    assert mic._stall_since is None and mic._recover_attempts == 0


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            setup_function()
            try:
                fn()
            finally:
                teardown_function()
            print("ok", name)
