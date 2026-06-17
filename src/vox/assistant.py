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
    "never mention it. When unsure, prefer [OPEN].\n\n"
    "If a request needs deep reasoning, careful analysis, long writing, or coding beyond a quick "
    "spoken answer, reply with exactly [BIG] and nothing else — a more capable model then takes "
    "over. Use this sparingly, only when a short answer genuinely won't do."
)

_anthropic_client = None
_openai_client = None


def respond(text: str, history=None, brain: str = "small") -> str:
    """One chat turn → reply text (control tag stripped)."""
    return respond_turn(text, history, brain)[0]


def respond_turn(text: str, history=None, brain: str = "small") -> tuple[str, bool]:
    """One chat turn → (reply text, expects_reply).

    The model tags its reply [OPEN]/[DONE] (see _SYSTEM); we strip the tag and let it decide
    whether Vox keeps listening. The small brain may emit [BIG] to defer the turn to the big
    brain. Falls back to a '?' heuristic if the model omits the tag.
    """
    raw = complete(text, history, brain=brain, system=_SYSTEM)
    if (CONFIG.escalate_to_big_brain and brain == "small"
            and raw.strip().upper().startswith("[BIG]")):
        raw = complete(text, history, brain="big", system=_SYSTEM)  # small brain deferred
    return _split_signal(raw)


def _brain(name: str) -> tuple[str, str]:
    """(provider, model) for the named brain ('small' or 'big')."""
    if name == "big":
        return CONFIG.big_brain_provider, CONFIG.big_brain_model
    return CONFIG.small_brain_provider, CONFIG.small_brain_model


def complete(text: str, history=None, *, brain: str = "small", system: str = _SYSTEM) -> str:
    """One raw completion from the named brain with the given system prompt. Provider-agnostic."""
    provider, model = _brain(brain)
    if provider == "claude_sdk":
        return _claude_sdk(text, history, model, system)
    if provider == "claude_cli":
        return _claude_cli(text, history, model, system)
    if provider == "openai":
        return _openai(text, history, model, system)
    return _anthropic(text, history, model, system)


def _split_signal(raw: str) -> tuple[str, bool]:
    """Pull the trailing [OPEN]/[DONE] turn-taking tag off a reply → (clean text, expects_reply)."""
    s = (raw or "").strip()
    if s.upper().startswith("[BIG]"):  # stray defer token (big brain shouldn't emit it) → drop
        s = s[5:].strip()
    m = re.search(r"\[(open|done)\]", s, re.IGNORECASE)  # normally trailing; match anywhere to be safe
    if m:
        clean = (s[: m.start()] + s[m.end():]).strip()
        return clean, m.group(1).lower() == "open"
    return s, s.endswith("?")  # model didn't tag → fall back to the question heuristic


def _anthropic(text, history, model, system):
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
            model=model, max_tokens=CONFIG.llm_max_tokens, system=system, messages=msgs)
        return "".join(b.text for b in resp.content if b.type == "text").strip()
    except Exception as exc:
        return f"(LLM error: {exc})"


def _openai(text, history, model, system):
    key = os.environ.get(CONFIG.llm_api_key_env)
    if not key:
        return f"I need {CONFIG.llm_api_key_env} in your .env — add it and restart Vox."
    global _openai_client
    if _openai_client is None:
        from openai import OpenAI
        _openai_client = OpenAI(api_key=key, base_url=CONFIG.llm_base_url or None)
    msgs = ([{"role": "system", "content": system}]
            + [{"role": r, "content": c} for r, c in (history or [])]
            + [{"role": "user", "content": text}])
    try:
        resp = _openai_client.chat.completions.create(
            model=model, max_tokens=CONFIG.llm_max_tokens, messages=msgs)
        return (resp.choices[0].message.content or "").strip()
    except Exception as exc:
        return f"(LLM error: {exc})"


def _claude_sdk(text, history, model, system):
    # Claude Code via the Agent SDK — runs on your Claude subscription, no API key.
    import asyncio

    from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, TextBlock, query

    convo = "\n".join(f"{'You' if r == 'user' else 'Vox'}: {c}" for r, c in (history or []))
    prompt = f"{convo + chr(10) if convo else ''}You: {text}"
    opts = ClaudeAgentOptions(system_prompt=system, allowed_tools=[], max_turns=1, model=model)

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


def _claude_cli(text, history, model, system):
    # Use the Claude Code CLI (`claude -p`) — runs on your Claude subscription, no API key.
    convo = "\n".join(f"{'You' if r == 'user' else 'Vox'}: {c}" for r, c in (history or []))
    prompt = f"{system}\n\nConversation so far:\n{convo + chr(10) if convo else ''}You: {text}\nVox:"
    cmd = ["claude", "-p", prompt] + (["--model", model] if model else [])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        return r.stdout.strip() if r.returncode == 0 else f"(claude CLI error: {r.stderr.strip() or 'failed'})"
    except FileNotFoundError:
        return "Claude CLI not found — install Claude Code, or set a different brain provider."
    except Exception as exc:
        return f"(claude CLI error: {exc})"
