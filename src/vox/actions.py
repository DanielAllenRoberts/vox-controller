"""Deterministic command actions for CONTROL mode.

open apps · go to apps/known sites · web search · switch browser tabs (by name, index,
or relative) · switch app windows (by name, index, or next) · toggle Arc's sidebar.
Unknown input hands off to the assistant (no guessing).
"""

import difflib
import re
import subprocess
import urllib.parse

from vox.config import CONFIG

# Spoken name -> actual macOS app name, where they differ.
_APP_ALIASES = {
    "chrome": "Google Chrome", "google chrome": "Google Chrome",
    "vs code": "Visual Studio Code", "vscode": "Visual Studio Code", "code": "Visual Studio Code",
}

# Known spoken site name -> URL. Navigation only opens sites it knows (no guessing).
_SITE_ALIASES = {
    "github": "https://github.com", "gmail": "https://mail.google.com",
    "google": "https://google.com", "youtube": "https://youtube.com",
    "twitter": "https://x.com", "x": "https://x.com", "reddit": "https://reddit.com",
    "hacker news": "https://news.ycombinator.com", "chatgpt": "https://chatgpt.com",
    "claude": "https://claude.ai", "gemini": "https://gemini.google.com",
    "netflix": "https://netflix.com", "spotify": "https://open.spotify.com",
    "amazon": "https://amazon.com", "maps": "https://maps.google.com",
    "calendar": "https://calendar.google.com", "drive": "https://drive.google.com",
    "docs": "https://docs.google.com", "notion": "https://notion.so",
    "linear": "https://linear.app", "slack": "https://slack.com",
    "figma": "https://figma.com", "stack overflow": "https://stackoverflow.com",
    "wikipedia": "https://wikipedia.org", "twitch": "https://twitch.tv",
}

# Chromium-family browsers share an AppleScript dictionary for tab creation/indexing.
_CHROMIUM = {"Arc", "Google Chrome", "Brave Browser", "Microsoft Edge", "Chromium"}

# Spoken numbers/ordinals -> index.
_NUMBERS = {
    "one": 1, "first": 1, "two": 2, "second": 2, "three": 3, "third": 3,
    "four": 4, "fourth": 4, "five": 5, "fifth": 5, "six": 6, "sixth": 6,
    "seven": 7, "seventh": 7, "eight": 8, "eighth": 8, "nine": 9, "ninth": 9,
    "ten": 10, "tenth": 10, "eleven": 11, "eleventh": 11, "twelve": 12, "twelfth": 12,
}


def _to_index(word: str) -> int | None:
    w = word.strip().lower()
    return int(w) if w.isdigit() else _NUMBERS.get(w)


def handle(text: str) -> str:
    """Interpret a control-mode utterance and act. Returns a human-readable result."""
    intent = parse(text)
    if intent is None:
        return _handoff(text)
    name, arg = intent
    dispatch = {
        "navigate": _navigate, "navigate_new": _navigate_new, "search": _search,
        "tab": _tab, "tab_move": _tab_move, "tab_index": _tab_index,
        "window": _window, "window_move": _window_move, "window_index": _window_index,
        "desktop_move": _desktop_move, "desktop_index": _desktop_index,
        "sidebar": _sidebar,
    }
    return dispatch.get(name, lambda _: _handoff(text))(arg)


def parse(text: str) -> tuple[str, str] | None:
    """Map an utterance to an (intent, argument) pair, or None."""
    t = text.lower().strip().rstrip(".!?")

    # Show / hide the tab sidebar (Arc).
    m = re.search(r"\b(show|hide|toggle)\s+(?:the\s+)?(?:tabs|sidebar)\b", t)
    if m:
        return ("sidebar", m.group(1))

    # Tab: relative (next/previous).
    m = re.search(r"\b(next|previous|prev)\s+tab\b", t)
    if m:
        return ("tab_move", m.group(1))
    # Tab: absolute — "last tab", "first tab", "tab 10", "the tenth tab".
    m = (re.search(r"\b(last|first)\s+tab\b", t)
         or re.search(r"\btab\s+(?:number\s+)?(\w+)\b", t)
         or re.search(r"\b(?:go to|switch to|open|select)\s+(?:the\s+)?(\w+)\s+tab\b", t))
    if m:
        w = m.group(1)
        if w in ("first", "last"):
            return ("tab_index", w)
        if _to_index(w) is not None:
            return ("tab_index", str(_to_index(w)))
    # Tab: by name.
    m = re.search(r"\b(?:go to|switch to|open)\s+(?:my\s+)?(.+?)\s+tab\b", t)
    if m:
        return ("tab", m.group(1).strip())

    # Window: relative (next/previous).
    m = re.search(r"\b(next|previous|prev)\s+window\b", t)
    if m:
        return ("window_move", m.group(1))
    # Window: by index — "window 2", "go to window three".
    m = (re.search(r"\bwindow\s+(?:number\s+)?(\w+)\b", t)
         or re.search(r"\b(?:go to|switch to|open|select)\s+(?:the\s+)?(\w+)\s+window\b", t))
    if m and _to_index(m.group(1)) is not None:
        return ("window_index", str(_to_index(m.group(1))))
    # Window: by name.
    m = re.search(r"\b(?:go to|switch to|open)\s+(?:my\s+)?(.+?)\s+window\b", t)
    if m:
        return ("window", m.group(1).strip())

    # Desktop / Space switching (macOS Mission Control).
    m = re.search(r"\b(next|previous|prev)\s+desktop\b", t)
    if m:
        return ("desktop_move", "next" if m.group(1) == "next" else "previous")
    m = (re.search(r"\bdesktop\s+(?:number\s+)?(\w+)\b", t)
         or re.search(r"\b(?:go to|switch to|open)\s+(?:the\s+)?(\w+)\s+desktop\b", t))
    if m and _to_index(m.group(1)) is not None:
        return ("desktop_index", str(_to_index(m.group(1))))
    # Open a NEW tab (force a fresh tab even if one is already open).
    m = re.search(r"\b(?:open|go\s*to)\s+(?:a\s+)?new\s+(?:the\s+)?(?:app\s+)?(.+)", t)
    if m:
        return ("navigate_new", re.sub(r"\s+app$", "", m.group(1).strip()))
    # Open / go to (app or known site).
    m = re.search(r"\b(?:open|go\s*to)\s+(?:the\s+)?(?:app\s+)?(.+)", t)
    if m:
        return ("navigate", re.sub(r"\s+app$", "", m.group(1).strip()))
    # Explicit web search.
    m = re.search(r"\bsearch\s+(?:for\s+)?(.+)", t)
    if m:
        return ("search", m.group(1).strip())
    return None


def resolve_app_name(app: str) -> str:
    return _APP_ALIASES.get(app.lower().strip(), app.title())


def known_url(target: str) -> str | None:
    """URL for a *known* target (site alias or real domain), else None — never a guess."""
    t = target.lower().strip().rstrip("/")
    if t in _SITE_ALIASES:
        return _SITE_ALIASES[t]
    if "." in t:
        return t if t.startswith("http") else f"https://{t}"
    return None


def _osa(script: str) -> tuple[bool, str]:
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    return r.returncode == 0, (r.stdout or r.stderr).strip()


def _app_exists(name: str) -> bool:
    return _osa(f'id of app "{name}"')[0]


def _browser_tab_script(browser: str, url: str) -> str | None:
    if browser in _CHROMIUM or browser == "Safari":
        return (f'tell application "{browser}"\n    activate\n'
                f'    tell front window to make new tab with properties {{URL:"{url}"}}\n'
                f'end tell')
    return None


def _open_url(url: str) -> None:
    script = _browser_tab_script(CONFIG.browser, url)
    if script and _osa(script)[0]:
        return
    subprocess.run(["open", url], capture_output=True, text=True)


def _navigate(target: str, force_new: bool = False) -> str:
    name = resolve_app_name(target)
    if _app_exists(name):
        subprocess.run(["open", "-a", name], capture_output=True, text=True)
        return f"Opening {name}."
    url = known_url(target)
    if url:
        if not force_new:
            i = _find_tab_for_url(url)
            if i is not None:
                _select_tab(CONFIG.browser, i + 1)
                return f"Switched to existing {target} tab."
        _open_url(url)
        return f"New {target} tab." if force_new else f"Going to {url}."
    return _handoff(target)


def _navigate_new(target: str) -> str:
    return _navigate(target, force_new=True)


def _find_tab_for_url(url: str) -> int | None:
    host = urllib.parse.urlparse(url).netloc
    if not host:
        return None
    ok, urls = _tab_urls(CONFIG.browser)
    return next((i for i, u in enumerate(urls) if host in u), None) if ok else None


def _search(query: str) -> str:
    _open_url("https://www.google.com/search?q=" + urllib.parse.quote_plus(query))
    return f"Searching for {query!r}."


# --- Browser tab switching ---

def _tab_titles(browser: str) -> tuple[bool, list[str]]:
    """Read the front window's tab titles (newline-joined so commas in titles are safe)."""
    prop = "name" if browser == "Arc" else "title" if browser in _CHROMIUM else None
    if prop is None:
        return False, []
    ok, out = _osa(f'tell application "{browser}"\n'
                   f'    set AppleScript\'s text item delimiters to linefeed\n'
                   f'    return ({prop} of every tab of front window) as text\nend tell')
    return ok, [t for t in out.split("\n") if t.strip()] if ok else []


def _tab_urls(browser: str) -> tuple[bool, list[str]]:
    if browser != "Arc" and browser not in _CHROMIUM:
        return False, []
    ok, out = _osa(f'tell application "{browser}"\n'
                   f'    set AppleScript\'s text item delimiters to linefeed\n'
                   f'    return (URL of every tab of front window) as text\nend tell')
    return ok, out.split("\n") if ok else []


def _select_tab(browser: str, n: int) -> tuple[bool, str]:
    sel = (f'tell application "Arc" to tell tab {n} of front window to select'
           if browser == "Arc" else
           f'tell application "{browser}" to set active tab index of front window to {n}')
    return _osa(f'tell application "{browser}" to activate\n{sel}')


def _best_match(query: str, titles: list[str]) -> int | None:
    """Fuzzy-match a spoken query to a tab title (substring or close phonetic match)."""
    q = query.lower().strip()
    best, best_score = None, 0.0
    for i, title in enumerate(titles):
        tl = title.lower()
        if q in tl:
            score = 0.9
        else:
            score = difflib.SequenceMatcher(None, q, tl).ratio()
            for w in tl.split():
                score = max(score, difflib.SequenceMatcher(None, q, w).ratio())
        if score > best_score:
            best, best_score = i, score
    return best if best_score >= 0.55 else None


def _tab(query: str) -> str:
    b = CONFIG.browser
    ok, titles = _tab_titles(b)
    if not ok:
        return f"Couldn't read tabs (tab switching may not support {b})."
    i = _best_match(query, titles)
    if i is None:
        return f"No tab matching {query!r}."
    sok, sout = _select_tab(b, i + 1)
    return f"Switched to {titles[i]!r}." if sok else f"Couldn't switch tab ({sout})."


def _tab_move(direction: str) -> str:
    expr = {"next": "idx + 1", "previous": "idx - 1", "prev": "idx - 1"}[direction]
    b = CONFIG.browser
    if b == "Arc":
        script = (f'tell application "Arc"\n    set n to count of tabs of front window\n'
                  f'    set aid to id of active tab of front window\n    set idx to 1\n'
                  f'    repeat with i from 1 to n\n'
                  f'        if id of tab i of front window is aid then set idx to i\n    end repeat\n'
                  f'    set j to {expr}\n    if j < 1 then set j to n\n    if j > n then set j to 1\n'
                  f'    tell tab j of front window to select\nend tell')
    elif b in _CHROMIUM:
        script = (f'tell application "{b}"\n    set n to count of tabs of front window\n'
                  f'    set idx to active tab index of front window\n    set j to {expr}\n'
                  f'    if j < 1 then set j to n\n    if j > n then set j to 1\n'
                  f'    set active tab index of front window to j\nend tell')
    else:
        return f"Tab switching isn't wired up for {b} yet."
    ok, out = _osa(script)
    return f"Tab: {direction}." if ok else f"Couldn't move tab ({out})."


def _tab_index(arg: str) -> str:
    expr = {"first": "1", "last": "n"}.get(arg, arg)
    b = CONFIG.browser
    if b == "Arc":
        script = (f'tell application "Arc"\n    activate\n    set n to count of tabs of front window\n'
                  f'    set j to {expr}\n    if j < 1 then set j to 1\n    if j > n then set j to n\n'
                  f'    tell tab j of front window to select\nend tell')
    elif b in _CHROMIUM:
        script = (f'tell application "{b}"\n    activate\n    set n to count of tabs of front window\n'
                  f'    set j to {expr}\n    if j < 1 then set j to 1\n    if j > n then set j to n\n'
                  f'    set active tab index of front window to j\nend tell')
    else:
        return f"Tab switching isn't wired up for {b} yet."
    ok, out = _osa(script)
    return f"Tab {arg}." if ok else f"Couldn't switch tab ({out})."


# --- App window switching (needs Accessibility permission) ---

def _window(query: str) -> str:
    q = query.replace('"', "")
    script = ('tell application "System Events"\n'
              '    set p to first application process whose frontmost is true\n'
              '    repeat with w in windows of p\n'
              f'        if name of w contains "{q}" then\n'
              '            perform action "AXRaise" of w\n            return "ok"\n        end if\n'
              '    end repeat\n    return "notfound"\nend tell')
    return _window_result(*_osa(script), found=f"Switched to the {query!r} window.",
                          missing=f"No window matching {query!r} in the front app.")


def _window_move(direction: str) -> str:
    # ⌘` cycles windows of the frontmost app (⌘⇧` reverses). Works within the current
    # macOS Space — windows on another Space/desktop can't be reached this way.
    mods = "command down" if direction == "next" else "{command down, shift down}"
    ok, out = _osa(f'tell application "System Events" to keystroke "`" using {mods}')
    if ok:
        return f"Window: {direction}."
    return _perm_msg() if _is_perm_err(out) else f"Couldn't switch window ({out})."


def _desktop_move(direction: str) -> str:
    # Ctrl+→ / Ctrl+← move between macOS desktops/Spaces (Mission Control).
    code = 124 if direction == "next" else 123  # right / left arrow key code
    ok, out = _osa(f'tell application "System Events" to key code {code} using control down')
    if ok:
        return f"Desktop: {direction}."
    return _perm_msg() if _is_perm_err(out) else f"Couldn't switch desktop ({out})."


def _desktop_index(arg: str) -> str:
    # Ctrl+<n> — needs "Switch to Desktop N" enabled in Keyboard → Shortcuts → Mission Control.
    ok, out = _osa(f'tell application "System Events" to keystroke "{arg}" using control down')
    if ok:
        return f"Desktop {arg} (if that shortcut is enabled)."
    return _perm_msg() if _is_perm_err(out) else f"Couldn't switch desktop ({out})."


def _window_index(arg: str) -> str:
    script = ('tell application "System Events"\n'
              '    set p to first application process whose frontmost is true\n'
              '    set ws to windows of p\n'
              f'    if (count of ws) < {arg} then return "few"\n'
              f'    perform action "AXRaise" of (item {arg} of ws)\n    return "ok"\nend tell')
    return _window_result(*_osa(script), found=f"Window {arg}.",
                          missing=f"There aren't {arg} windows in the front app.")


def _is_perm_err(out: str) -> bool:
    o = out.lower()
    return "assistive access" in o or "not allowed" in o


def _perm_msg() -> str:
    return ("Needs Accessibility permission: System Settings → Privacy & Security → "
            "Accessibility → enable your terminal, then restart it.")


def _window_result(ok: bool, out: str, found: str, missing: str) -> str:
    if ok and out == "ok":
        return found
    if _is_perm_err(out):
        return _perm_msg()
    return missing if ok else f"Couldn't switch window ({out})."


def _sidebar(direction: str) -> str:
    # Arc shows tabs in a sidebar toggled by ⌘S. State isn't readable, so show/hide/
    # toggle all flip it. Needs Accessibility permission.
    if CONFIG.browser != "Arc":
        return f"Sidebar toggle is Arc-specific (browser is {CONFIG.browser})."
    ok, out = _osa('tell application "Arc" to activate\n'
                   'tell application "System Events" to keystroke "s" using command down')
    if ok:
        return "Toggled the tab sidebar."
    if "assistive access" in out.lower() or "not allowed" in out.lower():
        return ("That needs Accessibility permission: System Settings → Privacy & "
                "Security → Accessibility → enable your terminal.")
    return f"Couldn't toggle sidebar ({out})."


def _handoff(what: str) -> str:
    # Anything the deterministic layer can't handle. Once the assistant (M4) is wired this
    # hands off ("did you mean …?"); for now we just say so. See docs/plan/observations.md.
    return f"Handing off to the assistant (not wired yet): {what!r}"
