"""Silent notification bubble — a pop-up text card in a corner of the screen.

The quiet sibling of the vox-speak MCP. `speak()` is the right heads-up when you're away from the
keyboard; it's the wrong one in a meeting, on a call, or when three agents finish inside a minute.
This draws the same message instead: a small rounded card in a screen corner, labelled with **who
sent it**, that stays until you close it. Nothing is spoken and nothing takes focus.

**Runs in a separate HELPER PROCESS**, for the same reason ``vox.overlay`` does: the daemon is a
single blocking audio loop with no ``NSApplication`` run loop, and a visible window whose main
thread never services its run loop makes the whole app unresponsive (the beachball freeze). So the
caller spawns a short-lived helper (`python -m vox.bubble --helper <json>`) that owns its OWN
``NSApplication`` + run loop. The MCP server has the same problem with its stdio loop.

**Why an NSPanel and not an NSWindow.** The card has a ✕ you can click, so unlike the click-badge
overlay it can't be mouse-transparent. A normal window would have to activate the app to handle
that click — stealing your focus, which is the one thing this must never do. A panel with
``NSWindowStyleMaskNonactivatingPanel`` takes the click *without* activating. That plus
``NSApplicationActivationPolicyProhibited`` (no Dock icon, can never become active) is what makes a
dismissible card that still can't interrupt you.

``show()`` / ``hide()`` / ``is_active()`` are the caller-side API; ``_run_helper`` is the child.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

from vox.config import CONFIG

# A bubble is a glance, not a document. Long text makes a card that covers the work you're doing —
# which is the one thing this feature exists to avoid. Truncate rather than grow.
_MAX_CHARS = 280
_MAX_SOURCE_CHARS = 32

_CORNERS = ("top-right", "top-left", "bottom-right", "bottom-left")

# duration sentinel: < 0 means "whatever the settings say"; 0 means "stay until dismissed".
_USE_CONFIGURED = -1.0


class BubbleUnavailable(Exception):
    """Raised when the bubble can't be shown, so the caller can fall back (e.g. to speaking)."""


_proc: subprocess.Popen | None = None  # the running helper process (None when nothing is shown)


def _setting(key: str, fallback):
    """Runtime override from the dashboard's settings_store, else the Config default. Fully guarded
    (mirrors executor._setting): if the store is missing or errors, behave as if unset. Lets the
    corner and duration change from the dashboard without restarting the daemon or the MCP server."""
    try:
        from vox.web import settings_store
        val = settings_store.get(key)
        return fallback if val is None else val
    except Exception:
        return fallback


def is_active() -> bool:
    """True while a bubble helper is alive (a card is on screen)."""
    return _proc is not None and _proc.poll() is None


def show(text: str, *, source: str = "", corner: str = "",
         duration: float = _USE_CONFIGURED) -> str:
    """Draw ``text`` as a bubble in a screen corner. Returns the text actually shown.

    ``source`` labels the card with who sent it (a registered agent name — see ``vox.agents``), so
    with several CLIs running you can tell at a glance which one is talking.

    ``duration`` is seconds on screen: **0 stays until you click the ✕**, a positive value fades
    out after that long, and the default (negative) takes whatever the dashboard is set to.

    Replaces any bubble already on screen — deliberately: two stacked cards cover more of the screen
    than one notification is worth, and the caller still gets this function's return value as
    confirmation. Raises BubbleUnavailable if the helper can't be spawned.
    """
    global _proc
    body = " ".join((text or "").split())  # collapse newlines/runs — it's one card, not a page
    if not body:
        raise BubbleUnavailable("nothing to show")
    if len(body) > _MAX_CHARS:
        body = body[:_MAX_CHARS - 1].rstrip() + "…"
    who = " ".join((source or "").split())[:_MAX_SOURCE_CHARS]

    where = (corner or str(_setting("bubble_corner", CONFIG.bubble_corner))).strip().lower()
    if where not in _CORNERS:
        where = CONFIG.bubble_corner
    secs = float(duration)
    if secs < 0:
        secs = float(_setting("bubble_duration", CONFIG.bubble_duration))
    width = float(_setting("bubble_max_width", CONFIG.bubble_max_width))

    hide()  # never stack two bubbles
    payload = {"text": body, "source": who, "corner": where,
               "duration": max(0.0, secs), "width": max(160.0, width)}
    fd, path = tempfile.mkstemp(suffix=".json", prefix="vox_bubble_")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(payload, f)
        _proc = subprocess.Popen(
            [sys.executable, "-m", "vox.bubble", "--helper", path],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            # Own session: a card that stays until you dismiss it must outlive whatever spawned it.
            # Otherwise a Ctrl-C in the calling shell, or an MCP server shutting down, takes the
            # notification with it — and the message you hadn't read yet is the thing you lose.
            # hide() still closes it; so does the ✕.
            start_new_session=True)
    except Exception as exc:
        raise BubbleUnavailable(f"couldn't spawn bubble helper: {exc}") from exc
    return body


def hide() -> None:
    """Dismiss the bubble early (terminate the helper). Safe when nothing is showing."""
    global _proc
    if _proc is not None:
        try:
            if _proc.poll() is None:
                _proc.terminate()
        except Exception:
            pass
        _proc = None


# --- the helper child: draws the card and runs its own NSApplication run loop --------------------

_PAD_X, _PAD_Y = 16.0, 12.0   # inner padding around the content
_MARGIN = 18.0                # gap from the screen edges
_RADIUS = 14.0
_HEADER_H = 16.0              # the source / ✕ row
_GAP = 6.0                    # between the header row and the message
_CLOSE_W = 18.0

_keepalive: list = []  # strong refs for objects AppKit only holds weakly (the button's target)


def _measure(AppKit, text: str, font, inner_w: float) -> float:
    """Height the wrapped text needs at ``inner_w``. The card is sized to its content — a fixed
    height either clips a long message or leaves a half-empty box on a short one."""
    attrs = {AppKit.NSFontAttributeName: font}
    s = AppKit.NSAttributedString.alloc().initWithString_attributes_(text, attrs)
    rect = s.boundingRectWithSize_options_(
        AppKit.NSMakeSize(inner_w, 10_000.0),
        AppKit.NSStringDrawingUsesLineFragmentOrigin | AppKit.NSStringDrawingUsesFontLeading)
    return float(rect.size.height)


def _origin(corner: str, vf, w: float, h: float) -> tuple[float, float]:
    """Bottom-left origin for the card, in Cocoa global coords. ``vf`` is the screen's *visible*
    frame, so we sit inside the menu bar and the Dock rather than under them."""
    right = vf.origin.x + vf.size.width - w - _MARGIN
    left = vf.origin.x + _MARGIN
    top = vf.origin.y + vf.size.height - h - _MARGIN
    bottom = vf.origin.y + _MARGIN
    return {
        "top-right": (right, top),
        "top-left": (left, top),
        "bottom-right": (right, bottom),
        "bottom-left": (left, bottom),
    }[corner]


def _build_panel(AppKit, x: float, y: float, w: float, h: float):
    """A floating, non-activating panel. Non-activating is the whole trick: it accepts the click on
    the ✕ without making this process the active app, so dismissing a notification never pulls you
    out of what you were doing."""
    style = AppKit.NSWindowStyleMaskBorderless | getattr(
        AppKit, "NSWindowStyleMaskNonactivatingPanel", 1 << 7)
    panel = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
        AppKit.NSMakeRect(x, y, w, h), style, AppKit.NSBackingStoreBuffered, False)
    panel.setOpaque_(False)
    panel.setBackgroundColor_(AppKit.NSColor.clearColor())
    panel.setLevel_(AppKit.NSScreenSaverWindowLevel)   # above normal + fullscreen windows
    panel.setHasShadow_(True)                          # it reads as a card, not an annotation
    try:
        panel.setFloatingPanel_(True)
        panel.setBecomesKeyOnlyIfNeeded_(True)
        panel.setHidesOnDeactivate_(False)
    except Exception:
        pass
    # Non-capturable: stays out of screen recordings, AND out of Vox's own `LOOK:` screenshots, so a
    # notification about one task can't become input to the next.
    try:
        panel.setSharingType_(AppKit.NSWindowSharingNone)
    except Exception:
        pass
    panel.setCollectionBehavior_(
        AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
        | AppKit.NSWindowCollectionBehaviorStationary
        | AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary)
    return panel


def _build_card(AppKit, w: float, h: float):
    """The card's content view: a native HUD-blur panel with rounded corners, falling back to a
    plain dark layer if NSVisualEffectView isn't available. HUD material is always dark, so white
    text reads correctly in both light and dark mode without us picking a theme."""
    frame = AppKit.NSMakeRect(0, 0, w, h)
    try:
        view = AppKit.NSVisualEffectView.alloc().initWithFrame_(frame)
        view.setMaterial_(AppKit.NSVisualEffectMaterialHUDWindow)
        view.setBlendingMode_(AppKit.NSVisualEffectBlendingModeBehindWindow)
        view.setState_(AppKit.NSVisualEffectStateActive)
    except Exception:
        view = AppKit.NSView.alloc().initWithFrame_(frame)
        view.setWantsLayer_(True)
        view.layer().setBackgroundColor_(
            AppKit.NSColor.colorWithCalibratedWhite_alpha_(0.12, 0.92).CGColor())
    view.setWantsLayer_(True)
    view.layer().setCornerRadius_(_RADIUS)
    view.layer().setMasksToBounds_(True)
    return view


def _build_label(AppKit, text: str, font, colour, x: float, y: float, w: float, h: float):
    """A non-editable, word-wrapping NSTextField — a label, not an input."""
    tf = AppKit.NSTextField.alloc().initWithFrame_(AppKit.NSMakeRect(x, y, w, h))
    tf.setStringValue_(text)
    tf.setEditable_(False)
    tf.setSelectable_(False)
    tf.setBordered_(False)
    tf.setBezeled_(False)
    tf.setDrawsBackground_(False)
    tf.setFont_(font)
    tf.setTextColor_(colour)
    cell = tf.cell()
    cell.setWraps_(True)
    cell.setLineBreakMode_(AppKit.NSLineBreakByWordWrapping)
    return tf


def _closer(AppKit):
    """Target object for the ✕. Defined lazily because AppKit is only imported in the child, and
    kept in ``_keepalive`` because a control's target is an unretained reference — let it get
    collected and clicking the ✕ does nothing."""
    from Foundation import NSObject

    class _BubbleCloser(NSObject):
        def dismiss_(self, sender):
            AppKit.NSApp().terminate_(None)

    obj = _BubbleCloser.alloc().init()
    _keepalive.append(obj)
    return obj


def _build_close(AppKit, x: float, y: float):
    """The ✕. Borderless and dim until you look for it — the card shouldn't shout about its own
    close button."""
    btn = AppKit.NSButton.alloc().initWithFrame_(
        AppKit.NSMakeRect(x, y, _CLOSE_W, _CLOSE_W))
    btn.setBordered_(False)
    btn.setBezelStyle_(AppKit.NSBezelStyleRegularSquare)
    attrs = {
        AppKit.NSFontAttributeName: AppKit.NSFont.systemFontOfSize_(12.0),
        AppKit.NSForegroundColorAttributeName:
            AppKit.NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.65),
    }
    btn.setAttributedTitle_(
        AppKit.NSAttributedString.alloc().initWithString_attributes_("✕", attrs))
    target = _closer(AppKit)
    btn.setTarget_(target)
    btn.setAction_("dismiss:")
    return btn


def _run_helper(path: str) -> None:
    """Child entry point: load the payload, draw the card, fade it in, and run an NSApplication run
    loop until the ✕ is clicked (or the duration elapses, when one was set)."""
    try:
        with open(path) as f:
            payload = json.load(f)
    finally:
        try:
            os.unlink(path)  # single-use temp file
        except Exception:
            pass
    text = payload.get("text") or ""
    if not text:
        return

    import AppKit
    from Foundation import NSTimer

    app = AppKit.NSApplication.sharedApplication()
    # Prohibited: a pure overlay — no Dock icon, can't become active, never steals focus.
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyProhibited)

    font = AppKit.NSFont.systemFontOfSize_(13.0)
    head_font = AppKit.NSFont.boldSystemFontOfSize_(10.0)
    w = float(payload["width"])
    inner_w = w - 2 * _PAD_X
    text_h = _measure(AppKit, text, font, inner_w)
    # The header row always exists — it carries the ✕ even when there's no source to name.
    h = _PAD_Y + text_h + _GAP + _HEADER_H + _PAD_Y

    # mainScreen() is the display holding the active window — i.e. the one you're looking at. On a
    # single display it's the same as screens()[0]; on a laptop + monitor it's the difference between
    # the bubble appearing where you're working and appearing on the other screen.
    screen = AppKit.NSScreen.mainScreen() or AppKit.NSScreen.screens()[0]
    x, y = _origin(payload["corner"], screen.visibleFrame(), w, h)

    panel = _build_panel(AppKit, x, y, w, h)
    card = _build_card(AppKit, w, h)

    head_y = h - _PAD_Y - _HEADER_H
    source = payload.get("source") or ""
    if source:
        card.addSubview_(_build_label(
            AppKit, source.upper(), head_font,
            AppKit.NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.55),
            _PAD_X, head_y, inner_w - _CLOSE_W - 6.0, _HEADER_H))
    card.addSubview_(_build_close(AppKit, w - _PAD_X - _CLOSE_W, head_y - 1.0))
    card.addSubview_(_build_label(
        AppKit, text, font, AppKit.NSColor.whiteColor(),
        _PAD_X, _PAD_Y, inner_w, text_h))
    panel.setContentView_(card)

    panel.setAlphaValue_(0.0)
    panel.orderFrontRegardless()
    AppKit.NSAnimationContext.beginGrouping()
    AppKit.NSAnimationContext.currentContext().setDuration_(0.18)
    panel.animator().setAlphaValue_(1.0)
    AppKit.NSAnimationContext.endGrouping()

    def _fade_out(_timer):
        AppKit.NSAnimationContext.beginGrouping()
        AppKit.NSAnimationContext.currentContext().setDuration_(0.35)
        panel.animator().setAlphaValue_(0.0)
        AppKit.NSAnimationContext.endGrouping()
        NSTimer.scheduledTimerWithTimeInterval_repeats_block_(
            0.4, False, lambda _t: app.terminate_(None))

    # duration 0 = stay until dismissed. No safety timeout on purpose: a notification that vanished
    # while you were looking at another window did nothing, which is the whole complaint this
    # setting answers. The parent's hide(), and the next bubble, both still close it.
    secs = float(payload.get("duration") or 0.0)
    if secs > 0:
        NSTimer.scheduledTimerWithTimeInterval_repeats_block_(secs, False, _fade_out)
    app.run()


# --- CLI: `--helper <json>` is the child; a bare message runs a standalone test ------------------

if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Vox silent notification bubble")
    ap.add_argument("message", nargs="?", help="standalone test: show this message")
    ap.add_argument("--helper", help="internal: run as the bubble helper on this JSON payload file")
    ap.add_argument("--source", default="", help="who the message is from (shown on the card)")
    ap.add_argument("--corner", default="", choices=("", *_CORNERS), help="override the corner")
    ap.add_argument("--duration", type=float, default=_USE_CONFIGURED,
                    help="seconds on screen; 0 = stay until dismissed")
    _a = ap.parse_args()

    if _a.helper:
        _run_helper(_a.helper)
    else:
        import time

        _msg = _a.message or "Vox is ready — this is a silent notification bubble."
        _shown = show(_msg, source=_a.source, corner=_a.corner, duration=_a.duration)
        print(f"bubble helper spawned: {_shown!r}")
        _secs = _a.duration if _a.duration >= 0 else float(
            _setting("bubble_duration", CONFIG.bubble_duration))
        if _secs > 0:
            time.sleep(_secs + 1.5)
            hide()
            print("done")
        else:
            print("staying until you click the ✕ (ctrl-c to give up on it)")
            while is_active():
                time.sleep(0.25)
            print("dismissed")
