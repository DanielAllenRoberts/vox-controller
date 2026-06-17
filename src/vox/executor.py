"""LLM-as-executor (idea #12): on an uncertain command, the small brain decides what the
user meant and either runs a Vox action or replies.

Provider-agnostic by design: instead of native tool-calling (which differs per provider and
needs an API key), it asks the brain to *translate* the speech into one Vox command (or a short
reply). So it works on the Claude subscription (SDK/CLI), the Anthropic/OpenAI APIs, or a local
LLM — whatever the small brain is set to. See docs/plan/ideas.md #12-13.
"""

from vox import actions, assistant
from vox.config import CONFIG

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


def execute(text: str, history=None) -> tuple[bool, str]:
    """Try to fulfil an uncertain command with the small brain.

    `history` carries a short clarification exchange (the brain's question + prior turns) so a
    follow-up answer has context. Returns (acted, message): acted=True means a Vox action ran
    (message is its result); acted=False means it replied conversationally (the spoken reply).
    """
    if not CONFIG.llm_executor_enabled:
        return False, assistant.respond(text, history)

    ctx = actions.environment_context()
    prompt = f"{text}\n\n[Current Mac state — use this to pick the right app/tab]\n{ctx}" if ctx else text
    raw = assistant.complete(prompt, history, system=_SYSTEM, brain="small").strip()
    if not raw:
        return False, assistant.respond(text, history)
    upper = raw.upper()
    if upper.startswith("IGNORE"):  # background chatter / not meant for Vox → stay silent
        return False, ""
    if upper.startswith("CHAT:"):
        return False, raw.split(":", 1)[1].strip() or assistant.respond(text, history)
    if upper.startswith("TYPE:"):
        return True, actions.type_text(raw.split(":", 1)[1].strip())
    if upper.startswith("EDIT:"):
        instruction = raw.split(":", 1)[1].strip()
        return True, actions.edit_selection(lambda sel: _rewrite(sel, instruction))
    if upper.startswith("LOOK:"):
        if not CONFIG.screen_vision_enabled:
            return False, "Screen vision is turned off."
        question = raw.split(":", 1)[1].strip() or "What is on the screen?"
        path = actions.capture_screen()
        if not path:
            return False, ("I couldn't capture the screen — enable Screen Recording for your "
                           "terminal in System Settings → Privacy & Security.")
        return False, assistant.look(question, path, brain="big")  # screen-reading needs the sharper eye

    command = raw.splitlines()[0].strip().strip('"').rstrip(".")
    if actions.parse(command) is None:
        return False, "I couldn't map that to something I can do."
    return True, actions.handle(command)
