"""Floating numbered overlay for click-by-number (idea #52).

Draws a small numbered badge over each clickable element (frames from
``vox.ax.targets_with_frames``) so you can say "click 14". Dragon does this with vision/OCR; we use
the native AX frames — exact identity, no image analysis.

**Runs in a separate HELPER PROCESS.** The daemon is a single blocking audio loop with no
``NSApplication`` run loop, and a visible ``NSWindow`` whose main thread never services its run loop
makes the whole app unresponsive (the beachball freeze). So the daemon spawns a short-lived helper
(`python -m vox.overlay --helper <json>`) that owns its OWN ``NSApplication`` + run loop (responsive),
draws the badges, and lives until the daemon hides it (terminate) or a safety timeout. The daemon
still does the actual click via ``ax.click_index`` — the helper only draws. This keeps AppKit
completely out of the daemon's main loop, so the overlay can never freeze it.

``show()`` / ``hide()`` / ``is_active()`` are the daemon-side API; ``_run_helper`` is the child.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile


class OverlayUnavailable(Exception):
    """Raised when the overlay can't be shown, so the caller can fall back."""


_proc: subprocess.Popen | None = None  # the running helper process (None when nothing is shown)


def is_active() -> bool:
    """True while the overlay helper is alive (badges on screen)."""
    return _proc is not None and _proc.poll() is None


def show(items) -> int:
    """Spawn the helper to draw a numbered badge over each element in ``items`` (dicts with
    index/x/y/w/h from ax.targets_with_frames). Numbers are 1-based (badge N ↔ items[N-1]). Replaces
    any existing overlay. Returns the count. Raises OverlayUnavailable if the helper can't be spawned."""
    global _proc
    if not items:
        raise OverlayUnavailable("nothing to show")
    hide()  # never stack two overlays
    payload = [{"n": it["index"] + 1, "x": float(it["x"]), "y": float(it["y"]),
                "w": float(it["w"]), "h": float(it["h"])} for it in items]
    fd, path = tempfile.mkstemp(suffix=".json", prefix="vox_overlay_")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(payload, f)
        _proc = subprocess.Popen(
            [sys.executable, "-m", "vox.overlay", "--helper", path],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as exc:
        raise OverlayUnavailable(f"couldn't spawn overlay helper: {exc}") from exc
    return len(payload)


def hide() -> None:
    """Dismiss the overlay (terminate the helper). Safe when nothing is showing."""
    global _proc
    if _proc is not None:
        try:
            if _proc.poll() is None:
                _proc.terminate()
        except Exception:
            pass
        _proc = None


# --- the helper child: draws the badges and runs its own NSApplication run loop ------------------

def _build_window(AppKit, screen_frame):
    """Borderless, transparent, click-through, top-level window covering ``screen_frame`` (the union
    of all displays). Its content view uses a zero-origin coord space, so badges are positioned in
    window-local coords (global-cocoa minus the union origin)."""
    win = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        screen_frame, AppKit.NSWindowStyleMaskBorderless, AppKit.NSBackingStoreBuffered, False)
    win.setOpaque_(False)
    win.setBackgroundColor_(AppKit.NSColor.clearColor())
    win.setLevel_(AppKit.NSScreenSaverWindowLevel)   # above normal + fullscreen windows
    win.setIgnoresMouseEvents_(True)                 # click-through: never eats a click
    win.setHasShadow_(False)
    # Mark the overlay as non-capturable so it's excluded from screen recordings and doesn't read as
    # a capture surface — reduces the chance it trips DRM-protected video (streaming) into blacking out.
    try:
        win.setSharingType_(AppKit.NSWindowSharingNone)
    except Exception:
        pass
    win.setCollectionBehavior_(
        AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
        | AppKit.NSWindowCollectionBehaviorStationary
        | AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary)
    view = AppKit.NSView.alloc().initWithFrame_(
        AppKit.NSMakeRect(0, 0, screen_frame.size.width, screen_frame.size.height))
    view.setWantsLayer_(True)
    win.setContentView_(view)
    return win


def _make_badge(AppKit, num: int, x: float, y: float):
    """One numbered badge — an NSTextField with a rounded blue layer (x/y are Cocoa bottom-left)."""
    tf = AppKit.NSTextField.alloc().initWithFrame_(AppKit.NSMakeRect(x, y, 26.0, 18.0))
    tf.setStringValue_(str(num))
    tf.setEditable_(False)
    tf.setSelectable_(False)
    tf.setBordered_(False)
    tf.setBezeled_(False)
    tf.setDrawsBackground_(False)
    tf.setAlignment_(AppKit.NSTextAlignmentCenter)
    tf.setFont_(AppKit.NSFont.boldSystemFontOfSize_(11))
    tf.setTextColor_(AppKit.NSColor.whiteColor())
    tf.setWantsLayer_(True)
    layer = tf.layer()
    layer.setBackgroundColor_(AppKit.NSColor.systemBlueColor().CGColor())
    layer.setCornerRadius_(4.0)
    layer.setBorderWidth_(1.0)
    layer.setBorderColor_(AppKit.NSColor.whiteColor().CGColor())
    return tf


def _run_helper(path: str, ttl: float = 45.0) -> None:
    """Child entry point: load badges from ``path``, draw them, and run an NSApplication run loop
    until the parent terminates us or ``ttl`` seconds pass (safety so a crashed parent can't orphan
    the overlay). Own run loop ⇒ the window is responsive and never beachballs."""
    try:
        with open(path) as f:
            badges = json.load(f)
    finally:
        try:
            os.unlink(path)  # single-use temp file
        except Exception:
            pass
    if not badges:
        return

    import AppKit
    from Foundation import NSTimer

    app = AppKit.NSApplication.sharedApplication()
    # Prohibited: a pure overlay — no Dock icon, can't become active, never steals focus.
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyProhibited)

    screens = AppKit.NSScreen.screens()
    primary_h = screens[0].frame().size.height  # AX Y is measured from the top of the primary display
    # Cover the UNION of every display (incl. Sidecar / second screens) so badges off the primary
    # display aren't clipped to it.
    frames = [s.frame() for s in screens]
    min_x = min(f.origin.x for f in frames)
    min_y = min(f.origin.y for f in frames)
    max_x = max(f.origin.x + f.size.width for f in frames)
    max_y = max(f.origin.y + f.size.height for f in frames)
    win = _build_window(AppKit, AppKit.NSMakeRect(min_x, min_y, max_x - min_x, max_y - min_y))
    view = win.contentView()
    for b in badges:
        # AX (global, top-left origin) → Cocoa (global, bottom-left) via the primary height, then to
        # window-local coords by subtracting the union origin.
        gx = float(b["x"])
        gy = primary_h - float(b["y"]) - 18.0
        view.addSubview_(_make_badge(AppKit, int(b["n"]), gx - min_x, gy - min_y))
    win.orderFrontRegardless()

    # Safety auto-dismiss — the parent normally terminates us first (on the next utterance).
    NSTimer.scheduledTimerWithTimeInterval_repeats_block_(
        ttl, False, lambda _t: app.terminate_(None))
    app.run()


# --- CLI: `--helper <json>` is the child; no args = standalone test over the frontmost app -------

if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Vox numbered clickable overlay (idea #52)")
    ap.add_argument("--helper", help="internal: run as the overlay helper on this JSON badge file")
    ap.add_argument("--delay", type=float, default=3.0, help="standalone test: focus delay (s)")
    _a = ap.parse_args()

    if _a.helper:
        _run_helper(_a.helper)
    else:
        import time
        from vox import ax

        print(f"focus the app to overlay… showing in {_a.delay:.0f}s")
        time.sleep(_a.delay)
        _targets = ax.targets_with_frames(limit=80)
        if not _targets:
            print("no clickable elements found")
            raise SystemExit(0)
        _n = show(_targets)
        print(f"spawned overlay helper with {_n} badges — holding 5s")
        time.sleep(5)
        hide()
        print("hidden")
