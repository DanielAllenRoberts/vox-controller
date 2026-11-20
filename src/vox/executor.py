"""LLM-as-executor (idea #12): on an uncertain command, the small brain decides what the
user meant and either runs a Vox action or replies.

Provider-agnostic by design: instead of native tool-calling (which differs per provider and
needs an API key), it asks the brain to *translate* the speech into one Vox command (or a short
reply). So it works on the Claude subscription (SDK/CLI), the Anthropic/OpenAI APIs, or a local
LLM — whatever the small brain is set to. See docs/plan/ideas.md #12-13.
"""

import re
import time

from vox import actions, assistant, prompts
from vox.config import CONFIG

# Sentinel returned as the message (with acted=True) when the brain decides the user wants to
# START DICTATION — they said "start typing" or a garbled version the deterministic _is_dictate
# missed (e.g. "dot typing"). The loop's execute() callers detect this and switch into
# _dictation_mode instead of treating it as a normal action result.
ENTER_DICTATION = "\x00ENTER_DICTATION\x00"


def _setting(key: str, fallback):
    """Read a runtime override from the dashboard's settings_store, else fall back to Config.
    Fully guarded (mirrors assistant._setting): if vox.web.settings_store is missing or errors,
    return the fallback so the executor behaves exactly as before. None from the store means
    'unset' → fallback. Lets the LLM-executor / screen-vision toggles take effect on the next
    command without a restart."""
    try:
        from vox.web import settings_store
        val = settings_store.get(key)
        return fallback if val is None else val
    except Exception:
        return fallback

_SYSTEM = (
    "You are the action layer of Vox, a hands-free Mac voice controller. Vox's deterministic "
    "parser couldn't handle what the user just said. Turn it into ONE Vox command, or a short reply.\n"
    "Commands (output the command line verbatim, nothing else):\n"
    "  open <app or website>          ·  go to <website>             ·  search <query>\n"
    "  quit <app>  (close a whole app, e.g. 'close Notion' → quit Notion; NOT close tab)\n"
    "  press <keys>  (a keyboard shortcut in the app in front. Use it for every standard shortcut\n"
    "                 you're sure of: 'save this' → press cmd+s, 'reopen the closed tab' → press\n"
    "                 cmd+shift+t, 'undo that' → press cmd+z, 'print' → press cmd+p, press escape)\n"
    "  reload  (reload the current page — ALWAYS prefer this over clicking a reload button, which\n"
    "           only exists on some pages and breaks on the next one)\n"
    "  go to my <name> tab            ·  next tab / previous tab     ·  go back  ·  close tab\n"
    "  next window / previous window  ·  swipe left / swipe right    ·  profile <number>\n"
    "  <app> window  (switch to / cycle an app's windows, e.g. 'Cursor window')\n"
    "  show tabs / hide tabs\n"
    "  pause music / play music / next song / previous song  (Spotify, Music or a video, in the\n"
    "      background. 'pause', or a mis-heard 'pose my music' → pause music. NEVER press space for it)\n"
    "  what's playing  ·  play my <name> playlist  ·  shuffle my <name> playlist  ·  add this song to my\n"
    "      <name> playlist  ·  play <song> by <artist>   (Spotify; 'put my film score list on' → play my\n"
    "      film score playlist; 'save this tune to chill' → add this song to my chill playlist)\n"    "  move <app or 'this window'> to the <left/right/other/main/ipad> screen  ·  maximize <app or window>\n"
    "      ·  snap this window to the left half / right half  ·  center this window  (multiple displays:\n"
    "      the Mac state lists them left to right. 'screen 2' / 'next screen' on their own = desktops)\n"
    "Two more things you can do with text at the cursor:\n"
    "  • Compose text and insert it (e.g. 'write me an email about X', 'write a function that "
    "sums a list'): output  TYPE: <the full finished text>. It ALWAYS inserts at the user's "
    "current cursor — NEVER ask where to put it, just write it.\n"
    "  • Rewrite the text the user has SELECTED (e.g. 'make this pretty', 'fix the spelling', "
    "'make it formal', 'shorten this'): output  EDIT: <the rewrite instruction>. Don't ask what "
    "kind of text it is — the selection is fetched and rewritten automatically.\n"
    "To SEE the screen (e.g. 'what does this say?', 'what's on my screen', 'read this error', "
    "'what's this article about'): output  LOOK: <the question to answer about the screen>\n"
    "For a QUESTION that needs live or current information from the internet (weather, news, scores, "
    "prices, opening hours, facts you may not know, or how to do something in a particular app): output  "
    "WEB: <the question>. Vox looks it up and answers out loud. (Use 'search <query>' only when they "
    "want the browser to show search results.)\n"
    "To use a command from the app's MENUS when it's app-specific and you don't know its shortcut, or the user names a menu "
    "command ('export as PDF', 'show the developer tools', 'reopen the closed tab', 'zoom in'): output  "
    "MENU: <the menu item's title as the app would write it, e.g. Export as PDF>. Vox finds it in the "
    "front app's menu bar and chooses it. Prefer this over CLICK for anything that lives in a menu.\n"
    "When the user wants to LOG / REPORT AN ISSUE, BUG OR PROBLEM WITH VOX for the developer ('log an "
    "issue', 'report a bug', 'note this problem', even if mis-heard as 'login issue'): output  ISSUE: "
    "<their description, cleaned up but in their words>. Never answer it yourself.\n"
    "To SAVE A STANDING PREFERENCE about how to do things, especially in one app ('from now on in "
    "Zen, when I say refresh press command R', 'in Spotify always search instead of browsing'): output  "
    "NOTE: <app name, or everywhere> | <the preference, written as an instruction to yourself>. Use "
    "TEACH instead when it's simply a phrase that should run one fixed command.\n"
    "To CHANGE ONE OF VOX'S OWN SETTINGS when asked ('use a deeper voice', 'show bubbles at the "
    "bottom left', 'think before answering'): output  SET: <key> | <value>  using ONLY these keys: "
    "tts_enabled (true/false), kokoro_voice (am_onyx deep US male, am_michael US male, af_bella US "
    "female, af_heart warm US female, bf_emma UK female, bm_george UK male), learning_mode "
    "(auto/suggest/off), auto_dictation (true/false), small_brain_thinking (on/off), "
    "screen_vision_enabled (true/false), agent_alerts (bubble/speak/off), bubble_corner "
    "(top-right/top-left/bottom-right/bottom-left), fast_wake (true/false). Anything else: CHAT: "
    "that it has to be changed in Vox's settings.\n"
    "To SHOW the user where something is WITHOUT clicking it ('where's the export button', 'show me "
    "where settings is', 'point at X', 'circle X', 'circle where Sam's birthday is on my calendar'): "
    "output  POINT: <what to point at, as it would appear on screen, e.g. Sam's birthday>. Vox rings it on "
    "screen. Use CLICK only when they want it pressed.\n"
    "To CLICK any on-screen control by what the user calls it ('click the play button', 'press "
    "submit', 'tap the menu', 'select Settings'): output  CLICK: <what to click>. This also covers "
    "items INSIDE the current app — a Slack/Discord/Teams channel or DM, a chat, a conversation, a "
    "person's name, a playlist, a file, any sidebar entry. IMPORTANT: when the user wants to open / go "
    "to / switch to something that lives inside the focused app rather than a website or a Mac app, use "
    "CLICK: <its name> — do NOT treat an in-app name as a website (e.g. on Slack, 'go to the github "
    "chat' is  CLICK: github , NOT opening github.com). Vox finds and clicks the exact control (and can "
    "list what's on screen if your first guess misses) in a separate step — just pass the target.\n"
    "For a task that needs SEVERAL steps on screen, or a target with no label (a spot in a video, a "
    "drawing, a map, an unlabelled icon): output  AGENT: <the task in one sentence>. This hands over "
    "to a slower tier that can see the screen, act, look again, and repeat. Use it ONLY when one "
    "command genuinely can't do the job — e.g. 'find the total on this invoice and put it in the "
    "spreadsheet', 'scrub the video to the halfway point', 'fill in this form', and requests that chain "
    "steps across apps like 'open Slack and send Sam a message saying testing' (open, find the person, "
    "type, send: never just CLICK the person's name in whatever app is in front). A single click, a "
    "single app switch, or anything with a visible label is NOT this — use CLICK: or a command, which "
    "are far faster.\n"
    "To set a TIMER, ALARM, REMINDER or ROUTINE: output  SCHEDULE: <kind> | <when> | <text> | <repeat>\n"
    "  <kind> = timer, alarm, reminder, or routine.\n"
    "  <when> = the ABSOLUTE local date-time as 24-hour ISO YYYY-MM-DDTHH:MM, which YOU compute from "
    "the 'Now:' time in the Mac state — turn 'in 10 minutes' / 'at 3:45 pm' / 'tomorrow at 7am' / "
    "'every day at 9' into the real clock date+time (pick the next future occurrence).\n"
    "  <text> = what to remind about (leave blank for a bare timer/alarm).\n"
    "  <repeat> = once, daily, weekdays, weekly, or an interval like 'every 30 minutes' / "
    "'every 2 hours' (the reminder then repeats on that interval). For an interval, set <when> to "
    "the FIRST fire = Now + the interval.\n"
    "  Examples (when Now is 2026-06-23 15:04): 'remind me to call Sam in 10 minutes' → "
    "SCHEDULE: reminder | 2026-06-23T15:14 | call Sam | once  ·  'set an alarm for 7am' → "
    "SCHEDULE: alarm | 2026-06-24T07:00 |  | once  ·  'remind me at 3:45 pm that I have a meeting' → "
    "SCHEDULE: reminder | 2026-06-23T15:45 | I have a meeting | once  ·  'remind me every day at 9 to "
    "stretch' → SCHEDULE: reminder | 2026-06-24T09:00 | stretch | daily  ·  'remind me every 30 "
    "minutes to check on the cat' → SCHEDULE: reminder | 2026-06-23T15:34 | check on the cat | "
    "every 30 minutes.\n"
    "The user's CODING AGENTS (Claude Code sessions Vox runs in their project folders, managed by a "
    "CEO): to start one, ask one something, get an update, give one new instructions, stop one, or ask "
    "who's working on what ('start an agent in the getprice folder to fix the login bug', 'what's the "
    "update on the scraper?', 'ask the getprice agent if it's done', 'tell the docs agent to also update "
    "the README', 'stop the getprice agent', 'what are my agents doing?'), output  AGENTS: <the request "
    "in the user's words>. This is NOT the on-screen AGENT for clicking around apps.\n"
    "To use the user's CONNECTED APPS (their email/Gmail, Google Calendar events, Slack, Notion, Trello, "
    "GitHub, Drive… whatever the Mac state lists under 'Connections'): output  APPS: <the request in the "
    "user's words, with any detail they gave>. Use it for reading ('any new email from Sam?', 'what's in "
    "my inbox', 'what did Alex say on Slack') and for doing ('reply to Sam saying thanks'); Vox asks the "
    "user before anything is sent or changed. Prefer APPS over opening the app on screen whenever a "
    "matching connection is listed. Never open a connection's website instead.\n"
    "A ROUTINE is a scheduled REQUEST that Vox carries out at that time, rather than a line it reads "
    "out: use kind routine whenever the user wants Vox to DO or TELL them something on a schedule "
    "('every weekday at 7 tell me what's on my calendar and the weather' → SCHEDULE: routine | "
    "<next weekday 07:00> | tell me what's on my calendar and the weather | weekdays  ·  'every day at "
    "9 check my calendar and board and tell me what to work on' → SCHEDULE: routine | <next 09:00> | "
    "check my calendar and board and tell me what to work on | daily  ·  'every morning at 8 open my "
    "email' → SCHEDULE: routine | <next 08:00> | open my email | daily  ·  'every weekday at 9 ask my agents "
    "for an update' → SCHEDULE: routine | <next weekday 09:00> | ask my agents for an update | weekdays). "
    "<text> is the request in the "
    "user's words. 'Remind me to X' stays a reminder.\n"
    "To START DICTATION — when the user wants to TYPE WITH THEIR VOICE, i.e. begin dictating text "
    "that Vox transcribes at the cursor ('start typing', 'start dictation', 'begin typing', "
    "'dictate', 'take dictation', or a mis-heard version like 'dot typing' / 'star typing' / 'start "
    "typ'): output exactly  DICTATE  and nothing else. This hands the keyboard to the user's voice "
    "(everything they say next is typed) — it is DIFFERENT from TYPE, which composes specific text "
    "you write. When the user just wants to start dictating, DICTATE — don't write anything yourself.\n"
    "The user's WORKSPACE BOARD (a Trello-style kanban of their tasks) is shown in the Mac state "
    "below when it has anything on it. To ANSWER a question about it ('what's on my board', 'what "
    "am I doing', 'how many issues are open'), read it off what you can see and reply with "
    "CHAT: <your answer> — the CHAT: prefix is required for anything spoken, never bare prose. "
    "To CHANGE it, output  BOARD: <verb> | <arg> | <arg>  (one line per change; for several changes "
    "output several BOARD: lines) using:\n"
    "  BOARD: add_card | <list> | <title>        ·  BOARD: move_card | <card> | <list>\n"
    "  BOARD: update_card | <card> | <new title> ·  BOARD: note | <card> | <text to append>\n"
    "  BOARD: delete_card | <card>               ·  BOARD: add_list | <name>\n"
    "  BOARD: add_board | <name>                 ·  BOARD: due | <card> | <date: friday, tomorrow, 2026-11-20 15:00, or none>\n"
    "  BOARD: tag | <card> | <tag, tag>          ·  BOARD: archive | <card>\n"
    "  BOARD: checklist | <card> | <item to add>  ·  BOARD: restore | <deleted card>  (bring back a "
    "card deleted earlier; 'put them back' after deleting several → one restore line per card, "
    "titles from your short-term memory)\n"
    "Refer to a card by its TITLE as the user said it (close is fine, it's matched fuzzily), or by "
    "the #id shown. Examples: 'add a card to doing called fix the scraper' → "
    "BOARD: add_card | Doing | fix the scraper  ·  'move the AC direct card to done' → "
    "BOARD: move_card | AC direct | Done  ·  'put a note on the scraper card that it needs "
    "proxies' → BOARD: note | scraper | needs proxies. When you know a card's #id (from the board "
    "below or your short-term memory) use it: 'move it to doing' right after adding card #14 → "
    "BOARD: move_card | #14 | Doing.\n"
    "To TEACH A NEW COMMAND — when the user asks for a phrase to mean something FROM NOW ON "
    "('whenever I say refresh, refresh the page', 'make \"reload\" reload this tab', 'from now on X "
    "should Y', 'save that as a command called X'): output  TEACH: <the trigger phrase> | <the Vox "
    "command line it should run>. The right side must be one of the commands above, written exactly "
    "as you would output it on its own — e.g.  TEACH: refresh | go back  is wrong, "
    "TEACH: refresh | reload  is right only if 'reload' is a command. This SAVES the mapping so the "
    "phrase works instantly every time after, with no AI. Use it whenever the user is describing a "
    "standing rule for a phrase rather than asking for a one-off action — do NOT just reply that "
    "you've noted it, and never claim you saved something without emitting TEACH.\n"
    "The SAME directive also CHANGES a command that was added earlier: if the phrase is already "
    "taught, TEACH re-points it at the new action instead of adding a duplicate. So 'when I say "
    "refresh, use reload instead', 'change the refresh command to reload' and 'make refresh do "
    "something else' are all  TEACH: refresh | reload . Built-in commands cannot be changed — Vox "
    "will say so; don't refuse on its behalf, just emit the TEACH.\n"
    "Rules:\n"
    "• Be autonomous — strongly prefer ACTING over asking. Make a sensible choice and do it; never "
    "ask for confirmation. Questions slow the user down, so only ask when you genuinely cannot "
    "proceed without one missing detail you can't infer (e.g. a search with no topic at all).\n"
    "• If it maps to a command, output just that command line (e.g. close tab).\n"
    "• For TYPE, write the actual finished text (no preamble, no quotes). For EDIT, give only the "
    "instruction — the selected text is fetched and rewritten in a separate step.\n"
    "• To ask (rarely): CHAT: <short question>. For a real question: CHAT: <one short spoken "
    "sentence>.\n"
    "• For something you truly can't do: CANT: <what you would have needed, in a few words: a "
    "command or tool that doesn't exist, being able to see or read something, or a clearer request> "
    "| <one short spoken sentence telling the user>. The first part is logged so the gap can be "
    "fixed; only the second part is spoken.\n"
    "• Only when you're CONFIDENT it's background talk NOT addressed to Vox (overheard "
    "conversation, third-person speech with no request for you) output exactly: IGNORE. A question "
    "— or anything that might be meant for you — is NOT chatter; answer or do it. When unsure, do "
    "NOT ignore.\n"
    "• Earlier turns may be shown for context (e.g. your own question + the user's answer) — use them.\n"
    "• Transcripts may be garbled — infer intent. Output only the command / TYPE / EDIT / CHAT / IGNORE line."
)

_EDIT_SYSTEM = (
    "You rewrite text. Output ONLY the rewritten text — no preamble, no explanation, no quotes, "
    "no markdown fences. Preserve the user's meaning; change only what the instruction asks for."
)


def _rewrite(selected: str, instruction: str) -> str:
    """Apply a rewrite instruction to selected text (used by the EDIT / 'make this pretty' flow).
    Raises RuntimeError when the brain fails, so the caller leaves the user's text alone.

    A long selection gets room to finish: the output is about as long as the input (~4 characters
    a token, so chars/2 tokens is double headroom), and writing ~2,000 words takes longer than the
    usual 45 s limit (a 1,700-word essay timed out there, issue f0ff52bd)."""
    n = len(selected)
    out = assistant.complete(f"Instruction: {instruction}\n\nText to rewrite:\n{selected}",
                             system=prompts.get("edit"), brain="small", prompt="edit",
                             timeout=min(300.0, 45.0 + n / 100), max_tokens=min(32000, max(800, n // 2 + 500)))
    if assistant.failed(out):
        raise RuntimeError(out.strip().strip("()"))
    return out


_LOOK_AXTREE_SYSTEM = (
    "You answer questions about what's on the user's Mac screen. Instead of an image you're given "
    "the focused app's accessibility (AX) tree as indented text — each line is a UI element "
    "(role, title, value). Read it and answer concisely for text-to-speech (1-2 sentences). "
    "If the tree genuinely can't answer the question and it needs deeper visual reasoning (e.g. the "
    "content is in an image/canvas the tree doesn't expose, or the layout is too complex to infer), "
    "reply with EXACTLY '[BIG]' and nothing else to hand off to a more capable model."
)


def _look_axtree(question: str) -> str | None:
    """Answer a 'what's on my screen' question from the AX tree as text (no screenshot).

    Returns the spoken answer, or None when the tree is unavailable/empty so the caller can fall
    back to the screenshot path. Guarded: the AX read shells AppleScript and degrades to None."""
    try:
        from vox.web import axtree
        snap = axtree.snapshot_text()
    except Exception:
        return None
    if "error" in snap:
        return None
    prompt = (f"Focused app: {snap.get('app', '?')}\n\nAX tree:\n{snap['text']}\n\n"
              f"Question: {question}")
    # The AX tree is structured TEXT, so the cheap/small brain reads it fine — no need for the
    # vision-grade big brain. kind="vision_axtree" tags it on the Token Usage page. When the tree
    # genuinely can't answer (e.g. Chromium/Electron content the tree doesn't expose — Arc, Slack),
    # the brain replies '[BIG]'. Re-reading the SAME empty tree on the big brain doesn't add vision
    # (it just replies '[BIG]' again, which then got spoken aloud) — so instead we return None to
    # hand the caller off to REAL vision: the screenshot path, which already uses the big brain.
    answer = assistant.complete(prompt, system=prompts.system("look"), brain="small", kind="vision_axtree", prompt="look")
    if answer.strip().upper().startswith("[BIG]"):
        return None
    return answer


_CLICK_PICK_SYSTEM = (
    "You decide which on-screen control the user wants to click. You're given the LABELS of the "
    "elements currently clickable on screen (sidebar items, chats, channels, buttons, links, menu "
    "items, people, files…) and what the user asked for. The request came from SPEECH-TO-TEXT, so it "
    "is OFTEN MIS-TRANSCRIBED — match by how it SOUNDS, not exact spelling. A word that sounds like a "
    "label is almost certainly that label, even if spelled differently (e.g. 'alec' or 'ellis' → "
    "'Alex Fairbairn', 'get up' → 'github', 'daily report' → 'daily-report').\n"
    "'My account', 'my email', 'my profile' or 'me' means the USER'S OWN entry: on a sign-in or "
    "'pick an account' screen that's the account shown by an email address or name. It is never "
    "'Use another account', 'Add account' or 'Sign out'. If several accounts are listed and nothing "
    "says which is theirs, reply ASK: <the first one>.\n"
    "Reply with EXACTLY ONE of:\n"
    "• the single best-matching label, copied VERBATIM from the list — when you're reasonably "
    "confident (a clear sound-alike with no rival counts as confident).\n"
    "• ASK: <label>  — only when you have a plausible guess but are genuinely torn (so Vox can "
    "confirm 'Did you mean <label>?' before clicking). Copy <label> verbatim from the list.\n"
    "• NONE  — when nothing on the list plausibly matches.\n"
    "No quotes, no other words."
)

# A 'yes' to our 'Did you mean <X>?' click prompt should just run the click — match common spoken
# affirmations, and pull <X> back out of the question we asked (carried in the clarification history).
_AFFIRMATIVE = re.compile(
    r"^\s*(?:yes|yeah|yep|yup|ya|sure|correct|right|exactly|definitely|"
    r"that'?s?\s+(?:right|it|him|her|the\s+one)|do\s+it|go\s+ahead|ok(?:ay)?|please|uh[\s-]*huh)\b",
    re.I)
_DID_YOU_MEAN = re.compile(r"did you mean\s+(.+?)\s*\?\s*$", re.I)


# A connections request that wanted to change something, waiting for the user's yes:
# (request, asked_at). See vox.mcp_servers.run.
_HELD_APPS: tuple[str, float] | None = None
_NEGATIVE_REPLY = re.compile(r"^\s*(?:no|nope|nah|don'?t|do not|cancel|stop|never ?mind|leave it)\b", re.I)


def _apps(request: str, *, approved: bool = False) -> str:
    """Run a request against the user's MCP connections; hold it for a yes if it changes something."""
    global _HELD_APPS
    from vox import mcp_servers
    out = mcp_servers.run(request, approved=approved)
    if out.upper().startswith("CONFIRM:"):
        _HELD_APPS = (request, time.time())
        what = out.split(":", 1)[1].strip().rstrip(".")
        return f"I'm about to {what[:1].lower() + what[1:]}. Should I go ahead?"
    _HELD_APPS = None
    return out


def _held_apps_reply(text: str):
    global _HELD_APPS
    try:  # an agent waiting for the user's OK ("The GetPrice agent wants to run npm install…")
        from vox import team
        if team.pending_approval() is not None:
            if _AFFIRMATIVE.match(text or ""):
                return False, team.answer(True)
            if _NEGATIVE_REPLY.match(text or ""):
                return False, team.answer(False)
    except Exception:
        pass
    if _HELD_APPS is None or time.time() - _HELD_APPS[1] > 180:
        return None
    if _AFFIRMATIVE.match(text or ""):
        req, _ = _HELD_APPS
        _HELD_APPS = None
        msg = _apps(req, approved=True)
        assistant._dbg("[executor]", f"decision=APPS (approved {req!r}) → {msg!r}")
        return False, msg
    if _NEGATIVE_REPLY.match(text or ""):
        _HELD_APPS = None
        return False, "Okay, I won't."
    return None


def _confirmed_click_target(text: str, history) -> str | None:
    """If we just asked 'Did you mean <X>?' for a click and the user affirmed, return <X> to click.
    Reads the candidate from the most-recent assistant turn in the clarification history."""
    if not history or not _AFFIRMATIVE.match(text or ""):
        return None
    for role, content in reversed(history):
        if role == "assistant":
            m = _DID_YOU_MEAN.search((content or "").strip())  # may follow "I couldn't find X."
            return m.group(1).strip() if m else None
    return None


def _parse_pick(raw: str, labels: list[str]) -> tuple[str, str | None]:
    """Pull the decision out of the picker's reply, tolerating a big brain that 'thinks out loud'
    before its final answer. Returns ("pick"|"ask"|"none", label). The chosen label must appear
    verbatim in `labels` (case-insensitive) — guards both reasoning preamble and hallucinated labels.
    Scans from the LAST line up, since the final answer comes at the end."""
    by_lower = {l.lower(): l for l in labels}
    for line in reversed([ln.strip().strip('"').strip("'").rstrip(".,")
                           for ln in (raw or "").splitlines() if ln.strip()]):
        if line.upper().startswith("ASK:"):
            cand = line.split(":", 1)[1].strip().strip('"').strip("'").rstrip(".,")
            if cand.lower() in by_lower:
                return "ask", by_lower[cand.lower()]
        elif line.upper().strip("[]") == "NONE":
            return "none", None
        elif line.lower() in by_lower:
            return "pick", by_lower[line.lower()]
    return "none", None


def _click_fuzzy(target: str) -> str:
    """LLM-assisted click fallback — the 'let the brain SEE the elements in case of confusion' path.
    The fast targeted AXPress couldn't find `target` verbatim, so list what's actually clickable on
    screen (Electron-aware) and let the BIG brain map the user's (often mis-transcribed) words to a
    real label by sound. On a confident match it clicks; when genuinely unsure it returns a 'Did you
    mean <X>?' question (a 'yes' then runs it, via _confirmed_click_target); else 'couldn't find'."""
    # ONE enumeration drives both attempts: the labels the brain reads, and (if that fails) the
    # numbered marks it looks at. Sharing the list also keeps badge N ↔ targets.click_index(N-1) aligned.
    try:
        from vox import targets
        items = targets.visible_targets() or []
    except Exception:
        items = []
    labels = actions._dedupe([i["label"] for i in items]) or actions.clickable_targets()
    from vox import mishear
    mishear.note_labels(labels)
    if not labels:
        return f"I couldn't find a '{target}' to click."
    listing = "\n".join(f"  - {label}" for label in labels)
    prompt = (f"Clickable elements on screen:\n{listing}\n\n"
              f"The user wants to click: {target!r}\n"
              f"Your answer (a verbatim label, or ASK: <label>, or NONE):")
    raw = assistant.complete(prompt, system=prompts.get("click_pick"), brain="big", kind="click_axtree", prompt="click_pick")
    kind, label = _parse_pick(raw, labels)
    assistant._dbg("[executor]", f"click pick for {target!r} from {len(labels)} on-screen labels → {kind}:{label!r}")
    if kind == "pick":
        # Click the element we actually listed, by its index — not by re-searching for its label.
        # The label came from THIS enumeration, so its index is exact, and for a page element that
        # keeps the click on the in-page path instead of hoping the AX tree is up.
        idx = next((i for i, it in enumerate(items) if it["label"] == label), None)
        if idx is not None:
            try:
                from vox import targets
                res = targets.click_index(idx)
            except Exception:
                res = None
            if res and res[0] == "clicked":
                return f"Clicked {res[1] or label}."
        return actions.click_element(label)
    # Labels alone can't express "the second last message" or "the one at 7:52pm" — order and
    # position simply aren't in a text list. So before giving up (or guessing with a half-confident
    # ASK), SHOW the brain the screen with a number on every clickable element and let it point.
    seen = _click_by_vision(target, items)
    if seen:
        return seen
    if kind == "ask":
        return f"Did you mean {label}?"  # acted=False question → a 'yes' next turn clicks it
    return f"I couldn't find a '{target}' to click on the screen."


# NB: assistant.look() takes no system prompt (it's the shared vision entry point), so the framing
# has to travel with the question itself — without it the model just sees "which badge number?" and
# has no idea what the badges even are.
_CLICK_VISION_PROMPT = (
    "This is a screenshot of the user's Mac. EVERY clickable element has a small blue badge with a "
    "white number at its top-left corner.\n\n"
    "There are exactly {n} badges, numbered 1 to {n}. Any other number is wrong — if you can't read "
    "a badge clearly, answer with the nearest one you CAN read, or NONE.\n\n"
    "The user wants to click: {target!r}\n\n"
    "They often describe it by POSITION or CONTENT that a list of labels can't capture — 'the second "
    "last message', 'the one sent at 7:52pm', 'the reply under Alex's photo'. Find the element they "
    "mean and answer with ONLY the number on its badge. If the thing they describe has no badge of "
    "its own, answer with the number of the badge sitting on it or nearest to it. If you genuinely "
    "cannot see what they mean, answer NONE.\n\n"
    "Reply with a bare number or NONE — no words, no punctuation."
)


_POSITIONAL = re.compile(r"\b(first|second|third|last|top|bottom|left|right|middle|next|previous|"
                         r"one|icon|image|picture|colou?r|red|blue|green|at|from|under|above|below|near)\b")


def _plain_label(target: str) -> bool:
    """A request that names a control ("Later", "save draft"), as opposed to describing where it is
    ("the second message", "the blue icon at the top"). Only plain labels can be label-checked."""
    t = (target or "").lower().strip()
    return 0 < len(t.split()) <= 3 and not _POSITIONAL.search(t)


def _labels_agree(said: str, label: str) -> bool:
    import difflib
    a, b = said.lower().strip(), label.lower().strip()
    if a in b or b in a:
        return True
    if {w for w in a.split() if len(w) > 2} & {w for w in b.split() if len(w) > 2}:
        return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.6


def _vision_prompt(target: str, n: int) -> str:
    """The find-it-in-a-screenshot prompt, falling back to the default if an edit broke its
    {target}/{n} placeholders (a broken prompt must not break clicking)."""
    try:
        return prompts.get("click_vision").format(target=target, n=n)
    except (KeyError, IndexError, ValueError):
        return _CLICK_VISION_PROMPT.format(target=target, n=n)


def _schedule(body: str) -> str | None:
    """One SCHEDULE: line → the reminder/alarm/routine made (its confirmation), or None."""
    try:
        from vox import scheduler
        # Preferred: the brain emits a structured "kind | ISO-when | text | repeat" (it computed
        # the absolute time from 'Now:'), so we create it directly — no fragile English re-parse.
        msg = None
        if "|" in body:
            parts = [p.strip() for p in body.split("|")]
            parts += [""] * (4 - len(parts))  # pad so missing trailing fields are just empty
            msg = scheduler.create_structured(parts[0], parts[1], parts[2], parts[3])
        # Fallback: a plain-English restatement (model ignored the format) → the deterministic
        # parser (now connector-tolerant: "to"/"that"/"about"/"saying").
        if msg is None:
            msg = scheduler.parse_and_create(body)
        return msg
    except Exception:
        return None


# The directive prefixes the router answers with. A model sometimes opens with a sentence ("I'll set
# both the reminder and the follow-up for you.") before them; that sentence isn't a command, and
# reading it as one lost the whole request (issue dc62c863).
_DIRECTIVE = re.compile(r"^(?:IGNORE\b|DICTATE\b|(?:CHAT|CANT|WEB|MENU|ISSUE|NOTE|SET|LOOK|POINT|CLICK|AGENTS?|"
                        r"APPS|SCHEDULE|BOARD|TEACH|TYPE|EDIT)\s*:)", re.I)


def _drop_preamble(raw: str) -> str:
    """Drop chatty lines BEFORE the first directive line, if there is one. Untouched otherwise."""
    lines = raw.splitlines()
    for i, ln in enumerate(lines):
        if _DIRECTIVE.match(ln.strip()):
            lead = [x.strip() for x in lines[:i] if x.strip()]
            # Only drop sentences ("I'll do both for you."), never a bare command line like
            # "close tab", which the old first-line-wins rule would have run.
            if i and all(x[-1] in ".!?:" or len(x.split()) >= 6 for x in lead):
                return "\n".join(lines[i:]).strip()
            return raw
    return raw


def _router_system() -> str:
    """The router prompt plus the notes for the app in front (app-scoped notes: the user's idea,
    loaded per app like the command DB, so the main prompt doesn't carry every app's quirks)."""
    system = prompts.system("router")
    try:
        from vox import assistant as _a
        block = _a._rules_block(_a._focused_app())
        if block:
            system = f"{system}\n\n{block}"
    except Exception:
        pass
    return system


def _point_by_vision(target: str) -> str | None:
    """Point at something the AX/DOM lookup couldn't find by name: badge every visible target on a
    screenshot, ask the big brain which badge the user means (the click-by-vision recipe), then ring
    that element instead of clicking it. None when vision is off or can't tell."""
    if not _setting("screen_vision_enabled", CONFIG.screen_vision_enabled):
        return None
    try:
        from vox import overlay, targets
        items = targets.visible_targets() or []
        shot = actions.capture_screen() if items else None
        marked = overlay.annotate(shot, items) if shot else None
        if not marked:
            return None
        prompt = _vision_prompt(target, len(items)).replace(
            "The user wants to click:", "The user wants to SEE where this is (nothing will be clicked):")
        answer = assistant.look(prompt, marked, brain="big")
        nums = re.findall(r"\d{1,3}", answer or "")
        n = int(nums[-1]) if nums else 0
        assistant._dbg("[executor]", f"point-by-vision for {target!r} over {len(items)} marks → {(answer or '').strip()!r}")
        if not 1 <= n <= len(items):
            return None
        it = items[n - 1]
        overlay.point([{**it, "label": it.get("label") or target}])
        return f"There's {it.get('label') or target}."
    except Exception:
        return None


def _click_by_vision(target: str, items) -> str | None:
    """Vision escalation for clicking (idea #37's set-of-marks, off the back of #52).

    Annotates a screenshot with the SAME numbered badges the overlay draws, asks the big brain which
    number the user meant, and clicks that element by its real AX frame. The model only has to pick a
    number — it never estimates pixel coordinates — so the click target stays an exact element.

    Returns the click result, or None to let the caller fall back. Gated by ``click_vision_fallback``
    (default on) since it costs a vision call, and fully guarded."""
    if not items or not _setting("click_vision_fallback", True):
        return None
    if not _setting("screen_vision_enabled", CONFIG.screen_vision_enabled):
        return None
    try:
        from vox import overlay
        shot = actions.capture_screen()
        if not shot:
            return None
        marked = overlay.annotate(shot, items)
        if not marked:
            return None
        answer = assistant.look(
            _vision_prompt(target, len(items)), marked, brain="big")
        # LAST number wins, not the first: the model reasons out loud despite being told not to, so
        # its answer is at the END ("...I can see 3 dialogs... badge 11" must click 11, not 3). Same
        # hardening _parse_pick already does on the label path.
        nums = re.findall(r"\d{1,3}", answer or "")
        m = nums[-1] if nums else None
        assistant._dbg("[executor]",
                       f"click-by-vision for {target!r} over {len(items)} marks → {(answer or '').strip()!r}")
        if not m:
            return None
        n = int(m)
        if not 1 <= n <= len(items):
            # Out of range means it read a badge that isn't there (seen live: "153" over 35 marks).
            # Trusting it would click an arbitrary element, so give up and let the caller fall back.
            assistant._dbg("[executor]", f"click-by-vision: badge {n} out of range 1..{len(items)}")
            return None
        picked = (items[n - 1].get("label") or "").strip()
        if picked and _plain_label(target) and not _labels_agree(target, picked):
            # Seen live: asked for "Later", vision picked badge 11 ("Got it") and it got clicked.
            # When the request was a plain label, a pick whose label plainly isn't it is a misread,
            # so ask instead. A 'yes' next turn clicks it via _confirmed_click_target.
            assistant._dbg("[executor]", f"click-by-vision: picked {picked!r} for {target!r}, labels disagree → confirm")
            # Say it wasn't found first: "Did you mean Speak replies?" alone, for a misheard name, sounded like
            # nonsense (seen live). The question stays last so a 'yes' still clicks it.
            return f"I couldn't find {target}. Did you mean {picked}?"
        from vox import targets
        res = targets.click_index(n - 1)  # badge N ↔ items[N-1], same as the overlay
        if res and res[0] == "clicked":
            return f"clicked {res[1]} (#{n}, found by looking at the screen)"
        return None
    except Exception:
        return None


_BOARD_OK = ("Added", "Moved", "Renamed", "Deleted", "Created", "Set", "Cleared", "Archived", "Restored")


def _spoken_due(due: str) -> str:
    """"2026-11-13" → "Friday the 13th"-ish: "Friday 13 November", plus the time when there is one."""
    from vox import board_store
    when = board_store.due_datetime(due)
    if when is None:
        return due
    day = when.strftime("%A %-d %B")
    return f"{day} at {when.strftime('%-I:%M %p').lower()}" if "T" in due else day


# How each successful board result is counted when several land in one turn: (pattern, key, phrase
# for a count of n). The phrase takes n and, for adds/moves into one list, that list's name.
_Q = r"""(?:'.*'|".*")"""   # a quoted title: repr() uses double quotes when it contains an apostrophe
_BOARD_KINDS = [
    (re.compile(rf"Deleted {_Q}\.$"), "deleted", lambda n, _l: f"Deleted {n} cards"),
    (re.compile(rf"Archived {_Q}\.$"), "archived", lambda n, _l: f"Archived {n} cards"),
    (re.compile(rf"Restored {_Q}\.$"), "restored", lambda n, _l: f"Restored {n} cards"),
    (re.compile(rf"Added a note to {_Q}\.$"), "noted", lambda n, _l: f"Added notes to {n} cards"),
    (re.compile(rf"Added {_Q} to the checklist on {_Q}\.$"), "checked", lambda n, _l: f"Added {n} checklist items"),
    (re.compile(rf"Added {_Q} to {_Q}\.$"), "tagged", lambda n, _l: f"Tagged {n} cards"),
    (re.compile(rf"Added {_Q} to (.+)\.$"), "added",
     lambda n, l: f"Added {n} cards to {l}" if l else f"Added {n} cards"),
    (re.compile(rf"Moved {_Q} to (.+)\.$"), "moved",
     lambda n, l: f"Moved {n} cards to {l}" if l else f"Moved {n} cards"),
    (re.compile(rf"Set {_Q} due .*$"), "due", lambda n, _l: f"Set deadlines on {n} cards, with reminders"),
    (re.compile(rf"Cleared the deadline on {_Q}\.$"), "cleared", lambda n, _l: f"Cleared {n} deadlines"),
    (re.compile(rf"Renamed it to {_Q}\.$"), "renamed", lambda n, _l: f"Renamed {n} cards"),
]


def _board_summary(msgs: list[str]) -> str:
    """One short sentence for several board changes. Counts, not a list: "Deleted 5 cards." /
    "Deleted 2 cards. Added 3 cards to Doing." Reading every title back was too much (user
    feedback 2026-11-07). A kind that happened once keeps its own sentence ("Deleted 'Invoice'."),
    and a failure that stopped the run is said at the end."""
    if len(msgs) == 1:
        return msgs[0]
    groups: dict[str, dict] = {}   # key → {"n", "lists", "first", "phrase"}, in first-seen order
    tail = []
    for m in msgs:
        for pat, key, phrase in _BOARD_KINDS:
            hit = pat.match(m)
            if hit:
                g = groups.setdefault(key, {"n": 0, "lists": set(), "first": m, "phrase": phrase})
                g["n"] += 1
                if hit.groups():
                    g["lists"].add(hit.group(1))
                break
        else:
            tail.append(m)   # lists/boards created, or the failure that stopped the run
    parts = []
    for g in groups.values():
        if g["n"] == 1:
            parts.append(g["first"].rstrip("."))
        else:
            one_list = next(iter(g["lists"])) if len(g["lists"]) == 1 else None
            parts.append(g["phrase"](g["n"], one_list))
    parts += [t.rstrip(".") for t in tail]
    return ". ".join(parts) + "."


def _plainly_named(said: str, title: str) -> bool:
    """Did the user name this card, or did fuzzy matching guess it? Deletes require the former:
    replaying real traffic showed garbled speech producing confident delete guesses."""
    s, t = said.strip().lower().lstrip("#"), (title or "").strip().lower()
    return bool(s) and (s in t or t in s)


def _did(text: str) -> None:
    """Record a board change in short-term memory, in more detail than what's spoken."""
    try:
        from vox import working_memory
        working_memory.note_did(text)
    except Exception:
        pass


def _list_name(conn, card: dict) -> str:
    try:
        r = conn.execute("SELECT name FROM board_list WHERE id = ?", (card["listId"],)).fetchone()
        return r["name"] if r else "?"
    except Exception:
        return "?"


def _board(body: str) -> str:
    """Change the workspace board (idea #51). ``<verb> | <arg> | <arg>``, mirroring SCHEDULE's shape.

    Cards are addressed by TITLE, not id — voice never produces an id — via ``board_store.find_card``,
    which matches exactly, then partially, then fuzzily. Reads aren't handled here: the board is
    already in the prompt (``actions.board_block``), so the brain answers "what's on my board?"
    directly instead of paying for a round-trip."""
    parts = [p.strip() for p in (body or "").split("|")]
    verb = (parts[0] or "").lower().replace(" ", "_") if parts else ""
    a1 = parts[1] if len(parts) > 1 else ""
    a2 = parts[2] if len(parts) > 2 else ""
    try:
        from vox import board_store
        conn = board_store.build()
    except Exception:
        return "I couldn't open the board."
    try:
        if verb in ("add_card", "add", "new_card"):
            if not a1 or not a2:
                return "Which list, and what should the card say?"
            card = board_store.add_card(conn, a1, a2)
            _did(f"added card #{card['id']} {card['title']!r} to {a1}")
            return f"Added {card['title']!r} to {a1}."
        if verb in ("move_card", "move"):
            card = board_store.find_card(conn, a1)
            if card is None:
                return f"I couldn't find a card called {a1!r}."
            board_store.move_card(conn, card["id"], a2)
            _did(f"moved card #{card['id']} {card['title']!r} from {_list_name(conn, card)} to {a2}")
            return f"Moved {card['title']!r} to {a2}."
        if verb in ("update_card", "edit", "rename_card"):
            card = board_store.find_card(conn, a1)
            if card is None:
                return f"I couldn't find a card called {a1!r}."
            board_store.update_card(conn, card["id"], title=a2 or None)
            _did(f"renamed card #{card['id']} from {card['title']!r} to {a2!r}")
            return f"Renamed it to {a2!r}."
        if verb in ("note", "append"):  # add detail to a card without losing what's there
            card = board_store.find_card(conn, a1)
            if card is None:
                return f"I couldn't find a card called {a1!r}."
            merged = f"{card.get('body', '')}\n{a2}".strip()
            board_store.update_card(conn, card["id"], body=merged)
            return f"Added a note to {card['title']!r}."
        if verb in ("delete_card", "delete", "remove"):
            card = board_store.find_card(conn, a1)
            if card is None:
                return f"I couldn't find a card called {a1!r}."
            if not (a1.strip().lstrip("#").isdigit() or _plainly_named(a1, card["title"])):
                return f"Did you mean {card['title']!r}? Say its name to delete it."
            where = _list_name(conn, card)
            board_store.delete_card(conn, card["id"])
            _did(f"deleted card {card['title']!r} from {where} (restorable: BOARD: restore | {card['title']})")
            return f"Deleted {card['title']!r}."
        if verb in ("due", "deadline", "set_due"):
            card = board_store.find_card(conn, a1)
            if card is None:
                return f"I couldn't find a card called {a1!r}."
            updated = board_store.update_card(conn, card["id"], due=a2 or "")
            if not updated["due"]:
                return f"Cleared the deadline on {card['title']!r}."
            return f"Set {card['title']!r} due {_spoken_due(updated['due'])}, with a reminder."
        if verb in ("tag", "label", "tags"):
            card = board_store.find_card(conn, a1)
            if card is None:
                return f"I couldn't find a card called {a1!r}."
            tags = card["tags"] + [t.strip() for t in a2.split(",") if t.strip() and t.strip() not in card["tags"]]
            board_store.update_card(conn, card["id"], tags=tags)
            return f"Added {a2!r} to {card['title']!r}."
        if verb in ("archive", "archive_card"):
            card = board_store.find_card(conn, a1)
            if card is None:
                return f"I couldn't find a card called {a1!r}."
            board_store.update_card(conn, card["id"], archived=True)
            _did(f"archived card #{card['id']} {card['title']!r}")
            return f"Archived {card['title']!r}."
        if verb in ("checklist", "check_item", "add_item"):
            card = board_store.find_card(conn, a1)
            if card is None:
                return f"I couldn't find a card called {a1!r}."
            items = card["checklist"] + [{"text": a2, "done": False}]
            board_store.update_card(conn, card["id"], checklist=items)
            return f"Added {a2!r} to the checklist on {card['title']!r}."
        if verb in ("restore", "undelete", "restore_card", "undo_delete"):
            card = board_store.restore_card(conn, a1)
            if card is None:
                return f"I couldn't find a deleted card called {a1!r}."
            _did(f"restored card #{card['id']} {card['title']!r} to {_list_name(conn, card)}")
            return f"Restored {card['title']!r}."
        if verb in ("add_list", "new_list"):
            return f"Added a {board_store.add_list(conn, a1)['name']!r} list."
        if verb in ("add_board", "new_board", "create_board"):
            return f"Created the {board_store.create_board(conn, a1)['name']!r} board."
        return f"I don't know how to {verb!r} on the board."
    except ValueError as exc:            # the store's own "no such list" / "already exists"
        msg = str(exc)                   # these get SPOKEN, so start them like a sentence
        return msg[:1].upper() + msg[1:] if msg else "That didn't work on the board."
    except Exception as exc:
        assistant._dbg("[board]", f"{verb} failed: {exc}")
        return "That didn't work on the board."
    finally:
        conn.close()


def _teach(phrase: str, action: str) -> str:
    """"Whenever I say X, do Y" → a real command in the DB, scoped to the focused app (idea #24).

    The missing third way to learn. Until now Vox could learn by REPETITION (3 hits) or by
    "remember that" AFTER an action — but there was no way to say up front "from now on X means Y",
    which is the most natural way to ask. Without it the request fell through to the chat brain,
    which can only talk: seen live, it replied "I've saved that as a standing rule" having saved
    nothing at all.

    Saved as ``source='user'``, deliberately: you asked for it explicitly, so it must NOT expire
    under probation the way an auto-learned guess does. Refuses to shadow a builtin phrase, the same
    way ``remap()`` does, so teaching can't quietly break a shipped command."""
    if not phrase or not action:
        return "Tell me both parts — like 'whenever I say refresh, reload the page'."
    parsed = actions.parse(action)
    if parsed is None:
        return f"I don't know how to {action}, so I can't map {phrase!r} to it yet."
    intent, arg = parsed
    try:
        from vox import command_cache, command_store
        conn = command_store.build()
        try:
            # Guard against shadowing a shipped command. Checked against the PHRASE TABLE directly,
            # across every context: resolve() only searches the global set plus the focused app, so
            # it silently misses an app-scoped builtin (it let "next tab" be re-pointed at "go back").
            clash = conn.execute(
                "SELECT c.label, c.intent FROM command c JOIN phrase p ON p.command_id=c.id "
                "WHERE lower(p.text)=lower(?) AND c.source='builtin' LIMIT 1", (phrase,)).fetchone()
            if clash:
                return (f"'{phrase}' is already a built-in command "
                        f"({clash['label'] or clash['intent']}), so I've left it alone.")
            # Already taught? CHANGE it rather than adding a rival row with the same trigger.
            # "when I say refresh, use reload instead" is an edit, and without this it created a
            # second command for the same phrase and the resolver had to pick between them.
            prior = conn.execute(
                "SELECT c.id, c.intent, c.arg, c.source FROM command c "
                "JOIN phrase p ON p.command_id = c.id "
                "WHERE lower(p.text)=lower(?) AND c.source IN ('user','learned') LIMIT 1",
                (phrase,)).fetchone()
            if prior is not None:
                was = command_store.remap(conn, prior["id"], intent, arg, allow_user=True)
                if was is None:
                    return f"I couldn't change the {phrase!r} command."
                old = f"{was['intent']} {was['arg']}".strip()
                return f"Changed {phrase!r} from {old} to {action}."

            app = command_cache.current_app()
            ctx = command_store._ensure_context(
                conn, "app", app, app, 10) if app else command_store._ensure_context(
                conn, "global", None, "Everywhere", 0)
            cid = command_store._add_command(
                conn, ctx, intent, f"{phrase.title()} (taught)", [phrase], arg=arg)
            conn.execute("UPDATE command SET source='user' WHERE id=?", (cid,))
            conn.commit()
        finally:
            conn.close()
        command_cache.refresh()
    except Exception as exc:
        assistant._dbg("[teach]", f"failed to save {phrase!r} → {intent}/{arg}: {exc}")
        return "I couldn't save that command just now."
    where = f"in {app}" if app else "everywhere"
    return f"Got it — saying '{phrase}' {where} will now {action}."


def _observe(heard: str, intent: str, arg: str, *, success: bool) -> None:
    """Hand a completed LLM-resolved action to the learning layer (idea #24; full design in
    ``docs/plan/command-learning/``). This is the ONE place the learner is fed — the model resolves
    an utterance to an action exactly as before, and the learner observes the outcome.

    Phase 1 is shadow mode: it accumulates candidates and evidence, and writes no commands. Fully
    guarded, so an observer bug can never break the action the user actually asked for."""
    try:
        from vox import command_cache, command_learn
        command_learn.observe(heard, intent, arg, app=command_cache.current_app(),
                              success=success, log=command_cache.log)
    except Exception:
        pass


def _start_agent(task: str) -> tuple[bool, str]:
    """Hand ``task`` to the agent tier (it sees the screen and acts, step by step)."""
    from vox import agent
    if not _setting("agent_enabled", CONFIG.agent_enabled):
        assistant._dbg("[executor]", f"decision=AGENT {task!r} → tier disabled")
        return False, "That needs the agent tier, which is switched off in Vox's settings."
    if agent.is_running():
        return False, "I'm already doing something on screen — say stop to cancel it."

    # Runs on a worker thread and speaks its own result when it finishes: a run can take a
    # minute, and blocking the voice loop here would wedge listening exactly like a dead mic
    # does. Keeping the loop alive is also what lets "stop" reach agent.abort().
    def _finished(acted, message):
        try:
            from vox import sounds, tts
            if message == agent.SILENT_DONE:  # a plain action you can see happened → chime, no voice
                sounds.play(_setting("sound_oneshot", CONFIG.sound_oneshot))
            elif message:
                tts.speak(message)
        except Exception:
            pass

    agent.run_async(task, on_done=_finished)
    assistant._dbg("[executor]", f"decision=AGENT {task!r} → started (async)")
    return True, "On it — say stop or press escape to cancel."


# Words that ask to type by voice, mis-hears included ("dot typing", "start typ", "take dictation").
_ASKS_TO_TYPE = re.compile(r"\b(?:typ|dictat|transcri|write|writing|keyboard)", re.IGNORECASE)


def execute(text: str, history=None) -> tuple[bool, str]:
    """Try to fulfil an uncertain command with the small brain.

    `history` carries a short clarification exchange (the brain's question + prior turns) so a
    follow-up answer has context. Returns (acted, message): acted=True means a Vox action ran
    (message is its result); acted=False means it replied conversationally (the spoken reply).
    """
    if not _setting("llm_executor_enabled", CONFIG.llm_executor_enabled):
        return False, assistant.respond(text, history)

    # Which app this utterance is about, captured NOW — before the LLM round-trip below, which is
    # the longest gap in Vox between the user speaking and something being pressed. Asking again
    # afterwards is issue O18: focus has often moved on, and the click lands in the wrong app.
    aim = actions.focus_target()

    # A 'yes' to our earlier 'Did you mean <X>?' click prompt → just click <X> (deterministic, no
    # second LLM round-trip). Anything other than an affirmation falls through to the brain below.
    # A 'yes' (or 'no') to "Send Sam an email…? Say yes to go ahead": the held connections request.
    held = _held_apps_reply(text)
    if held is not None:
        return held
    # A bare "no" / "nope" with nothing waiting for an answer is not an instruction. Given to the brain
    # with recent deletions in short-term memory it was read as "undo" and restored 8 board cards
    # (2026-11-07). Corrections that say what's wrong ("no, the other one") still go through.
    if not history and re.fullmatch(r"\s*(?:no|nope|nah|no thanks|no thank you)[.!]?\s*", text or "", re.I):
        return False, "Okay."

    cand = _confirmed_click_target(text, history)
    if cand:
        result = actions.click_element(cand)
        assistant._dbg("[executor]", f"decision=CLICK (confirmed {cand!r}) → {result!r}")
        return result.lower().startswith("clicked"), result

    ctx = actions.environment_context()
    prompt = f"{text}\n\n[Current Mac state — use this to pick the right app/tab]\n{ctx}" if ctx else text
    # What just ran, so a correction ("no, that's not what I wanted — it should do X") has something
    # to refer to, and so the brain doesn't redo an action it just did.
    recent = actions.recent_actions_block()
    if recent:
        prompt = f"{prompt}\n\n{recent}"
    try:  # "what's on my calendar today?": the day's events, when the question is about them
        from vox import routines
        cal = routines.calendar_context(text)
    except Exception:
        cal = ""
    if cal:
        prompt = f"{prompt}\n\n{cal}"
    try:  # what was just said and done, in every mode (one-shots have no other history)
        from vox import working_memory
        short = working_memory.block()
    except Exception:
        short = ""
    if short:
        prompt = f"{prompt}\n\n{short}"
    board = actions.board_block()   # so it can answer about the board and name cards precisely
    if board:
        prompt = f"{prompt}\n\n{board}"
    began = time.time()
    raw = assistant.complete(prompt, history, system=_router_system(), brain="small", prompt="router").strip()
    from vox import runtime
    if runtime.stopped_since(began):
        # The stop button was pressed while the brain was thinking. The caller has already moved
        # on; don't click or type anything now that nobody is waiting for it (issues.md O4).
        assistant._dbg("[executor]", "stop button pressed during the call → not acting on it")
        return False, ""
    if not raw:
        return False, assistant.respond(text, history)
    if assistant.failed(raw):
        # The brain errored ("Credit balance is too low", a timeout…). Running that text through the
        # command parser gave "I couldn't map that to something I can do", which hid the real problem.
        assistant._dbg("[executor]", f"decision=BRAIN FAILED {raw[:80]!r}")
        return False, f"My brain didn't answer: {raw.strip().strip('()')[:120]}"
    trimmed = _drop_preamble(raw)
    if trimmed != raw:
        assistant._dbg("[executor]", f"dropped a preamble before the directive: {raw[:len(raw) - len(trimmed)].strip()!r}")
        raw = trimmed
    # The brain's raw output IS the "tool call" (Vox uses translate-to-command, not native function-
    # calling). complete() already logged the full prompt + raw response; these _dbg lines complete
    # the picture by logging which action ran and what it returned — the tool interaction.
    upper = raw.upper()
    if upper.startswith("IGNORE"):  # background chatter / not meant for Vox → stay silent
        assistant._dbg("[executor]", "decision=IGNORE → stay silent (chatter)")
        return False, ""
    if upper.startswith("CHAT:"):
        reply = raw.split(":", 1)[1].strip() or assistant.respond(text, history)
        assistant._dbg("[executor]", f"decision=CHAT → speak {reply!r}")
        return False, reply
    if upper.startswith("CANT:"):  # it can't do this: say so, and log what was missing (vox.issues)
        missing, _, reply = raw.split(":", 1)[1].partition("|")
        reply = reply.strip() or missing.strip() or "I can't do that."
        from vox import issues
        issues.missing_hint = missing.strip() if "|" in raw else ""
        assistant._dbg("[executor]", f"decision=CANT (missing: {missing.strip()!r}) → speak {reply!r}")
        return False, reply
    if upper.startswith("WEB:"):
        from vox import web_search
        q = raw.split(":", 1)[1].strip() or text
        msg = web_search.answer(q)
        assistant._dbg("[executor]", f"decision=WEB {q!r} → {msg!r}")
        return False, msg
    if upper.startswith("MENU:"):
        want = raw.split(":", 1)[1].strip()
        from vox import ax
        res = ax.press_menu(want)
        status, item = res if res else ("unavailable", None)
        assistant._dbg("[executor]", f"decision=MENU {want!r} → {status} {item and item['title']!r}")
        if status == "pressed":
            return True, f"{item['title']}."
        if status == "disabled":
            return True, f"{item['title']} isn't available right now."
        if status == "not_found":
            return True, f"I couldn't find {want!r} in this app's menus."
        return True, "I couldn't use that menu."
    if upper.startswith("ISSUE:"):
        msg = actions.run_intent("log_issue", raw.split(":", 1)[1].strip())
        assistant._dbg("[executor]", f"decision=ISSUE → {msg!r}")
        return True, msg
    if upper.startswith("NOTE:"):
        where, _, what = raw.split(":", 1)[1].partition("|")
        where, what = where.strip(), what.strip()
        app = None if where.lower() in ("", "everywhere", "global", "all apps", "any app") else where
        try:
            from vox.web import rules
            rules.add_rule(what, app=app)
            msg = f"Noted for {app}." if app else "Noted."
        except Exception as exc:
            msg = f"Couldn't save that note ({exc})."
        assistant._dbg("[executor]", f"decision=NOTE app={app!r} {what!r} → {msg!r}")
        return False, msg
    if upper.startswith("SET:"):
        key, _, value = raw.split(":", 1)[1].partition("|")
        msg = actions.set_setting(f"{key.strip()}={value.strip()}")
        assistant._dbg("[executor]", f"decision=SET {key.strip()!r} = {value.strip()!r} → {msg!r}")
        return False, msg
    if upper.startswith("POINT:"):  # show where something is, without pressing it (ideas #69.2)
        target = raw.split(":", 1)[1].strip()
        from vox import ax
        with ax.pinned_to(*(aim or (0, ""))):
            result = actions.point_at(target)  # falls back to looking at the screen itself
        assistant._dbg("[executor]", f"decision=POINT target={target!r} → {result!r}")
        return result.startswith("There's"), result
    if upper.startswith("DICTATE"):  # user wants to type by voice → tell the loop to enter dictation
        if not _ASKS_TO_TYPE.search(text or ""):
            # Dictation types everything said next, so entering it by mistake is costly: on 17 Nov a
            # mis-heard "Hey Vox, open Claude" ("i think lord") came back DICTATE, likely because
            # "start typing" sat in the recent conversation, and the next four commands were typed
            # into the terminal. Only go in when the words themselves ask to type.
            assistant._dbg("[executor]", f"decision=DICTATE refused: {text!r} doesn't ask to type")
            return False, "Sorry, I didn't catch that. Say it again?"
        assistant._dbg("[executor]", "decision=DICTATE → enter dictation mode")
        return True, ENTER_DICTATION
    if upper.startswith("TYPE:"):
        body = raw.split(":", 1)[1].strip()
        result = actions.type_text(body)
        assistant._dbg("[executor]", f"decision=TYPE → actions.type_text({body!r}) → {result!r}")
        return True, result
    if upper.startswith("EDIT:"):
        instruction = raw.split(":", 1)[1].strip()
        result = actions.edit_selection(lambda sel: _rewrite(sel, instruction))
        assistant._dbg("[executor]", f"decision=EDIT instruction={instruction!r} → {result!r}")
        return True, result
    if upper.startswith("LOOK:"):
        if not _setting("screen_vision_enabled", CONFIG.screen_vision_enabled):
            return False, "Screen vision is turned off."
        question = raw.split(":", 1)[1].strip() or "What is on the screen?"
        mode = _setting("screen_vision_mode", CONFIG.screen_vision_mode)
        # "axtree"/"auto" → read the AX tree as text first (token-light, no image).
        if mode in ("axtree", "auto"):
            answer = _look_axtree(question)
            if answer is not None:
                assistant._dbg("[executor]", f"decision=LOOK (axtree) q={question!r} → {answer!r}")
                return False, answer
            if mode == "axtree":  # tree-only: no screenshot fallback
                return False, "I couldn't read the screen's accessibility tree."
            # mode == "auto": tree errored/empty → fall through to the screenshot path.
        path = actions.capture_screen()
        if not path:
            return False, ("I couldn't capture the screen — enable Screen Recording for your "
                           "terminal in System Settings → Privacy & Security.")
        answer = assistant.look(question, path, brain="big")  # screen-reading needs the sharper eye
        assistant._dbg("[executor]", f"decision=LOOK (screenshot) q={question!r} → {answer!r}")
        return False, answer
    if upper.startswith("SCHEDULE:"):
        # "Remind me at 8:30, and if I haven't got back to you by 9 open my uni profile" is two
        # things: a reminder and a routine, as two SCHEDULE: lines. Make every one of them.
        bodies = [ln.split(":", 1)[1].strip() for ln in raw.splitlines()
                  if ln.strip().upper().startswith("SCHEDULE:")][:10]
        msgs = []
        for body in bodies:
            msg = _schedule(body)
            assistant._dbg("[executor]", f"decision=SCHEDULE {body!r} → {msg!r}")
            msgs.append(msg or "I couldn't work out a time for that — try saying it with a clear time.")
        return False, " ".join(msgs)
    if upper.startswith("BOARD:"):
        # Several changes in one sentence ("add cards for X, Y and Z") arrive as several BOARD:
        # lines. Board edits are visible and easy to undo, so run them all, in order, stopping at
        # the first failure. Everything else stays first-directive-wins (todo.md §1b).
        bodies = [ln.split(":", 1)[1].strip() for ln in raw.splitlines()
                  if ln.strip().upper().startswith("BOARD:")][:40]   # 'clear my board' can be dozens
        msgs = []
        for body in bodies:
            msgs.append(_board(body))
            assistant._dbg("[executor]", f"decision=BOARD {body!r} → {msgs[-1]!r}")
            if not msgs[-1].startswith(_BOARD_OK):
                break
        return False, _board_summary(msgs)
    if upper.startswith("TEACH:"):
        body = raw.split(":", 1)[1].strip()
        phrase, _, action = body.partition("|")
        msg = _teach(phrase.strip(), action.strip())
        assistant._dbg("[executor]", f"decision=TEACH {phrase.strip()!r} → {action.strip()!r} :: {msg!r}")
        return False, msg
    if upper.startswith("AGENTS:"):
        req = raw.split(":", 1)[1].strip() or text
        from vox import team
        msg = team.ceo(req)
        assistant._dbg("[executor]", f"decision=AGENTS {req!r} → {msg!r}")
        return False, msg
    if upper.startswith("APPS:"):
        req = raw.split(":", 1)[1].strip() or text
        msg = _apps(req)
        assistant._dbg("[executor]", f"decision=APPS {req!r} → {msg!r}")
        return False, msg
    if upper.startswith("AGENT:"):
        return _start_agent(raw.split(":", 1)[1].strip())
    if upper.startswith("CLICK:"):
        target = raw.split(":", 1)[1].strip()
        # Everything from here on talks to the app captured BEFORE the round-trip above — the
        # verbatim finder, the enumeration the brain reads, the screenshot it looks at and the
        # eventual press all see one app (issue O18).
        from vox import ax
        with ax.pinned_to(*(aim or (0, ""))):
            # Fast path: the targeted AXPress finder (Electron-aware, early-exit). Only if it can't
            # find the target verbatim do we fall back to listing the screen + letting the brain
            # pick (slower). A click REFUSED because focus left that app is not a miss — retrying it
            # would just click whatever is in front now, so say so instead.
            result = actions.click_element(target, ask_if_ambiguous=True)
            if result.startswith(actions.WHICH_ONE):
                # Several controls share that name and they're numbered on screen now — the
                # user's next word is the number. Silent, like "show clickable".
                assistant._dbg("[executor]", f"decision=CLICK target={target!r} → {result!r}")
                return True, result
            if not (result.lower().startswith("clicked")
                    or result.startswith(actions.FOCUS_MOVED)):
                result = _click_fuzzy(target)
        assistant._dbg("[executor]", f"decision=CLICK target={target!r} → {result!r}")
        clicked = result.lower().startswith("clicked")
        _observe(text, "click", target, success=clicked)
        # Success → silent "did it" cue; failure → speak the "couldn't find it" so the user hears it.
        return clicked, result

    command = raw.splitlines()[0].strip().strip('"').rstrip(".")
    # PROSE GUARD. A reply the model forgot to prefix with CHAT: must not be run through the command
    # parser: parsing is substring-based, so an ordinary sentence can hit a command by accident. Seen
    # live — "There's one open issue about one-word commands…" matched the `open <target>` rule and
    # Vox tried to open a website called "issue about one-word commands like refresh…". A command is
    # never more than one sentence (`search <query>` is long but singular), so multiple sentences is
    # a reliable tell. Speaking the answer is both safer and what the user actually wanted.
    multi_sentence = re.search(r"[.!?]\s+[A-Z\"']", command) is not None
    if multi_sentence and len(command.split()) > 12:
        assistant._dbg("[executor]", f"decision=PROSE (no CHAT: prefix) → speak {command[:60]!r}…")
        return False, command
    parsed = actions.parse(command)
    if parsed is None:
        # Never dead-end on "I couldn't map that". A request Vox's fixed commands don't cover goes to
        # the agent tier, which looks at the screen and works it out; if that can't run, ask.
        if _setting("agent_enabled", CONFIG.agent_enabled):
            ok, msg = _start_agent(text)
            if ok:
                assistant._dbg("[executor]", f"decision=COMMAND {command!r} → no mapping → escalated to AGENT")
                return ok, msg
        assistant._dbg("[executor]", f"decision=COMMAND {command!r} → no mapping → asking")
        return False, f"What did you want me to do? I heard: {text.strip()[:120]}"
    result = actions.handle(command)
    assistant._dbg("[executor]", f"decision=COMMAND {command!r} → actions.handle → {result!r}")
    _observe(text, parsed[0], parsed[1], success=not actions.failed(result))
    return True, result
