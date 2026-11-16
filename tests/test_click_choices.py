""""click Send" with two Send buttons → number the matches and ask, don't guess (Apple Voice Control).

Runs under pytest, or standalone without it:  .venv/bin/python tests/test_click_choices.py
Nothing here touches the screen — the AX tree, the overlay and the mouse are faked.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vox import actions, ax, targets  # noqa: E402


# --- a fake AX tree -------------------------------------------------------------------------------

class El:
    def __init__(self, name, frame, kids=()):
        self.name, self.frame, self.kids = name, frame, list(kids)


def _install_tree(root):
    clicks = []
    ax._load = lambda: {"AXUIElementPerformAction": lambda el, act: 0}
    ax._app_root = lambda fns, settle=None: root
    ax._name_of = lambda fns, el: el.name
    ax._attr = lambda fns, el, name: el.kids if name == "AXChildren" else None
    ax._pressable = lambda fns, el, chain: el
    ax._frame = lambda fns, el: el.frame
    ax._focus_moved = lambda pid=None: None
    ax._click_at = lambda x, y: clicks.append((x, y))
    return clicks


def _tree(*kids):
    return El("window", (0, 0, 1000, 800), kids)


# --- ax.overlaps ----------------------------------------------------------------------------------

def test_overlaps():
    assert ax.overlaps((0, 0, 10, 10), (5, 5, 10, 10))
    assert not ax.overlaps((0, 0, 10, 10), (20, 0, 10, 10))
    assert ax.overlaps((0, 0, 100, 40), (10, 10, 20, 10))   # text inside its button
    assert ax.overlaps(None, (0, 0, 1, 1))                    # unplaceable → never a 2nd match


# --- ax.click -------------------------------------------------------------------------------------

def test_two_separate_sends_are_ambiguous():
    clicks = _install_tree(_tree(El("Send", (10, 10, 50, 20)), El("Send", (10, 500, 50, 20))))
    assert ax.click("send", ask_if_ambiguous=True) == ("ambiguous", "Send")
    assert clicks == []                                         # nothing pressed


def test_without_asking_the_first_send_is_clicked():
    clicks = _install_tree(_tree(El("Send", (10, 10, 50, 20)), El("Send", (10, 500, 50, 20))))
    assert ax.click("send") == ("clicked", "Send")
    assert clicks == [(35.0, 20.0)]


def test_one_send_just_clicks():
    clicks = _install_tree(_tree(El("Send", (10, 10, 50, 20)), El("Cancel", (100, 10, 50, 20))))
    assert ax.click("send", ask_if_ambiguous=True) == ("clicked", "Send")
    assert len(clicks) == 1


def test_overlapping_same_label_is_one_control():
    # e.g. a toolbar group labelled "Send" wrapping the real "Send" button
    clicks = _install_tree(_tree(El("Send", (10, 10, 100, 40)), El("Send", (20, 15, 50, 20))))
    assert ax.click("send", ask_if_ambiguous=True)[0] == "clicked"
    assert len(clicks) == 1


def test_substring_matches_never_ask():
    clicks = _install_tree(_tree(El("Send now", (10, 10, 50, 20)), El("Send later", (10, 500, 50, 20))))
    assert ax.click("send", ask_if_ambiguous=True)[0] == "clicked"
    assert len(clicks) == 1


def test_a_clipped_sliver_is_not_a_second_match():
    clicks = _install_tree(_tree(El("Jump to date", (600, 150, 170, 1)), El("Jump to date", (660, 164, 77, 28))))
    assert ax.click("jump to date", ask_if_ambiguous=True)[0] == "clicked"
    assert clicks == [(698.5, 178.0)]                           # the real one, not the 1-px sliver


def test_plain_click_skips_a_leading_sliver():
    clicks = _install_tree(_tree(El("Sam", (400, 150, 120, 1)), El("Sam", (180, 640, 120, 19))))
    assert ax.click("sam") == ("clicked", "Sam")
    assert clicks == [(240.0, 649.5)]


# --- targets.distinct_exact -----------------------------------------------------------------------

def _it(label, x, y, w=50, h=20):
    return {"label": label, "x": x, "y": y, "w": w, "h": h}


def test_distinct_exact_filters_and_dedupes():
    items = [_it("Send", 0, 0), _it("Reply", 0, 100), _it("send", 0, 200), _it("Send", 5, 5),
             _it("Send", 0, 5000), _it("Send", 300, 0, h=1)]
    on = lambda it: it["y"] < 1000   # noqa: E731 — the last one is scrolled off-screen
    assert targets.distinct_exact(items, "Send", on_screen=on) == [0, 2]


# --- actions.click_element ------------------------------------------------------------------------

def test_click_element_offers_choices():
    _install_tree(_tree(El("Send", (10, 10, 50, 20)), El("Send", (10, 500, 50, 20))))
    targets.click_label = lambda t, ask_if_ambiguous=False: None   # not a browser
    targets.offer_choices = lambda label: 2
    actions.focus_target = lambda: None
    out = actions.click_element("Send", ask_if_ambiguous=True)
    assert out.startswith(actions.WHICH_ONE) and "2" in out, out
    assert not actions.failed(out)                               # must not escalate to the brain


def test_click_element_falls_back_when_it_cant_number():
    clicks = _install_tree(_tree(El("Send", (10, 10, 50, 20)), El("Send", (10, 500, 50, 20))))
    targets.click_label = lambda t, ask_if_ambiguous=False: None
    targets.offer_choices = lambda label: None                   # e.g. only one on screen
    actions.focus_target = lambda: None
    assert actions.click_element("Send", ask_if_ambiguous=True).startswith("Clicked")
    assert len(clicks) == 1


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print("ok ", name)
    print(f"{len(tests)} passed")
