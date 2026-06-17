"""Deterministic command actions for CONTROL mode: open apps and go to apps/websites."""

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

# Spoken site name -> URL, for website navigation.
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
}

# Chromium-family browsers share an AppleScript dictionary for tab creation.
_CHROMIUM = {"Arc", "Google Chrome", "Brave Browser", "Microsoft Edge", "Chromium"}


def handle(text: str) -> str:
    """Interpret a control-mode utterance and act. Returns a human-readable result."""
    intent = parse(text)
    if intent is None:
        return f"no command matched: {text!r}"
    name, arg = intent
    if name == "navigate":
        return _navigate(arg)
    return f"unknown intent: {name}"


def parse(text: str) -> tuple[str, str] | None:
    """Map an utterance to an (intent, argument) pair, or None.

    "open X" and "go to X" both navigate — to the app if installed, else a website.
    Uses search (not match) so a leaked wake word — "hey vox, open cursor" — still works.
    """
    t = text.lower().strip().rstrip(".!?")
    m = re.search(r"\b(?:open|go\s*to)\s+(?:the\s+)?(?:app\s+)?(.+)", t)
    if m:
        target = re.sub(r"\s+app$", "", m.group(1).strip())  # "calculator app" -> "calculator"
        return ("navigate", target)
    return None


def resolve_app_name(app: str) -> str:
    return _APP_ALIASES.get(app.lower().strip(), app.title())


def resolve_url(target: str) -> tuple[str, bool]:
    """Return (url, confident). `confident` is False when we're only guessing — the
    hook where a low-confidence target should later escalate to the assistant."""
    t = target.lower().strip().rstrip("/")
    if t in _SITE_ALIASES:
        return _SITE_ALIASES[t], True
    if "." in t:  # already looks like a domain
        return (t if t.startswith("http") else f"https://{t}"), True
    if " " not in t:  # single word -> best-guess .com (a guess)
        return f"https://{t}.com", False
    return "https://www.google.com/search?q=" + urllib.parse.quote_plus(target), False


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
    """Open a URL as a new tab in the preferred browser; fall back to the default opener.

    (`open <url>` lets the browser pick window-vs-tab — Arc opens a new window — so we
    drive the browser via AppleScript to get a tab in the existing window.)
    """
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
    url, confident = resolve_url(target)
    _open_url(url)
    if confident:
        return f"Going to {url}."
    # Low confidence: today we flag it; once the assistant is wired (M4) this is
    # where we hand off ("did you mean …?"). See docs/plan/observations.md.
    return f'Going to {url} — but I wasn\'t sure; say "open <name>" if I misheard.'
