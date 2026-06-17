"""Assistant (LLM) brain — provider-agnostic. Powers ASSISTANT mode (and later, escalation).

Pick a provider in config (anthropic / openai-compatible / claude_cli). Keys come from .env.
"""

import os
import re
import subprocess

from vox.config import CONFIG

_SYSTEM = (
    "You are Vox, a hands-free voice assistant and Mac controller the user built themselves. "
    "You run locally (Whisper speech-to-text + a wake word) and you're being SPOKEN to, so "
    "reply concisely and conversationally — usually 1–3 sentences, plain text, no markdown.\n\n"
    "How Vox works (so you understand yourself):\n"
    "• CONTROL mode (\"take control\"): deterministic Mac commands run via AppleScript/keystrokes "
    "— open apps, go to apps/websites (reusing a tab in the current Arc profile), switch browser "
    "tabs/app windows/macOS desktops/Arc profiles, web search, dictation, go back. You don't run "
    "these yourself.\n"
    "• ASSISTANT mode (\"Hey Vox\"): this is you — open conversation and questions.\n"
    "• DICTATION (\"start typing\"): the user's speech is typed at the cursor.\n"
    "Unrecognised control commands 'hand off' to you. The user can also say \"Vox, <command>\" "
    "for a one-shot command from idle.\n\n"
    "Be helpful, warm, and direct. If asked to do something you can't do from here, briefly say "
    "how they'd do it by voice.\n\n"
    "Turn-taking: at the very end of every reply, append exactly one control tag — [OPEN] if you "
    "expect the user to respond (you asked a question or invited them to keep going), or [DONE] if "
    "the exchange reached a natural stopping point. The tag is stripped before it's shown or spoken; "
    "never mention it. When unsure, prefer [OPEN]."
)

_anthropic_client = None
_openai_client = None


def respond(text: str, history=None) -> str:
    """One chat turn → reply text (control tag stripped). Used where we don't care about turn-taking."""
    return respond_turn(text, history)[0]


def respond_turn(text: str, history=None) -> tuple[str, bool]:
    """One chat turn → (reply text, expects_reply).

    The model tags its reply [OPEN]/[DONE] (see _SYSTEM); we strip the tag and let it decide
    whether Vox keeps listening. Falls back to a '?' heuristic if the model omits the tag.
    """
    provider = CONFIG.llm_provider
    if provider == "claude_sdk":
        raw = _claude_sdk(text, history)
    elif provider == "claude_cli":
        raw = _claude_cli(text, history)
    elif provider == "openai":
        raw = _openai(text, history)
    else:
        raw = _anthropic(text, history)
    return _split_signal(raw)


def _split_signal(raw: str) -> tuple[str, bool]:
    """Pull the trailing [OPEN]/[DONE] turn-taking tag off a reply → (clean text, expects_reply)."""
    s = (raw or "").strip()
    m = re.search(r"\[(open|done)\]", s, re.IGNORECASE)  # normally trailing; match anywhere to be safe
    if m:
        clean = (s[: m.start()] + s[m.end():]).strip()
        return clean, m.group(1).lower() == "open"
    return s, s.endswith("?")  # model didn't tag → fall back to the question heuristic


def _anthropic(text, history):
    key = os.environ.get(CONFIG.llm_api_key_env or "ANTHROPIC_API_KEY")
    if not key:
        return f"I need {CONFIG.llm_api_key_env} in your .env — add it and restart Vox."
    global _anthropic_client
    if _anthropic_client is None:
        from anthropic import Anthropic
        _anthropic_client = Anthropic(api_key=key)
    msgs = [{"role": r, "content": c} for r, c in (history or [])] + [{"role": "user", "content": text}]
    try:
        resp = _anthropic_client.messages.create(
            model=CONFIG.llm_model, max_tokens=CONFIG.llm_max_tokens, system=_SYSTEM, messages=msgs)
        return "".join(b.text for b in resp.content if b.type == "text").strip()
    except Exception as exc:
        return f"(LLM error: {exc})"


def _openai(text, history):
    key = os.environ.get(CONFIG.llm_api_key_env)
    if not key:
        return f"I need {CONFIG.llm_api_key_env} in your .env — add it and restart Vox."
    global _openai_client
    if _openai_client is None:
        from openai import OpenAI
        _openai_client = OpenAI(api_key=key, base_url=CONFIG.llm_base_url or None)
    msgs = ([{"role": "system", "content": _SYSTEM}]
            + [{"role": r, "content": c} for r, c in (history or [])]
            + [{"role": "user", "content": text}])
    try:
        resp = _openai_client.chat.completions.create(
            model=CONFIG.llm_model, max_tokens=CONFIG.llm_max_tokens, messages=msgs)
        return (resp.choices[0].message.content or "").strip()
    except Exception as exc:
        return f"(LLM error: {exc})"


def _claude_sdk(text, history):
    # Claude Code via the Agent SDK — runs on your Claude subscription, no API key.
    import asyncio

    from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, TextBlock, query

    convo = "\n".join(f"{'You' if r == 'user' else 'Vox'}: {c}" for r, c in (history or []))
    prompt = f"{convo + chr(10) if convo else ''}You: {text}"
    opts = ClaudeAgentOptions(system_prompt=_SYSTEM, allowed_tools=[], max_turns=1)

    async def _run():
        parts = []
        async for msg in query(prompt=prompt, options=opts):
            if isinstance(msg, AssistantMessage):
                parts += [b.text for b in msg.content if isinstance(b, TextBlock)]
        return "".join(parts).strip()

    try:
        return asyncio.run(_run()) or "(no response)"
    except Exception as exc:
        return f"(claude SDK error: {exc})"


def _claude_cli(text, history):
    # Use the Claude Code CLI (`claude -p`) — runs on your Claude subscription, no API key.
    convo = "\n".join(f"{'You' if r == 'user' else 'Vox'}: {c}" for r, c in (history or []))
    prompt = f"{_SYSTEM}\n\nConversation so far:\n{convo + chr(10) if convo else ''}You: {text}\nVox:"
    try:
        r = subprocess.run(["claude", "-p", prompt], capture_output=True, text=True, timeout=90)
        return r.stdout.strip() if r.returncode == 0 else f"(claude CLI error: {r.stderr.strip() or 'failed'})"
    except FileNotFoundError:
        return "Claude CLI not found — install Claude Code, or set a different llm_provider."
    except Exception as exc:
        return f"(claude CLI error: {exc})"
