"""Setup helpers for Vox.app's onboarding: voice previews and the "get to know you" step.

Get-to-know-you looks at which apps are installed (names only: nothing inside them is read) and asks
the small brain for a few friendly, specific questions ("I see Logic Pro: do you make music?"). The
answers are saved as long-term memories, so Vox starts out knowing a little about the person and
keeps learning from there. Everything is optional, and a brain failure falls back to standard
questions.
"""

from __future__ import annotations

import json
import os
import re
import threading

PREVIEW_TEXT = "Hi, I'm Vox. This is how I'll sound when I answer you."

# Built-in and system apps say nothing about the person.
_BORING = {
    "Safari", "Mail", "Calendar", "Contacts", "Reminders", "Notes", "Maps", "Photos", "Messages",
    "FaceTime", "Music", "Podcasts", "TV", "News", "Stocks", "Books", "App Store", "System Settings",
    "System Preferences", "Preview", "TextEdit", "Calculator", "Chess", "Clock", "Weather", "Home",
    "Freeform", "Shortcuts", "Siri", "Time Machine", "Font Book", "Image Capture", "Photo Booth",
    "Stickies", "Dictionary", "Automator", "Mission Control", "Launchpad", "Finder", "Utilities",
    "Vox", "Find My", "Tips", "Journal", "Passwords", "Image Playground", "iPhone Mirroring",
    "Phone", "Games", "Preview", "Screenshot", "Migration Assistant", "Boot Camp Assistant",
}

_FALLBACK_QUESTIONS = [
    "What should I call you?",
    "What do you mostly use your Mac for: work, study, making things, something else?",
    "Is there anything you'd like me to help you with most?",
]


def installed_apps(limit: int = 120) -> list[str]:
    names: set[str] = set()
    for d in ("/Applications", "/Applications/Utilities", os.path.expanduser("~/Applications")):
        try:
            for f in os.listdir(d):
                if f.endswith(".app"):
                    names.add(f[:-4])
        except Exception:
            pass
    return sorted(n for n in names if n not in _BORING)[:limit]


def preview(engine: str, voice: str) -> None:
    """Say the preview line in a voice, in the background. No AI involved."""
    from vox import tts

    def run():
        try:
            if engine == "say":
                tts.speak_with(PREVIEW_TEXT, engine="say", say_voice=voice, label="preview")
            else:
                tts.speak_with(PREVIEW_TEXT, engine="kokoro", kokoro_voice=voice, label="preview")
        except Exception:
            pass
    threading.Thread(target=run, daemon=True).start()


def questions() -> dict:
    """{"observation": str, "questions": [str], "apps": [str]} for the get-to-know-you step."""
    apps = installed_apps()
    if not apps:
        return {"observation": "", "questions": _FALLBACK_QUESTIONS, "apps": []}
    prompt = (
        "These are the apps installed on someone's Mac (Apple's built-in apps removed):\n"
        + ", ".join(apps)
        + "\n\nYou are Vox, their new voice assistant, meeting them for the first time. Write ONE short, "
        "warm sentence noticing 2-3 apps that say something about them, then exactly three short "
        "questions. The first asks what to call them. Each of the other two must NAME the app that "
        "prompted it and ask plainly about it, in the form \"I saw you have <App>: <question>?\" "
        "(for example \"I saw you have <App>: do you use it for work or for fun?\"). Pick the apps that "
        "say the most about the person, whatever field they're in. Never state guesses about them as "
        "facts; ask. Reply as JSON only: "
        '{"observation": "...", "questions": ["...", "...", "..."]}'
    )
    try:
        from vox import assistant
        raw = assistant.complete(prompt, brain="small", kind="onboarding",
                                 system="Reply with compact JSON only. No markdown.")
        m = re.search(r"\{.*\}", raw or "", re.S)
        data = json.loads(m.group(0)) if m else {}
        qs = [str(q).strip() for q in data.get("questions", []) if str(q).strip()][:3]
        if len(qs) >= 2:
            return {"observation": str(data.get("observation", "")).strip(), "questions": qs, "apps": apps}
    except Exception:
        pass
    return {"observation": "", "questions": _FALLBACK_QUESTIONS, "apps": apps}


def save_answers(answers: list[dict]) -> int:
    """Store each answered question as a long-term memory. Returns how many were saved."""
    from vox import memory
    n = 0
    for qa in answers or []:
        q, a = str(qa.get("question", "")).strip(), str(qa.get("answer", "")).strip()
        if not a:
            continue
        memory.add(f"Asked during setup: {q} They said: {a}", tier="core", tags=["about-me", "setup"])
        n += 1
    return n
