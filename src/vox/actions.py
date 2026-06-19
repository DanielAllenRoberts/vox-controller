"""Deterministic command actions for CONTROL mode.

open apps · go to apps/known sites · web search · switch browser tabs (by name, index,
or relative) · switch app windows (by name, index, or next) · toggle Arc's sidebar.
Unknown input hands off to the assistant (no guessing).
"""

import difflib
import os
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
    """Interpret a control-mode utterance and act. Returns a human-readable result.

    Chains "<cmd> and <cmd>" into two commands, but only when *both* halves parse
    (so "search cats and dogs" isn't split).
    """
    parts = re.split(r"\s+and\s+", text.strip())
    if len(parts) > 1 and all(parse(p) for p in parts):
        return "  ·  ".join(_run(p) for p in parts)
    return _run(text)


def _run(text: str) -> str:
    intent = parse(text)
    if intent is None:
        return _handoff(text)
    name, arg = intent
    dispatch = {
        "navigate": _navigate, "navigate_new": _navigate_new, "search": _search, "back": _back,
        "tab": _tab, "tab_arrow": _tab_arrow, "tab_index": _tab_index,
        "window": _window, "window_move": _window_move, "window_index": _window_index,
        "desktop_move": _desktop_move, "desktop_index": _desktop_index,
        "profile": _profile, "profile_move": _profile_move, "app_cycle": _app_cycle,
        "sidebar": _sidebar, "close_tab": lambda _: close_tab(),
    }
    return dispatch.get(name, lambda _: _handoff(text))(arg)


def parse(text: str) -> tuple[str, str] | None:
    """Map an utterance to an (intent, argument) pair, or None."""
    t = text.lower().strip().rstrip(".!?")

    # Open a NEW tab (force fresh) — first, so "open a new youtube tab" isn't read as a switch.
    m = re.search(r"\b(?:open|go\s*to)\s+(?:a\s+)?new\s+(.+)", t)
    if m:
        tgt = re.sub(r"^(?:the\s+)?", "", m.group(1).strip())
        return ("navigate_new", re.sub(r"\s+(?:tab|app)$", "", tgt))

    # Browser/app: go back (⌘[).
    if re.search(r"\bgo back\b|\bnavigate back\b", t):
        return ("back", "")

    # Close the current tab (⌘W).
    if re.search(r"\bclose\s+(?:this\s+|the\s+|current\s+)?tabs?\b", t):
        return ("close_tab", "")

    # Show / hide / toggle the tab sidebar (Arc). Tolerant of Whisper splitting "sidebar" into
    # "side bar" and of singular "tab".
    m = re.search(r"\b(show|hide|toggle)\s+(?:the\s+|my\s+)?(?:tabs?|side\s?bar|panel)\b", t)
    if m:
        return ("sidebar", m.group(1))

    # Tab: jump to top/bottom of the current profile's tabs.
    if re.search(r"\b(?:top|first)\s+tab\b|\bto\s+(?:the\s+)?top\b", t):
        return ("tab_arrow", "up:30")
    if re.search(r"\b(?:bottom|last)\s+tab\b|\bto\s+(?:the\s+)?bottom\b", t):
        return ("tab_arrow", "down:30")
    # Tab: relative movement (Arc sidebar vertical → ⌘⌥up/down; stays in your profile).
    m = re.search(r"\btab\s+(up|down)\b", t)  # "tab up", "tab down"
    if m:
        return ("tab_arrow", f"{m.group(1)}:1")
    m = re.search(r"\b(?:move\s+|go\s+)?(up|down)\s+(?:(\w+)\s+)?tabs?\b", t)
    if m:
        n = _to_index(m.group(2)) if m.group(2) else 1
        return ("tab_arrow", f"{m.group(1)}:{n or 1}")
    m = re.search(r"\b(next|previous|prev)\s+tab\b", t)
    if m:
        return ("tab_arrow", "down:1" if m.group(1) == "next" else "up:1")
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

    # Desktop / Space switching (macOS Mission Control). Synonyms: desktop / space / screen,
    # plus "swipe left/right" (easier to say than "next desktop").
    m = re.search(r"\bswipe\s+(left|right)\b", t)
    if m:
        return ("desktop_move", "next" if m.group(1) == "right" else "previous")
    m = re.search(r"\b(next|previous|prev)\s+(?:desktop|space|screen)\b", t)
    if m:
        return ("desktop_move", "next" if m.group(1) == "next" else "previous")
    m = (re.search(r"\b(?:desktop|space|screen)\s+(?:number\s+)?(\w+)\b", t)
         or re.search(r"\b(?:go to|switch to|open)\s+(?:the\s+)?(\w+)\s+(?:desktop|space|screen)\b", t))
    if m and _to_index(m.group(1)) is not None:
        return ("desktop_index", str(_to_index(m.group(1))))
    # Arc profile switching — relative (⌘⌥←/→) or absolute (Ctrl+<n>).
    m = re.search(r"\b(next|previous|prev)\s+profile\b", t)
    if m:
        return ("profile_move", "next" if m.group(1) == "next" else "previous")
    m = (re.search(r"\bprofile\s+(?:number\s+)?(\w+)\b", t)
         or re.search(r"\b(?:go to|switch to|open)\s+(?:the\s+)?(\w+)\s+profile\b", t))
    if m and _to_index(m.group(1)) is not None:
        return ("profile", str(_to_index(m.group(1))))
    # Cycle a specific app's windows across Spaces (simulated Dock-click) — "cursor
    # window", "next cursor window", "cursor space", "switch cursor".
    m = re.search(r"\b(?:next\s+)?([a-z][a-z ]*?)\s+(?:window|space|screen)\b", t)
    if m and m.group(1).strip() not in ("the", "my", "a", "this", "next"):
        return ("app_cycle", m.group(1).strip())
    m = re.search(r"\b(?:switch|cycle|toggle)\s+(?:to\s+)?([a-z]+(?:\s+[a-z]+)?)\b", t)
    if m:
        cand = m.group(1).strip()
        # Only treat a short, app-like name as a switch. Let natural sentences ("switch me over
        # to the next cursor tab") fall through to None → the LLM executor, which has context.
        _filler = {"me", "to", "us", "it", "back", "over", "the", "my", "a", "an",
                   "this", "that", "now", "please", "here", "tab", "tabs", "window", "windows"}
        if not set(cand.split()) & _filler:
            return ("app_cycle", cand)
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
    try:
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=20)
    except subprocess.TimeoutExpired:
        return False, "timed out"  # never let a wedged AppleScript freeze the loop
    return r.returncode == 0, (r.stdout or r.stderr).strip()


def _app_exists(name: str) -> bool:
    return _osa(f'id of app "{name}"')[0]


def running_apps() -> list[str]:
    """Names of currently-running, non-background apps — helps the brain pick the right one."""
    ok, out = _osa('tell application "System Events" to get name of '
                   'every process whose background only is false')
    return [a.strip() for a in out.split(",") if a.strip()] if ok else []


def frontmost_app() -> str:
    """Name of the focused (frontmost) app — tells the brain which app you're on. "" on failure."""
    ok, out = _osa('tell application "System Events" to get name of '
                   '(first process whose frontmost is true)')
    return out.strip() if ok else ""


def _active_tab(browser: str) -> tuple[str, str]:
    """(title, url) of the active tab of the front window. ("", "") on failure / unsupported."""
    if browser in _CHROMIUM:
        tab = "active tab of front window"
    elif browser == "Safari":
        tab = "current tab of front window"
    else:
        return "", ""
    ok, out = _osa(f'tell application "{browser}"\n'
                   f'    set AppleScript\'s text item delimiters to linefeed\n'
                   f'    return (name of {tab}) & linefeed & (URL of {tab})\nend tell')
    if not ok:
        return "", ""
    title, _, url = out.partition("\n")
    return title.strip(), url.strip()


def _domain(url: str) -> str:
    """Bare host of a URL (no scheme/www), for matching generic-titled tabs by site. "" if none."""
    host = urllib.parse.urlparse(url.strip()).netloc
    return host[4:] if host.startswith("www.") else host


def _now_line() -> str:
    """'Now: <Weekday YYYY-MM-DD HH:MM> (<tz>)' in the machine's local timezone — the brain's clock."""
    from datetime import datetime
    now = datetime.now().astimezone()
    return f"Now: {now.strftime('%A %Y-%m-%d %H:%M')} ({now.tzname()})"


def environment_context() -> str:
    """A short snapshot of the current Mac state for the executor's brain (focused app, active tab,
    running apps, open browser tabs + domains, and the time) so fuzzy references resolve to the right
    target. Best-effort; each part is included only if it succeeds, "" if nothing does."""
    parts = []
    app = frontmost_app()
    if app:
        parts.append(f"Focused app: {app}")
    # Browser tab detail (active tab + the open-tabs list) is only included when the browser is the
    # FOCUSED app — otherwise we were dumping every Arc tab on every turn, off-browser, wasting the
    # brain's context/tokens. When you're actually on the browser it's exactly what helps tab nav.
    on_browser = bool(app) and app.lower() == CONFIG.browser.lower()
    if on_browser:
        title, url = _active_tab(CONFIG.browser)
        if title or url:
            parts.append(f"Active tab: {title} — {url}".rstrip(" —"))
    apps = running_apps()
    if apps:
        parts.append("Running apps: " + ", ".join(apps[:40]))
    if on_browser:
        ok, titles = _tab_titles(CONFIG.browser)
        if ok and titles:
            _, urls = _tab_urls(CONFIG.browser)  # parallel to titles; surface the domain for matching
            entries = []
            for i, t in enumerate(titles[:25]):
                dom = _domain(urls[i]) if i < len(urls) else ""
                entries.append(f"{t[:60]} ({dom})" if dom else t[:60])
            parts.append(f"Open {CONFIG.browser} tabs: " + " | ".join(entries))
    parts.append(_now_line())
    return "\n".join(parts)


def capture_screen() -> str | None:
    """Capture the screen to a downscaled PNG for the vision brain; returns the path, or None.
    Needs Screen Recording permission (System Settings → Privacy & Security → Screen Recording)."""
    raw, small = "/tmp/vox_screen_raw.png", "/tmp/vox_screen.png"
    if subprocess.run(["screencapture", "-x", raw], capture_output=True).returncode != 0 \
            or not os.path.exists(raw):
        return None
    if subprocess.run(["sips", "-Z", "1568", raw, "--out", small],
                      capture_output=True).returncode == 0 and os.path.exists(small):
        os.remove(raw)
        return small
    return raw  # downscale failed — fall back to the full-res capture


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
        if not force_new and _reuse_tab(url):
            return f"Switched to existing {target} tab."
        _open_url(url)
        return f"New {target} tab." if force_new else f"Going to {url}."
    return _handoff(target)


def _navigate_new(target: str) -> str:
    return _navigate(target, force_new=True)


def _reuse_tab(url: str) -> bool:
    """Switch to an already-open tab for this URL *in the current space* (never jumping
    to another profile). Returns True if reused.

    Arc gives no way to know which space a pinned tab lives in, so we try the match and
    check whether selecting it changed the active space — if it jumped to another
    profile, we roll back and report no-reuse so the caller opens a fresh tab here.
    """
    host = urllib.parse.urlparse(url).netloc.replace('"', "")
    if not host:
        return False
    if CONFIG.browser == "Arc":
        # Reuse only tabs in the CURRENT space (reliable, never jumps profiles). Arc's
        # `tabs of front window` span ALL profiles, so matching there jumps you to another
        # profile — don't. Favorites/pinned outside the current space won't be reused.
        script = (
            'tell application "Arc"\n    activate\n'
            '    repeat with t in tabs of (active space of front window)\n'
            f'        if URL of t contains "{host}" then\n            tell t to select\n            return "ok"\n        end if\n'
            '    end repeat\n    return "none"\nend tell')
        return _osa(script) == (True, "ok")
    # Chrome family: no spaces — reuse any matching tab.
    ok, urls = _tab_urls(CONFIG.browser)
    if ok:
        i = next((j for j, u in enumerate(urls) if host in u), None)
        if i is not None:
            _select_tab(CONFIG.browser, i + 1)
            return True
    return False


_DASHBOARD_TITLE = "Vox Control Center"  # the dashboard's page <title>, used to find its window


def _focus_dashboard(url: str) -> bool:
    """Reuse an already-open dashboard WITHOUT yanking you to Arc's main window: only act if one is
    actually open. Raises an existing standalone 'Little Arc' window in place, or selects a matching
    tab — crucially activating Arc ONLY on a real match, so a fresh open (nothing to reuse) never
    switches you out of the app you're in. Returns True if one was focused."""
    host = urllib.parse.urlparse(url).netloc.replace('"', "")
    if not host:
        return False
    # (1) An existing standalone Little Arc window — raise it in place (no Arc activate → no Space jump).
    se = (
        f'tell application "System Events" to tell process "{CONFIG.browser}"\n'
        f'    repeat with w in windows\n'
        f'        if name of w contains "{_DASHBOARD_TITLE}" then\n'
        '            perform action "AXRaise" of w\n'
        '            return "ok"\n'
        '        end if\n'
        '    end repeat\n'
        '    return "none"\n'
        'end tell')
    if _osa(se) == (True, "ok"):
        return True
    # (2) A matching tab in the current Space — activate Arc only INSIDE the match (not before it),
    #     so checking-and-finding-nothing doesn't pull focus to Arc.
    if CONFIG.browser != "Arc":
        return _reuse_tab(url)
    tab = (
        'tell application "Arc"\n'
        '    if (count of windows) is 0 then return "none"\n'
        '    repeat with t in tabs of (active space of front window)\n'
        f'        if URL of t contains "{host}" then\n'
        '            tell t to select\n'
        '            activate\n'
        '            return "ok"\n'
        '        end if\n'
        '    end repeat\n'
        '    return "none"\n'
        'end tell')
    return _osa(tab) == (True, "ok")


def close_dashboard() -> str:
    """Close the dashboard without disrupting your workflow — no Space-switch, no focus-steal.
    (1) If it's a normal tab, close just that tab via the browser's AppleScript.
    (2) Otherwise press the standalone window's close button directly via accessibility — AXPress
    needs no focus, so it never switches Spaces. The tab path runs FIRST, so a dashboard tab in the
    main window is always closed as a tab and we never AXPress (and thus close) the main window —
    the standalone path only fires for a genuine 'Little Arc', which Arc's AppleScript can't see.
    Never raises."""
    url = f"http://{CONFIG.dashboard_host}:{CONFIG.dashboard_port}"
    host = urllib.parse.urlparse(url).netloc.replace('"', "")
    if not host:
        return "No dashboard URL configured."
    # (1) Close a matching TAB (incl. the active tab of the main window) — closes only the tab.
    tab = (
        f'tell application "{CONFIG.browser}"\n'
        '    repeat with w in windows\n'
        '        repeat with t in tabs of w\n'
        f'            if URL of t contains "{host}" then\n'
        '                tell t to close\n'
        '                return "ok"\n'
        '            end if\n'
        '        end repeat\n'
        '    end repeat\n'
        '    return "none"\n'
        'end tell')
    if _osa(tab) == (True, "ok"):
        return "Closed the dashboard."
    # (2) Standalone Little Arc window: press its close button (shallow chrome search, not the heavy
    #     web AX tree). AXPress needs no focus → non-disruptive.
    se = (
        f'tell application "System Events" to tell process "{CONFIG.browser}"\n'
        f'    repeat with w in windows\n'
        f'        if name of w contains "{_DASHBOARD_TITLE}" then\n'
        '            repeat with g in (UI elements of w)\n'
        '                try\n'
        '                    repeat with b in (buttons of g)\n'
        '                        if subrole of b is "AXCloseButton" then\n'
        '                            perform action "AXPress" of b\n'
        '                            return "ok"\n'
        '                        end if\n'
        '                    end repeat\n'
        '                end try\n'
        '                try\n'
        '                    repeat with g2 in (UI elements of g)\n'
        '                        try\n'
        '                            repeat with b in (buttons of g2)\n'
        '                                if subrole of b is "AXCloseButton" then\n'
        '                                    perform action "AXPress" of b\n'
        '                                    return "ok"\n'
        '                                end if\n'
        '                            end repeat\n'
        '                        end try\n'
        '                    end repeat\n'
        '                end try\n'
        '            end repeat\n'
        '        end if\n'
        '    end repeat\n'
        '    return "none"\n'
        'end tell')
    if _osa(se) == (True, "ok"):
        return "Closed the dashboard."
    return "No dashboard window was open."


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


def _tab_arrow(arg: str) -> str:
    # Move between tabs with ⌘⌥up/down — stays within the current profile (unlike the
    # full tab list, which spans all spaces). Arc's sidebar is vertical, hence up/down.
    direction, n = arg.split(":")
    code = 125 if direction == "down" else 126  # down / up arrow key code
    n = max(1, min(int(n), 30))
    script = (f'tell application "{CONFIG.browser}" to activate\n'
              'tell application "System Events"\n'
              f'    repeat {n} times\n'
              f'        key code {code} using {{command down, option down}}\n'
              '    end repeat\nend tell')
    ok, out = _osa(script)
    if ok:
        return f"Tab {direction}{f' ×{n}' if n > 1 else ''}."
    return _perm_msg() if _is_perm_err(out) else f"Couldn't move tab ({out})."


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


def _profile(arg: str) -> str:
    # Arc switches profiles/spaces with Ctrl+<n> when it's focused.
    ok, out = _osa('tell application "Arc" to activate\n'
                   f'tell application "System Events" to keystroke "{arg}" using control down')
    if ok:
        return f"Profile {arg}."
    return _perm_msg() if _is_perm_err(out) else f"Couldn't switch profile ({out})."


def _profile_move(direction: str) -> str:
    # Arc switches profiles/spaces with ⌘⌥←/→ when focused.
    code = 124 if direction == "next" else 123  # right / left arrow
    ok, out = _osa('tell application "Arc" to activate\n'
                   f'tell application "System Events" to key code {code} using {{command down, option down}}')
    if ok:
        return f"Profile: {direction}."
    return _perm_msg() if _is_perm_err(out) else f"Couldn't switch profile ({out})."


def _back(_: str) -> str:
    # Browser back — ⌘[ . Activate the browser first so the keystroke lands there.
    ok, out = _osa(f'tell application "{CONFIG.browser}" to activate\n'
                   'tell application "System Events" to keystroke "[" using command down')
    return "Back." if ok else (_perm_msg() if _is_perm_err(out) else f"Couldn't go back ({out})")


def close_tab() -> str:
    # Close the current browser tab (⌘W). Activate the browser first so the keystroke lands there.
    ok, out = _osa(f'tell application "{CONFIG.browser}" to activate\n'
                   'tell application "System Events" to keystroke "w" using command down')
    return "Closed the tab." if ok else (_perm_msg() if _is_perm_err(out) else f"Couldn't close the tab ({out}).")


def _app_cycle(app: str) -> str:
    # Click the app's Dock icon — cycles its windows even across Spaces (your manual trick).
    name = resolve_app_name(app)
    if not _app_exists(name):
        return f"No app called {name!r}."
    ok, out = _osa(f'tell application "System Events" to tell process "Dock" '
                   f'to click UI element "{name}" of list 1')
    if ok:
        return f"{name} window."
    return _perm_msg() if _is_perm_err(out) else f"Couldn't cycle {name} ({out})."


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
    # Arc toggles its tab sidebar from the View menu — "Show Sidebar" when hidden, "Hide Sidebar"
    # when shown. We click the menu item rather than press ⌘S because a menu click can't be swallowed
    # by a focused web app (Docs/Notion grab ⌘S as "Save"), and the item name reveals the current
    # state so show/hide are honoured exactly. direction is "show" | "hide" | "toggle". Needs
    # Accessibility permission.
    if CONFIG.browser != "Arc":
        return f"Sidebar control is Arc-specific (browser is {CONFIG.browser})."
    script = (
        'tell application "Arc" to activate\n'
        'tell application "System Events" to tell process "Arc"\n'
        '    set m to menu "View" of menu bar 1\n'
        '    set isHidden to (exists menu item "Show Sidebar" of m)\n'
        f'    if "{direction}" is "show" then\n'
        '        if isHidden then click menu item "Show Sidebar" of m\n'
        f'    else if "{direction}" is "hide" then\n'
        '        if not isHidden then click menu item "Hide Sidebar" of m\n'
        '    else if isHidden then\n'
        '        click menu item "Show Sidebar" of m\n'
        '    else\n'
        '        click menu item "Hide Sidebar" of m\n'
        '    end if\n'
        'end tell')
    ok, out = _osa(script)
    if ok:
        return {"show": "Showed the tab sidebar.",
                "hide": "Hid the tab sidebar."}.get(direction, "Toggled the tab sidebar.")
    if "assistive access" in out.lower() or "not allowed" in out.lower():
        return ("That needs Accessibility permission: System Settings → Privacy & "
                "Security → Accessibility → enable your terminal.")
    return f"Couldn't reach the sidebar menu ({out})."


def _as_str(s: str) -> str:
    """Encode a Python string as an AppleScript string expression (handles quotes + newlines)."""
    s = s.replace("\\", "\\\\").replace('"', '\\"').replace("\r\n", "\n").replace("\r", "\n")
    return '"' + s.replace("\n", '" & linefeed & "') + '"'


def _paste(text: str) -> None:
    """Insert text at the cursor via the clipboard (reliable — `keystroke` drops fast chars),
    restoring the previous clipboard afterwards."""
    _osa('set savedClip to ""\n'
         '    try\n        set savedClip to (the clipboard as text)\n    end try\n'
         f'set the clipboard to {_as_str(text)}\n'
         'tell application "System Events" to keystroke "v" using command down\n'
         'delay 0.1\n'
         'if savedClip is not "" then set the clipboard to savedClip')


# Dictation arrives as a series of independent dictate() calls — one per utterance,
# split by your pauses. This tiny state carries spacing + capitalization across those
# pauses so a mid-sentence pause doesn't fuse words ("there wasa brown cow") and a new
# sentence after a full stop is capitalized.
_dictation_active = False        # have we typed anything yet this session?
_dictation_new_sentence = True   # capitalize the next chunk (start, after . ! ? or a line break)


def reset_dictation() -> None:
    """Reset cross-chunk dictation state — call when entering dictation mode."""
    global _dictation_active, _dictation_new_sentence
    _dictation_active = False
    _dictation_new_sentence = True


def dictate(text: str) -> None:
    """Insert spoken text at the cursor (frontmost app). A few spoken words act as edit keys;
    everything else is pasted. Chunks are separated with a LEADING space (survives editors that
    trim trailing spaces) and the first word of each sentence is capitalized."""
    global _dictation_active, _dictation_new_sentence
    raw = text.strip()
    low = raw.lower().rstrip(".!?")
    # spoken edit words -> (key code, modifier). "new/next line" is a SOFT newline
    # (Shift+Return) so it doesn't *send* in chat apps; "enter"/"send" is a plain Return.
    specials = {
        "new line": (36, "shift down"), "newline": (36, "shift down"),
        "next line": (36, "shift down"), "new paragraph": (36, "shift down"),
        "enter": (36, ""), "return": (36, ""), "send": (36, ""), "submit": (36, ""),
        "backspace": (51, ""), "delete": (51, ""), "delete that": (51, ""), "tab key": (48, ""),
    }
    if low in specials:
        code, mod = specials[low]
        _osa(f'tell application "System Events" to key code {code}'
             + (f' using {{{mod}}}' if mod else ''))
        if code == 36:  # any Return → next chunk starts fresh on a new line
            _dictation_active = False       # no leading space right after a line break
            _dictation_new_sentence = True  # and capitalize it
        return
    if not raw:
        return
    # Capitalize the first letter when a new sentence starts (first chunk, or after . ! ?).
    if _dictation_new_sentence and raw[:1].islower():
        raw = raw[0].upper() + raw[1:]
    # Leading space separates this chunk from the previous one across the pause.
    _paste((" " if _dictation_active else "") + raw)
    _dictation_active = True
    _dictation_new_sentence = raw.rstrip()[-1:] in ".!?"


def type_text(text: str) -> str:
    """Insert composed (LLM) text at the cursor verbatim — no edit-key interpretation."""
    _paste(text)
    return "Typed it in."


def _get_clipboard() -> str:
    ok, out = _osa("return (the clipboard as text)")
    return out if ok else ""


def edit_selection(transform) -> str:
    """Rewrite the user's SELECTED text: copy it (⌘C), run transform(text)->text, paste it back
    (⌘V), then restore the clipboard. `transform` is a callable (e.g. an LLM call). Needs
    Accessibility permission; works anywhere standard copy/paste does (Docs, editors, fields)."""
    import time
    original = _get_clipboard()
    sentinel = "__vox_no_selection__"
    _osa(f'set the clipboard to "{sentinel}"\n'
         'tell application "System Events" to keystroke "c" using command down')
    time.sleep(0.15)
    selected = _get_clipboard()
    if selected == sentinel or not selected.strip():
        _osa(f'set the clipboard to {_as_str(original)}')
        return "Highlight some text first, then say it again."
    new_text = (transform(selected) or "").strip()
    if not new_text:
        _osa(f'set the clipboard to {_as_str(original)}')
        return "The brain returned nothing — left your text as is."
    _osa(f'set the clipboard to {_as_str(new_text)}\n'
         'tell application "System Events" to keystroke "v" using command down\n'
         'delay 0.1\n'
         f'set the clipboard to {_as_str(original)}')
    return "Done — rewrote the selection."


# Result-string markers meaning the deterministic attempt found no valid target. The LLM
# executor (which sees running apps + open tabs) may resolve it, so CONTROL mode escalates here.
_FAIL_MARKERS = (
    "no app called", "no tab matching", "no window matching",
    "not sure how to do that", "isn't wired up", "there aren't",
)


def failed(result: str) -> bool:
    """True if a handle() result looks like a 'no such target' failure worth escalating to the brain."""
    r = result.lower()
    return any(m in r for m in _FAIL_MARKERS)


def _handoff(what: str) -> str:
    # Anything the deterministic layer can't handle. CONTROL mode escalates this to the
    # executor / assistant (see core/loop.py); this string is just the fallback wording.
    return f"Not sure how to do that: {what!r}"
