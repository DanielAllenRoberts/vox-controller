"""Windows across displays: move a window to another screen, fill a screen, snap to a half.

"Move Slack to the left screen", "send this window to the other monitor", "maximise this window",
"snap this to the right". Uses the Accessibility API directly (AXPosition / AXSize on the app's
focused window), the same zero-dependency binding as ``vox.ax``, so it works for any app that has
normal windows and needs no extra tools.

Coordinates: AX uses a global space with the origin at the TOP-left of the main display; AppKit's
NSScreen uses the BOTTOM-left. Everything here is converted to AX space.
"""

from __future__ import annotations

import re

import time

_AXVALUE_CGPOINT = 1   # kAXValueCGPointType
_AXVALUE_CGSIZE = 2    # kAXValueCGSizeType
_SET: dict | None = None


def _setter():
    """Bind AXValueCreate once (kept out of ax._load so a failure here can't affect clicking)."""
    global _SET
    if _SET is None:
        _SET = {}
        try:
            import objc
            from Foundation import NSBundle
            bundle = NSBundle.bundleWithPath_("/System/Library/Frameworks/ApplicationServices.framework")
            objc.loadBundleFunctions(bundle, _SET, [("AXValueCreate", b"@In^{CGPoint=dd}")])
        except Exception:
            _SET = {}
    return _SET.get("AXValueCreate")


# --- displays ------------------------------------------------------------------------------------

def displays() -> list[dict]:
    """Connected displays, left to right: {"name", "x", "y", "w", "h", "main", "builtin"}. The
    rectangle is the usable area (no menu bar or Dock), in AX coordinates."""
    try:
        from AppKit import NSScreen
        import Quartz
    except Exception:
        return []
    screens = list(NSScreen.screens() or [])
    if not screens:
        return []
    main_h = screens[0].frame().size.height
    out = []
    for s in screens:
        v = s.visibleFrame()
        did = s.deviceDescription().get("NSScreenNumber")
        out.append({
            "name": str(s.localizedName() or "Display"),
            "x": float(v.origin.x), "y": float(main_h - (v.origin.y + v.size.height)),
            "w": float(v.size.width), "h": float(v.size.height),
            "main": bool(Quartz.CGDisplayIsMain(did)) if did is not None else False,
            "builtin": bool(Quartz.CGDisplayIsBuiltin(did)) if did is not None else False,
        })
    out.sort(key=lambda d: (d["x"], d["y"]))
    return out


def _display_of(frame, ds: list[dict]) -> int:
    """Index of the display holding most of ``frame`` (x, y, w, h)."""
    x, y, w, h = frame
    best, best_area = 0, -1.0
    for i, d in enumerate(ds):
        ix = max(0.0, min(x + w, d["x"] + d["w"]) - max(x, d["x"]))
        iy = max(0.0, min(y + h, d["y"] + d["h"]) - max(y, d["y"]))
        if ix * iy > best_area:
            best, best_area = i, ix * iy
    return best


_ORDINALS = {"first": 0, "1": 0, "one": 0, "second": 1, "2": 1, "two": 1, "third": 2, "3": 2, "three": 2}


def _pick(which: str, ds: list[dict], current: int) -> int | None:
    """Which display the user means: other/next/previous, left/right, main, laptop, ipad, a number,
    or part of a display's name. None if it can't be resolved."""
    w = (which or "").strip().lower()
    n = len(ds)
    if n < 2:
        return None
    if w in ("", "other", "next", "another", "second screen"):
        return (current + 1) % n
    if w in ("previous", "prev", "last"):
        return (current - 1) % n
    if w in ("left", "left hand", "leftmost"):
        return current - 1 if current > 0 else 0
    if w in ("right", "right hand", "rightmost"):
        return current + 1 if current < n - 1 else n - 1
    if w in ("main", "primary", "big", "external", "monitor", "desktop"):
        hit = next((i for i, d in enumerate(ds) if d["main"]), None)
        if w == "external":
            hit = next((i for i, d in enumerate(ds) if not d["builtin"] and "sidecar" not in d["name"].lower()), hit)
        return hit
    if w in ("laptop", "built in", "builtin", "macbook"):
        return next((i for i, d in enumerate(ds) if d["builtin"]), None)
    if w in ("ipad", "sidecar", "tablet"):
        return next((i for i, d in enumerate(ds) if "sidecar" in d["name"].lower()), None)
    if w in _ORDINALS:
        i = _ORDINALS[w]
        return i if i < n else None
    return next((i for i, d in enumerate(ds) if w and w in d["name"].lower()), None)


def _skeleton(word: str) -> str:
    """Rough sound key: first letter + the consonants after it, doubles collapsed ("cloud" and
    "Claude" → "cld", "zen" → "zn")."""
    w = re.sub(r"[^a-z]", "", word.lower())
    if not w:
        return ""
    out = w[0] + re.sub(r"[aeiouyhw]", "", w[1:])
    return re.sub(r"(.)\1+", r"\1", out)


def _sounds_like(heard: str, app: str) -> bool:
    a, b = _skeleton(heard), _skeleton(app)
    return len(a) >= 2 and a == b


# --- the window ----------------------------------------------------------------------------------

def _window(app: str = ""):
    """(fns, window element, app name) for the named app's front window, or the frontmost app's.
    Raises ValueError with a speakable message when there isn't one."""
    from vox import ax
    fns = ax._load()
    if not fns:
        raise ValueError("I can't control windows without Accessibility permission.")
    pid, name = None, ""
    if app:
        from AppKit import NSWorkspace
        want = app.strip().lower()
        for ra in NSWorkspace.sharedWorkspace().runningApplications():
            nm = str(ra.localizedName() or "")
            if nm.lower().replace("‎", "") == want or (want and want in nm.lower() and ra.activationPolicy() == 0):
                pid, name = int(ra.processIdentifier()), nm.replace("‎", "")
                break
        if pid is None:
            # A mis-heard app name ("move cloud to my other monitor" with Claude running, 9 Nov):
            # take the ONE open app that sounds the same rather than giving up.
            near = [(int(ra.processIdentifier()), str(ra.localizedName() or "").replace("‎", ""))
                    for ra in NSWorkspace.sharedWorkspace().runningApplications()
                    if ra.activationPolicy() == 0 and _sounds_like(want, str(ra.localizedName() or ""))]
            if len(near) == 1:
                pid, name = near[0]
        if pid is None:
            raise ValueError(f"{app} isn't open.")
    else:
        hit = ax.focused_app() or ax.frontmost()
        if not hit:
            raise ValueError("I couldn't tell which window you mean.")
        pid, name = hit
    root = fns["AXUIElementCreateApplication"](pid)
    win = ax._attr(fns, root, "AXFocusedWindow") or ax._attr(fns, root, "AXMainWindow")
    if win is None:
        wins = ax._attr(fns, root, "AXWindows") or []
        win = wins[0] if len(wins) else None
    if win is None:
        raise ValueError(f"{name or 'That app'} has no window to move.")
    return fns, win, name


def _frame(fns, win):
    from vox import ax
    pos = ax._axpair(fns, ax._attr(fns, win, "AXPosition"), _AXVALUE_CGPOINT)
    size = ax._axpair(fns, ax._attr(fns, win, "AXSize"), _AXVALUE_CGSIZE)
    if pos is None or size is None:
        return None
    return (pos[0], pos[1], size[0], size[1])


def _set_frame(fns, win, x, y, w, h) -> bool:
    create = _setter()
    if create is None:
        return False
    import objc  # noqa: F401  (struct wrappers come from Foundation)
    from Foundation import NSMakePoint
    pos = create(_AXVALUE_CGPOINT, NSMakePoint(x, y))
    size = create(_AXVALUE_CGSIZE, NSMakePoint(w, h))
    set_attr = fns["AXUIElementSetAttributeValue"]
    # Size, position, size again: a window that's too big for its new display gets clamped by the
    # app when it moves, so the second size lands it at the size we asked for.
    ok = set_attr(win, "AXSize", size) == 0
    ok = (set_attr(win, "AXPosition", pos) == 0) and ok
    set_attr(win, "AXSize", size)
    return ok


def _leave_fullscreen(fns, win) -> bool:
    """A window in macOS full screen can't be moved or resized (AXPosition fails with -25200): take it
    out first and wait for the animation. Returns True if it WAS full screen."""
    from vox import ax
    if not ax._attr(fns, win, "AXFullScreen"):
        return False
    fns["AXUIElementSetAttributeValue"](win, "AXFullScreen", False)
    for _ in range(30):   # up to ~3 s for the exit animation
        time.sleep(0.1)
        if not ax._attr(fns, win, "AXFullScreen"):
            break
    time.sleep(0.6)       # the frame settles a moment after the flag flips
    return True


def _restore_fullscreen(fns, win) -> None:
    time.sleep(0.3)
    fns["AXUIElementSetAttributeValue"](win, "AXFullScreen", True)


# --- what Vox calls ------------------------------------------------------------------------------

def move_to_display(which: str = "other", app: str = "") -> str:
    """Move a window to another display, keeping its place and proportions there."""
    ds = displays()
    if len(ds) < 2:
        return "There's only one screen connected."
    try:
        fns, win, name = _window(app)
    except ValueError as exc:
        return str(exc)
    f = _frame(fns, win)
    if f is None:
        return f"I couldn't read where {name or 'that window'} is."
    cur = _display_of(f, ds)
    to = _pick(which, ds, cur)
    if to is not None and to != cur and _leave_fullscreen(fns, win):
        f = _frame(fns, win) or f
        moved = _move(fns, win, f, ds, cur, to)
        _restore_fullscreen(fns, win)   # full screen again, now on the new display
        return moved if not moved.startswith("Moved") else f"Moved {name or 'it'} to the {_spoken(ds[to], to, ds)}, full screen."
    return _move_checked(fns, win, f, ds, cur, to, which, name)


def _move_checked(fns, win, f, ds, cur, to, which, name) -> str:
    if to is None:
        return f"I couldn't tell which screen '{which}' is."
    if to == cur:
        return f"{name or 'It'} is already on that screen."
    out = _move(fns, win, f, ds, cur, to)
    return out if not out.startswith("Moved") else f"Moved {name or 'it'} to the {_spoken(ds[to], to, ds)}."


def _move(fns, win, f, ds, cur, to) -> str:
    a, b = ds[cur], ds[to]
    # Same relative position and size on the new display, shrunk to fit if needed.
    w = min(f[2] * b["w"] / a["w"], b["w"]) if f[2] > b["w"] else min(f[2], b["w"])
    h = min(f[3], b["h"])
    rx = (f[0] - a["x"]) / max(1.0, a["w"] - f[2]) if a["w"] > f[2] else 0.0
    ry = (f[1] - a["y"]) / max(1.0, a["h"] - f[3]) if a["h"] > f[3] else 0.0
    x = b["x"] + max(0.0, min(1.0, rx)) * max(0.0, b["w"] - w)
    y = b["y"] + max(0.0, min(1.0, ry)) * max(0.0, b["h"] - h)
    if not _set_frame(fns, win, x, y, w, h):
        return "That window wouldn't let me move it."
    return "Moved."


def place(layout: str, app: str = "") -> str:
    """Fill the current display, or snap to its left/right half, or centre."""
    ds = displays()
    if not ds:
        return "I couldn't read the screen layout."
    try:
        fns, win, name = _window(app)
    except ValueError as exc:
        return str(exc)
    f = _frame(fns, win)
    if f is None:
        return f"I couldn't read where {name or 'that window'} is."
    if _leave_fullscreen(fns, win):   # maximise/snap a full-screen window: it leaves full screen
        f = _frame(fns, win) or f
    d = ds[_display_of(f, ds)]
    lay = (layout or "").lower()
    if lay in ("fill", "maximize", "maximise", "max", "full"):
        x, y, w, h = d["x"], d["y"], d["w"], d["h"]
    elif lay == "left":
        x, y, w, h = d["x"], d["y"], d["w"] / 2, d["h"]
    elif lay == "right":
        x, y, w, h = d["x"] + d["w"] / 2, d["y"], d["w"] / 2, d["h"]
    elif lay in ("center", "centre", "middle"):
        w, h = min(f[2], d["w"]), min(f[3], d["h"])
        x, y = d["x"] + (d["w"] - w) / 2, d["y"] + (d["h"] - h) / 2
    else:
        return f"I don't know how to put a window '{layout}'."
    if not _set_frame(fns, win, x, y, w, h):
        return f"{name or 'That app'} wouldn't let me resize its window."
    said = {"left": "on the left half", "right": "on the right half", "center": "in the middle",
            "centre": "in the middle", "middle": "in the middle"}.get(lay, "filling the screen")
    return f"{name or 'It'} is {said}."


def _spoken(d: dict, i: int, ds: list[dict]) -> str:
    if "sidecar" in d["name"].lower():
        return "iPad"
    if d["builtin"]:
        return "laptop screen"
    if len(ds) == 2:
        return "left screen" if i == 0 else "right screen"
    return f"{d['name']} screen"


def describe() -> str:
    """One line for the brain: the displays, left to right."""
    ds = displays()
    if len(ds) < 2:
        return ""
    return "Displays, left to right: " + "; ".join(
        f"{_spoken(d, i, ds)} ({d['name']}{', main' if d['main'] else ''})" for i, d in enumerate(ds))
