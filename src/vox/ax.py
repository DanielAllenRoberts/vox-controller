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
                # Boolean AXValueGetValue(AXValueRef, AXValueType, void* out). Boolean=C(uchar),
                # AXValueType=I(uint32), out=pointer to a 2-double struct. CGPoint and CGSize share
                # that {dd} layout, so one binding extracts both (fields read as .x/.y either way).
                ("AXValueGetValue", b"C@Io^{CGPoint=dd}"),
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


# --- numbered-overlay support (idea #52): clickable elements WITH screen frames ------------------

_AXVALUE_CGPOINT = 1  # kAXValueCGPointType
_AXVALUE_CGSIZE = 2   # kAXValueCGSizeType

# The pressable element refs from the last targets_with_frames() call, indexed to match the returned
# list — so click_index(n) can AXPress element n without re-walking (the "say a number" step).
_LAST_TARGETS: list = []


def _axpair(fns, axval, type_const):
    """Extract the two doubles from an AXPosition/AXSize AXValue, or None. (Both are 2-double
    structs; AXValueGetValue fills a CGPoint whose .x/.y hold x,y or w,h.)"""
    if axval is None:
        return None
    try:
        ok, pt = fns["AXValueGetValue"](axval, type_const, None)
        return (float(pt.x), float(pt.y)) if ok else None
    except Exception:
        return None


def _frame(fns, el):
    """(x, y, w, h) screen frame of `el` in AX coordinates (top-left origin), or None. A zero-size
    element (offscreen / not laid out) returns None so it never gets a badge."""
    pos = _axpair(fns, _attr(fns, el, "AXPosition"), _AXVALUE_CGPOINT)
    size = _axpair(fns, _attr(fns, el, "AXSize"), _AXVALUE_CGSIZE)
    if pos is None or size is None:
        return None
    x, y = pos
    w, h = size
    if w <= 0 or h <= 0:
        return None
    return (x, y, w, h)


def targets_with_frames(limit: int = 80):
    """Clickable elements in the focused app WITH their on-screen frames, for a numbered overlay
    (idea #52). Returns a list of ``{index, label, role, x, y, w, h}`` (frame in AX top-left-origin
    screen coords), or None if native AX is unavailable. Also caches each element's pressable ref so
    ``click_index()`` can press it. Role-gated + deduped by (label, rounded position) like ``targets()``."""
    global _LAST_TARGETS
    fns = _load()
    if not fns:
        return None
    root = _app_root(fns)
    if root is None:
        return None
    out, cache, seen, n = [], [], set(), [0]

    def walk(el, depth, chain):
        if len(out) >= limit or depth > _MAX_DEPTH or n[0] > _BUDGET:
            return
        n[0] += 1
        if _attr(fns, el, "AXRole") in _CLICKABLE_ROLES:
            nm = _attr(fns, el, "AXTitle")
            if not (isinstance(nm, str) and nm.strip()):
                nm = _attr(fns, el, "AXDescription")
            if isinstance(nm, str) and nm.strip() and len(nm.strip()) < 60:
                fr = _frame(fns, el)
                if fr is not None:
                    key = (nm.strip(), round(fr[0]), round(fr[1]))  # same label at same spot = dupe
                    if key not in seen:
                        seen.add(key)
                        press = _pressable(fns, el, chain)
                        if press is not None:  # only list things we can actually click
                            idx = len(out)
                            out.append({"index": idx, "label": nm.strip(),
                                        "role": _attr(fns, el, "AXRole"),
                                        "x": fr[0], "y": fr[1], "w": fr[2], "h": fr[3]})
                            cache.append((press, nm.strip()))
        child_chain = chain + [el]
        for k in (_attr(fns, el, "AXChildren") or []):
            if len(out) >= limit:
                break
            walk(k, depth + 1, child_chain)

    try:
        walk(root, 0, [])
    except Exception:
        return None
    _LAST_TARGETS = cache
    return out


def click_index(i: int):
    """AXPress the i-th element from the last ``targets_with_frames()`` call (the "click 14" step).
    Returns ("clicked", label) / ("press_failed", label), or None if the index is stale/invalid."""
    fns = _load()
    if not fns or not (isinstance(i, int) and 0 <= i < len(_LAST_TARGETS)):
        return None
    press_el, label = _LAST_TARGETS[i]
    try:
        fns["AXUIElementPerformAction"](press_el, "AXScrollToVisible")
    except Exception:
        pass
    try:
        err = fns["AXUIElementPerformAction"](press_el, "AXPress")
    except Exception:
        return ("press_failed", label)
    return ("clicked", label) if err == 0 else ("press_failed", label)


# --- CLI: try the numbered-click engine before it's wired to voice/overlay (idea #52) ------------
# `--list` prints the clickable elements of whatever app is frontmost after `--delay` seconds (so
# you can focus a real app first); `--click N` re-enumerates and presses the N-th (1-based, matching
# how the overlay will number them). Read-only for --list; --click actually presses.

if __name__ == "__main__":
    import argparse
    import time as _time

    ap = argparse.ArgumentParser(description="Vox AX — numbered clickable-element probe (idea #52)")
    ap.add_argument("--list", action="store_true", help="list clickable elements (read-only)")
    ap.add_argument("--click", type=int, metavar="N", help="press the N-th element (1-based)")
    ap.add_argument("--delay", type=float, default=3.0,
                    help="seconds to wait first, so you can focus the target app (default 3)")
    ap.add_argument("--limit", type=int, default=80, help="max elements (default 80)")
    _a = ap.parse_args()

    if _a.delay > 0:
        print(f"Focus the app you want to test… reading in {_a.delay:.0f}s")
        _time.sleep(_a.delay)

    _t = targets_with_frames(limit=_a.limit)
    if _t is None:
        print("native AX unavailable (permissions? not macOS?)")
        raise SystemExit(1)
    if not _t:
        print("no clickable elements found in the frontmost app")
        raise SystemExit(0)

    for _e in _t:
        print(f"  [{_e['index'] + 1:2}] {_e['role']:12} {_e['label'][:44]:44} "
              f"@ ({_e['x']:.0f},{_e['y']:.0f}) {_e['w']:.0f}x{_e['h']:.0f}")

    if _a.click is not None:
        _res = click_index(_a.click - 1)  # 1-based on the CLI → 0-based index
        print(f"\nclick {_a.click} → {_res}")
    else:
        print(f"\n{len(_t)} elements.  Press one with:  "
              f"python -m vox.ax --click <N> --delay 3")
