"""LLM-as-executor (idea #12): on an uncertain command, the small brain decides what the
user meant and either runs a Vox action or replies.

Provider-agnostic by design: instead of native tool-calling (which differs per provider and
needs an API key), it asks the brain to *translate* the speech into one Vox command (or a short
reply). So it works on the Claude subscription (SDK/CLI), the Anthropic/OpenAI APIs, or a local
LLM — whatever the small brain is set to. See docs/plan/ideas.md #12-13.
"""

import re

from vox import actions, assistant, ax
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
    # numbered marks it looks at. Sharing the list also keeps badge N ↔ ax.click_index(N-1) aligned.
    try:
        items = ax.targets_with_frames() or []
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
        answer = assistant.look(_CLICK_VISION_PROMPT.format(target=target), marked, brain="big")
        m = re.search(r"\d{1,3}", answer or "")
        assistant._dbg("[executor]",
                       f"click-by-vision for {target!r} over {len(items)} marks → {(answer or '').strip()!r}")
        if not m:
            return None
        n = int(m.group())
        if not 1 <= n <= len(items):
            return None
        res = ax.click_index(n - 1)  # badge N ↔ items[N-1], same as the overlay
        if res and res[0] == "clicked":
            return f"clicked {res[1]} (#{n}, found by looking at the screen)"
        return None
    except Exception:
        return None


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
    parsed = actions.parse(command)
    if parsed is None:
        assistant._dbg("[executor]", f"decision=COMMAND {command!r} → no mapping (no-op)")
        return False, "I couldn't map that to something I can do."
    result = actions.handle(command)
    assistant._dbg("[executor]", f"decision=COMMAND {command!r} → actions.handle → {result!r}")
    _observe(text, parsed[0], parsed[1], success=not actions.failed(result))
    return True, result
