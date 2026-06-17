"""Deterministic command actions for CONTROL mode: open apps, go to apps/sites, search.

Navigation only acts on what it KNOWS (installed app, known site, real domain). Unknown
targets are NOT guessed — they hand off to the assistant. Web search is explicit ("search X").
"""

import re
import subprocess
import urllib.parse

from vox.config import CONFIG

# Spoken name -> actual macOS app name, where they differ.
_APP_ALIASES = {
    "chrome": "Google Chrome",
    "google chrome": "Google Chrome",
    "vs code": "Visual Studio Code",
    "vscode": "Visual Studio Code",
    "code": "Visual Studio Code",
}

# Known spoken site name -> URL. Navigation only opens sites it knows (no guessing).
_SITE_ALIASES = {
    "github": "https://github.com",
    "gmail": "https://mail.google.com",
    "google": "https://google.com",
    "youtube": "https://youtube.com",
    "twitter": "https://x.com",
    "x": "https://x.com",
    "reddit": "https://reddit.com",
    "hacker news": "https://news.ycombinator.com",
    "chatgpt": "https://chatgpt.com",
    "claude": "https://claude.ai",
    "gemini": "https://gemini.google.com",
    "netflix": "https://netflix.com",
    "spotify": "https://open.spotify.com",
    "amazon": "https://amazon.com",
    "maps": "https://maps.google.com",
    "calendar": "https://calendar.google.com",
    "drive": "https://drive.google.com",
    "docs": "https://docs.google.com",
    "notion": "https://notion.so",
    "linear": "https://linear.app",
    "slack": "https://slack.com",
    "figma": "https://figma.com",
    "stack overflow": "https://stackoverflow.com",
    "wikipedia": "https://wikipedia.org",
    "twitch": "https://twitch.tv",
}

# Chromium-family browsers share an AppleScript dictionary for tab creation.
_CHROMIUM = {"Arc", "Google Chrome", "Brave Browser", "Microsoft Edge", "Chromium"}


def handle(text: str) -> str:
    """Interpret a control-mode utterance and act. Returns a human-readable result."""
    intent = parse(text)
    if intent is None:
        return _handoff(text)
    name, arg = intent
    if name == "navigate":
        return _navigate(arg)
    if name == "search":
        return _search(arg)
    return _handoff(text)


def parse(text: str) -> tuple[str, str] | None:
    """Map an utterance to an (intent, argument) pair, or None.

    "open X" / "go to X" both navigate (app if installed, else a known site). "search X"
    runs an explicit web search. Uses search-anywhere so a leaked wake word still works.
    """
    t = text.lower().strip().rstrip(".!?")
    m = re.search(r"\b(?:open|go\s*to)\s+(?:the\s+)?(?:app\s+)?(.+)", t)
    if m:
        target = re.sub(r"\s+app$", "", m.group(1).strip())  # "calculator app" -> "calculator"
        return ("navigate", target)
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
    if "." in t:  # already looks like a domain
        return t if t.startswith("http") else f"https://{t}"
    return None


def _app_exists(name: str) -> bool:
    """True if an app with this name is installed — via LaunchServices, no launch."""
    r = subprocess.run(["osascript", "-e", f'id of app "{name}"'], capture_output=True, text=True)
    return r.returncode == 0


def _browser_tab_script(browser: str, url: str) -> str | None:
    """AppleScript to open `url` as a new tab in the browser's existing front window."""
    if browser in _CHROMIUM or browser == "Safari":
        return (f'tell application "{browser}"\n'
                f'    activate\n'
                f'    tell front window to make new tab with properties {{URL:"{url}"}}\n'
                f'end tell')
    return None


def _open_url(url: str) -> None:
    """Open a URL as a new tab in the preferred browser; fall back to the default opener."""
    script = _browser_tab_script(CONFIG.browser, url)
    if script:
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
        if r.returncode == 0:
            return
    subprocess.run(["open", url], capture_output=True, text=True)


def _navigate(target: str) -> str:
    name = resolve_app_name(target)
    if _app_exists(name):
        subprocess.run(["open", "-a", name], capture_output=True, text=True)
        return f"Opening {name}."
    url = known_url(target)
    if url:
        _open_url(url)
        return f"Going to {url}."
    return _handoff(target)


def _search(query: str) -> str:
    _open_url("https://www.google.com/search?q=" + urllib.parse.quote_plus(query))
    return f"Searching for {query!r}."


def _handoff(what: str) -> str:
    # Anything the deterministic layer can't handle (unknown target, or no command verb
    # at all). Once the assistant (M4) is wired this hands off ("did you mean …?"); for
    # now we just say so. See docs/plan/observations.md.
    return f"Handing off to the assistant (not wired yet): {what!r}"
