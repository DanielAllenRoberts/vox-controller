"""Deterministic command actions for CONTROL mode. Start small: open macOS apps."""

import re
import subprocess


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
    """Map an utterance to an (intent, argument) pair, or None. Requires a verb."""
    t = text.lower().strip().rstrip(".!?")
    m = re.match(r"(?:please\s+)?open\s+(?:the\s+)?(?:app\s+)?(.+)", t)
    if m:
        app = re.sub(r"\s+app$", "", m.group(1).strip())  # "calculator app" -> "calculator"
        return ("open_app", app)
    return None


def _open_app(app: str) -> str:
    name = app.title()
    result = subprocess.run(["open", "-a", name], capture_output=True, text=True)
    if result.returncode == 0:
        return f"Opening {name}."
    return f"Couldn't open {name!r} ({result.stderr.strip() or 'not found'})."
