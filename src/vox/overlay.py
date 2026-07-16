"""Floating numbered overlay for click-by-number (idea #52).

Draws a small numbered badge over each clickable element (frames from
``vox.ax.targets_with_frames``) so you can say "click 14". Dragon does this with vision/OCR; we use
the native AX frames — exact identity, no image analysis.

The daemon has NO ``NSApplication`` run loop (it's a single blocking audio loop + worker threads), so
the usual "run the app" model doesn't apply. Instead we: grab ``NSApplication.sharedApplication()``
once, build a borderless, transparent, click-through, screen-saver-level ``NSWindow`` covering the
primary display, add one ``NSTextField`` badge per element, then ``orderFrontRegardless()`` +
``display()`` to flush the draw synchronously and pump the run loop for a few ms. The WindowServer
keeps the drawn content on screen while the voice loop blocks on the next utterance; ``hide()``
orders it out.

Fully LAZY + GUARDED: PyObjC/AppKit is imported only inside ``show()``; any failure raises
``OverlayUnavailable`` so the caller (dispatch) can fall back gracefully. Must be called on the main
thread (dispatch runs there) — AppKit is not thread-safe.
"""

from __future__ import annotations


class OverlayUnavailable(Exception):
    """Raised when the overlay can't be built/shown, so the caller can fall back."""


_win = None       # the reused NSWindow (built once)
_badges: list = []  # current NSTextField badge subviews (cleared on each show)
_active = False   # is the overlay currently on screen?


def is_active() -> bool:
    return _active


def _build_window(AppKit, screen_frame):
    """Create the borderless, transparent, click-through, top-level window once."""
    style = AppKit.NSWindowStyleMaskBorderless
    win = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        screen_frame, style, AppKit.NSBackingStoreBuffered, False)
    win.setOpaque_(False)
    win.setBackgroundColor_(AppKit.NSColor.clearColor())
    win.setLevel_(AppKit.NSScreenSaverWindowLevel)   # above normal + fullscreen app windows
    win.setIgnoresMouseEvents_(True)                 # click-through: never steals a click
    win.setHasShadow_(False)
    win.setCollectionBehavior_(
        AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
        | AppKit.NSWindowCollectionBehaviorStationary
        | AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary)
    view = AppKit.NSView.alloc().initWithFrame_(screen_frame)
    view.setWantsLayer_(True)
    win.setContentView_(view)
    return win


def _make_badge(AppKit, num: int, x: float, y: float):
    """One numbered badge (an NSTextField with a rounded colored layer)."""
    w, h = 26.0, 18.0
    tf = AppKit.NSTextField.alloc().initWithFrame_(AppKit.NSMakeRect(x, y, w, h))
    tf.setStringValue_(str(num))
    tf.setEditable_(False)
    tf.setSelectable_(False)
    tf.setBordered_(False)
    tf.setBezeled_(False)
    tf.setDrawsBackground_(False)  # background comes from the layer (rounded)
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


def show(items) -> int:
    """Draw a numbered badge over each element in ``items`` (from ax.targets_with_frames — dicts with
    x/y/w/h in AX top-left screen coords) and return how many were drawn. Raises OverlayUnavailable
    on any AppKit failure. Numbers are 1-based (badge N ↔ items[N-1])."""
    global _win, _badges, _active
    if not items:
        raise OverlayUnavailable("nothing to show")
    try:
        import AppKit
        from Foundation import NSDate, NSRunLoop
    except Exception as exc:
        raise OverlayUnavailable(f"AppKit unavailable: {exc}") from exc
    try:
        AppKit.NSApplication.sharedApplication()  # establish the WindowServer connection (once)
        # Primary display (AX's origin) — its height flips AX's top-left Y to Cocoa's bottom-left Y.
        primary = AppKit.NSScreen.screens()[0]
        frame = primary.frame()
        screen_h = frame.size.height

        if _win is None:
            _win = _build_window(AppKit, frame)
        view = _win.contentView()

        for b in _badges:  # clear the previous round's badges
            b.removeFromSuperview()
        _badges = []

        for it in items:
            num = it["index"] + 1
            # Badge sits at the element's top-left; flip Y (AX top-left → Cocoa bottom-left).
            bx = float(it["x"])
            by = screen_h - float(it["y"]) - 18.0
            badge = _make_badge(AppKit, num, bx, by)
            view.addSubview_(badge)
            _badges.append(badge)

        _win.orderFrontRegardless()   # show WITHOUT activating our process (no focus steal)
        _win.display()                # flush the draw synchronously (no run loop needed)
        # Pump the run loop briefly so the window server paints before we go back to listening.
        NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.05))
        _active = True
        return len(_badges)
    except OverlayUnavailable:
        raise
    except Exception as exc:
        raise OverlayUnavailable(f"overlay draw failed: {exc}") from exc


def hide() -> None:
    """Remove the overlay from screen (safe to call when nothing is showing)."""
    global _active
    _active = False
    try:
        if _win is not None:
            _win.orderOut_(None)
            from Foundation import NSDate, NSRunLoop
            NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.02))
    except Exception:
        pass


# --- CLI: show the overlay over the frontmost app for a few seconds, then hide ------------------

if __name__ == "__main__":
    import time
    from vox import ax

    print("Focus the app to overlay… showing in 3s")
    time.sleep(3)
    targets = ax.targets_with_frames(limit=80)
    if not targets:
        print("no clickable elements found")
        raise SystemExit(0)
    n = show(targets)
    print(f"drew {n} badges — holding 4s")
    # Keep the process alive so the window stays painted (a real run would go back to listening here).
    time.sleep(4)
    hide()
    print("hidden")
