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
     "Open Reminders and leave it on screen. Say 'remind me in 5 minutes to stretch': it appears within about 10 seconds, without touching the page.", "code"),
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
     "Say 'log an issue, <what went wrong>'. Vox says 'Issue logged' and it appears under Testing → Logged issues with what was on screen.", "code"),
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
    ("web-weather", "Voice & speed", "Weather",
     "'What's the weather like in Cape Town?' and plain 'what's the weather?' (uses Settings → General → Home location) → a real answer in about 2 s.", "claude"),
    ("web-answers", "Voice & speed", "Answers from the web",
     "'How do I quantize MIDI in Logic Pro?', 'who won the last F1 race?' → a short spoken answer naming the site (6-9 s).", "claude"),
    ("time-answer", "Voice & speed", "Knows the time",
     "'Hey Vox, what time is it?' → the right time.", "claude"),
    ("wake-plus-question", "Voice & speed", "Wake word + question in one breath",
     "'Hey Vox what's the weather like' in one go: it answers, instead of waking and waiting for you to ask again.", "code"),
    ("learning-quality", "Control", "Learned commands make sense",
     "Commands → Learning: no stutters ('open arc open arc'), rants, corrections or phrasings Vox already understood. Odd ones wait for a second sighting.", "code"),
    ("echo-guard", "Voice & speed", "Vox ignores its own voice",
     "Ask something with a long answer on speakers (no headphones): Vox doesn't hear its own reply as you talking, and doesn't cut itself off.", "code"),
    ("mic-after-reply", "Voice & speed", "Mic keeps working after Vox speaks",
     "Have a few back-and-forths with Vox. The log used to show 'mic input stalled' about 3 s after every reply (and Vox missed what you said next); it shouldn't any more. Also watch whether your music volume still drops when Vox talks.", "code"),
    ("output-follows-device", "Voice & speed", "Replies play on the current output",
     "Switch from speakers to headphones (or back) while Vox is running: the next reply plays on the new device without a restart.", "code"),
    ("setup-voice-answers", "Vox.app", "Answer setup questions by voice",
     "Settings → Advanced → Run Setup Again: the main window hides while Setup is open. On 'About you', each question names the app it's about, and the mic button next to it records your answer and types it in.", "code"),
    ("commands-grid", "Vox.app", "Commands by app",
     "Commands opens on a grid of apps with counts; click one for its commands. 'Open GitHub/Gmail…' sit in one collapsed 'Open apps and sites' row. Search still looks across everything. ⌘[ goes back.", "code"),
    ("block-apps", "Control", "Block apps Vox won't open",
     "Commands → Blocked: add Slack (type it, or Choose App…, or right-click a tile). Say 'open Slack' or 'switch to Slack' → Vox refuses and says it's blocked. Unblock with the ×.", "code"),
    ("green-switches", "Vox.app", "Switches are green when on",
     "Every switch (Commands, Rules, Vocabulary, Settings, menu bar) is green when on, even while another app is in front.", "code"),
    ("personality-steady", "Vox.app", "Personality page doesn't jump",
     "Click through several characters: the card at the top stays the same size and the grid doesn't move. 'Show More' opens the full description in a popover.", "code"),
    ("board-deadlines", "Organise", "Card deadlines with reminders",
     "Open a card → Due date → pick a day (and a time). The card shows it (orange when close, red when late) and Vox reminds you at 9:00 that day, or at the time. Clearing the date or archiving removes the reminder. By voice: 'the invoice card is due friday'.", "code"),
    ("board-select", "Organise", "Select several cards",
     "⌘-click cards on the Board, then Move To / Archive / Delete from the bar at the bottom. Esc or Done clears it. Paste several lines into Add Card to add one card per line.", "code"),
    ("board-extras", "Organise", "Tags, checklists, archive, search",
     "Tags get colours; a checklist shows 2/3 on the card; Archive hides a card (toolbar archive button shows them, Restore brings one back); search filters every list. By voice: 'tag the invoice card work', 'add draft it to the invoice checklist', 'archive the invoice card', 'what's due this week?'.", "code"),
    ("shortcuts-menus", "Control", "Shortcuts and menu commands",
     "In any app: 'save this' (⌘S), 'undo that' (⌘Z), 'reopen the tab I closed' (⌘⇧T). For app-specific commands Vox uses the app's own menus: in Zen 'open the developer tools', 'zoom in'; in Pages/Preview 'export as PDF'.", "code"),
    ("memory-quality", "Memory", "Long-term memory keeps facts about you",
     "Hey Vox: 'my sister Jess lives in Durban' and 'remember that I'm vegetarian' → Memory → long-term. 'From now on when I say refresh press command R' and 'remember to call the bank' → not long-term (today's notes only). Saying the same fact twice keeps one.", "code"),
    ("chatgpt-brain", "Vox.app", "ChatGPT as a brain",
     "Settings → Brains → API keys: paste an OpenAI key. Then Quick replies → Provider → ChatGPT; the Model menu lists the models your key can use (read from OpenAI). Ask Vox something: it answers via ChatGPT (Activity shows 'chatgpt').", "code"),
    ("api-keys-settings", "Vox.app", "API keys in Settings",
     "Settings → Brains → API keys shows which keys are saved (never the key itself); paste to add, Remove… to delete. No restart needed.", "code"),
    ("other-one", "Control", "'No, the other one' after a wrong click",
     "Where there are two buttons with the same name (e.g. two 'Reply' links), say 'click Reply'. If it hit the wrong one, say 'no, the other one' within a minute: numbers appear on just the Reply buttons; say the number.", "code"),
    ("live-pages", "Vox.app", "Board and Reminders update by themselves",
     "Open the Board (or Reminders) and leave it on screen. Say 'add a card called test' (or set a reminder): it appears within about 2 seconds, no refresh.", "code"),
    ("units-spoken", "Voice & speed", "Units are said in words",
     "'What's the weather?': Vox says '16 millimetres', '22 degrees Celsius', '15 kilometres per hour', not 'm m' or 'C'.", "code"),
    ("fullscreen-move", "Control", "Move a full-screen window to another screen",
     "With Zen in full screen (green button): 'move Zen to the other screen'. It leaves full screen, moves, and goes full screen again on the other display.", "code"),
    ("multi-screen", "Control", "Move windows between screens",
     "With the iPad (Sidecar) or a second monitor connected: 'move Slack to the iPad', 'move this window to the other screen', 'send it to the main monitor'. Then 'maximise this window', 'snap this to the left half', 'center this window'.", "code"),
    ("setup-connections", "Vox.app", "Setup: connect your apps",
     "Settings → Advanced → Run Setup Again: after picking a voice there's 'Connect your apps' (Mac Calendar, MCP servers such as Composio, Spotify). Everything is optional; Skip works.", "code"),
    ("mcp-connections", "Vox.app", "Connections: add any MCP server",
     "Settings → Connections → Add Connection…: a URL (e.g. your Composio MCP server URL + its key header) or a command. It tests itself and shows the tool count. Then ask 'any new email from Sam?' or 'what's on my Trello?': Vox uses it, and asks 'Should I go ahead?' before sending or changing anything (say yes or no).", "code"),
    ("spotify-now", "Control", "What's playing?",
     "With Spotify (or Music) playing: 'what song is this?' / 'what's playing?' / 'who sings this?'. It says the title and artist.", "code"),
    ("spotify-link", "Control", "Spotify: playlists and adding songs",
     "Settings → General → Spotify: follow the steps (free developer app, paste Client ID, Connect). Then 'play my film score playlist', 'shuffle my focus playlist', 'add this song to my film score playlist', 'play Cataclysm by Tom Dabrowski'.", "code"),
    ("youtube-play-pause", "Control", "Play/pause YouTube only when needed",
     "With a YouTube video in your browser: 'play YouTube' while it's playing → 'It's already playing' (it used to pause it). 'Pause the video' / 'play the video' press YouTube's own button. 'Play music' still means Spotify/Music.", "code"),
    ("pause-mishear", "Control", "'Pose my music' still pauses",
     "With music playing: 'Vox, pause my music' (it's often heard as 'pose'). It pauses, and never presses Space in the app in front.", "code"),
    ("reminders-wait", "Organise", "Reminders wait until you're back",
     "Say 'remind me in 2 minutes to stretch', then lock the screen (or leave the Mac) for 7 minutes. Nothing is said while you're away; when you're back it says 'While you were away: …'. Alarms and timers still go off on time. Settings → General → Reminders.", "code"),
    ("routines", "Organise", "Routines",
     "Say 'every weekday at 7, tell me what's on my calendar and the weather' (or Reminders → + → Routine). It shows under Reminders → Routines; press ▶ to run it now: a short spoken briefing. Also try 'every day at 9 check my calendar and board and tell me what to work on', and 'every morning at 8 open my email'.", "code"),
    ("calendar", "Organise", "Calendar access (Google via Composio, or the Mac's Calendar)",
     "Settings → Brains → API keys → Composio: paste your project key from dashboard.composio.dev (your Google Calendar is already connected there). Then 'what's on my calendar today?' and routines read it. The Mac's Calendar (Settings → Permissions) works too, and both are merged.", "code"),
    ("core-prompt", "Vox.app", "Master prompt (Core)",
     "Teach Vox → Prompts → 'Core: what Vox is': one prompt about who Vox is, what it can do and how it behaves, sent above the router, chat, screen questions, routines and the agent (each says 'Sent with Core above it'). Ask 'Hey Vox, what can you do?': a real overview, using your name.", "code"),
    ("guide-page", "Vox.app", "Guide page",
     "Sidebar → Guide: every feature grouped by area, what it does, phrases to say (click one to copy), where it lives. Search for 'board' or 'pause'.", "code"),
    ("stop-button", "Vox.app", "Stop button (⏹)",
     "While Vox is speaking a long reply, or thinking about a request, press ⏹ next to the type box (menu bar panel or Home), or ⌘. there. It stops at once and keeps listening. Hover shows what it stopped.", "code"),
    ("board-counts", "Organise", "Several board changes are summed up",
     "Say 'delete the test cards' (or add several at once): Vox says 'Deleted 4 cards.' instead of reading every title.", "code"),
    ("one-engine", "Voice & speed", "Dictation types each word once",
     "'Start typing', say 'testing', 'stop typing'. It types 'Testing.' once (a second engine left over from a restart was typing everything twice).", "code"),
    ("short-term-memory", "Memory", "Vox remembers what was just said and done",
     "Ask 'add a card called buy ink', then separately 'move it to Doing': it moves THAT card. Or say a name, then later 'what was that name again?'. Works across one-shots, typed and spoken turns, and survives a restart (last 30 minutes).", "code"),
    ("memory-updates", "Memory", "Changed facts are updated, not doubled",
     "'Remember that my favourite band is Muse', later 'remember that my favourite band is Radiohead now'. The Memory page shows only Radiohead. A second, different fact ('I also love jazz') is kept alongside.", "code"),
    ("memory-dream", "Memory", "Memory tidied overnight",
     "Mention something lasting in passing ('we just moved to Cape Town', 'I've started learning piano'). The next morning (after 3 a.m., or when the Mac wakes) the Memory page has it, and an old fact it replaces is updated. Settings → Control → Memory → Tidy memory overnight turns it off.", "code"),
    ("board-undo", "Organise", "Put deleted cards back",
     "Say 'delete the test cards' (or 'clear my board'), then 'put them all back': each comes back to its old column with its notes, tags, deadline and checklist.", "code"),
    # --- The basics (built before the app; never had a test entry) -----------------------------
    ("basics-modes", "Basics", "Wake, control, sleep",
     "'Hey Vox' → it listens for a question. 'Take control' → say commands one after another. 'Stand down' or 'go to sleep' → back to idle.", "code"),
    ("basics-oneshot", "Basics", "One command from idle",
     "From idle: 'Vox, open Safari'. It does it and stays idle, no mode switch.", "code"),
    ("basics-dictation", "Basics", "Dictation",
     "Click into a text field. 'Start typing', speak a sentence, 'new line', another, then 'stop typing'.", "code"),
    ("basics-open", "Basics", "Open apps, websites and searches",
     "'Open Notes', 'go to github', 'search best pizza near me'. Opens in your own browser.", "code"),
    ("basics-tabs", "Basics", "Tabs and windows",
     "'Go to my GitHub tab', 'next tab', 'previous tab', 'close tab', 'next window', 'Cursor window', 'go back'.", "code"),
    ("basics-profiles", "Basics", "Browser spaces (Zen and Arc)",
     "In Zen: 'profile 1', 'profile 2', 'next profile', 'switch to the GetPrice space'. Uses Zen's own Spaces menu, so it lands on the right one.", "code"),
    ("basics-compose", "Basics", "Write text for you",
     "Click into a message box: 'write a short note to Sam saying I'll be ten minutes late'. It types the finished text at the cursor.", "code"),
    ("basics-rewrite", "Basics", "Rewrite selected text",
     "Select a paragraph: 'make this more formal' or 'fix the spelling'. The selection is replaced with the rewrite.", "code"),
    ("basics-look", "Basics", "Questions about the screen",
     "'What's on my screen?', 'read this error to me', 'what is this article about?'.", "code"),
    ("basics-click", "Basics", "Click by name",
     "'Click Send', 'click the search box', 'click Downloads' in Finder's sidebar.", "code"),
    ("basics-show-clickable", "Basics", "Numbered click badges",
     "'Show clickable' → numbers appear on everything clickable. 'Click 12' presses that one. 'Hide' clears them.", "code"),
    ("basics-timers", "Basics", "Timers, alarms and reminders",
     "'Set a timer for 2 minutes', 'remind me at 5pm to call the bank', 'what reminders do I have?', 'cancel the bank reminder'.", "code"),
    ("basics-quiet-success", "Basics", "Quiet when it worked",
     "'Open Notes': a short sound, no spoken 'Done'. It only talks when there's something to say.", "code"),
    ("basics-say-stop", "Basics", "Say 'stop' during a slow request",
     "Ask something slow ('Hey Vox, explain how a mortgage works in detail') and say 'stop' while it thinks. It cancels and keeps listening.", "code"),
    ("basics-teach", "Basics", "Teach a phrase",
     "'Whenever I say refresh, press command R'. Then say 'refresh': it presses ⌘R. Shows on Commands.", "code"),
    ("basics-wrong", "Basics", "'No, that's wrong'",
     "After Vox does the wrong thing with a learned command, say 'no, that's wrong'. That command is switched off, and Commands → Learning shows it.", "code"),
    ("basics-remember", "Memory", "Remember things about you",
     "'Remember that my sister is called Sam' → Memory page shows it. Later, in another chat: 'what's my sister called?'.", "code"),
    ("basics-name", "Memory", "Knows your name",
     "Tell it 'my name is …' once. Greetings and reminders then use it.", "code"),
    ("pages-personality", "Vox.app", "Personalities",
     "Personality page: pick a different persona, ask Vox something, it answers in that style and voice. Edit one, or make your own.", "code"),
    ("pages-vocabulary", "Vox.app", "Vocabulary (fix mis-heard words)",
     "Vocabulary page: add 'clawed → Claude'. Say 'open clawed': it opens Claude.", "code"),
    ("pages-rules", "Vox.app", "Rules",
     "Rules page: add 'Always answer in one sentence'. Ask Vox something: the reply follows it. Turn it off again.", "code"),
    ("pages-memory", "Vox.app", "Memory page",
     "Memory page lists what Vox remembers about you; delete one and it's gone from answers.", "code"),
    ("pages-activity", "Vox.app", "Activity page",
     "Activity shows recent requests, which brain answered, and cost/time.", "code"),
    ("pages-learning", "Vox.app", "Learned commands",
     "Commands → Learning lists commands Vox worked out and saved, with hits; remove one.", "code"),
    ("pages-board-drag", "Organise", "Drag cards on the Board",
     "Board page: drag a card to another column and within a column. Add a column.", "code"),
    ("mcp-speak", "Agents", "Coding agents talk through Vox",
     "In Claude Code (with the vox-control MCP): 'tell me out loud when you're done'. Vox speaks the summary, one voice at a time.", "code"),
    ("mcp-bubble", "Agents", "Quiet notification bubble",
     "An agent calls notify (e.g. 'notify me when the build finishes'): a bubble appears, nothing is spoken.", "code"),
    ("mcp-control", "Agents", "Agents can use your Mac through Vox",
     "In Claude Code: 'use vox-control to open Notes and make a note saying hello'. It works through Vox's tools.", "code"),
    ("mcp-protected", "Agents", "Agents can't act in protected apps",
     "With Terminal (or a blocked app) in front, ask Claude Code to use vox-control's press or type_text: it's refused and told to ask you. In other apps it works. (Restart Claude Code so it loads the new MCP.)", "code"),
    ("mcp-board", "Agents", "Agents can read and change the Board",
     "In Claude Code: 'add a card to my Vox board called test from Claude'. It shows on the Board page.", "code"),
    ("agent-screen", "Agents", "Screen agent for multi-step jobs (off by default)",
     "Settings → turn on the agent. 'Open Slack and send Sam a message saying testing': it does every step; Esc or 'stop' halts it.", "code"),
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
