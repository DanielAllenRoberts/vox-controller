"""One list of clickable targets for the focused app — AX for native, DOM for web pages.

This is the single place that decides *where* the clickable list comes from, so the overlay
(``dispatch._overlay``), the brain's label list and the set-of-marks vision fallback
(``executor._click_fuzzy`` / ``_click_by_vision``) all see the same numbering and the same elements.

Routing:
  * **Not a browser** -> ``ax.targets_with_frames()``, exactly as before. Native apps measured
    reliable (Slack 121-132, Cursor 107, Logic Pro 200) and nothing changes for them.
  * **A browser** -> the page's elements come from the DOM (``vox.webdom``), because the web AX
    tree is only intermittently present (collapsed in 20% of samples, see ``webdom``'s header).
    The browser's own chrome still comes from AX, which stayed reliable throughout — so "click
    reload" and "click 3" for a toolbar button keep working.

Clicks route back to whichever source produced the element: chrome via ``ax.click_index`` (a real
CGEvent click at the element's frame), page elements via ``webdom.click`` (dispatched inside the
page). Clicking page elements in-page is deliberate: it can't be misplaced by window-geometry
arithmetic, and it works while the AX tree is down.
"""

from vox import ax, webdom

# Learned per pid: how far the web content area sits inside the window (left, top). Measured
# whenever AXWebArea happens to be exposed, and reused when it isn't — the insets are a property of
# the window's chrome, not of the page, so a value learned while the tree was healthy stays valid
# through a collapse. Only used to place BADGES; clicks never depend on it.
_insets: dict[int, tuple[float, float]] = {}


def _frontmost():
    """(pid, app name) of the frontmost app, or (None, "")."""
    try:
        from AppKit import NSWorkspace
        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        return (app.processIdentifier(), app.localizedName() or "") if app else (None, "")
    except Exception:
        return (None, "")


def _webarea_frame(fns, root, want=None):
    """Frame of the AXWebArea holding the current page, or None if it isn't exposed.

    ``want`` is the DOM's ``(innerWidth, innerHeight)``; the web area whose size MATCHES it is the
    page. That test matters in Arc, whose own shell UI is web-based and shows up as a full-window
    AXWebArea *before* the tab's — taking the first one found put the origin at (0,0) and threw
    every badge off by the width of the sidebar. Matching on size makes this self-validating: if
    nothing matches, we return None and the caller falls back rather than trusting a wrong frame."""
    hits, n = [], [0]

    def walk(el, d):
        if n[0] > 3000 or d > 16:
            return
        n[0] += 1
        if ax._attr(fns, el, "AXRole") == "AXWebArea":
            fr = ax._frame(fns, el)
            if fr is not None:
                hits.append(fr)
        for k in (ax._attr(fns, el, "AXChildren") or []):
            walk(k, d + 1)

    try:
        walk(root, 0)
    except Exception:
        return None
    if not hits:
        return None
    if want:
        for fr in hits:
            if abs(fr[2] - want[0]) <= 4 and abs(fr[3] - want[1]) <= 4:
                return fr
        return None  # a web area exists but none is the page — don't guess
    return hits[0]


def _content_origin(pid, fns, root, geom):
    """Screen coords of the web viewport's top-left corner, for placing badges.

    The page itself reports its window's screen position (``window.screenX/screenY``), so an origin
    is always derivable from the DOM call we've already made — no AX needed, and therefore nothing
    here breaks when the web AX tree collapses. AXWebArea, when present, is authoritative and is
    also used to *learn* this window's chrome insets so a later collapse stays pixel-accurate.

    Only ever affects where badges are DRAWN; clicks go through the page and never use this."""
    sx, sy = float(geom.get("sx", 0)), float(geom.get("sy", 0))
    want = (geom.get("iw"), geom.get("ih")) if geom.get("iw") and geom.get("ih") else None

    wa = _webarea_frame(fns, root, want) if root is not None else None
    if wa is not None:
        _insets[pid] = (wa[0] - sx, wa[1] - sy)
        return (wa[0], wa[1])

    if pid in _insets:
        dx, dy = _insets[pid]
        return (sx + dx, sy + dy)

    # Never seen a healthy tree for this window: assume the horizontal chrome is a left sidebar
    # (Arc puts its tabs there; Chrome/Safari have none, so the delta is 0) and the vertical chrome
    # is all on top. Approximate at worst, and self-corrects the first time AXWebArea shows up.
    return (sx + max(0.0, float(geom.get("ow", 0)) - float(geom.get("iw", 0))),
            sy + max(0.0, float(geom.get("oh", 0)) - float(geom.get("ih", 0))))


# Roles that are real controls rather than page prose. Browser chrome (reload, back, the address
# field, tab buttons) is all in here; the bulk of a web page's AX tree — static text, headings,
# rows, cells, images, links — is not, which is what keeps the chrome pass from re-listing the page.
_CHROME_ROLES = {
    "AXButton", "AXPopUpButton", "AXMenuButton", "AXTextField", "AXSearchField",
    "AXComboBox", "AXCheckBox", "AXRadioButton", "AXTabButton", "AXToolbar",
}
_MAX_CHROME = 40  # a browser's chrome is small; this only guards a pathological tree


def _chrome_extras(page_items, limit: int):
    """AX controls the DOM list doesn't already cover — the browser's own chrome, mostly.

    Yields ``(ax_index, item)`` so the caller can route clicks back to ``ax.click_index``. Matching
    is by lowercased label, so a page button the DOM already listed is never duplicated."""
    seen = {(it["label"] or "").strip().lower() for it in page_items}
    out = []
    try:
        for i, it in enumerate(ax.targets_with_frames(limit=limit) or []):
            if len(out) >= _MAX_CHROME:
                break
            if it.get("role") not in _CHROME_ROLES:
                continue
            label = (it.get("label") or "").strip().lower()
            if not label or label in seen:
                continue
            seen.add(label)
            out.append((i, it))
    except Exception:
        return []
    return out


# The elements behind the last visible_targets() call, so click_index() knows which backend owns
# each number: ("ax", ax_index) or ("web", browser, dom_index).
_LAST: list = []


def visible_targets(limit: int = 400):
    """Clickable targets for the focused app, numbered, with screen frames. None if unavailable.

    Items are ``{index, label, role, x, y, w, h}`` exactly like ``ax.targets_with_frames`` — the
    overlay, ``overlay.annotate`` and the label list all consume this unchanged.

    On a browser the PAGE comes from the DOM and the browser's own chrome is appended from AX.

    Chrome can't be separated geometrically — in a fullscreen Arc window the web view covers the
    whole window, so the toolbar overlays the page and any rect test either swallows every toolbar
    button or floods the list with duplicates. It IS separable by label: the DOM list is definitive
    for page content, so an interactive AX element whose label isn't already in it is either chrome
    or something the DOM selector missed — both worth listing. Dropping chrome entirely was tried
    first and broke "click the refresh button", which needs Arc's reload button."""
    global _LAST
    pid, app = _frontmost()
    if app in webdom.BROWSERS:
        page = webdom.elements(app, limit=limit)
        if page and page.get("items"):
            fns = ax._load()
            root = fns["AXUIElementCreateApplication"](pid) if fns else None
            ox, oy = _content_origin(pid, fns, root, page.get("geom") or {})
            out = [{"index": i, "label": it["l"], "role": it.get("r") or it["t"],
                    "x": ox + it["x"], "y": oy + it["y"], "w": it["w"], "h": it["h"]}
                   for i, it in enumerate(page["items"])]
            owners = [("web", app, i) for i in range(len(out))]
            for i, it in _chrome_extras(out, limit=limit):
                out.append({**it, "index": len(out)})
                owners.append(("ax", i))
            _LAST = owners
            return out
        # JS blocked, or no page (a browser's own new-tab/settings screen) — AX is all we have.

    items = ax.targets_with_frames(limit=limit)
    _LAST = [("ax", i) for i in range(len(items))] if items else []
    return items


def click_label(target: str):
    """Click a page element by what it's called, when a browser is focused. ``("clicked", label)``,
    or None to let the caller fall back to the AX path (which still owns browser chrome).

    Needed because the by-label click (``actions.click_element``) searches the AX tree: on a page
    whose web AX tree has collapsed there is nothing to find, even though the element is plainly
    there in the DOM. Matching happens here rather than in JS so it stays one implementation, and
    the click then goes through the same in-page path as a numbered click."""
    _, app = _frontmost()
    if app not in webdom.BROWSERS:
        return None
    t = (target or "").strip().lower()
    if not t:
        return None
    page = webdom.elements(app)
    if not page or not page.get("items"):
        return None
    items = page["items"]
    hit = next((i for i, it in enumerate(items) if it["l"].strip().lower() == t), None)
    if hit is None:  # substring, shortest label wins — the tightest match, not the first on the page
        cands = [i for i, it in enumerate(items) if t in it["l"].strip().lower()]
        hit = min(cands, key=lambda i: len(items[i]["l"])) if cands else None
    if hit is None:
        return None
    label = webdom.click(app, hit)
    return ("clicked", label or items[hit]["l"]) if label else None


def click_index(i: int):
    """Click target `i` (0-based) from the last ``visible_targets()``. Returns
    ``("clicked", label)`` / ``("press_failed", label)``, or None for a stale index."""
    if not (isinstance(i, int) and 0 <= i < len(_LAST)):
        return None
    owner = _LAST[i]
    if owner[0] == "ax":
        return ax.click_index(owner[1])
    label = webdom.click(owner[1], owner[2])
    return ("clicked", label) if label else ("press_failed", None)
