"""Low-level desktop input synthesis — scroll, key combos, click variants, drag (idea #61).

Why this exists: Vox could already scroll, press key combos and right-click, but ONLY inside the
agent tier (``agent.py``) — which is gated off by default, needs an Anthropic API key, and spends a
multi-second model loop deciding to do it. These gestures are cheap CGEvent calls. They belong on
the fast deterministic path, so "scroll down" costs milliseconds instead of a round-trip to a model.
``actions.py`` wires them to voice commands and ``agent.py`` calls the same helpers, so there is one
implementation of each gesture rather than two that drift.

Keyboard events are synthesized as CGEvents rather than AppleScript ``keystroke``. AppleScript costs
~150-250ms per press (osascript spawn + System Events round-trip); a CGEvent is well under 10ms, and
it is the only one of the two that can be aimed at a specific process.

Delivery (idea #61, from Hermes' `computer_use`): by default events go to the global HID tap
(``CGEventPost``), which is what the OS itself does — reliable, but it acts on whatever is frontmost
and moves the real cursor. With ``input_background_delivery`` on, events are posted to a specific
process instead (``CGEventPostToPid``), so Vox can drive a window without raising it or stealing
your pointer. That is **app-dependent**: AppKit apps generally honour posted events, Chromium and
Electron frequently ignore posted *mouse* events while still accepting keys. Every helper falls back
to the global tap when no pid is resolved, so the worst case is today's behaviour.
"""

from __future__ import annotations

from vox.config import CONFIG


# macOS virtual keycodes (US layout). Only what a spoken combo plausibly needs — the long tail of
# keypad/media keys isn't worth carrying until something asks for it.
_KEYCODES = {
    "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8, "v": 9,
    "b": 11, "q": 12, "w": 13, "e": 14, "r": 15, "y": 16, "t": 17,
    "1": 18, "2": 19, "3": 20, "4": 21, "6": 22, "5": 23, "=": 24, "9": 25, "7": 26,
    "-": 27, "8": 28, "0": 29, "]": 30, "o": 31, "u": 32, "[": 33, "i": 34, "p": 35,
    "l": 37, "j": 38, "'": 39, "k": 40, ";": 41, "\\": 42, ",": 43, "/": 44, "n": 45,
    "m": 46, ".": 47, "`": 50,
    "return": 36, "tab": 48, "space": 49, "delete": 51, "escape": 53,
    "left": 123, "right": 124, "down": 125, "up": 126,
    "home": 115, "pageup": 116, "forwarddelete": 117, "end": 119, "pagedown": 121,
    "f1": 122, "f2": 120, "f3": 99, "f4": 118, "f5": 96, "f6": 97,
    "f7": 98, "f8": 100, "f9": 101, "f10": 109, "f11": 103, "f12": 111,
}

# Spoken/alias forms → the canonical key name above. Whisper writes what you say, so "command",
# "control" and "escape" arrive spelled out far more often than "cmd"/"ctrl"/"esc".
_ALIASES = {
    "cmd": "command", "super": "command", "meta": "command", "win": "command", "apple": "command",
    "ctrl": "control", "opt": "option", "alt": "option",
    "enter": "return", "esc": "escape", "del": "delete", "backspace": "delete",
    "spacebar": "space", "page up": "pageup", "page down": "pagedown",
    "arrow up": "up", "arrow down": "down", "arrow left": "left", "arrow right": "right",
}

_MODIFIERS = ("command", "shift", "option", "control", "fn")

# Spoken digits, so "press command shift four" works as well as "press command shift 4".
_DIGIT_WORDS = {"zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
                "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9"}


def _flags(mods):
    """OR the CGEvent flag masks for a list of canonical modifier names."""
    import Quartz
    masks = {
        "command": Quartz.kCGEventFlagMaskCommand,
        "shift": Quartz.kCGEventFlagMaskShift,
        "option": Quartz.kCGEventFlagMaskAlternate,
        "control": Quartz.kCGEventFlagMaskControl,
        "fn": Quartz.kCGEventFlagMaskSecondaryFn,
    }
    out = 0
    for m in mods:
        out |= masks.get(m, 0)
    return out


def background_enabled() -> bool:
    """Is background (no-focus-steal) delivery on? Read through the dashboard's settings override so
    it flips live, with the frozen Config default as the floor — same pattern as `command_db_enabled`."""
    try:
        from vox.web import settings_store
        val = settings_store.get("input_background_delivery")
        if val is not None:
            return bool(val)
    except Exception:
        pass
    return bool(getattr(CONFIG, "input_background_delivery", False))


def target_pid():
    """The pid to aim events at, or None for the global HID tap. None whenever background delivery is
    off, so the default path is byte-for-byte what Vox did before this module existed."""
    if not background_enabled():
        return None
    try:
        from vox import ax
        return ax._frontmost_pid()
    except Exception:
        return None


def _post(ev, pid=None) -> None:
    """Post one event — to `pid` when background delivery gave us one, else the global HID tap."""
    import Quartz
    if pid is not None:
        try:
            Quartz.CGEventPostToPid(pid, ev)
            return
        except Exception:
            pass  # PostToPid unavailable/refused → fall through to the global tap
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)


# --- keyboard ---------------------------------------------------------------------------------

def normalize_combo(combo: str):
    """Parse a spoken/typed combo into (modifiers, key). "command shift four" and "cmd+shift+4"
    both give (["command", "shift"], "4"). Returns None when the final key isn't one we can press."""
    raw = str(combo or "").strip().lower()
    if not raw:
        return None
    for spoken, canon in (("page up", "pageup"), ("page down", "pagedown"),
                          ("arrow up", "up"), ("arrow down", "down"),
                          ("arrow left", "left"), ("arrow right", "right")):
        raw = raw.replace(spoken, canon)
    parts = [p for p in raw.replace("-", "+").replace("+", " ").split() if p]
    parts = [_ALIASES.get(p, p) for p in parts]
    parts = [_DIGIT_WORDS.get(p, p) for p in parts]
    if not parts:
        return None
    mods = [p for p in parts if p in _MODIFIERS]
    rest = [p for p in parts if p not in _MODIFIERS]
    if not rest:
        return None
    key = rest[-1]
    if key not in _KEYCODES:
        return None
    return (mods, key)


def press(combo: str, pid=None) -> str:
    """Press a key combination — "cmd+s", "command shift 4", "escape". Returns a human-readable
    result (the caller speaks or logs it)."""
    parsed = normalize_combo(combo)
    if parsed is None:
        return f"failed: I don't know the key {combo!r}."
    mods, key = parsed
    try:
        import Quartz
        code = _KEYCODES[key]
        flags = _flags(mods)
        if pid is None:
            pid = target_pid()
        for down in (True, False):
            ev = Quartz.CGEventCreateKeyboardEvent(None, code, down)
            if flags:
                Quartz.CGEventSetFlags(ev, flags)
            _post(ev, pid)
    except Exception as exc:
        return f"failed: couldn't press that ({exc})."
    return "pressed " + "+".join(mods + [key])


# --- mouse ------------------------------------------------------------------------------------

def click_at(x: float, y: float, button: str = "left", clicks: int = 1, pid=None) -> None:
    """Synthesize a click at global screen point (x, y). CGEvent and AX share the same top-left-origin
    global space, so an AX frame needs no flip. `clicks` 2 sends a real double-click (the click-state
    field is what makes the app treat it as one, not just two clicks in a row)."""
    import Quartz
    pt = Quartz.CGPointMake(float(x), float(y))
    if pid is None:
        pid = target_pid()
    down, up, btn = {
        "left": (Quartz.kCGEventLeftMouseDown, Quartz.kCGEventLeftMouseUp, Quartz.kCGMouseButtonLeft),
        "right": (Quartz.kCGEventRightMouseDown, Quartz.kCGEventRightMouseUp, Quartz.kCGMouseButtonRight),
        "middle": (Quartz.kCGEventOtherMouseDown, Quartz.kCGEventOtherMouseUp, Quartz.kCGMouseButtonCenter),
    }.get(button, (Quartz.kCGEventLeftMouseDown, Quartz.kCGEventLeftMouseUp, Quartz.kCGMouseButtonLeft))

    move = Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventMouseMoved, pt, btn)
    _post(move, pid)
    for n in range(1, max(1, int(clicks)) + 1):
        for kind in (down, up):
            ev = Quartz.CGEventCreateMouseEvent(None, kind, pt, btn)
            # kCGMouseEventClickState = 1 for a single click, 2 for the second click of a double.
            Quartz.CGEventSetIntegerValueField(ev, Quartz.kCGMouseEventClickState, n)
            _post(ev, pid)


def drag(x1: float, y1: float, x2: float, y2: float, steps: int = 20, pid=None) -> None:
    """Press at (x1,y1), move to (x2,y2) in `steps` increments, release. The intermediate moves are
    what make it a drag — apps that track dragging ignore a straight down→up at two points."""
    import time

    import Quartz
    if pid is None:
        pid = target_pid()
    btn = Quartz.kCGMouseButtonLeft
    start = Quartz.CGPointMake(float(x1), float(y1))
    _post(Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventMouseMoved, start, btn), pid)
    _post(Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventLeftMouseDown, start, btn), pid)
    time.sleep(0.05)
    for i in range(1, max(1, int(steps)) + 1):
        f = i / float(steps)
        pt = Quartz.CGPointMake(x1 + (x2 - x1) * f, y1 + (y2 - y1) * f)
        _post(Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventLeftMouseDragged, pt, btn), pid)
        time.sleep(0.01)
    end = Quartz.CGPointMake(float(x2), float(y2))
    time.sleep(0.05)
    _post(Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventLeftMouseUp, end, btn), pid)


def scroll(direction: str = "down", amount: int = 5, at=None, pid=None) -> str:
    """Scroll `amount` wheel lines in `direction` (up/down/left/right). `at` is an optional (x, y) to
    move the pointer to first — scrolling applies to whatever is under the pointer, so a target that
    isn't under it needs the move."""
    import time

    import Quartz
    d = (direction or "down").strip().lower()
    if d not in ("up", "down", "left", "right"):
        return f"failed: I can't scroll {direction!r}."
    try:
        n = max(1, int(amount))
    except Exception:
        n = 5
    if pid is None:
        pid = target_pid()
    try:
        if at is not None and len(at) == 2:
            pt = Quartz.CGPointMake(float(at[0]), float(at[1]))
            _post(Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventMouseMoved, pt,
                                                 Quartz.kCGMouseButtonLeft), pid)
        # Positive wheel1 scrolls the content up (view moves toward the top), so "down" is negative.
        dy = {"up": 3, "down": -3}.get(d, 0)
        dx = {"left": 3, "right": -3}.get(d, 0)
        for _ in range(n):
            ev = Quartz.CGEventCreateScrollWheelEvent(None, Quartz.kCGScrollEventUnitLine, 2, dy, dx)
            _post(ev, pid)
            time.sleep(0.02)
    except Exception as exc:
        return f"failed: couldn't scroll ({exc})."
    return f"scrolled {d}"
