"""Assistant (LLM) brain — provider-agnostic. Powers ASSISTANT mode (and later, escalation).

Pick a provider in config (anthropic / openai-compatible / claude_cli). Keys come from .env.
"""

import os
import re
import subprocess
import time

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
    "over. Use this sparingly, only when a short answer genuinely won't do.\n\n"
    "Voice: your reply is shown in full and also read aloud. When the spoken version should be "
    "shorter than the written one, add a final line 'SAY: <concise spoken version>' — then only "
    "that line is read aloud (it's removed from the shown text). Skip it when the whole reply is "
    "fine to speak.\n\n"
    "Memory: you can remember things across conversations. When the user shares something worth "
    "keeping, append a capture directive on its own line at the very end of your reply — "
    "'MEMORY[core]: <fact>' for durable, always-relevant facts (their name, standing "
    "preferences, long-term projects, standing instructions) or 'MEMORY[daily]: <note>' for "
    "passing, session-specific things (what you did today, one-off requests). It's stripped before "
    "the reply is shown or spoken; never mention it. Use it sparingly and only for genuinely useful "
    "facts — core is rare and high-signal, daily is contextual. Don't repeat things you already "
    "remember."
)

_anthropic_client = None
_openai_client = None


def _setting(key: str, fallback):
    """Read a runtime override from the dashboard's settings_store, else fall back to Config.
    Fully guarded: if vox.web.settings_store is missing or errors, return the fallback so the
    daemon behaves exactly as before. None from the store also means 'unset' → fallback."""
    try:
        from vox.web import settings_store
        val = settings_store.get(key)
        return fallback if val is None else val
    except Exception:
        return fallback


def _active_persona() -> str:
    """The live active persona text for the system prompt.

    Reads the dashboard's personalities store (the persona the user picked in the UI),
    falling back to CONFIG.personality, then "". Fully guarded: if vox.web.personalities
    is missing or broken, behave exactly as today (CONFIG.personality / "")."""
    try:
        from vox.web import personalities
        active = personalities.get_active()
        if active:
            return active
    except Exception:
        pass
    return CONFIG.personality or ""


def _rules_block() -> str:
    """The user's enabled custom rules, rendered for the system prompt.

    Reads the dashboard's rules store (vox.web.rules.enabled_rules_text()). Fully
    guarded: if the module is missing or broken, return "" so the daemon behaves
    exactly as today (no rules layered on)."""
    try:
        from vox.web import rules
        text = (rules.enabled_rules_text() or "").strip()
        if text:
            return ("Additional rules from the user (follow these, they override "
                    f"defaults where they conflict):\n{text}")
    except Exception:
        pass
    return ""


def _mem_text(h) -> str:
    """The text of a recall hit, whether it's a dict ({text:...}) or a plain string."""
    if isinstance(h, dict):
        return (h.get("text") or "").strip()
    return (h or "").strip() if isinstance(h, str) else ""


def _memory_block(user_text: str) -> str:
    """Remembered context for this turn, rendered for the system prompt.

    Injects ALL core memories (labelled so the model treats them as durable) plus the
    top relevant daily entries (keyword-matched to this turn). Works with both the
    tiered store (memory.core() + memory.recall returning core+daily with a `tier`)
    and the legacy flat store (recall only) — whichever ships. Fully guarded: if the
    module is missing or broken, return "" so the daemon behaves exactly as today."""
    try:
        from vox import memory

        core_lines: list[str] = []
        # Prefer an explicit core() accessor (tiered store); fall back to filtering
        # recall hits by their `tier`, then to nothing (legacy flat store has no core).
        try:
            core_lines = [t for t in (_mem_text(h) for h in (memory.core() or [])) if t]
        except AttributeError:
            pass

        hits = memory.recall(user_text, k=5) or []
        daily_lines: list[str] = []
        for h in hits:
            text = _mem_text(h)
            if not text:
                continue
            tier = h.get("tier") if isinstance(h, dict) else None
            if tier == "core" or text in core_lines:
                # A core hit surfaced by recall — only keep it in the core section.
                if not core_lines and tier == "core":
                    core_lines.append(text)
                continue
            daily_lines.append(text)

        # No core() accessor and no tier metadata (legacy store): treat recall hits as
        # the things-you-remember block, preserving today's behaviour.
        blocks: list[str] = []
        if core_lines:
            blocks.append("What you always remember about the user:\n"
                          + "\n".join(f"• {t}" for t in core_lines))
        if daily_lines:
            label = ("Recent notes that may be relevant (use if helpful):"
                     if core_lines else "Things you remember about the user (use if relevant):")
            blocks.append(label + "\n" + "\n".join(f"• {t}" for t in daily_lines))
        return "\n\n".join(blocks)
    except Exception:
        pass
    return ""


def _autocapture_on() -> bool:
    """Whether auto-capture is enabled (dashboard toggle, default on). Guarded → True
    if the settings store is missing/broken, so capture works out of the box."""
    return bool(_setting("memory_autocapture", True))


def _mem_add(text: str, tier: str) -> None:
    """Save one memory at the given tier. Tries the tiered API (add(text, tier=...))
    and falls back to the legacy flat API (add(text)) if it doesn't accept a tier.
    Fully guarded: a missing/broken memory module is a silent no-op — capture must
    never break a reply."""
    text = (text or "").strip()
    if not text:
        return
    try:
        from vox import memory
        try:
            memory.add(text, tier=tier)
        except TypeError:
            memory.add(text)  # legacy flat store: no tiers
    except Exception:
        pass


# MEMORY[core]: ... / MEMORY[daily]: ... — a capture directive the model may append.
# Matched on its own line; the rest of the line (to EOL) is the fact/note.
_MEMORY_DIRECTIVE = re.compile(r"(?im)^[ \t]*MEMORY\[(core|daily)\]:[ \t]*(.+?)[ \t]*$")

# Explicit user request to remember something → core by default. Captures the fact
# after "remember that/to" so "remember that I like tea" stores "I like tea".
_REMEMBER_THAT = re.compile(r"(?i)\bremember\s+(?:that|to)\s+(.+)", re.DOTALL)
_REMEMBER_THIS = re.compile(r"(?i)\bremember\s+(?:this|that)\b")


def _capture_from_reply(reply: str) -> str:
    """Parse any MEMORY[core|daily] directives the model appended, store them (gated on
    the autocapture setting), and return the reply with those directive lines stripped
    so they're never shown or spoken. Always strips, even when capture is off, so a
    directive never leaks into the output. Fully guarded."""
    if not reply or "MEMORY[" not in reply:
        return reply
    try:
        on = _autocapture_on()
        if on:
            for m in _MEMORY_DIRECTIVE.finditer(reply):
                # A trailing [OPEN]/[DONE]/[BIG] tag may share the directive's line — drop it
                # so it doesn't leak into the stored fact.
                fact = re.sub(r"(?i)\[(open|done|big)\]", "", m.group(2)).strip()
                _mem_add(fact, m.group(1).lower())
        # Strip the directive lines regardless (don't leak the syntax to the user).
        cleaned = _MEMORY_DIRECTIVE.sub("", reply)
        # Collapse any blank lines the removal left behind.
        cleaned = re.sub(r"\n[ \t]*\n[ \t]*\n+", "\n\n", cleaned)
        return cleaned.strip()
    except Exception:
        return reply


def _capture_from_user(user_text: str) -> None:
    """Handle an explicit 'remember that X' / 'remember this' user turn by saving to
    core (gated on the autocapture setting). Best-effort and guarded — a no-op if the
    turn isn't a remember request, capture is off, or the memory module is missing."""
    if not user_text:
        return
    try:
        if not _autocapture_on():
            return
        m = _REMEMBER_THAT.search(user_text)
        if m:
            _mem_add(m.group(1), "core")
        elif _REMEMBER_THIS.search(user_text):
            # "remember this" with no explicit fact → store the surrounding utterance.
            _mem_add(user_text, "core")
    except Exception:
        pass


def _record_usage(provider, model, brain, kind, usage, latency_ms):
    """Record one LLM call for the dashboard (token usage / cost). LAZY + GUARDED: a missing or
    broken vox.web.usage module must NEVER break a reply — recording is best-effort telemetry.

    `usage` is a (input_tokens, output_tokens) tuple, or None when the provider didn't expose
    token counts (e.g. SDK/CLI subscription calls); the usage store decides how to handle that."""
    try:
        from vox.web import usage as usage_mod
        inp, out = usage if usage else (None, None)
        usage_mod.record_usage(
            provider=provider, model=model, brain=brain, kind=kind,
            input_tokens=inp, output_tokens=out, latency_ms=latency_ms,
        )
    except Exception:
        pass  # telemetry only — never surface to the voice loop


def _sdk_extract_tokens(msg) -> tuple | None:
    """Pull (input_tokens, output_tokens) from a claude-agent-sdk ResultMessage.

    The ResultMessage carries the authoritative cumulative ``usage`` dict (Anthropic
    API shape: ``input_tokens``/``output_tokens``, plus cache fields) and
    ``total_cost_usd``. Returns a tuple when real counts are present, else None so
    the usage store treats it as a subscription call (tokens null, cost 0).

    Fully guarded: any shape mismatch returns None rather than raising — telemetry
    must never break a reply."""
    try:
        u = getattr(msg, "usage", None)
        if not isinstance(u, dict):
            return None
        inp = u.get("input_tokens")
        out = u.get("output_tokens")
        if inp is None and out is None:
            return None
        return (inp, out)
    except Exception:
        return None


def respond(text: str, history=None, brain: str = "small") -> str:
    """One chat turn → reply text (control tag stripped)."""
    return respond_turn(text, history, brain)[0]


def respond_turn(text: str, history=None, brain: str = "small") -> tuple[str, bool]:
    """One chat turn → (reply text, expects_reply).

    The model tags its reply [OPEN]/[DONE] (see _SYSTEM); we strip the tag and let it decide
    whether Vox keeps listening. The small brain may emit [BIG] to defer the turn to the big
    brain. Falls back to a '?' heuristic if the model omits the tag.
    """
    persona = _active_persona()
    system = _SYSTEM if not persona else \
        f"{_SYSTEM}\n\nYour personality (stay in character while staying helpful): {persona}"
    # Layer the user's dashboard rules + relevant memories on top (both guarded → no-op if absent).
    for block in (_rules_block(), _memory_block(text)):
        if block:
            system = f"{system}\n\n{block}"
    raw = complete(text, history, brain=brain, system=system)
    if (CONFIG.escalate_to_big_brain and brain == "small"
            and raw.strip().upper().startswith("[BIG]")):
        raw = complete(text, history, brain="big", system=system)  # small brain deferred
    # Memory (both guarded): an explicit "remember that X" user turn → core; a
    # MEMORY[core|daily] directive the model appended → captured and stripped from the reply.
    _capture_from_user(text)
    raw = _capture_from_reply(raw)
    return _split_signal(raw)


def _brain(name: str) -> tuple[str, str]:
    """(provider, model) for the named brain ('small' or 'big'). Runtime overrides from the
    dashboard's settings_store win over Config (guarded; falls back to Config when unset)."""
    if name == "big":
        return (_setting("big_brain_provider", CONFIG.big_brain_provider),
                _setting("big_brain_model", CONFIG.big_brain_model))
    return (_setting("small_brain_provider", CONFIG.small_brain_provider),
            _setting("small_brain_model", CONFIG.small_brain_model))


def complete(text: str, history=None, *, brain: str = "small", system: str = _SYSTEM,
             kind: str = "chat") -> str:
    """One raw completion from the named brain with the given system prompt. Provider-agnostic.
    `kind` ("chat"|"command"|"rewrite") only tags the dashboard usage record."""
    provider, model = _brain(brain)
    if provider == "claude_sdk":
        return _claude_sdk(text, history, model, system, brain, kind)
    if provider == "claude_cli":
        return _claude_cli(text, history, model, system, brain, kind)
    if provider == "openai":
        return _openai(text, history, model, system, brain, kind)
    return _anthropic(text, history, model, system, brain, kind)


def split_say(text: str) -> tuple[str, str]:
    """Split a reply into (shown, spoken). A 'SAY: …' line means only that is spoken (and is
    removed from the shown text); without it, shown == spoken."""
    m = re.search(r"(?im)^[ \t]*say:[ \t]*(.+?)[ \t]*$", text or "")
    if not m:
        return text, text
    spoken = m.group(1).strip()
    shown = (text[:m.start()] + text[m.end():]).strip()
    return shown, spoken or shown


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


def _anthropic(text, history, model, system, brain="small", kind="chat"):
    key = os.environ.get(CONFIG.llm_api_key_env or "ANTHROPIC_API_KEY")
    if not key:
        return f"I need {CONFIG.llm_api_key_env} in your .env — add it and restart Vox."
    global _anthropic_client
    if _anthropic_client is None:
        from anthropic import Anthropic
        _anthropic_client = Anthropic(api_key=key)
    msgs = [{"role": r, "content": c} for r, c in (history or [])] + [{"role": "user", "content": text}]
    t0 = time.monotonic()
    try:
        # 45s cap (matches the SDK path) so a stalled request can't freeze the voice loop — the
        # client otherwise defaults to ~10 min. On timeout the SDK raises and we fall through below.
        resp = _anthropic_client.with_options(timeout=45.0).messages.create(
            model=model, max_tokens=CONFIG.llm_max_tokens, system=system, messages=msgs)
        _record_usage("anthropic", model, brain, kind,
                      (resp.usage.input_tokens, resp.usage.output_tokens),
                      (time.monotonic() - t0) * 1000)
        return "".join(b.text for b in resp.content if b.type == "text").strip()
    except Exception as exc:
        return f"(LLM error: {exc})"


def _openai(text, history, model, system, brain="small", kind="chat"):
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
    t0 = time.monotonic()
    try:
        # 45s cap (matches the SDK/anthropic paths) so a stalled DeepSeek/local call can't freeze
        # the voice loop — the client otherwise defaults to ~10 min.
        resp = _openai_client.with_options(timeout=45.0).chat.completions.create(
            model=model, max_tokens=CONFIG.llm_max_tokens, messages=msgs)
        u = getattr(resp, "usage", None)
        _record_usage("openai", model, brain, kind,
                      (u.prompt_tokens, u.completion_tokens) if u else None,
                      (time.monotonic() - t0) * 1000)
        return (resp.choices[0].message.content or "").strip()
    except Exception as exc:
        return f"(LLM error: {exc})"


def _claude_sdk(text, history, model, system, brain="big", kind="chat"):
    # Claude Code via the Agent SDK — runs on your Claude subscription, no API key.
    import asyncio

    from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, TextBlock, query

    convo = "\n".join(f"{'You' if r == 'user' else 'Vox'}: {c}" for r, c in (history or []))
    prompt = f"{convo + chr(10) if convo else ''}You: {text}"
    opts = ClaudeAgentOptions(system_prompt=system, allowed_tools=[], max_turns=6, model=model)
    captured = {}  # tokens from the ResultMessage if the SDK exposes usage

    async def _run():
        parts = []
        async for msg in query(prompt=prompt, options=opts):
            if isinstance(msg, AssistantMessage):
                parts += [b.text for b in msg.content if isinstance(b, TextBlock)]
            # The ResultMessage (has total_cost_usd) carries the cumulative usage.
            if hasattr(msg, "total_cost_usd"):
                got = _sdk_extract_tokens(msg)
                if got is not None:
                    captured["usage"] = got
        return "".join(parts).strip()

    t0 = time.monotonic()
    try:
        reply = asyncio.run(asyncio.wait_for(_run(), timeout=45)) or "(no response)"
        # Subscription call: tokens recorded only if the SDK exposed them (else None → cost 0).
        _record_usage("claude_sdk", model, brain, kind, captured.get("usage"),
                      (time.monotonic() - t0) * 1000)
        return reply
    except asyncio.TimeoutError:
        return "(the brain timed out — try again)"  # never hang the loop on a wedged call
    except Exception as exc:
        return f"(claude SDK error: {exc})"


def _claude_cli(text, history, model, system, brain="small", kind="chat"):
    # Use the Claude Code CLI (`claude -p`) — runs on your Claude subscription, no API key.
    convo = "\n".join(f"{'You' if r == 'user' else 'Vox'}: {c}" for r, c in (history or []))
    prompt = f"{system}\n\nConversation so far:\n{convo + chr(10) if convo else ''}You: {text}\nVox:"
    cmd = ["claude", "-p", prompt] + (["--model", model] if model else [])
    t0 = time.monotonic()
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        if r.returncode == 0:
            # Subscription CLI doesn't surface tokens here → record with usage None (cost 0).
            _record_usage("claude_cli", model, brain, kind, None, (time.monotonic() - t0) * 1000)
            return r.stdout.strip()
        return f"(claude CLI error: {r.stderr.strip() or 'failed'})"
    except FileNotFoundError:
        return "Claude CLI not found — install Claude Code, or set a different brain provider."
    except Exception as exc:
        return f"(claude CLI error: {exc})"


def look(question: str, image_path: str, brain: str = "small") -> str:
    """Answer a question about an on-screen image using a vision-capable brain."""
    provider, model = _brain(brain)
    if provider in ("claude_sdk", "claude_cli"):
        return _sdk_look(question, image_path, model, brain)
    if provider == "anthropic":
        return _anthropic_look(question, image_path, model, brain)
    return "Looking at the screen needs a Claude or Anthropic brain — this one can't see images."


def _sdk_look(question, image_path, model, brain="small"):
    # Claude Code via the SDK reads the image file with its Read tool — runs on your subscription.
    import asyncio

    from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, TextBlock, query

    prompt = (f"Read the image file {image_path} — it's a screenshot of the user's Mac. "
              f"Then answer concisely for text-to-speech (1-2 sentences): {question}")
    opts = ClaudeAgentOptions(allowed_tools=["Read"], max_turns=8,
                              permission_mode="bypassPermissions", model=model)

    captured = {}

    async def _run():
        parts = []
        async for msg in query(prompt=prompt, options=opts):
            if isinstance(msg, AssistantMessage):
                parts += [b.text for b in msg.content if isinstance(b, TextBlock)]
            if hasattr(msg, "total_cost_usd"):  # ResultMessage → cumulative usage
                got = _sdk_extract_tokens(msg)
                if got is not None:
                    captured["usage"] = got
        return "".join(parts).strip()

    t0 = time.monotonic()
    try:
        reply = asyncio.run(asyncio.wait_for(_run(), timeout=90)) or "(no response)"
        _record_usage("claude_sdk", model, brain, "vision", captured.get("usage"),
                      (time.monotonic() - t0) * 1000)
        return reply
    except asyncio.TimeoutError:
        return "(vision timed out — try again)"
    except Exception as exc:
        return f"(vision error: {exc})"


def _anthropic_look(question, image_path, model, brain="small"):
    import base64
    key = os.environ.get(CONFIG.llm_api_key_env or "ANTHROPIC_API_KEY")
    if not key:
        return f"I need {CONFIG.llm_api_key_env} in your .env for API vision."
    global _anthropic_client
    if _anthropic_client is None:
        from anthropic import Anthropic
        _anthropic_client = Anthropic(api_key=key)
    with open(image_path, "rb") as f:
        data = base64.standard_b64encode(f.read()).decode()
    t0 = time.monotonic()
    try:
        resp = _anthropic_client.with_options(timeout=90.0).messages.create(  # vision: 90s like the SDK path
            model=model, max_tokens=CONFIG.llm_max_tokens,
            messages=[{"role": "user", "content": [
                {"type": "image",
                 "source": {"type": "base64", "media_type": "image/png", "data": data}},
                {"type": "text", "text": f"{question} Answer concisely (1-2 sentences)."}]}])
        _record_usage("anthropic", model, brain, "vision",
                      (resp.usage.input_tokens, resp.usage.output_tokens),
                      (time.monotonic() - t0) * 1000)
        return "".join(b.text for b in resp.content if b.type == "text").strip()
    except Exception as exc:
        return f"(vision error: {exc})"
