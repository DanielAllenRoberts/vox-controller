"""Shared pytest setup.

vox-speak hands its lines to the running Vox (vox.speak_client). Tests must never reach a real Vox
the developer has open, so every test sees Vox as not answering, except the tests of that client
itself, which control it directly.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


@pytest.fixture(autouse=True)
def _no_real_vox(request, monkeypatch):
    if request.module.__name__.endswith("test_speak_via_vox"):
        return
    from vox import speak_client
    monkeypatch.setattr(speak_client, "speak_via_vox", lambda *a, **kw: None)
