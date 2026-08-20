"""LLM-as-executor (idea #12): on an uncertain command, the small brain decides what the
user meant and either runs a Vox action or replies.

Provider-agnostic by design: instead of native tool-calling (which differs per provider and
needs an API key), it asks the brain to *translate* the speech into one Vox command (or a short
reply). So it works on the Claude subscription (SDK/CLI), the Anthropic/OpenAI APIs, or a local
LLM — whatever the small brain is set to. See docs/plan/ideas.md #12-13.
"""

import re

from vox import actions, assistant
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
    "  reload  (reload the current page — ALWAYS prefer this over clicking a reload button, which\n"
    "           only exists on some pages and breaks on the next one)\n"
    "  go to my <name> tab            ·  next tab / previous tab     ·  go back  ·  close tab\n"
    "  next window / previous window  ·  swipe left / swipe right    ·  profile <number>\n"
    "  <app> window  (switch to / cycle an app's windows, e.g. 'Cursor window')\n"
    "  show tabs / hide tabs\n"
    "Two more things you can do with text at the cursor:\n"
    "  • Compose text and insert it (e.g. 'write me an email about X', 'write a function that "
    "sums a list'): output  TYPE: <the full finished text>. It ALWAYS inserts at the user's "
    "current cursor — NEVER ask where to put it, just write it.\n"
    "  • Rewrite the text the user has SELECTED (e.g. 'make this pretty', 'fix the spelling', "
    "'make it formal', 'shorten this'): output  EDIT: <the rewrite instruction>. Don't ask what "
    "kind of text it is — the selection is fetched and rewritten automatically.\n"
    "To SEE the screen (e.g. 'what does this say?', 'what's on my screen', 'read this error', "
    "'what's this article about'): output  LOOK: <the question to answer about the screen>\n"
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
    "spreadsheet', 'scrub the video to the halfway point', 'fill in this form'. A single click, a "
    "single app switch, or anything with a visible label is NOT this — use CLICK: or a command, which "
    "are far faster.\n"
    "To set a TIMER, ALARM, or REMINDER: output  SCHEDULE: <kind> | <when> | <text> | <repeat>\n"
    "  <kind> = timer, alarm, or reminder.\n"
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
    "To CHANGE it, output  BOARD: <verb> | <arg> | <arg>  using exactly one of:\n"
    "  BOARD: add_card | <list> | <title>        ·  BOARD: move_card | <card> | <list>\n"
    "  BOARD: update_card | <card> | <new title> ·  BOARD: note | <card> | <text to append>\n"
    "  BOARD: delete_card | <card>               ·  BOARD: add_list | <name>\n"
    "  BOARD: add_board | <name>\n"
    "Refer to a card by its TITLE as the user said it (close is fine, it's matched fuzzily), or by "
    "the #id shown. Examples: 'add a card to doing called fix the scraper' → "
    "BOARD: add_card | Doing | fix the scraper  ·  'move the AC direct card to done' → "
    "BOARD: move_card | AC direct | Done  ·  'put a note on the scraper card that it needs "
    "proxies' → BOARD: note | scraper | needs proxies.\n"
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
    "• To ask (rarely): CHAT: <short question>. For a real question or something you truly can't "
    "do: CHAT: <one short spoken sentence>.\n"
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
    """Apply a rewrite instruction to selected text (used by the EDIT / 'make this pretty' flow)."""
    return assistant.complete(f"Instruction: {instruction}\n\nText to rewrite:\n{selected}",
                              system=_EDIT_SYSTEM, brain="small")


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
    answer = assistant.complete(prompt, system=_LOOK_AXTREE_SYSTEM, brain="small", kind="vision_axtree")
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


def _confirmed_click_target(text: str, history) -> str | None:
    """If we just asked 'Did you mean <X>?' for a click and the user affirmed, return <X> to click.
    Reads the candidate from the most-recent assistant turn in the clarification history."""
    if not history or not _AFFIRMATIVE.match(text or ""):
        return None
    for role, content in reversed(history):
        if role == "assistant":
            m = _DID_YOU_MEAN.match((content or "").strip())
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
    if not labels:
        return f"I couldn't find a '{target}' to click."
    listing = "\n".join(f"  - {label}" for label in labels)
    prompt = (f"Clickable elements on screen:\n{listing}\n\n"
              f"The user wants to click: {target!r}\n"
              f"Your answer (a verbatim label, or ASK: <label>, or NONE):")
    raw = assistant.complete(prompt, system=_CLICK_PICK_SYSTEM, brain="big", kind="click_axtree")
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
            _CLICK_VISION_PROMPT.format(target=target, n=len(items)), marked, brain="big")
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
        from vox import targets
        res = targets.click_index(n - 1)  # badge N ↔ items[N-1], same as the overlay
        if res and res[0] == "clicked":
            return f"clicked {res[1]} (#{n}, found by looking at the screen)"
        return None
    except Exception:
        return None


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
            return f"Added {card['title']!r} to {a1}."
        if verb in ("move_card", "move"):
            card = board_store.find_card(conn, a1)
            if card is None:
                return f"I couldn't find a card called {a1!r}."
            board_store.move_card(conn, card["id"], a2)
            return f"Moved {card['title']!r} to {a2}."
        if verb in ("update_card", "edit", "rename_card"):
            card = board_store.find_card(conn, a1)
            if card is None:
                return f"I couldn't find a card called {a1!r}."
            board_store.update_card(conn, card["id"], title=a2 or None)
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
            board_store.delete_card(conn, card["id"])
            return f"Deleted {card['title']!r}."
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


def execute(text: str, history=None) -> tuple[bool, str]:
    """Try to fulfil an uncertain command with the small brain.

    `history` carries a short clarification exchange (the brain's question + prior turns) so a
    follow-up answer has context. Returns (acted, message): acted=True means a Vox action ran
    (message is its result); acted=False means it replied conversationally (the spoken reply).
    """
    if not _setting("llm_executor_enabled", CONFIG.llm_executor_enabled):
        return False, assistant.respond(text, history)

    # A 'yes' to our earlier 'Did you mean <X>?' click prompt → just click <X> (deterministic, no
    # second LLM round-trip). Anything other than an affirmation falls through to the brain below.
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
    board = actions.board_block()   # so it can answer about the board and name cards precisely
    if board:
        prompt = f"{prompt}\n\n{board}"
    raw = assistant.complete(prompt, history, system=_SYSTEM, brain="small").strip()
    if not raw:
        return False, assistant.respond(text, history)
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
    if upper.startswith("DICTATE"):  # user wants to type by voice → tell the loop to enter dictation
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
        body = raw.split(":", 1)[1].strip()
        msg = None
        try:
            from vox import scheduler
            # Preferred: the brain emits a structured "kind | ISO-when | text | repeat" (it computed
            # the absolute time from 'Now:'), so we create it directly — no fragile English re-parse.
            if "|" in body:
                parts = [p.strip() for p in body.split("|")]
                parts += [""] * (4 - len(parts))  # pad so missing trailing fields are just empty
                msg = scheduler.create_structured(parts[0], parts[1], parts[2], parts[3])
            # Fallback: a plain-English restatement (model ignored the format) → the deterministic
            # parser (now connector-tolerant: "to"/"that"/"about"/"saying").
            if msg is None:
                msg = scheduler.parse_and_create(body)
        except Exception:
            msg = None
        assistant._dbg("[executor]", f"decision=SCHEDULE {body!r} → {msg!r}")
        return False, (msg or "I couldn't work out a time for that — try saying it with a clear time.")
    if upper.startswith("BOARD:"):
        body = raw.split(":", 1)[1].strip()
        msg = _board(body)
        assistant._dbg("[executor]", f"decision=BOARD {body!r} → {msg!r}")
        return False, msg
    if upper.startswith("TEACH:"):
        body = raw.split(":", 1)[1].strip()
        phrase, _, action = body.partition("|")
        msg = _teach(phrase.strip(), action.strip())
        assistant._dbg("[executor]", f"decision=TEACH {phrase.strip()!r} → {action.strip()!r} :: {msg!r}")
        return False, msg
    if upper.startswith("AGENT:"):
        task = raw.split(":", 1)[1].strip()
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
                from vox import tts
                if message:
                    tts.speak(message)
            except Exception:
                pass

        agent.run_async(task, on_done=_finished)
        assistant._dbg("[executor]", f"decision=AGENT {task!r} → started (async)")
        return True, "On it — say stop or press escape to cancel."
    if upper.startswith("CLICK:"):
        target = raw.split(":", 1)[1].strip()
        # Fast path: the targeted AXPress finder (Electron-aware, early-exit). Only if it can't find
        # the target verbatim do we fall back to listing the screen + letting the brain pick (slower).
        result = actions.click_element(target)
        if not result.lower().startswith("clicked"):
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
        assistant._dbg("[executor]", f"decision=COMMAND {command!r} → no mapping (no-op)")
        return False, "I couldn't map that to something I can do."
    result = actions.handle(command)
    assistant._dbg("[executor]", f"decision=COMMAND {command!r} → actions.handle → {result!r}")
    _observe(text, parsed[0], parsed[1], success=not actions.failed(result))
    return True, result
