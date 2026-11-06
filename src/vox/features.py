"""The feature list behind Insights → Testing: everything built that a person should try by hand.

Each entry says how to test it and how far it has been checked so far:
  * ``"code"``: unit tests / API checks / screenshots only. Nobody has used it for real.
  * ``"claude"``: Claude ran it for real in the app or engine.
The user's own verdicts (works / broken / partly) and comments are stored separately, in
``<data>/feature-tests.json``, so they survive this list being edited.

Add an entry here whenever something user-facing is built. Remove one only when the feature is gone.
"""

from __future__ import annotations

import json
import threading
import time

from vox.paths import DATA_DIR

_STORE = DATA_DIR / "feature-tests.json"
_LOCK = threading.Lock()

STATUSES = ("untested", "works", "partly", "broken")

# (id, area, title, how to test, checked)
FEATURES: list[tuple[str, str, str, str, str]] = [
    # --- Vox.app -------------------------------------------------------------------------------
    ("app-setup", "Vox.app", "First-run setup",
     "Run Setup Again (Settings → Advanced). Every step's blue button should do the next thing and never be greyed out with no explanation.", "code"),
    ("setup-voice", "Vox.app", "Setup: pick a voice",
     "Run Setup Again → the 'Pick a voice' step. Press play on a few: each speaks a short line in that voice. Tapping one makes it Vox's voice.", "code"),
    ("setup-about-you", "Vox.app", "Setup: a little about you",
     "Run Setup Again → 'A little about you' asks 3 questions based on your installed apps. Answer one, Continue, then check Memory → Long-term: it's saved.", "code"),
    ("app-menubar", "Vox.app", "Menu bar icon and panel",
     "Click the waveform in the menu bar: state, type box, last reply, Listening / Speak replies switches, Open Vox, Settings, Quit.", "code"),
    ("app-type", "Vox.app", "Type to Vox",
     "Type 'open safari' on Home or in the menu bar. It runs as if spoken; the reply appears under 'Vox said'.", "code"),
    ("app-pause", "Vox.app", "Pause listening",
     "Home → Pause (or Listening off in the menu bar): Vox ignores speech, typing still works. Resume turns it back on.", "code"),
    ("app-close-quit", "Vox.app", "Closing vs quitting",
     "Closing the window keeps Vox in the menu bar. Quit stops listening. Saying 'quit Vox' stays quit (it doesn't come back).", "code"),
    ("app-settings", "Vox.app", "Settings window",
     "⌘, → each tab makes sense. Model menus only show models the provider can run. After a 'restart' setting, a Restart Now bar appears.", "code"),
    ("app-permissions", "Vox.app", "Permissions survive rebuilds",
     "After an app update, Microphone and Accessibility are still allowed (no re-prompt).", "claude"),
    ("app-conversation", "Vox.app", "Conversation page",
     "Oldest at the top, newest at the bottom, updates live while you talk.", "claude"),
    ("app-reminders-page", "Vox.app", "Reminders page shows what you set by voice",
     "Say 'remind me in 5 minutes to stretch', open Reminders: it's there (refreshes when the page opens).", "code"),
    ("app-voicelab", "Vox.app", "Voice Lab",
     "Record a phrase: it's transcribed and named, Vox doesn't react while recording, play/delete work.", "code"),
    ("app-holdtotalk", "Vox.app", "Hold Right ⌥ to talk",
     "Hold, speak, let go: runs immediately, no wake word. ⌥-shortcuts still work.", "code"),
    # --- Voice & speed ------------------------------------------------------------------------
    ("barge-in-real-speech", "Voice & speed", "Typing doesn't interrupt Vox",
     "While Vox is speaking a reply, type on your keyboard: it keeps talking. Saying 'stop' or 'wait' still cuts it off.", "claude"),
    ("fast-wake", "Voice & speed", "Fast wake",
     "Say 'hey vox': the ready sound comes about half a second sooner than before.", "code"),
    ("small-brain-fast", "Voice & speed", "Quick replies are faster",
     "Commands the parser doesn't know ('refresh page') answer in about 1 s.", "claude"),
    ("claude-sdk-warm", "Voice & speed", "Claude subscription brain is faster",
     "With Quick replies on 'Claude subscription', commands answer in about 1 s (was about 5 s).", "claude"),
    ("whisper-cpu", "Voice & speed", "Lower CPU while listening",
     "Activity Monitor: Vox's python well under 200% while you talk.", "code"),
    ("smart-turn", "Voice & speed", "Smarter end-of-sentence (opt in)",
     "Settings → Listening → End of sentence → Smart. Pausing mid-thought shouldn't cut you off.", "code"),
    # --- Control ------------------------------------------------------------------------------
    ("click-sidebars", "Control", "Click sidebar items (Vox, Finder, Mail…)",
     "In Vox.app say 'click on memory'. 'show clickable' numbers the sidebar items too.", "code"),
    ("browser-follow", "Control", "Browser commands use YOUR browser",
     "In Zen: 'show tabs', 'next tab', 'first tab', 'go to my github tab'. Arc must not open.", "code"),
    ("pointing", "Control", "Point at things on screen",
     "'point at the export button' / 'circle the save button': a ring flies there and fades.", "code"),
    ("auto-dictation", "Control", "Dragon-style typing (off by default)",
     "Settings → Control → Typing on. In a text box, speech is typed; whole commands still run; 'scratch that' undoes.", "code"),
    ("no-greedy-commands", "Control", "Commands don't fire mid-sentence",
     "'I think we should go back to the old design' must NOT press Back.", "code"),
    ("board-multi", "Control", "Several board changes at once",
     "'add buy milk, call the plumber and book flights to my to do list' → three cards.", "code"),
    ("board-safe-delete", "Control", "Vague deletes ask first",
     "'remove the call' → 'Did you mean …?' and nothing is deleted.", "claude"),
    ("vision-check", "Control", "Vision clicks double-check",
     "If vision picks a differently named button, Vox asks 'Did you mean …?' instead of clicking.", "claude"),
    ("input-primitives", "Control", "Scroll / press keys / right-click / drag",
     "'scroll down', 'press command R', 'right click Submit', 'drag 3 to 7'.", "code"),
    ("log-issue", "Control", "Log an issue by voice",
     "Say 'log an issue, <what went wrong>'. Vox says 'Logged it' and it appears under Testing → Logged issues with what was on screen.", "code"),
    ("point-vision", "Control", "Pointing looks at the screen",
     "'point at <something only visible, not a button>': if it's not found by name, Vox looks at the screen and rings it.", "code"),
    ("media-background", "Control", "Music control in the background",
     "With Spotify playing behind another app: 'pause the music', 'play music', 'next song', 'previous track'. Spotify must NOT come to the front.", "code"),
    ("prompts-page", "Vox.app", "Prompts page",
     "Teach Vox → Prompts: read each prompt; edit one, Save, Reset to Default. 'Last Sent' shows exactly what the model got after you use Vox.", "code"),
    ("app-notes", "Control", "Notes for one app",
     "Rules page: add 'refresh means press command R' set to Zen. In Zen say 'refresh' → ⌘R. Or say 'from now on in Zen, when I say refresh press command R'.", "code"),
    ("quit-app", "Control", "Close an app",
     "'close Notion' quits Notion (not a browser tab). 'close tab' still closes a tab.", "code"),
    ("specific-app", "Control", "Open the right app",
     "'open Notion Calendar' opens Notion Calendar, not Notion.", "code"),
    ("ptt-no-cutoff", "Vox.app", "Hold-to-talk never cuts you off",
     "Hold Right ⌥ and talk for 30+ seconds: no click mid-way; it sends when you let go.", "code"),
    ("voice-settings", "Control", "Change settings by voice",
     "'reply silently from now on' → no spoken replies; 'speak replies again' → back. Also 'use a deeper voice', 'stop learning commands'. Asking to change the brain is refused.", "claude"),
    ("time-answer", "Voice & speed", "Knows the time",
     "'Hey Vox, what time is it?' → the right time.", "claude"),
    ("wake-plus-question", "Voice & speed", "Wake word + question in one breath",
     "'Hey Vox what's the weather like' in one go: it answers, instead of waking and waiting for you to ask again.", "code"),
    ("learning-quality", "Control", "Learned commands make sense",
     "Commands → Learning: no stutters ('open arc open arc'), rants, corrections or phrasings Vox already understood. Odd ones wait for a second sighting.", "code"),
    # --- Agents -------------------------------------------------------------------------------
    ("agent-alerts", "Agents", "'David needs you' alerts",
     "Add the hook from mcp/README.md; a registered agent waiting on a permission shows a bubble naming it.", "code"),
    ("named-agents", "Agents", "Named agents speak as themselves",
     "'your name is David, register yourself' → announcements say 'David here'.", "code"),
]


def _read() -> dict:
    try:
        return json.loads(_STORE.read_text())
    except Exception:
        return {}


def all_features() -> list[dict]:
    notes = _read()
    out = []
    for fid, area, title, how, checked in FEATURES:
        n = notes.get(fid, {})
        out.append({"id": fid, "area": area, "title": title, "how": how, "checked": checked,
                    "status": n.get("status", "untested"), "comment": n.get("comment", ""),
                    "updated": n.get("updated")})
    return out


def update(fid: str, status: str | None = None, comment: str | None = None) -> dict:
    if fid not in {f[0] for f in FEATURES}:
        raise KeyError(fid)
    if status is not None and status not in STATUSES:
        raise ValueError(f"status must be one of {', '.join(STATUSES)}")
    with _LOCK:
        notes = _read()
        n = notes.get(fid, {})
        if status is not None:
            n["status"] = status
        if comment is not None:
            n["comment"] = comment.strip()
        n["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        notes[fid] = n
        _STORE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _STORE.with_suffix(".tmp")
        tmp.write_text(json.dumps(notes, indent=2))
        tmp.replace(_STORE)
    return next(f for f in all_features() if f["id"] == fid)
