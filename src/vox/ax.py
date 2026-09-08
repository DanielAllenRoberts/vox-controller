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

import contextlib
import time

# Interactive-ish roles whose label is worth listing as a click target (matches the old AppleScript
# enumeration). The click SEARCH below is broader — it matches a label on any node — but the LISTING
# stays role-gated so the fuzzy-pick list isn't flooded with structural text.
# Text-input roles — a message box / search field you'd click into to start typing. Listed even when
# unlabelled (empty boxes have no title) with a "text box" fallback label, so they still get a badge.
_TEXT_INPUT_ROLES = {"AXTextField", "AXTextArea", "AXComboBox", "AXSearchField"}

_CLICKABLE_ROLES = {
    "AXButton", "AXLink", "AXMenuItem", "AXMenuBarItem", "AXCheckBox", "AXRadioButton",
    "AXTabButton", "AXPopUpButton", "AXStaticText", "AXRow", "AXCell",
    "AXHeading", "AXImage", "AXDisclosureTriangle",
} | _TEXT_INPUT_ROLES

_BUDGET = 9000       # node-visit safety cap (native is fast; this is just a runaway guard)
_MAX_DEPTH = 45
_SETTLE = 0.4        # seconds — let Electron build its web-content AX tree on FIRST touch per app only

_FNS = None          # lazily-bound C functions ({} once load is attempted; None until then)
_enabled_pids = set()  # pids we've already set AXManualAccessibility on (so we settle only once)
# Most elements we've ever enumerated for a pid. Chromium/Electron build their web-content AX tree on
# demand and TEAR IT BACK DOWN again; because we only assert AXManualAccessibility once per pid, a
# later walk can silently come back with just the native window chrome — which all lives in the
# top-left, so the overlay looks like it's piling badges in the corner. Comparing against the best
# we've seen for that app is how we notice the tree collapsed and re-assert. (Restarting the daemon
# "fixed" it precisely because a fresh process re-enables everything.)
_best_count: dict[int, int] = {}
_THIN_ABSOLUTE = 20  # below this the tree is almost certainly chrome-only
# pids we've already spent one cold re-assert on (no healthy baseline to compare against). Without
# this, an app that really does have <20 clickables would re-settle on every single enumeration.
_cold_retried: set[int] = set()
# pids whose window-less retry we've already paid for. Cleared as soon as the app exposes a window
# again, so this bounds the cost of a permanently-broken app without disarming real recoveries.
_blind_spent: set[int] = set()
_RETRY_SETTLE = 1.5  # Electron rebuilds its whole web-content tree on a re-assert; _SETTLE is too
                     # short for that, and reading early looks the same as reading nothing.


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


# --- which app are we talking to? (issue O18) ---------------------------------------------------
# Every entry point below used to ask "who is frontmost?" at the moment it ran. That's the wrong
# question: what the user meant is the app they were LOOKING AT when they spoke, and the press lands
# anywhere from an AX walk (~0.1-1.5 s) to an LLM round-trip (seconds) later. Anything that moves
# focus in that window — the user clicking, a remote-desktop session, a notification — silently
# redirected the click into a different application. Pinning fixes the target once, up front, so the
# whole read-find-press sequence talks to one app.
_PIN: tuple[int, str] | None = None   # (pid, app name) this utterance is aimed at, or None


def frontmost():
    """(pid, name) of the frontmost app per NSWorkspace, or None.

    Instant, and NOT to be trusted on its own — see ``frontmost_verified()``. Kept only as the
    last-resort fallback for when System Events can't answer at all."""
    try:
        from AppKit import NSWorkspace
        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        return (app.processIdentifier(), app.localizedName() or "") if app else None
    except Exception:
        return None


def frontmost_verified():
    """(pid, name) of the frontmost app, asked live rather than read from a cache. None on failure.

    ``NSWorkspace.frontmostApplication()`` is a KVO property refreshed by main-run-loop processing,
    and the Vox daemon deliberately runs no ``NSApplication`` run loop (see ``overlay.py`` /
    ``bubble.py``). Measured in a long-lived run-loop-less process, it stuck on one stale app for
    five and a half minutes while a freshly-spawned process read the truth every time. Every AX call
    below resolves its target through a pid, so a frozen answer doesn't fail — it quietly reads and
    presses a different application (issue O18). ~150 ms; correctness is worth it."""
    try:
        from vox import actions
        return actions.frontmost_app_pid()
    except Exception:
        return None


def pinned():
    """The (pid, name) every AX call is currently aimed at, or None (= whatever is frontmost)."""
    return _PIN


@contextlib.contextmanager
def pinned_to(pid, name: str = ""):
    """Aim every AX read and press inside this block at ONE app, instead of re-resolving "frontmost"
    on each call. Nested pins are ignored — the OUTERMOST wins, because it's the one closest to the
    utterance. A falsy pid is a no-op, so callers that can't resolve a target behave exactly as before."""
    global _PIN
    if _PIN is not None or not pid:
        yield _PIN
        return
    _PIN = (int(pid), name or "")
    try:
        yield _PIN
    finally:
        _PIN = None


def _target_pid():
    """The pid this utterance's AX calls should talk to: the pinned app, else the live frontmost."""
    return _PIN[0] if _PIN else _frontmost_pid()


def _focus_moved(pid=None):
    """Name of the app in front NOW when it isn't ``pid`` (default: the pinned app) — else None.

    Called immediately before a press, and deliberately through ``frontmost_verified()``: the whole
    point of the guard is to catch a "frontmost" our fast cached answer got wrong.

    When it fires we REFUSE the press rather than delivering it anyway. The press is a synthesized
    mouse click at screen coordinates, and those coordinates belong to a window that is no longer on
    top — the click would land on whichever app IS on top, at a spot nobody chose. The AXPress
    fallback would at least hit the right control, but silently, inside an app the user has just
    navigated away from: a hidden action on stale intent. (``input.py`` has background event delivery
    — ``input_background_delivery``, idea #61 — that could aim a press at a specific window, but it's
    off by default and untested, so it isn't an option here.) A click that didn't happen is
    recoverable and reported; a click on the wrong thing is neither."""
    want = pid if pid is not None else (_PIN[0] if _PIN else None)
    if want is None:
        return None
    now = frontmost_verified()
    if now is None or now[0] == want:
        return None  # still ours, or we can't tell → don't block a click the user asked for
    return now[1] or "another app"


def _frontmost_pid():
    """pid of the frontmost app — the fallback every UNPINNED AX call resolves its root through, so
    it has to be the verified answer, not the cached one (issue O18)."""
    p = frontmost_verified() or frontmost()
    return p[0] if p else None


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


def _label_of(fns, el, role):
    """A display label for a listable element: title → description → placeholder, else "text box" for
    an unlabelled input (so an empty Slack/YouTube box still gets a badge). None if nothing usable."""
    for attr in ("AXTitle", "AXDescription", "AXPlaceholderValue"):
        nm = _attr(fns, el, attr)
        if isinstance(nm, str) and nm.strip():
            return nm.strip()
    return "text box" if role in _TEXT_INPUT_ROLES else None


def _app_root(fns, settle: float | None = None):
    """The target app's AX root, with web content enabled (settles once per app). Or None.

    The target is the PINNED app when one is pinned (see ``pinned_to``), else whatever is frontmost
    right now — which is what this used to always do, and what sent "click on settings" to Cursor
    while the user was looking at Arc (issue O18).

    ``settle`` overrides the wait after asserting AXManualAccessibility. The retry path passes a
    longer one: Electron rebuilds its whole web-content tree from scratch, and 0.4s is enough for a
    first touch on a warm app but not for a rebuild — coming back too early reads the half-built
    tree and looks identical to "there's nothing here"."""
    pid = _target_pid()
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
        budget = _SETTLE if settle is None else settle
        # POLL, don't sleep the whole budget. The wait exists because the tree needs a moment to
        # build, not because it needs a fixed amount of time — most apps are ready far sooner than
        # the worst case, and a flat sleep charges every app the slowest app's price. Measured:
        # "show clickable" went 1s → 3s when the budget went to 1.5s, for no benefit once the tree
        # was already up. Polling returns as soon as there's something to read.
        deadline = time.monotonic() + budget
        while time.monotonic() < deadline:
            time.sleep(0.05)
            if _attr(fns, app, "AXWindows"):
                break
        _enabled_pids.add(pid)
    return app


def _has_windows(fns, app) -> bool:
    """Does this app expose ANY AX window? A frontmost app that reports none has a collapsed tree —
    everything we can still read is the menu bar, which lives on the application element itself.

    This is the difference between "an app with few controls" and "an app whose content is missing",
    which a raw element count can't tell apart. Obsidian sitting at exactly 9 elements — File, Edit,
    View… — read as a stable, healthy little tree to the count-based check, so it was never retried
    and the click-by-vision fallback kept picking menu-bar badges for sidebar targets."""
    try:
        return bool(_attr(fns, app, "AXWindows"))
    except Exception:
        return True  # unknown → don't trigger a retry on a guess


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
    """Find a control labelled `target` in the target app and AXPress the nearest pressable element.
    Returns ("clicked", label) / ("not_found", None) / ("press_failed", label) /
    ("focus_changed", app_now), or None if native AX is unavailable (caller should fall back to
    AppleScript). Exact label wins over a substring match.

    The app searched is the pinned one when a caller has pinned it (``pinned_to``), and the press is
    refused if that app stopped being frontmost while we were walking its tree — see ``_focus_moved``
    for why refusing beats pressing anyway."""
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
                    found["exact"] = (pe, el, nm.strip())  # keep the labelled el for its frame
                    return
            elif found["fallback"] is None and tl in low:
                pe = _pressable(fns, el, chain)
                if pe is not None:
                    found["fallback"] = (pe, el, nm.strip())
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
    press_el, el, label = hit
    moved = _focus_moved()
    if moved:
        return ("focus_changed", moved)
    try:
        fns["AXUIElementPerformAction"](press_el, "AXScrollToVisible")  # virtualised lists
    except Exception:
        pass
    # Prefer a real click at the element's centre — AXPress reports success on many web/Electron
    # controls (Slack rows, buttons) yet only highlights/hovers. Read the frame AFTER scrolling so
    # it's current, then synthesize a click there; AXPress stays as the native fallback.
    frame = _frame(fns, el)
    if frame is not None:
        try:
            x, y, w, h = frame
            _click_at(x + w / 2.0, y + h / 2.0)
            return ("clicked", label)
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
        role = _attr(fns, el, "AXRole")
        if role in _CLICKABLE_ROLES:
            nm = _label_of(fns, el, role)
            if nm and len(nm) < 60 and nm not in seen:
                seen.add(nm)
                out.append(nm)
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
# …and WHICH app they were read from. The badges the user is answering ("click 14") were drawn over
# that app's window, so a click on a cached frame is only meaningful while that app is still in
# front — the gap here is the longest in Vox (the user has to read the badges and speak a number).
_LAST_TARGETS_PID: int | None = None


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


def targets_with_frames(limit: int = 400, _retry: bool = True, _settle: float | None = None):
    """Clickable elements in the focused app WITH their on-screen frames, for a numbered overlay
    (idea #52). Returns a list of ``{index, label, role, x, y, w, h}`` (frame in AX top-left-origin
    screen coords), or None if native AX is unavailable. Also caches each element's pressable ref so
    ``click_index()`` can press it. Role-gated + deduped by (label, rounded position) like ``targets()``.

    ``limit`` has to clear a whole app's clickables, not just the first screenful: the walk is
    depth-first, so a low cap drains into whichever subtree comes first — in Cursor/Slack that's the
    left sidebar (file tree / channel list), which alone exceeded the old cap of 80 and left the
    entire content area unbadged (badges looked like they'd piled up in the top-left). A busy Slack
    measured 227 elements, so 400 leaves real headroom; the walk costs ~70 ms whether it's capped or
    not (``_BUDGET``'s node-visit cap dominates) and still guards a runaway tree."""
    global _LAST_TARGETS, _LAST_TARGETS_PID
    fns = _load()
    if not fns:
        return None
    root = _app_root(fns, _settle)
    if root is None:
        return None
    out, cache, seen, n = [], [], set(), [0]

    def walk(el, depth, chain):
        if len(out) >= limit or depth > _MAX_DEPTH or n[0] > _BUDGET:
            return
        n[0] += 1
        role = _attr(fns, el, "AXRole")
        if role in _CLICKABLE_ROLES:
            nm = _label_of(fns, el, role)
            if nm and len(nm) < 60:
                fr = _frame(fns, el)
                if fr is not None:
                    key = (nm, round(fr[0]), round(fr[1]))  # same label at same spot = dupe
                    if key not in seen:
                        seen.add(key)
                        press = _pressable(fns, el, chain)
                        if press is not None:  # only list things we can actually click
                            idx = len(out)
                            out.append({"index": idx, "label": nm, "role": role,
                                        "x": fr[0], "y": fr[1], "w": fr[2], "h": fr[3]})
                            cache.append((press, nm, fr))  # keep the frame for a real click
        child_chain = chain + [el]
        for k in (_attr(fns, el, "AXChildren") or []):
            if len(out) >= limit:
                break
            walk(k, depth + 1, child_chain)

    try:
        walk(root, 0, [])
    except Exception:
        return None

    # Did this app's web-content tree collapse out from under us? Re-assert AXManualAccessibility
    # (dropping the once-per-pid memo) and walk once more. There are TWO ways to be too thin to be
    # real, and the second one is why "show clickables" could stay broken for a whole session:
    #
    #   RELATIVE — we've seen far more from this pid before, so the tree collapsed since.
    #   ABSOLUTE — we've never seen a healthy tree for this pid AT ALL. The relative test can't catch
    #     this: `best` is 0, so `best and …` short-circuits and no retry ever fires. An app whose
    #     tree happened to be down the FIRST time the daemon touched it (Electron builds web content
    #     on demand — Obsidian and Slack both enumerate zero windows in that state) then stayed
    #     un-enumerable until the daemon was restarted, which is what made this look intermittent.
    #
    # The absolute arm is tried at most ONCE per pid: an app that genuinely has only a handful of
    # clickable elements must not pay the _SETTLE wait on every single enumeration.
    pid = _target_pid()
    if pid:
        best = _best_count.get(pid, 0)
        thin = len(out) < _THIN_ABSOLUTE
        # NO WINDOWS is the decisive tell and outranks the count heuristics: a frontmost app that
        # exposes zero AX windows is definitively broken, not merely sparse, so this arm re-arms
        # every walk rather than being spent once. The count arms stay for the cases where windows
        # ARE exposed but the web content inside them collapsed.
        blind = not _has_windows(fns, root)
        if not blind:
            _blind_spent.discard(pid)  # it recovered — re-arm the blind retry for next time
        collapsed = (blind and pid not in _blind_spent) or \
                    ((thin and len(out) < best // 2) if best
                     else (thin and pid not in _cold_retried))
        if _retry and collapsed:
            if blind:
                # Pay the rebuild wait once per broken episode, not on every walk: an app that
                # stays window-less would otherwise add _RETRY_SETTLE to every enumeration and
                # still come back empty. Cleared above the moment windows reappear.
                _blind_spent.add(pid)
            elif not best:
                _cold_retried.add(pid)   # count-based cold guess: spend it once, never repeat
            _enabled_pids.discard(pid)
            return targets_with_frames(limit, _retry=False, _settle=_RETRY_SETTLE)
        _best_count[pid] = max(best, len(out))

    _LAST_TARGETS, _LAST_TARGETS_PID = cache, pid
    return out


def _click_at(cx: float, cy: float) -> None:
    """Synthesize a real left-click at global screen point (cx, cy). CGEvent and AX share the same
    top-left-origin global coordinate space, so the AX frame needs no flip. Move → down → up."""
    import Quartz
    pt = Quartz.CGPointMake(float(cx), float(cy))
    for kind in (Quartz.kCGEventMouseMoved, Quartz.kCGEventLeftMouseDown, Quartz.kCGEventLeftMouseUp):
        ev = Quartz.CGEventCreateMouseEvent(None, kind, pt, Quartz.kCGMouseButtonLeft)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)


def click_index(i: int):
    """Click the i-th element from the last ``targets_with_frames()`` call (the "click 14" step).
    Prefers a REAL mouse click at the element's centre — ``AXPress`` reports success on many
    web/Electron controls (Slack sidebar, buttons) yet does nothing, whereas a synthesized click at
    the exact coords we already have actually works. Falls back to AXPress (native controls, no cursor
    move). Returns ("clicked", label) / ("press_failed", label) / ("focus_changed", app_now), or
    None if the index is stale.

    The frames are cached from the enumeration that drew the badges, so they only mean anything
    while THAT app is still in front — hence the same guard as ``click()`` (issue O18)."""
    if not (isinstance(i, int) and 0 <= i < len(_LAST_TARGETS)):
        return None
    press_el, label, frame = _LAST_TARGETS[i]
    moved = _focus_moved(_LAST_TARGETS_PID)
    if moved:
        return ("focus_changed", moved)
    fns = _load()
    if fns is not None:  # bring virtualised/scrolled targets into view before clicking
        try:
            fns["AXUIElementPerformAction"](press_el, "AXScrollToVisible")
        except Exception:
            pass
    if frame is not None:
        try:
            x, y, w, h = frame
            _click_at(x + w / 2.0, y + h / 2.0)
            return ("clicked", label)
        except Exception:
            pass  # coordinate click failed → fall back to AXPress
    if fns is None:
        return None
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


# --- value setting + frame lookup (idea #61) ---------------------------------------------------
# `set_value` exists because driving a control by *clicking* it is often several steps: a popup
# needs a press, a menu walk and a second press; a slider needs a drag with no way to know where
# 30% is. Setting the AX value says what you mean in one call, and it can't miss by a few pixels.

# Roles whose value is worth setting directly. AXPopUpButton/AXMenuButton go down the menu path
# below instead — setting their AXValue is accepted and silently ignored by most apps.
_SETTABLE = ("AXSlider", "AXTextField", "AXTextArea", "AXCheckBox", "AXRadioButton",
             "AXIncrementor", "AXComboBox")


def _find_labelled(fns, root, target: str, roles=None):
    """Walk for an element labelled `target` (exact wins over substring), optionally restricted to
    `roles`. Returns (element, label, role) or None. Separate from `click`'s walk because that one
    resolves to the nearest *pressable ancestor* — here we want the labelled element itself."""
    tl = (target or "").strip().lower()
    if not tl:
        return None
    found = {"exact": None, "fallback": None, "n": 0}

    def walk(el, depth):
        if found["exact"] or depth > _MAX_DEPTH or found["n"] > _BUDGET:
            return
        found["n"] += 1
        role = _attr(fns, el, "AXRole") or ""
        if roles is None or role in roles:
            nm = _attr(fns, el, "AXTitle")
            if not (isinstance(nm, str) and nm.strip()):
                nm = _attr(fns, el, "AXDescription")
            if isinstance(nm, str) and nm.strip():
                low = nm.strip().lower()
                if low == tl:
                    found["exact"] = (el, nm.strip(), role)
                    return
                if found["fallback"] is None and tl in low:
                    found["fallback"] = (el, nm.strip(), role)
        for k in (_attr(fns, el, "AXChildren") or []):
            walk(k, depth + 1)
            if found["exact"]:
                return

    try:
        walk(root, 0)
    except Exception:
        return None
    return found["exact"] or found["fallback"]


def _coerce(value: str, role: str):
    """Turn a spoken value into what the control expects: a number for sliders, a bool for
    checkboxes, the raw string otherwise."""
    v = str(value).strip()
    if role in ("AXCheckBox", "AXRadioButton"):
        return 1 if v.lower() in ("on", "true", "yes", "checked", "enabled", "1") else 0
    if role in ("AXSlider", "AXIncrementor"):
        try:
            return float(v.rstrip("%"))
        except ValueError:
            return v
    return v


def set_value(target: str, value: str):
    """Set the control labelled `target` to `value`. Returns ("set", label) / ("not_found", None) /
    ("set_failed", label), or None if native AX is unavailable."""
    fns = _load()
    if not fns:
        return None
    root = _app_root(fns)
    if root is None:
        return None

    hit = _find_labelled(fns, root, target, roles=_SETTABLE)
    if hit is not None:
        el, label, role = hit
        try:
            err = fns["AXUIElementSetAttributeValue"](el, "AXValue", _coerce(value, role))
        except Exception:
            return ("set_failed", label)
        return ("set", label) if err == 0 else ("set_failed", label)

    # No directly-settable control — try a popup/menu button and pick the matching option.
    hit = _find_labelled(fns, root, target, roles=("AXPopUpButton", "AXMenuButton"))
    if hit is None:
        return ("not_found", None)
    el, label, _role = hit
    return _pick_menu_option(fns, el, label, value)


def _pick_menu_option(fns, el, label: str, value: str):
    """Open a popup button and press the menu item matching `value`. This is what "select the
    matching option directly" costs on macOS: the menu doesn't exist as AX children until the
    button has been pressed."""
    import time
    try:
        if fns["AXUIElementPerformAction"](el, "AXPress") != 0:
            return ("set_failed", label)
    except Exception:
        return ("set_failed", label)
    time.sleep(0.15)  # the menu is built on press; nothing to walk until it lands

    want = str(value).strip().lower()
    try:
        for menu in (_attr(fns, el, "AXChildren") or []):
            for item in (_attr(fns, menu, "AXChildren") or []):
                nm = _attr(fns, item, "AXTitle") or ""
                if isinstance(nm, str) and nm.strip() and (
                        nm.strip().lower() == want or want in nm.strip().lower()):
                    if fns["AXUIElementPerformAction"](item, "AXPress") == 0:
                        return ("set", f"{label} → {nm.strip()}")
                    return ("set_failed", label)
    except Exception:
        pass
    try:  # nothing matched — close the menu we opened rather than leaving it hanging
        from vox import input as vox_input
        vox_input.press("escape")
    except Exception:
        pass
    return ("set_failed", label)


def frame_of(target: str):
    """Global (x, y, w, h) of the element labelled `target`, or None. Lets callers aim a right-click
    or a drag at a control they can name, reusing the same lookup `click` uses."""
    fns = _load()
    if not fns:
        return None
    root = _app_root(fns)
    if root is None:
        return None
    hit = _find_labelled(fns, root, target)
    if hit is None:
        return None
    el, label, _role = hit
    try:
        fns["AXUIElementPerformAction"](el, "AXScrollToVisible")
    except Exception:
        pass
    frame = _frame(fns, el)
    return (label, frame) if frame is not None else None


def frame_index(i: int):
    """(label, frame) for the i-th element of the last ``targets_with_frames()`` call — the badge
    numbers the overlay drew. None for a stale index or an element with no frame."""
    if not (isinstance(i, int) and 0 <= i < len(_LAST_TARGETS)):
        return None
    _press_el, label, frame = _LAST_TARGETS[i]
    return (label, frame) if frame is not None else None
