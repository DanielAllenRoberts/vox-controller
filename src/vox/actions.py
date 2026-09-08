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


def run_intent(name: str, arg: str, _text: str | None = None) -> str:
    """Execute a known ``(intent, arg)`` action directly via the dispatch map. Used by the command
    DB resolver, which already has the intent+arg and must NOT re-parse. Unknown intent → handoff."""
    dispatch = {
        "navigate": _navigate, "navigate_new": _navigate_new, "search": _search, "back": _back,
        "tab": _tab, "tab_arrow": _tab_arrow, "tab_index": _tab_index,
        "window": _window, "window_move": _window_move, "window_index": _window_index,
        "desktop_move": _desktop_move, "desktop_index": _desktop_index,
        "profile": _profile, "profile_move": _profile_move, "app_cycle": _app_cycle,
        "sidebar": _sidebar, "close_tab": lambda _: close_tab(),
        "reload": _reload,
        "click": click_element,
        "scroll": _scroll, "press": _press,
        "right_click": _right_click, "double_click": _double_click,
        "drag": _drag, "set_value": _set_value,
    }
    return dispatch.get(name, lambda _: _handoff(_text if _text is not None else name))(arg)


def _run(text: str) -> str:
    intent = parse(text)
    if intent is None:
        return _handoff(text)
    name, arg = intent
    return run_intent(name, arg, _text=text)


def parse(text: str) -> tuple[str, str] | None:
    """Map an utterance to an (intent, argument) pair, or None."""
    t = text.lower().strip().rstrip(".!?")

    # --- desktop primitives (idea #61) ---------------------------------------------------------
    # These go FIRST. "right click submit" contains "click submit", and "scroll to the top" contains
    # "to the top" (the jump-to-first-tab phrase) — both would be swallowed by the patterns below.

    # Right / double click, by control label or by a badge number from the overlay.
    m = re.search(r"\b(right|double)[\s-]?click\s+(?:on\s+)?(?:the\s+)?(.+)", t)
    if m:
        tgt = re.sub(r"\s+(?:button|link|icon|tab|menu|option|item|checkbox|control|toggle)$", "",
                     m.group(2).strip())
        if tgt:
            return ("right_click" if m.group(1) == "right" else "double_click", tgt)

    # Scroll. "scroll to the top/bottom" and "page up/down" are separate because a jump is a
    # keystroke, not a pile of wheel ticks.
    if re.search(r"\bscroll\s+(?:to\s+)?(?:the\s+)?top\b|\bgo\s+to\s+the\s+top\s+of\s+the\s+page\b", t):
        return ("scroll", "top")
    if re.search(r"\bscroll\s+(?:to\s+)?(?:the\s+)?bottom\b|\bgo\s+to\s+the\s+bottom\s+of\s+the\s+page\b", t):
        return ("scroll", "bottom")
    m = re.search(r"\bpage\s+(up|down)\b", t)
    if m:
        return ("scroll", "pageup" if m.group(1) == "up" else "pagedown")
    m = re.search(r"\bscroll\s+(up|down|left|right)(?:\s+(?:by\s+)?(\w+))?", t)
    if m:
        n = _to_index(m.group(2) or "") or (int(m.group(2)) if (m.group(2) or "").isdigit() else None)
        return ("scroll", f"{m.group(1)}:{n or 5}")
    if re.fullmatch(r"(?:please\s+)?scroll", t):
        return ("scroll", "down:5")

    # Press a key combination — but ONLY when it really names keys. "press submit" is someone
    # asking for a click, so an unrecognised combo falls through to the click/LLM path instead of
    # failing with "I don't know the key 'submit'".
    m = re.search(r"\b(?:press|hit|tap)\s+(?:the\s+)?(.+)", t)
    if m:
        from vox import input as vox_input
        combo = re.sub(r"\s+(?:key|keys|button)$", "", m.group(1).strip())
        if vox_input.normalize_combo(combo) is not None:
            return ("press", combo)

    # Drag one target onto another ("drag 3 to 7", "drag Inbox onto Archive").
    m = re.search(r"\bdrag\s+(?:the\s+)?(.+?)\s+(?:to|onto|into|on to)\s+(?:the\s+)?(.+)", t)
    if m:
        return ("drag", f"{m.group(1).strip()}||{m.group(2).strip()}")

    # Set a control's value directly ("set volume to 30", "set theme to dark"). Timers/alarms are
    # the scheduler's, and it already gets first refusal in dispatch — this guard is belt-and-braces.
    m = re.search(r"\bset\s+(?:the\s+)?(.+?)\s+to\s+(.+)", t)
    if m and not re.search(r"\b(timer|alarm|reminder|schedule)\b", t):
        return ("set_value", f"{m.group(1).strip()}||{m.group(2).strip()}")

    # Click a labelled button / link / control by name, via the accessibility tree ("click Submit",
    # "click the Log in button"). Checked first — "click" is distinctive. Trailing role words are
    # stripped so "click the submit button" looks for a control labelled "submit".
    m = re.search(r"\bclick\s+(?:on\s+)?(?:the\s+)?(.+)", t)
    if m:
        tgt = re.sub(r"\s+(?:button|link|icon|tab|menu|option|item|checkbox|control|toggle)$", "",
                     m.group(1).strip())
        if tgt:
            return ("click", tgt)

    # Open a NEW tab (force fresh) — first, so "open a new youtube tab" isn't read as a switch.
    m = re.search(r"\b(?:open|go\s*to)\s+(?:a\s+)?new\s+(.+)", t)
    if m:
        tgt = re.sub(r"^(?:the\s+)?", "", m.group(1).strip())
        return ("navigate_new", re.sub(r"\s+(?:tab|app)$", "", tgt))

    # Browser/app: go back (⌘[).
    if re.search(r"\bgo back\b|\bnavigate back\b", t):
        return ("back", "")

    # Reload the current page (⌘R). Only the CANONICAL wording is builtin — this is the command line
    # the brain emits and the right-hand side of a `TEACH:`. "refresh" is deliberately NOT here: the
    # user wants that mapping to come from actually teaching it, so the learning path gets exercised
    # rather than hidden behind a hardcoded synonym.
    if re.fullmatch(r"(?:please\s+)?reload(?:\s+(?:the\s+|this\s+)?(?:page|tab|site))?", t):
        return ("reload", "")

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


def _osa(script: str, timeout: float = 20) -> tuple[bool, str]:
    try:
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=timeout)
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


def frontmost_app_pid() -> tuple[int, str] | None:
    """(unix pid, name) of the focused app, straight from System Events. None on failure.

    The pid comes along because the accessibility API talks in pids, and the obvious way to get one
    — ``NSWorkspace.frontmostApplication()`` — cannot be trusted here: it's a cached property
    refreshed by main-run-loop processing, and the Vox daemon deliberately runs no ``NSApplication``
    run loop (see ``overlay.py`` / ``bubble.py``). Measured in a long-lived run-loop-less process, it
    sat on one stale app for five and a half minutes while a fresh process read the truth every
    time — which is how "click on settings" pressed Cursor's Settings while the user was looking at
    Arc (issue O18). ~150 ms, and worth every one of them."""
    ok, out = _osa('tell application "System Events" to get {unix id, name} of '
                   '(first process whose frontmost is true)')
    pid, _, name = (out or "").partition(",")
    return (int(pid.strip()), name.strip()) if ok and pid.strip().isdigit() else None


def frontmost_app() -> str:
    """Name of the focused (frontmost) app — tells the brain which app you're on. "" on failure."""
    hit = frontmost_app_pid()
    return hit[1] if hit else ""


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


def board_block(max_cards: int = 40) -> str:
    """The workspace board as compact prompt text, or "" if empty/unavailable (idea #51).

    Given to the action layer so the brain can both ANSWER about the board ("what's in my to-do?")
    and resolve a card the user names ("move the AC Direct card to doing") without a round-trip.
    Card ids are included because they're the unambiguous handle when two titles look alike.
    Capped: a long board would otherwise crowd out the rest of the prompt."""
    try:
        from vox import board_store
        conn = board_store.build()
        try:
            snap = board_store.board_snapshot(conn)
            names = [b["name"] for b in board_store.list_boards(conn)]
        finally:
            conn.close()
    except Exception:
        return ""
    lists = (snap or {}).get("lists") or []
    if not lists:
        return ""
    shown, lines = 0, []
    for l in lists:
        cards = l.get("cards") or []
        lines.append(f"  {l['name']} ({len(cards)}):")
        for c in cards:
            if shown >= max_cards:
                lines.append("    …more not shown")
                break
            lines.append(f"    #{c['id']} {c['title']}")
            shown += 1
    other = [n for n in names if n != (snap or {}).get("name")]
    extra = f" Other boards: {', '.join(other)}." if other else ""
    return (f"[Workspace board \"{(snap or {}).get('name', 'Workspace')}\" — the user's task board."
            f"{extra} Use BOARD: to change it]\n" + "\n".join(lines))


def recent_actions_block(limit: int = 6) -> str:
    """The last few actions Vox ran, as prompt text. "" when there's nothing (or the DB is off).

    Given to BOTH brains. The action layer uses it to avoid repeating or contradicting what just
    happened; the chat brain needs it because that's where the damage showed — asked "how did you
    refresh the page?" it denied doing it and invented a mechanism, purely because nothing in its
    prompt said what had just run."""
    try:
        from vox import command_store
        conn = command_store.connect()
        try:
            rows = command_store.recent_actions(conn, limit)
        finally:
            conn.close()
    except Exception:
        return ""
    if not rows:
        return ""
    lines = []
    for r in reversed(rows):  # oldest first — reads as a timeline
        ts = (r.get("ts") or "")[-8:-3]  # HH:MM
        did = r.get("resolved_intent") or "?"
        if r.get("resolved_arg"):
            did += f" {r['resolved_arg']}"
        how = {"db": "saved command", "parser": "built-in command",
               "llm": "worked out by you"}.get(r.get("resolved_by"), r.get("resolved_by") or "?")
        flags = ""
        if not r.get("success"):
            flags += " (failed)"
        if r.get("negated"):
            flags += " (user said this was wrong)"
        where = f" in {r['context_value']}" if r.get("context_value") else ""
        lines.append(f"  {ts} heard \"{r.get('heard_phrase') or ''}\"{where} → ran: {did} "
                     f"[{how}]{flags}")
    return ("[What Vox has just done — these ALREADY happened, you did them. Use this to answer "
            "questions about recent actions and to understand corrections like \"that's not what I "
            "wanted\". Never deny an action listed here.]\n" + "\n".join(lines))


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


# Search the focused app's accessibility tree for a control whose label matches `target`, and
# AXPress the nearest pressable element. Two hard-won lessons drive the design (diagnosed against
# Slack, an Electron app — see docs/plan/issues.md):
#   1. Electron/Chromium apps don't expose their web-content AX tree until an assistive client sets
#      `AXManualAccessibility` on the process — so we set it first, else the sidebar/buttons simply
#      aren't there (the old script silently found nothing).
#   2. The matching label is often an AXStaticText with NO AXPress action; the *clickable* element is
#      an ancestor (the AXRow/AXGroup/AXLink wrapping it). So on a match we walk UP to the nearest
#      ancestor that supports AXPress and press that — not the label.
# Exact name matches win over substring matches (we press the thing literally named `target` before
# anything merely containing it). `AXScrollToVisible` first handles virtualised lists. Bounded
# depth/breadth AND a node-visit budget, with role-gated reads, so the walk stays as fast as
# `clickable_targets()` and can't time out before reaching a deep target (the old name+description
# read on every node did — see docs/plan/issues.md).
_CLICK_SCRIPT = '''
property gPressEl : missing value
property gLabel : ""
property gFallback : missing value
property gFallbackLabel : ""
property gVisited : 0

on actionNames(el)
    try
        tell application "System Events" to return (name of actions of el) as text
    on error
        return ""
    end try
end actionNames

on pressableTarget(el, chain)
    -- el if it can be pressed, else the nearest ancestor (deepest first) that can.
    if my actionNames(el) contains "AXPress" then return el
    set i to (count of chain)
    repeat while i is greater than or equal to 1
        set anc to item i of chain
        if my actionNames(anc) contains "AXPress" then return anc
        set i to i - 1
    end repeat
    return missing value
end pressableTarget

on search(el, depth, chain, target)
    if depth > %(maxd)d then return false
    set gVisited to gVisited + 1
    if gVisited > %(budget)d then return true
    -- Role-gate the reads: get ROLE first (cheap), and only read NAME (then DESCRIPTION, lazily,
    -- for icon-only controls) on interactive roles. The old version read name+description on EVERY
    -- node and timed out on deep Electron trees before reaching the target — this matches the fast
    -- clickable_targets() walk. See docs/plan/issues.md.
    set r to "?"
    try
        tell application "System Events" to set r to role of el
    end try
    if r is in {"AXButton", "AXLink", "AXMenuItem", "AXMenuBarItem", "AXCheckBox", "AXRadioButton", "AXTabButton", "AXPopUpButton", "AXStaticText", "AXRow", "AXCell", "AXTextField", "AXHeading", "AXImage", "AXDisclosureTriangle"} then
        set nm to ""
        try
            tell application "System Events" to set nm to (name of el) as text
        end try
        if nm is missing value then set nm to ""
        if nm is "" then
            try
                tell application "System Events" to set nm to (description of el) as text
            end try
            if nm is missing value then set nm to ""
        end if
        if nm is not "" then
            if nm is target then
                set tgt to my pressableTarget(el, chain)
                if tgt is not missing value then
                    set gPressEl to tgt
                    set gLabel to nm
                    return true
                end if
            else if gFallback is missing value and (nm contains target) then
                set t2 to my pressableTarget(el, chain)
                if t2 is not missing value then
                    set gFallback to t2
                    set gFallbackLabel to nm
                end if
            end if
        end if
    end if
    set kids to {}
    try
        tell application "System Events" to set kids to UI elements of el
    end try
    set total to count of kids
    set n to total
    if n > %(maxb)d then set n to %(maxb)d
    repeat with i from 1 to n
        if my search(item i of kids, depth + 1, chain & {el}, target) then return true
    end repeat
    return false
end search

set gPressEl to missing value
set gLabel to ""
set gFallback to missing value
set gFallbackLabel to ""
set gVisited to 0
tell application "System Events"
    set p to first process whose frontmost is true
    try
        tell p to set value of attribute "AXManualAccessibility" to true
    end try
end tell
delay %(settle).1f
tell application "System Events"
    set p to first process whose frontmost is true
    try
        set root to front window of p
    on error
        set root to p
    end try
end tell
my search(root, 0, {}, "%(target)s")
if gPressEl is missing value and gFallback is not missing value then
    set gPressEl to gFallback
    set gLabel to gFallbackLabel
end if
if gPressEl is missing value then return "err" & tab & "not found"
try
    tell application "System Events" to perform action "AXScrollToVisible" of gPressEl
end try
try
    tell application "System Events" to perform action "AXPress" of gPressEl
    return "ok" & tab & gLabel
on error errMsg
    return "err" & tab & "press failed: " & errMsg
end try
'''


# Result prefix for a click that was REFUSED because focus left the app the utterance was aimed at
# (issue O18). Callers match on it to know the click didn't happen AND must not be retried somewhere
# else — deliberately not in `_FAIL_MARKERS`, because escalating would just re-run the click against
# whatever app is in front now, which is the exact mistake this whole change exists to prevent.
FOCUS_MOVED = "I didn't click"


def focus_target() -> tuple[int, str] | None:
    """(pid, name) of the app this utterance is aimed at — call it as EARLY as possible, then pin it.

    Re-asking "what's frontmost?" at press time is what issue O18 was: an LLM round-trip, a click or
    a remote-desktop session can move focus in between, and the press then lands in a different
    application with no signal that it happened.

    Answered from the focus watcher, which already polls this authoritatively every ~1.5 s — the
    same reading that produces the ``[app=…]`` in the command-DB log line, so the click goes to the
    app Vox told you it was scoped to. That makes it free but up to one poll old, which is fine
    because it is not the last word: whatever presses re-checks against a live reading first
    (``ax._focus_moved``), so a stale poll can only ever cost a refusal, never a wrong click.
    Falls back to asking directly when the watcher is off or hasn't polled yet."""
    from vox import ax, focus_watch
    return focus_watch.last() or ax.frontmost_verified() or ax.frontmost()


def click_element(target: str) -> str:
    """Find a control labelled `target` in the target app's accessibility tree and click it
    (AXPress the nearest pressable element). Uses the fast native AX engine (``vox.ax``, ~77 ms even
    on a miss) so it can't freeze the voice loop; falls back to the AppleScript walk only if native
    AX is unavailable. Needs Accessibility permission. Never raises.

    "Target app" is pinned up front (``focus_target``) and held for the whole find-and-press, so the
    click goes to the app the user was looking at when they spoke rather than to whatever happens to
    be frontmost by the time we press (issue O18). An outer pin — the executor sets one before its
    LLM round-trip — wins, since it was taken closer to the utterance."""
    t = (target or "").strip().replace("\\", " ").replace('"', " ")
    if not t:
        return "Click what? Try 'click Submit'."

    from vox import ax
    aim = None if ax.pinned() else focus_target()  # an outer pin already answered this
    with ax.pinned_to(*(aim or (0, ""))) as pin:
        return _click_pinned(t, target, pin[1] if pin else "")


def _click_pinned(t: str, target: str, want: str) -> str:
    """The body of ``click_element``, run with the target app already pinned."""
    # On a web page, ask the PAGE first. The browser's web AX tree is only intermittently exposed
    # (collapsed in 20% of samples — see vox/webdom.py), so an AX miss here means "the tree is down"
    # at least as often as it means "no such element". Returns None off-browser or on no match, so
    # browser chrome and every native app still take the AX path below unchanged.
    try:
        from vox import targets
        web = targets.click_label(t)
    except Exception:
        web = None
    if web is not None:
        return f"Clicked {web[1] or target}."

    # Native AX first — when it runs it's authoritative (a "not found" is a real, fast miss, NOT a
    # timeout), so we do NOT retry on the slow AppleScript path.
    try:
        from vox import ax
        res = ax.click(t)
    except Exception:
        res = None
    if res is not None:
        status, label = res
        if status == "clicked":
            return f"Clicked {label or target}."
        try:
            from vox import assistant
            assistant._dbg("[click]", f"click_element({target!r}) [native] → {status}"
                                      + (f" (aimed at {want}, now {label})" if status == "focus_changed" else ""))
        except Exception:
            pass
        if status == "focus_changed":
            # Refused, not failed: see ax._focus_moved for why pressing anyway is the worse option.
            return (f"{FOCUS_MOVED} — {label} is in front now, "
                    f"not {want or 'the app you were on'}.")
        if status == "not_found":
            return f"I couldn't find a '{target}' to click."  # fast, authoritative miss — no slow retry
        # status == "press_failed": native found it but the press errored → one-off AppleScript retry.

    # Native AX unavailable (or a rare native press failure) → AppleScript fallback.
    ok, out = _osa(_CLICK_SCRIPT % {"target": t, "maxd": 32, "maxb": 90, "budget": 6000, "settle": 0.6},
                   timeout=25)
    status, _, detail = (out or "").partition("\t")
    if ok and status.strip() == "ok":
        return f"Clicked {detail.strip() or target}."
    reason = detail.strip() or status.strip() or ("timed out" if not ok else "not found")
    try:
        from vox import assistant
        assistant._dbg("[click]", f"click_element({target!r}) [osa] → {reason}")
    except Exception:
        pass
    return f"I couldn't find a '{target}' to click."


# Collect the labels of on-screen elements the user could plausibly click — for giving the brain
# VISIBILITY of what's actually on screen so it can disambiguate (e.g. realise "github" is a Slack
# channel to CLICK, not a website to open). Same Electron AX unlock + deep walk as the click engine;
# filtered to interactive-ish roles and capped/early-stopped so it stays bounded on huge web trees.
_CLICKABLE_LIST_SCRIPT = '''
property gItems : {}
property gVisited : 0

on collect(el, depth)
    if depth > %(maxd)d then return
    if (count of gItems) is greater than or equal to %(limit)d then return
    set gVisited to gVisited + 1
    if gVisited > %(budget)d then return
    -- Read ROLE first; only read NAME for interactive roles. The tree is mostly structural
    -- AXGroup/AXWebArea nodes — skipping their name read is what keeps this bounded on Electron.
    set r to "?"
    try
        tell application "System Events" to set r to role of el
    end try
    if r is in {"AXButton", "AXLink", "AXMenuItem", "AXMenuBarItem", "AXCheckBox", "AXRadioButton", "AXTabButton", "AXPopUpButton", "AXStaticText", "AXRow", "AXCell", "AXTextField", "AXHeading", "AXDisclosureTriangle"} then
        set nm to ""
        try
            tell application "System Events" to set nm to (name of el) as text
        end try
        if nm is not missing value and nm is not "" and (length of nm) is less than 60 then
            if gItems does not contain nm then set end of gItems to nm
        end if
    end if
    set kids to {}
    try
        tell application "System Events" to set kids to UI elements of el
    end try
    set total to count of kids
    set n to total
    if n > %(maxb)d then set n to %(maxb)d
    repeat with i from 1 to n
        my collect(item i of kids, depth + 1)
    end repeat
end collect

set gItems to {}
set gVisited to 0
tell application "System Events"
    set p to first process whose frontmost is true
    try
        tell p to set value of attribute "AXManualAccessibility" to true
    end try
end tell
delay %(settle).1f
tell application "System Events"
    set p to first process whose frontmost is true
    try
        set root to front window of p
    on error
        set root to p
    end try
end tell
my collect(root, 0)
set AppleScript's text item delimiters to linefeed
return (gItems as text)
'''


def clickable_targets(limit: int = 300) -> list[str]:
    """Labels of on-screen elements the user could click in the focused app (deduped, capped).
    Uses the fast native AX engine (``vox.ax``); falls back to the AppleScript walk only if native AX
    is unavailable. Used to give the brain a view of what's clickable so it can disambiguate. Returns
    ``[]`` on any failure (never raises).

    Reads the FRAMED enumeration (``targets_with_frames``) rather than ``targets()``, for two reasons
    found while diagnosing a failed "click Alex's second last message":
      1. ``targets()`` lists elements with no on-screen frame at all — a closed menu's items are
         zero-size, and on Slack **177 of its 190 labels** were invisible menu entries. The brain was
         being asked to pick from things the user cannot see.
      2. The old cap of 60, spent depth-first, never got past the sidebar: the brain was handed 60
         channel/toolbar labels and not one message, then blamed for not finding the message.
    Same source as the numbered overlay, so what the brain can pick == what a badge is drawn on."""
    try:
        from vox import targets
        framed = targets.visible_targets(limit=limit)
        res = None if framed is None else _dedupe([i["label"] for i in framed])
    except Exception:
        res = None
    if res is not None:
        return res

    ok, out = _osa(_CLICKABLE_LIST_SCRIPT
                   % {"maxd": 30, "maxb": 90, "limit": limit, "budget": 4000, "settle": 0.6},
                   timeout=30)
    if not ok or not out:
        return []
    return _dedupe(line.strip() for line in out.splitlines())


def _dedupe(names) -> list[str]:
    """Order-preserving de-duplication of element labels."""
    seen, items = set(), []
    for name in names:
        if name and name not in seen:
            seen.add(name)
            items.append(name)
    return items


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


def _reload(_: str) -> str:
    """Reload the current page — ⌘R. There was no reload command at all until 2026-08-03, which is
    why "refresh" could never be taught as one: the brain had to fall back to CLICKing the browser's
    reload button, which only works while that button is in the accessibility tree.

    Unlike ``_back``/``close_tab`` this does NOT activate the browser first — reload is the one the
    user is most likely to say while the browser is already in front, and stealing focus to the
    browser when it isn't would reload a page they weren't looking at."""
    front = frontmost_app()
    target = front if front in _CHROMIUM or front == "Safari" else CONFIG.browser
    ok, out = _osa(f'tell application "{target}" to activate\n'
                   'tell application "System Events" to keystroke "r" using command down')
    return "Reloaded." if ok else (_perm_msg() if _is_perm_err(out) else f"Couldn't reload ({out}).")


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

    # Literal escape: "literally <words>" types the rest VERBATIM, so you can dictate a phrase that
    # would otherwise be a command (e.g. "literally delete line" types the words "delete line").
    m = re.match(r"(?i)^literally\s+(.+)$", raw)
    if m:
        lit = m.group(1).strip()
        if _dictation_new_sentence and lit[:1].islower():
            lit = lit[0].upper() + lit[1:]
        _paste((" " if _dictation_active else "") + lit)
        _dictation_active = True
        _dictation_new_sentence = lit.rstrip()[-1:] in ".!?"
        return

    # Bigger deletions + undo. These match the WHOLE utterance only (like the edit keys below), so
    # they never fire mid-sentence — say them on their own to use them, dictate them in a sentence
    # to type them. delete word / delete N words / delete the last five words → ⌥⌫ (per word).
    m = re.fullmatch(r"(?:delete|remove|scratch|erase)\s+(?:the\s+)?(?:last\s+)?(?:(\w+)\s+)?words?", low)
    if m:
        n = (_to_index(m.group(1)) if m.group(1) else 1) or 1
        n = max(1, min(n, 50))  # cap so a mis-hear can't wipe the doc
        _osa('tell application "System Events"\n'
             f'repeat {n} times\nkey code 51 using {{option down}}\nend repeat\nend tell')
        return
    if low in ("delete line", "delete the line", "delete this line", "delete the current line",
               "delete current line", "delete a line"):
        _osa('tell application "System Events" to key code 51 using {command down}')  # ⌘⌫ to line start
        _dictation_active = False
        return
    if low in ("delete paragraph", "delete the paragraph", "delete this paragraph", "delete a paragraph"):
        # Select to the start of the paragraph (⌥⇧↑) then delete the selection.
        _osa('tell application "System Events"\n'
             'key code 126 using {option down, shift down}\nkey code 51\nend tell')
        _dictation_active = False
        return
    if low in ("undo", "undo that", "undo it"):
        _osa('tell application "System Events" to keystroke "z" using {command down}')  # ⌘Z
        _dictation_active = False
        return
    if low in ("redo", "redo that", "redo it"):
        _osa('tell application "System Events" to keystroke "z" using {command down, shift down}')  # ⌘⇧Z
        return

    # spoken edit words -> (key code, modifier). "new/next line" is a SOFT newline
    # (Shift+Return) so it doesn't *send* in chat apps; "enter"/"send" is a plain Return.
    specials = {
        "new line": (36, "shift down"), "newline": (36, "shift down"),
        "next line": (36, "shift down"), "new paragraph": (36, "shift down"),
        "enter": (36, ""), "return": (36, ""), "send": (36, ""), "submit": (36, ""),
        "backspace": (51, ""), "delete": (51, ""), "delete that": (51, ""), "tab key": (48, ""),
    }
    # A retry Whisper batched into ONE chunk ("enter, enter") matched nothing, so saying it again
    # made things WORSE, not better — the loop that has you saying "enter" six times. Collapse a
    # repeated edit word back to one. Whole-utterance only, so dictating the word mid-sentence is
    # untouched, and it fires ONCE: the repeats were retries, not a request for six newlines.
    key = re.sub(r"\s+", " ", re.sub(r"[,;]+", " ", low)).strip()
    if key not in specials:
        for phrase in specials:
            esc = re.escape(phrase)
            if key and re.fullmatch(rf"{esc}(?:\s+{esc})+", key):
                key = phrase
                break
    if key in specials:
        code, mod = specials[key]
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
    "to click",  # click_element found no labelled control → escalate to the LLM + AX-tree click
)


def failed(result: str) -> bool:
    """True if a handle() result looks like a 'no such target' failure worth escalating to the brain."""
    r = result.lower()
    return any(m in r for m in _FAIL_MARKERS)


def _handoff(what: str) -> str:
    # Anything the deterministic layer can't handle. CONTROL mode escalates this to the
    # executor / assistant (see core/loop.py); this string is just the fallback wording.
    return f"Not sure how to do that: {what!r}"


# --- desktop primitives: scroll · press · right/double click · drag · set (idea #61) -------------
# These gestures already existed inside the agent tier (`agent.py`), which is gated off, needs an
# API key and spends a model round-trip deciding to use them. Here they're deterministic commands:
# "scroll down" is a CGEvent, not a conversation. `vox.input` holds the synthesis; this layer is
# only the spoken-argument parsing and the human-readable result.

def _scroll(arg: str) -> str:
    """"down:5" · "up:3" · "top" · "bottom" · "pageup" · "pagedown"."""
    from vox import input as vox_input
    a = (arg or "down:5").strip().lower()
    if a in ("top", "bottom"):
        # ⌘↑/⌘↓ jumps to the end in most apps; a fixed number of wheel ticks never quite does.
        res = vox_input.press("command+up" if a == "top" else "command+down")
        return f"scrolled to the {a}" if not res.startswith("failed") else res
    if a in ("pageup", "pagedown"):
        res = vox_input.press(a)
        return ("paged up" if a == "pageup" else "paged down") if not res.startswith("failed") else res
    direction, _, amount = a.partition(":")
    try:
        n = int(amount) if amount else 5
    except ValueError:
        n = 5
    return vox_input.scroll(direction or "down", n)


def _press(arg: str) -> str:
    """Press a spoken key combination — "command s", "escape", "control option t"."""
    from vox import input as vox_input
    if not (arg or "").strip():
        return "Press what? Try 'press command S'."
    return vox_input.press(arg)


def _resolve_point(target: str):
    """(label, (cx, cy)) for a spoken click target — a badge number from the overlay ("14") or a
    control label in the AX tree ("Submit"). None when neither finds it."""
    from vox import ax
    t = (target or "").strip().lower().rstrip(".")
    n = int(t) if t.isdigit() else _to_index(t)
    hit = ax.frame_index(n - 1) if n is not None else None
    if hit is None and not t.isdigit():
        hit = ax.frame_of(target)
    if hit is None:
        return None
    label, (x, y, w, h) = hit
    return (label, (x + w / 2.0, y + h / 2.0))


def _click_variant(target: str, button: str, clicks: int, verb: str) -> str:
    from vox import input as vox_input
    if not (target or "").strip():
        return f"{verb.capitalize()} what? Try '{verb} Submit'."
    hit = _resolve_point(target)
    if hit is None:
        return f"I couldn't find anything to click called {target!r}."
    label, (cx, cy) = hit
    try:
        vox_input.click_at(cx, cy, button=button, clicks=clicks)
    except Exception as exc:
        return f"failed: couldn't {verb} {label!r} ({exc})."
    return f"{verb}ed {label}"


def _right_click(target: str) -> str:
    return _click_variant(target, "right", 1, "right-click")


def _double_click(target: str) -> str:
    return _click_variant(target, "left", 2, "double-click")


def _drag(arg: str) -> str:
    """"source||destination" — either side a badge number or a control label."""
    from vox import input as vox_input
    src, _, dst = (arg or "").partition("||")
    if not src.strip() or not dst.strip():
        return "Drag what where? Try 'drag 3 to 7'."
    a, b = _resolve_point(src), _resolve_point(dst)
    if a is None:
        return f"I couldn't find anything called {src.strip()!r} to drag."
    if b is None:
        return f"I couldn't find anywhere called {dst.strip()!r} to drop it."
    try:
        vox_input.drag(a[1][0], a[1][1], b[1][0], b[1][1])
    except Exception as exc:
        return f"failed: couldn't drag ({exc})."
    return f"dragged {a[0]} to {b[0]}"


def _set_value(arg: str) -> str:
    """"label||value" — set a slider, text field, checkbox or dropdown directly."""
    from vox import ax
    label, _, value = (arg or "").partition("||")
    if not label.strip() or not value.strip():
        return "Set what to what? Try 'set volume to 30'."
    try:
        res = ax.set_value(label.strip(), value.strip())
    except Exception as exc:
        return f"failed: couldn't set that ({exc})."
    if res is None:
        return "failed: the accessibility engine isn't available."
    status, name = res
    if status == "set":
        return f"set {name} to {value.strip()}"
    if status == "not_found":
        return f"I couldn't find a control called {label.strip()!r} to set."
    return f"failed: found {name!r} but couldn't set it."
