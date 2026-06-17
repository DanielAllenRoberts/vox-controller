"""Deterministic command actions for CONTROL mode. Start small: open macOS apps."""

import re
import subprocess

# Spoken name -> actual macOS app name, where they differ.
_APP_ALIASES = {
    "chrome": "Google Chrome",
    "google chrome": "Google Chrome",
    "vs code": "Visual Studio Code",
    "vscode": "Visual Studio Code",
    "code": "Visual Studio Code",
}


def handle(text: str) -> str:
    """Interpret a control-mode utterance and act. Returns a human-readable result."""
    intent = parse(text)
    if intent is None:
        return f"no command matched: {text!r}"
    name, arg = intent
    if name == "open_app":
        return _open_app(arg)
    return f"unknown intent: {name}"


def parse(text: str) -> tuple[str, str] | None:
    """Map an utterance to an (intent, argument) pair, or None. Requires a verb.

    Uses search (not match) so a leaked wake word — "hey jarvis, open cursor" —
    still finds the command.
    """
    t = text.lower().strip().rstrip(".!?")
    m = re.search(r"\bopen\s+(?:the\s+)?(?:app\s+)?(.+)", t)
    if m:
        app = re.sub(r"\s+app$", "", m.group(1).strip())  # "calculator app" -> "calculator"
        return ("open_app", app)
    return None


def resolve_app_name(app: str) -> str:
    return _APP_ALIASES.get(app.lower().strip(), app.title())


def _open_app(app: str) -> str:
    name = resolve_app_name(app)
    result = subprocess.run(["open", "-a", name], capture_output=True, text=True)
    if result.returncode == 0:
        return f"Opening {name}."
    return f"Couldn't open {name!r} ({result.stderr.strip() or 'not found'})."
