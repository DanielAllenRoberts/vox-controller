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
    "  show tabs / hide tabs\n"
    "Rules:\n"
    "• If it maps to a command, output just that command line (e.g. close tab).\n"
    "• If it's a question or can't be done as a command, output: CHAT: <one short spoken sentence>\n"
    "• Transcripts may be garbled — infer intent. Output nothing except the command or the CHAT line."
)


def execute(text: str) -> tuple[bool, str]:
    """Try to fulfil an uncertain command with the small brain.

    Returns (acted, message): acted=True means a Vox action ran (message is its result);
    acted=False means it replied conversationally (message is the spoken reply).
    """
    if not CONFIG.llm_executor_enabled:
        return False, assistant.respond(text)

    raw = assistant.complete(text, system=_SYSTEM, brain="small").strip()
    if not raw:
        return False, assistant.respond(text)
    if raw.upper().startswith("CHAT:"):
        return False, raw.split(":", 1)[1].strip() or assistant.respond(text)

    command = raw.splitlines()[0].strip().strip('"').rstrip(".")
    if actions.parse(command) is None:
        return False, "I couldn't map that to something I can do."
    return True, actions.handle(command)
