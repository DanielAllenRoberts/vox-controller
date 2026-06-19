"""LLM-as-executor (idea #12): on an uncertain command, the small brain decides what the
user meant and either runs a Vox action or replies.

Provider-agnostic by design: instead of native tool-calling (which differs per provider and
needs an API key), it asks the brain to *translate* the speech into one Vox command (or a short
reply). So it works on the Claude subscription (SDK/CLI), the Anthropic/OpenAI APIs, or a local
LLM — whatever the small brain is set to. See docs/plan/ideas.md #12-13.
"""

from vox import actions, assistant
from vox.config import CONFIG


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
    "To set a TIMER, ALARM, or REMINDER ('remind me to call Sam in 10 minutes', 'set a timer for "
    "5 minutes', 'set an alarm for 7am', 'remind me every day at 9 to stretch'): output  "
    "SCHEDULE: <a clear, COMPLETE restatement that includes the time>, e.g. SCHEDULE: remind me "
    "to call Sam in 10 minutes.\n"
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
    "(role, title, value). Read it and answer concisely for text-to-speech (1-2 sentences)."
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
    # kind="vision_axtree" tags this on the Token Usage page so its cost/effectiveness is tracked.
    return assistant.complete(prompt, system=_LOOK_AXTREE_SYSTEM, brain="big", kind="vision_axtree")


def execute(text: str, history=None) -> tuple[bool, str]:
    """Try to fulfil an uncertain command with the small brain.

    `history` carries a short clarification exchange (the brain's question + prior turns) so a
    follow-up answer has context. Returns (acted, message): acted=True means a Vox action ran
    (message is its result); acted=False means it replied conversationally (the spoken reply).
    """
    if not _setting("llm_executor_enabled", CONFIG.llm_executor_enabled):
        return False, assistant.respond(text, history)

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
        phrase = raw.split(":", 1)[1].strip()
        try:
            from vox import scheduler
            msg = scheduler.parse_and_create(phrase)
        except Exception:
            msg = None
        assistant._dbg("[executor]", f"decision=SCHEDULE {phrase!r} → {msg!r}")
        return False, (msg or "I couldn't work out a time for that — try saying it with a clear time.")

    command = raw.splitlines()[0].strip().strip('"').rstrip(".")
    if actions.parse(command) is None:
        assistant._dbg("[executor]", f"decision=COMMAND {command!r} → no mapping (no-op)")
        return False, "I couldn't map that to something I can do."
    result = actions.handle(command)
    assistant._dbg("[executor]", f"decision=COMMAND {command!r} → actions.handle → {result!r}")
    return True, result
