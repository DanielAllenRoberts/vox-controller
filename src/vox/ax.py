"""Native macOS Accessibility (AXUIElement) access — fast, no extra dependency.

Why this exists: the AppleScript / System Events AX traversal that ``actions.click_element`` and
``actions.clickable_targets`` used does ~1 IPC round-trip per node, so a deep Electron tree (Slack,
Discord) takes seconds — and a *miss* walks the whole tree and could freeze the single-threaded voice
loop for ~25 s (the osascript timeout), after which focus has often drifted to another app. The native
AX C API is ~100× faster (a full Slack tree ≈ 77 ms), so a miss fails in well under a second and focus
can't drift.

No new pip package is needed: ``pyobjc-core`` + Cocoa + Quartz are already installed (they run the audio
stack); the AX functions live in the system ``ApplicationServices`` framework, whose bindings we load
directly with ``objc.loadBundleFunctions``. Everything here is fully guarded and returns ``None`` on any
failure so ``actions`` can fall back to the AppleScript path.

Encoding note (hard-won): ``AXUIElementRef`` must be encoded as ``@`` (it's a CFType → bridges as an
object), NOT ``^{__AXUIElement=}`` — the struct-pointer encoding makes children come back as a type that
can't be passed back into the C functions.
"""

import time

# Interactive-ish roles whose label is worth listing as a click target (matches the old AppleScript
# enumeration). The click SEARCH below is broader — it matches a label on any node — but the LISTING
# stays role-gated so the fuzzy-pick list isn't flooded with structural text.
_CLICKABLE_ROLES = {
    "AXButton", "AXLink", "AXMenuItem", "AXMenuBarItem", "AXCheckBox", "AXRadioButton",
    "AXTabButton", "AXPopUpButton", "AXStaticText", "AXRow", "AXCell", "AXTextField",
    "AXHeading", "AXImage", "AXDisclosureTriangle",
}

_BUDGET = 9000       # node-visit safety cap (native is fast; this is just a runaway guard)
_MAX_DEPTH = 45
_SETTLE = 0.4        # seconds — let Electron build its web-content AX tree on FIRST touch per app only

_FNS = None          # lazily-bound C functions ({} once load is attempted; None until then)
_enabled_pids = set()  # pids we've already set AXManualAccessibility on (so we settle only once)


def _load():
    """Bind the AX C functions once. Returns the function dict, or None if unavailable."""
    global _FNS
    if _FNS is None:
        _FNS = {}
        try:
            import objc
            from Foundation import NSBundle
            bundle = NSBundle.bundleWithPath_(
                "/System/Library/Frameworks/ApplicationServices.framework")
            objc.loadBundleFunctions(bundle, _FNS, [
                ("AXUIElementCreateApplication", b"@i"),
                ("AXUIElementCopyAttributeValue", b"i@@o^@"),
                ("AXUIElementCopyActionNames", b"i@o^@"),
                ("AXUIElementPerformAction", b"i@@"),
                ("AXUIElementSetAttributeValue", b"i@@@"),
            ])
        except Exception:
            _FNS = {}
    return _FNS if "AXUIElementCreateApplication" in _FNS else None


def _frontmost_pid():
    try:
        from AppKit import NSWorkspace
        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        return app.processIdentifier() if app else None
    except Exception:
        return None


def _attr(fns, el, name):
    """One AX attribute, or None. (err, value) — value valid only on err == 0 (kAXErrorSuccess)."""
    try:
        err, val = fns["AXUIElementCopyAttributeValue"](el, name, None)
        return val if err == 0 else None
    except Exception:
        return None


def _has_press(fns, el):
    try:
        err, names = fns["AXUIElementCopyActionNames"](el, None)
        return err == 0 and names is not None and "AXPress" in names
    except Exception:
        return False


def _app_root(fns):
    """The frontmost app's AX root, with web content enabled (settles once per app). Or None."""
    pid = _frontmost_pid()
    if not pid:
        return None
    try:
        app = fns["AXUIElementCreateApplication"](pid)
    except Exception:
        return None
    if pid not in _enabled_pids:
        try:  # Electron/Chromium hide their web-content AX tree until an assistive client asks
            fns["AXUIElementSetAttributeValue"](app, "AXManualAccessibility", True)
        except Exception:
            pass
        time.sleep(_SETTLE)  # first touch only — the tree needs a moment to build
        _enabled_pids.add(pid)
    return app


def _pressable(fns, el, chain):
    """`el` if it supports AXPress, else the nearest ancestor (deepest first) that does, else None.
    The matching label is often an AXStaticText with no AXPress — the row/group around it has it."""
    if _has_press(fns, el):
        return el
    for anc in reversed(chain):
        if _has_press(fns, anc):
            return anc
    return None


def click(target: str):
    """Find a control labelled `target` in the focused app and AXPress the nearest pressable element.
    Returns ("clicked", label) / ("not_found", None) / ("press_failed", label), or None if native AX
    is unavailable (caller should fall back to AppleScript). Exact label wins over a substring match."""
    fns = _load()
    if not fns:
        return None
    root = _app_root(fns)
    if root is None:
        return None
    tl = (target or "").strip().lower()
    if not tl:
        return ("not_found", None)
    found = {"exact": None, "fallback": None, "n": 0}

    def walk(el, depth, chain):
        if found["exact"] or depth > _MAX_DEPTH or found["n"] > _BUDGET:
            return
        found["n"] += 1
        nm = _attr(fns, el, "AXTitle")
        if not (isinstance(nm, str) and nm.strip()):
            nm = _attr(fns, el, "AXDescription")
        if isinstance(nm, str) and nm.strip():
            low = nm.strip().lower()
            if low == tl:
                pe = _pressable(fns, el, chain)
                if pe is not None:
                    found["exact"] = (pe, nm.strip())
                    return
            elif found["fallback"] is None and tl in low:
                pe = _pressable(fns, el, chain)
                if pe is not None:
                    found["fallback"] = (pe, nm.strip())
        kids = _attr(fns, el, "AXChildren") or []
        child_chain = chain + [el]
        for k in kids:
            walk(k, depth + 1, child_chain)
            if found["exact"]:
                return

    try:
        walk(root, 0, [])
    except Exception:
        return None
    hit = found["exact"] or found["fallback"]
    if hit is None:
        return ("not_found", None)
    press_el, label = hit
    try:
        fns["AXUIElementPerformAction"](press_el, "AXScrollToVisible")  # virtualised lists
    except Exception:
        pass
    try:
        err = fns["AXUIElementPerformAction"](press_el, "AXPress")
    except Exception:
        return ("press_failed", label)
    return ("clicked", label) if err == 0 else ("press_failed", label)


def targets(limit: int = 60):
    """Labels of on-screen clickable elements in the focused app (deduped, role-gated, capped).
    Returns a list, or None if native AX is unavailable (caller falls back to AppleScript)."""
    fns = _load()
    if not fns:
        return None
    root = _app_root(fns)
    if root is None:
        return None
    out, seen, n = [], set(), [0]

    def walk(el, depth):
        if len(out) >= limit or depth > _MAX_DEPTH or n[0] > _BUDGET:
            return
        n[0] += 1
        if _attr(fns, el, "AXRole") in _CLICKABLE_ROLES:
            nm = _attr(fns, el, "AXTitle")
            if not (isinstance(nm, str) and nm.strip()):
                nm = _attr(fns, el, "AXDescription")
            if isinstance(nm, str) and nm.strip() and len(nm.strip()) < 60 and nm.strip() not in seen:
                seen.add(nm.strip())
                out.append(nm.strip())
        for k in (_attr(fns, el, "AXChildren") or []):
            if len(out) >= limit:
                break
            walk(k, depth + 1)

    try:
        walk(root, 0)
    except Exception:
        return None
    return out
