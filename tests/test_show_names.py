""""Show names" (Apple Voice Control): badges that carry each control's label as well as its number.

Runs under pytest, or standalone without it:  .venv/bin/python tests/test_show_names.py
Nothing here draws on screen — the overlay and the target list are faked.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vox import dispatch, overlay, targets  # noqa: E402


def test_short_keeps_one_line_and_caps_length():
    assert overlay._short("Export") == "Export"
    assert overlay._short("  Save\n as  PDF ") == "Save as PDF"
    long = overlay._short("A very long label that would blanket its neighbours")
    assert len(long) == 28 and long.endswith("…")


def test_nudge_moves_down_until_clear():
    placed = [(0, 100, 60, 18)]
    assert overlay._nudge((200, 100, 50, 18), placed) == (200, 100, 50, 18)   # no overlap
    assert overlay._nudge((40, 100, 50, 18), placed) == (40, 81, 50, 18)      # one row down
    placed.append((40, 81, 50, 18))
    assert overlay._nudge((45, 100, 50, 18), placed) == (45, 62, 50, 18)      # two rows down


def test_nudge_gives_up_after_three_rows():
    placed = [(0, y, 100, 18) for y in (100, 81, 62, 43)]
    assert overlay._nudge((10, 100, 50, 18), placed) == (10, 43, 50, 18)


# --- dispatch routing -----------------------------------------------------------------------------

def _fake(shown):
    targets.visible_targets = lambda limit=400: [{"index": 0, "label": "Export", "x": 1, "y": 2, "w": 3, "h": 4}]
    overlay.is_active = lambda: False
    overlay.show = lambda items, names=False: shown.append(names) or len(items)
    overlay.hide = lambda: None


def test_show_names_draws_names():
    shown = []
    _fake(shown)
    acted, msg = dispatch._overlay("show names", "show names")
    assert acted and shown == [True] and "with names" in msg


def test_show_numbers_still_draws_numbers_only():
    shown = []
    _fake(shown)
    acted, _ = dispatch._overlay("show numbers", "show numbers")
    assert acted and shown == [False]


def test_hide_names_is_a_command():
    _fake([])
    assert dispatch._overlay("hide names", "hide names") == (True, "hidden")


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print("ok ", name)
    print(f"{len(tests)} passed")
