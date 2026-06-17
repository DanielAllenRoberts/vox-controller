"""Deterministic command actions for CONTROL mode: open apps, go to websites."""

import re
import subprocess
import urllib.parse

# Spoken name -> actual macOS app name, where they differ.
_APP_ALIASES = {
    "chrome": "Google Chrome",
    "google chrome": "Google Chrome",
    "vs code": "Visual Studio Code",
    "vscode": "Visual Studio Code",
    "code": "Visual Studio Code",
}

# Spoken site name -> URL, for "go to ...".
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


def handle(text: str) -> str:
    """Interpret a control-mode utterance and act. Returns a human-readable result."""
    intent = parse(text)
    if intent is None:
        return f"no command matched: {text!r}"
    name, arg = intent
    if name == "open_app":
        return _open_app(arg)
    if name == "go_to":
        return _go_to(arg)
    return f"unknown intent: {name}"


def parse(text: str) -> tuple[str, str] | None:
    """Map an utterance to an (intent, argument) pair, or None. Requires a verb.

    Uses search (not match) so a leaked wake word — "hey vox, open cursor" — still
    finds the command.
    """
    t = text.lower().strip().rstrip(".!?")
    m = re.search(r"\bopen\s+(?:the\s+)?(?:app\s+)?(.+)", t)
    if m:
        app = re.sub(r"\s+app$", "", m.group(1).strip())  # "calculator app" -> "calculator"
        return ("open_app", app)
    m = re.search(r"\bgo\s*to\s+(.+)", t)
    if m:
        return ("go_to", m.group(1).strip())
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


def _open_app(app: str) -> str:
    name = resolve_app_name(app)
    result = subprocess.run(["open", "-a", name], capture_output=True, text=True)
    if result.returncode == 0:
        return f"Opening {name}."
    return f"Couldn't open {name!r} ({result.stderr.strip() or 'not found'})."


def _app_exists(name: str) -> bool:
    """True if an app with this name is installed — resolved via LaunchServices, no launch."""
    r = subprocess.run(["osascript", "-e", f'id of app "{name}"'], capture_output=True, text=True)
    return r.returncode == 0


def _go_to(target: str) -> str:
    # "go to X": prefer an installed app, else treat X as a website.
    name = resolve_app_name(target)
    if _app_exists(name):
        subprocess.run(["open", "-a", name], capture_output=True, text=True)
        return f"Opening {name}."
    url, confident = resolve_url(target)
    subprocess.run(["open", url], capture_output=True, text=True)
    if confident:
        return f"Going to {url}."
    # Low confidence: today we flag it; once the assistant is wired (M4) this is
    # where we hand off ("did you mean …?"). See docs/plan/observations.md.
    return f'Going to {url} — but I wasn\'t sure; say "open <name>" if I misheard.'
