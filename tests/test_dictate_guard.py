"""Dictation is only entered when the words ask to type: a mis-heard command the brain answers with
DICTATE must not start typing everything the user says next (seen live 17 Nov: 'i think lord')."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vox import assistant, executor  # noqa: E402


def _run(heard: str):
    real = assistant.complete
    assistant.complete = lambda *a, **k: "DICTATE"
    try:
        return executor.execute(heard)
    finally:
        assistant.complete = real


def test_mishear_does_not_enter_dictation():
    acted, msg = _run("i think lord")
    assert msg != executor.ENTER_DICTATION and not acted


def test_real_requests_still_enter_dictation():
    for heard in ("start typing", "dot typing", "take dictation", "let me write something"):
        assert _run(heard)[1] == executor.ENTER_DICTATION, heard


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print("ok ", name)
    print(f"{len(tests)} passed")
