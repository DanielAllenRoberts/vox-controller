"""Shared pytest setup.

vox-speak stays quiet when Vox isn't running (vox.running). Tests mustn't depend on whether the
developer happens to have Vox open, so every test sees Vox as running, except the tests of that
check itself, which control it directly.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


@pytest.fixture(autouse=True)
def _vox_is_running(request, monkeypatch):
    if request.module.__name__.endswith("test_quiet_when_vox_quit"):
        return
    from vox import running
    monkeypatch.setattr(running, "vox_running", lambda *a, **kw: True)
