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


def show(items, names: bool = False) -> int:
    """Spawn the helper to draw a numbered badge over each element in ``items`` (dicts with
    index/x/y/w/h from ax.targets_with_frames). Numbers are 1-based (badge N ↔ items[N-1]). Replaces
    any existing overlay. Returns the count. Raises OverlayUnavailable if the helper can't be spawned.

    ``names``: Apple Voice Control's "Show names" — each badge also carries the control's label, so
    you can see what Vox will answer to ("click Export") as well as its number."""
    global _proc
    if not items:
        raise OverlayUnavailable("nothing to show")
    hide()  # never stack two overlays
    payload = [{"n": it["index"] + 1, "x": float(it["x"]), "y": float(it["y"]),
                "w": float(it["w"]), "h": float(it["h"]),
                **({"label": _short(it.get("label", ""))} if names else {})} for it in items]
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


def _short(label: str, limit: int = 28) -> str:
    """One line, at most ``limit`` characters — a name badge must not blanket its neighbours."""
    one = " ".join((label or "").split())
    return one if len(one) <= limit else one[: limit - 1].rstrip() + "…"


def _nudge(rect, placed, step: float = 19.0, tries: int = 3):
    """(x, y, w, h) moved down (Cocoa y decreases) until it clears every rect in ``placed`` — at most
    ``tries`` rows, then it stays where it is. Name badges are wider than the controls they label,
    so neighbours in a menu bar or toolbar would otherwise cover each other's names."""
    x, y, w, h = rect
    for _ in range(tries):
        if not any(x < px + pw and px < x + w and y < py + ph and py < y + h for px, py, pw, ph in placed):
            break
        y -= step
    return (x, y, w, h)


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


def annotate(image_path: str, items, out_path: str = "/tmp/vox_marks.png") -> str | None:
    """Draw the same numbered badges ONTO a screenshot and save it — "set of marks" for the vision
    brain (idea #37, the escalation path off #52).

    When the brain can't find a target by LABEL, a labelled list can't express "the second last
    message" or "the one at 7:52pm" — position and order simply aren't in the text. This hands it the
    picture instead, with a number on every clickable element, so it only has to answer "which
    number?" and we click that element by its real AX frame. Far more reliable than asking a model
    for raw pixel coordinates, because the click target stays a real element, not an estimate.

    Draws in-memory (no on-screen flash, and it sidesteps the overlay window being
    ``NSWindowSharingNone`` — which screenshots deliberately can't see). ``items`` are the dicts from
    ``ax.targets_with_frames``; badge N ↔ items[N-1], matching ``show()``. Returns the written path,
    or None if anything fails (caller falls back)."""
    try:
        import AppKit
        from Foundation import NSMakeRect, NSMakePoint

        img = AppKit.NSImage.alloc().initWithContentsOfFile_(image_path)
        if img is None:
            return None
        rep = img.representations()[0]
        px_w, px_h = float(rep.pixelsWide()), float(rep.pixelsHigh())
        screen = AppKit.NSScreen.screens()[0].frame()
        # The capture is downscaled (actions.capture_screen → sips -Z 1568) and may be Retina, so map
        # AX points → image pixels by the ratio actually measured off the image.
        sx, sy = px_w / float(screen.size.width), px_h / float(screen.size.height)

        canvas = AppKit.NSImage.alloc().initWithSize_(AppKit.NSMakeSize(px_w, px_h))
        canvas.lockFocus()
        AppKit.NSGraphicsContext.currentContext().setShouldAntialias_(True)
        img.drawInRect_fromRect_operation_fraction_(
            NSMakeRect(0, 0, px_w, px_h), AppKit.NSZeroRect, AppKit.NSCompositingOperationCopy, 1.0)

        font = AppKit.NSFont.boldSystemFontOfSize_(max(9.0, 11.0 * min(sx, sy)))
        for n, it in enumerate(items, start=1):
            bw, bh = 26.0 * sx, 16.0 * sy
            # AX is top-left origin; the image canvas is bottom-left. Flip, and keep the badge inside.
            bx = min(max(float(it["x"]) * sx, 0.0), px_w - bw)
            by = min(max(px_h - float(it["y"]) * sy - bh, 0.0), px_h - bh)
            AppKit.NSColor.systemBlueColor().setFill()
            AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                NSMakeRect(bx, by, bw, bh), 3.0, 3.0).fill()
            AppKit.NSColor.whiteColor().setStroke()
            AppKit.NSString.stringWithString_(str(n)).drawAtPoint_withAttributes_(
                NSMakePoint(bx + 3.0, by + 1.0),
                {AppKit.NSFontAttributeName: font,
                 AppKit.NSForegroundColorAttributeName: AppKit.NSColor.whiteColor()})
        canvas.unlockFocus()

        tiff = canvas.TIFFRepresentation()
        bmp = AppKit.NSBitmapImageRep.imageRepWithData_(tiff)
        png = bmp.representationUsingType_properties_(AppKit.NSBitmapImageFileTypePNG, {})
        return out_path if png.writeToFile_atomically_(out_path, True) else None
    except Exception:
        return None


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


def _make_badge(AppKit, num: int, x: float, y: float, label: str = ""):
    """One numbered badge — an NSTextField with a rounded blue layer (x/y are Cocoa bottom-left).
    With a ``label`` ("show names") it reads "14 Export", sized to fit, on a dark plate so it's
    told apart from a plain number badge at a glance."""
    tf = AppKit.NSTextField.alloc().initWithFrame_(AppKit.NSMakeRect(x, y, 26.0, 18.0))
    tf.setStringValue_(f"{num} {label}" if label else str(num))
    tf.setEditable_(False)
    tf.setSelectable_(False)
    tf.setBordered_(False)
    tf.setBezeled_(False)
    tf.setDrawsBackground_(False)
    tf.setAlignment_(AppKit.NSTextAlignmentCenter)
    # Smaller past 99 so a 3-digit number still fits the badge ("100" clipped to "10" at 11pt).
    # Shrinking the text rather than widening the box keeps badges uniform and occluding less — and
    # 3-digit numbers only show up on dense screens, where covering neighbours hurts most.
    tf.setFont_(AppKit.NSFont.boldSystemFontOfSize_(11 if num < 100 else 9))
    tf.setTextColor_(AppKit.NSColor.whiteColor())
    tf.setWantsLayer_(True)
    layer = tf.layer()
    layer.setBackgroundColor_(AppKit.NSColor.systemBlueColor().CGColor())
    layer.setCornerRadius_(4.0)
    layer.setBorderWidth_(1.0)
    layer.setBorderColor_(AppKit.NSColor.whiteColor().CGColor())
    if label:
        tf.setFont_(AppKit.NSFont.boldSystemFontOfSize_(10))
        tf.sizeToFit()
        fit = tf.frame().size.width
        tf.setFrame_(AppKit.NSMakeRect(x, y, fit + 8.0, 18.0))
        layer.setBackgroundColor_(AppKit.NSColor.colorWithWhite_alpha_(0.12, 0.88).CGColor())
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
    # ONE overlay window PER display — robust for Sidecar / multi-monitor. (A single window spanning
    # displays with a negative origin renders unreliably and scatters badges to a corner.) Each window
    # sits at its own screen's frame; a badge is placed in the window of the display it falls on.
    windows = [(_build_window(AppKit, s.frame()), s.frame()) for s in screens]
    placed: dict = {}  # per window: name-badge rects already drawn (see _nudge)
    for b in badges:
        # AX (global, top-left origin) → Cocoa (global, bottom-left) via the primary height.
        gx = float(b["x"])
        gy = primary_h - float(b["y"]) - 18.0
        # Which display does this element sit on? Test its CENTRE (Cocoa global) against each frame.
        ecx = gx + float(b.get("w", 0.0)) / 2.0
        ecy = primary_h - float(b["y"]) - float(b.get("h", 0.0)) / 2.0
        for win, sf in windows:
            if (sf.origin.x <= ecx < sf.origin.x + sf.size.width
                    and sf.origin.y <= ecy < sf.origin.y + sf.size.height):
                # Badge at the element's top-left, in THIS display's local (window) coords.
                badge = _make_badge(AppKit, int(b["n"]), gx - sf.origin.x, gy - sf.origin.y,
                                    b.get("label", ""))
                if b.get("label"):
                    f = badge.frame()
                    r = _nudge((f.origin.x, f.origin.y, f.size.width, f.size.height), placed.setdefault(id(win), []))
                    badge.setFrame_(AppKit.NSMakeRect(*r))
                    placed[id(win)].append(r)
                win.contentView().addSubview_(badge)
                break
    for win, _sf in windows:
        win.orderFrontRegardless()

    # Safety auto-dismiss — the parent normally terminates us first (on the next utterance).
    NSTimer.scheduledTimerWithTimeInterval_repeats_block_(
        ttl, False, lambda _t: app.terminate_(None))
    app.run()


# --- Pointing (ideas #69.2): show WHERE something is, without clicking it ------------------------

_point_proc: subprocess.Popen | None = None


def point(items, ttl: float = 4.5) -> int:
    """Ring each element in ``items`` (dicts with x/y/w/h in AX top-left screen coords, optional
    ``label``) with a glowing outline that flies in from the mouse pointer, pulses, then fades.
    Click-through and never takes focus. Replaces any pointing already on screen. Returns the count.
    Raises OverlayUnavailable if the helper can't be spawned."""
    global _point_proc
    items = [it for it in (items or []) if float(it.get("w", 0)) > 0 and float(it.get("h", 0)) > 0]
    if not items:
        raise OverlayUnavailable("nothing to point at")
    if _point_proc is not None and _point_proc.poll() is None:
        _point_proc.terminate()
    payload = {"ttl": float(ttl), "items": [{"x": float(it["x"]), "y": float(it["y"]), "w": float(it["w"]),
                                            "h": float(it["h"]), "label": str(it.get("label") or "")[:60]}
                                           for it in items[:8]]}
    fd, path = tempfile.mkstemp(suffix=".json", prefix="vox_point_")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(payload, f)
        _point_proc = subprocess.Popen([sys.executable, "-m", "vox.overlay", "--point", path],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as exc:
        raise OverlayUnavailable(f"couldn't spawn pointer helper: {exc}") from exc
    return len(payload["items"])


def _run_pointer(path: str) -> None:
    """Child entry point for ``point``: one transparent window per display, a ring per target."""
    try:
        with open(path) as f:
            spec = json.load(f)
    finally:
        try:
            os.unlink(path)
        except Exception:
            pass
    items, ttl = spec.get("items") or [], float(spec.get("ttl", 4.5))
    if not items:
        return

    import AppKit
    import objc
    from Foundation import NSTimer

    CABasicAnimation = objc.lookUpClass("CABasicAnimation")
    app = AppKit.NSApplication.sharedApplication()
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyProhibited)

    screens = AppKit.NSScreen.screens()
    primary_h = screens[0].frame().size.height
    windows = [(_build_window(AppKit, sc.frame()), sc.frame()) for sc in screens]
    accent = AppKit.NSColor.controlAccentColor()
    mouse = AppKit.NSEvent.mouseLocation()  # Cocoa global, bottom-left origin
    pad = 6.0

    for it in items:
        # AX (top-left origin) → Cocoa global (bottom-left origin).
        x, w, h = it["x"] - pad, it["w"] + pad * 2, it["h"] + pad * 2
        y = primary_h - it["y"] - it["h"] - pad
        cx, cy = x + w / 2, y + h / 2
        for win, sf in windows:
            if not (sf.origin.x <= cx < sf.origin.x + sf.size.width and sf.origin.y <= cy < sf.origin.y + sf.size.height):
                continue
            ox, oy = sf.origin.x, sf.origin.y
            target = AppKit.NSMakeRect(x - ox, y - oy, w, h)
            ring = AppKit.NSView.alloc().initWithFrame_(
                AppKit.NSMakeRect(mouse.x - ox - 14, mouse.y - oy - 14, 28, 28))  # starts at the pointer
            ring.setWantsLayer_(True)
            layer = ring.layer()
            layer.setCornerRadius_(min(14.0, h / 2))
            layer.setBorderWidth_(3.5)
            layer.setBorderColor_(accent.CGColor())
            layer.setBackgroundColor_(accent.colorWithAlphaComponent_(0.10).CGColor())
            layer.setShadowColor_(accent.CGColor())
            layer.setShadowOpacity_(0.9)
            layer.setShadowRadius_(12.0)
            layer.setShadowOffset_((0.0, 0.0))
            win.contentView().addSubview_(ring)

            label_view = None
            if it.get("label"):
                label_view = AppKit.NSTextField.labelWithString_(f"  {it['label']}  ")
                label_view.setFont_(AppKit.NSFont.systemFontOfSize_weight_(13, AppKit.NSFontWeightSemibold))
                label_view.setTextColor_(AppKit.NSColor.whiteColor())
                label_view.setWantsLayer_(True)
                label_view.layer().setBackgroundColor_(accent.CGColor())
                label_view.layer().setCornerRadius_(9.0)
                label_view.sizeToFit()
                lw, lh = label_view.frame().size.width, max(22.0, label_view.frame().size.height + 4)
                above = target.origin.y + target.size.height + 6
                ly = above if above + lh < sf.size.height else target.origin.y - lh - 6  # below if no room above
                label_view.setFrame_(AppKit.NSMakeRect(target.origin.x, ly, lw, lh))
                label_view.setAlphaValue_(0.0)
                win.contentView().addSubview_(label_view)

            def fly(_t, ring=ring, target=target, label_view=label_view):
                def anim(ctx):
                    ctx.setDuration_(0.45)
                    ctx.setTimingFunction_(objc.lookUpClass("CAMediaTimingFunction").functionWithName_("easeInEaseOut"))
                    ring.animator().setFrame_(target)
                    if label_view is not None:
                        label_view.animator().setAlphaValue_(1.0)
                AppKit.NSAnimationContext.runAnimationGroup_completionHandler_(anim, None)
                pulse = CABasicAnimation.animationWithKeyPath_("shadowRadius")
                pulse.setFromValue_(6.0)
                pulse.setToValue_(18.0)
                pulse.setDuration_(0.8)
                pulse.setAutoreverses_(True)
                pulse.setRepeatCount_(1e9)
                ring.layer().addAnimation_forKey_(pulse, "pulse")
            NSTimer.scheduledTimerWithTimeInterval_repeats_block_(0.02, False, fly)
            break

    for win, _sf in windows:
        win.orderFrontRegardless()

    def fade(_t):
        def anim(ctx):
            ctx.setDuration_(0.4)
            for win, _sf in windows:
                win.animator().setAlphaValue_(0.0)
        AppKit.NSAnimationContext.runAnimationGroup_completionHandler_(anim, lambda: app.terminate_(None))
    NSTimer.scheduledTimerWithTimeInterval_repeats_block_(max(1.0, ttl), False, fade)
    NSTimer.scheduledTimerWithTimeInterval_repeats_block_(max(1.0, ttl) + 2.0, False, lambda _t: app.terminate_(None))
    app.run()


# --- CLI: `--helper <json>` is the child; no args = standalone test over the frontmost app -------

if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Vox numbered clickable overlay (idea #52)")
    ap.add_argument("--helper", help="internal: run as the overlay helper on this JSON badge file")
    ap.add_argument("--point", help="internal: run as the pointer helper on this JSON file")
    ap.add_argument("--delay", type=float, default=3.0, help="standalone test: focus delay (s)")
    _a = ap.parse_args()

    if _a.point:
        _run_pointer(_a.point)
    elif _a.helper:
        _run_helper(_a.helper)
    else:
        import time
        from vox import targets as _t

        print(f"focus the app to overlay… showing in {_a.delay:.0f}s")
        time.sleep(_a.delay)
        _targets = _t.visible_targets(limit=80)  # same routing as voice: DOM on a page, AX natively
        if not _targets:
            print("no clickable elements found")
            raise SystemExit(0)
        _n = show(_targets)
        print(f"spawned overlay helper with {_n} badges — holding 5s")
        time.sleep(5)
        hide()
        print("hidden")
