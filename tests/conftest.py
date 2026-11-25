"""Shared pytest setup.

Tests mustn't depend on, or reach, a real Vox the developer has open:
* vox-speak stays quiet when Vox isn't running (vox.running), so every test sees Vox as running,
  except the tests of that check itself.
* vox-speak hands its lines to the running Vox (vox.speak_client), so every test sees Vox as not
  answering, except the tests of that client itself.
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


@pytest.fixture(autouse=True)
def _no_real_vox(request, monkeypatch):
    if request.module.__name__.endswith("test_speak_via_vox"):
        return
    from vox import speak_client
    monkeypatch.setattr(speak_client, "speak_via_vox", lambda *a, **kw: None)
