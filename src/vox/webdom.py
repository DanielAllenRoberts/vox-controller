"""Browser DOM bridge — read a web page's interactive elements straight from the page (idea #37).

Why this exists: on a web page the macOS AX tree is *intermittently* unavailable. Chromium builds
its web-content AX tree on demand and tears it back down; measured on Arc over 40 samples (2026-08-03)
it was **collapsed 20% of the time**, in runs of 25-35s, once never recovering inside the observation
window. Collapsed means ``AXWebArea`` is gone and the whole page reads as ~12 elements of browser
chrome — which is exactly the 8/13-target ``show clickable`` results in ``vox.log``. Re-asserting
``AXManualAccessibility`` and re-walking (``ax.targets_with_frames``'s existing rescue) does *not*
bring it back, so this is not a settle-time problem.

The DOM was correct on all 40 of those samples, including every one where AX had collapsed. So for
page content we ask the page directly, via the browser's AppleScript ``execute javascript`` — no CDP,
no extension, no new dependency, and it works on a window that isn't frontmost.

**Setup caveat:** the browser must allow JavaScript from Apple Events. Arc allows it out of the box;
Chrome and Safari need it enabled once (View/Develop -> Allow JavaScript from Apple Events),
otherwise the call fails (Chrome reports AppleEvent timeout -1712). ``available()`` reports this so
callers can fall back to AX rather than hang.

Scope: page content only. The browser's own chrome (tabs, sidebar, toolbar) stays on the AX path,
which measured reliable even while the web tree was collapsed. ``vox.targets`` merges the two.
"""

import json
import subprocess

# Browsers we can drive this way. Chromium-family + Safari share the `active tab of front window`
# shape; Safari's verb differs (`do JavaScript`), handled in _script().
_CHROMIUM = {"Arc", "Google Chrome", "Brave Browser", "Microsoft Edge", "Chromium"}
BROWSERS = _CHROMIUM | {"Safari"}

# osascript hard cap. Kept SHORT because this runs in the voice loop: a page whose JS is blocked
# (measured once at 8.0s) would otherwise stall Vox for that whole time. Losing page targets and
# falling back to AX is far better than freezing; the healthy call measures ~110 ms.
_TIMEOUT = 2.5

# One JS payload enumerates the page. Elements are stashed on `window.__vox` so a later click can
# address element N without re-querying (the list the badges were drawn from is the list we click).
# Filters mirror what a user can actually click: sized, not hidden, and inside the viewport — the
# viewport test is the important one, since the DOM (unlike a native app's AX tree) also contains
# everything scrolled off the page.
_ENUMERATE = r"""
(function(){
  var SEL = 'a[href],button,input:not([type=hidden]),select,textarea,summary,[role=button],'
          + '[role=link],[role=tab],[role=menuitem],[role=checkbox],[role=radio],[role=switch],'
          + '[role=option],[onclick],[contenteditable=true],[tabindex]:not([tabindex="-1"])';
  var vw = window.innerWidth, vh = window.innerHeight;
  var out = [], keep = [];
  var els = document.querySelectorAll(SEL);
  for (var i = 0; i < els.length && out.length < LIMIT; i++) {
    var e = els[i], r = e.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) continue;
    if (r.bottom <= 0 || r.right <= 0 || r.top >= vh || r.left >= vw) continue;
    var st = window.getComputedStyle(e);
    if (st.visibility === 'hidden' || st.display === 'none' || st.opacity === '0') continue;
    var lab = (e.getAttribute('aria-label') || e.innerText || e.value ||
               e.getAttribute('title') || e.getAttribute('placeholder') ||
               e.getAttribute('alt') || '').trim().replace(/\s+/g, ' ');
    if (!lab && e.tagName === 'INPUT') lab = 'text box';
    if (!lab) continue;
    keep.push(e);
    out.push({l: lab.slice(0, 60), t: e.tagName.toLowerCase(),
              r: e.getAttribute('role') || '',
              x: Math.round(r.left), y: Math.round(r.top),
              w: Math.round(r.width), h: Math.round(r.height)});
  }
  window.__vox = keep;
  return JSON.stringify({items: out, geom: {
    sx: window.screenX, sy: window.screenY,
    ow: window.outerWidth, oh: window.outerHeight,
    iw: window.innerWidth, ih: window.innerHeight}});
})()
"""

# Click element N of the last enumeration. Prefers a real MouseEvent sequence over el.click(): some
# widgets listen for mousedown/mouseup rather than click, and dispatching all three covers both.
_CLICK = r"""
(function(){
  var a = window.__vox;
  if (!a || !a[IDX]) return JSON.stringify({ok: false, why: 'stale'});
  var e = a[IDX];
  var lab = (e.getAttribute('aria-label') || e.innerText || e.value || '').trim().slice(0, 60);
  try { e.scrollIntoView({block: 'center', behavior: 'instant'}); } catch (err) {}
  var r = e.getBoundingClientRect();
  var cx = r.left + r.width / 2, cy = r.top + r.height / 2;
  var opts = {bubbles: true, cancelable: true, view: window, clientX: cx, clientY: cy};
  try {
    e.dispatchEvent(new MouseEvent('mousedown', opts));
    e.dispatchEvent(new MouseEvent('mouseup', opts));
    e.click();
  } catch (err) {
    return JSON.stringify({ok: false, why: String(err).slice(0, 80)});
  }
  return JSON.stringify({ok: true, label: lab});
})()
"""


def _script(browser: str, js: str) -> str:
    """AppleScript that runs `js` in the browser's active tab. Safari uses a different verb."""
    esc = js.replace("\\", "\\\\").replace('"', '\\"')
    if browser == "Safari":
        return (f'tell application "Safari" to do JavaScript "{esc}" '
                f'in current tab of front window')
    return (f'tell application "{browser}" to tell active tab of front window to '
            f'execute javascript "{esc}"')


def _run(browser: str, js: str):
    """Run `js` in the active tab and return its parsed JSON result, or None on any failure.

    ``execute javascript`` hands back the JS return value as a *string*, so the JSON arrives
    double-encoded — decoded twice here. Never raises."""
    try:
        p = subprocess.run(["osascript", "-"], input=_script(browser, js),
                           capture_output=True, text=True, timeout=_TIMEOUT)
    except Exception:
        return None
    if p.returncode != 0:
        return None
    raw = (p.stdout or "").strip()
    if not raw:
        return None
    try:
        val = json.loads(raw)
        return json.loads(val) if isinstance(val, str) else val
    except Exception:
        return None


def available(browser: str) -> bool:
    """Can we run JavaScript in this browser's active tab? False when the browser forbids
    Apple-Events JS (the once-off Developer-menu setting) — the caller should fall back to AX."""
    return browser in BROWSERS and _run(browser, "(function(){return JSON.stringify(1)})()") == 1


def elements(browser: str, limit: int = 300):
    """The page's clickable elements, in VIEWPORT coordinates, or None if unavailable.

    Returns ``{"items": [{label, role, x, y, w, h}, …], "geom": {…}}``. Coordinates are relative to
    the page viewport; ``vox.targets`` maps them to screen coordinates for badge drawing. The order
    is document order, and it is the order a later ``click(browser, i)`` addresses."""
    got = _run(browser, _ENUMERATE.replace("LIMIT", str(int(limit))))
    if not isinstance(got, dict) or "items" not in got:
        return None
    return got


def click(browser: str, index: int):
    """Click element `index` from the last ``elements()`` call, in the page itself.

    Returns the clicked element's label, or None if the page navigated since (the stashed list is
    gone) or the click failed. Clicking in-page rather than by coordinate means no window-geometry
    maths can misplace it, and it keeps working while the AX tree is collapsed."""
    got = _run(browser, _CLICK.replace("IDX", str(int(index))))
    if not isinstance(got, dict) or not got.get("ok"):
        return None
    return got.get("label") or "element"
