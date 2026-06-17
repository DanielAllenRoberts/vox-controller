# Vox — Agent-System Research

> Findings from a survey of how the best open-source / documented agent and voice systems are built, gathered to inform Vox's agent layer (the LLM-as-executor + learning vision in `../ideas.md` #12–#15). Each doc ends with a concrete "How this applies to Vox" section.

## The five docs

| Doc | Scope | Headline takeaway |
|---|---|---|
| [`voice-turn-taking.md`](voice-turn-taking.md) | Pipecat, LiveKit Agents, Smart Turn, Vapi/Retell/Deepgram | **Nobody uses raw silence as the turn signal.** Layer a semantic end-of-utterance decision on fast VAD and *adjust the silence timeout* by content. Smart Turn **v3** makes audio EOU CPU-viable (~12ms). Vox's `[OPEN]/[DONE]` tag solves a *different* problem (agent re-engagement, not user-EOU). |
| [`claude-agents.md`](claude-agents.md) | Anthropic "Building Effective Agents", Claude Agent SDK | **Start simple; add agency only when it pays.** Vox's planned cascade *is* the "routing" pattern. The Agent SDK = the Claude Code CLI (hence no API key / subscription). Switch `query()` → `ClaudeSDKClient` for free cross-turn memory; give the LLM **dedicated, gated** tools, never raw Bash. |
| [`coding-agents.md`](coding-agents.md) | OpenCode, Aider, Cline, Open Interpreter | **One agent loop everywhere:** message → LLM → run tool → feed back → loop to a terminal signal; **one action per turn** suits a voice loop. Copy OpenCode's **3-way `allow`/`ask`/`deny`** permission model (per-command-pattern). Use **native function-calling** over `actions.py`; inject per-turn `environment_details` (frontmost app, profile, tabs). |
| [`prompting-best-practices.md`](prompting-best-practices.md) | Anthropic/OpenAI/ElevenLabs prompt guides, leaked agent prompts | **Keep the `[OPEN]/[DONE]` tag** (zero latency, provider-portable; a forced schema/tool for one bit is an anti-pattern) — but *harden* it with few-shot. Add a **TTS number/format block** ("twenty twenty-six", not 2026) with the *reason*. Add explicit **mis-hear handling**. Soften ALL-CAPS "MUST" (over-triggers on Claude 4.x). |
| [`langchain-langgraph.md`](langchain-langgraph.md) | LangChain / LangGraph v1.0 | **Borrow, don't adopt.** Vox already hand-rolls LangGraph's core ideas in ~200 lines; the framework's payoff (durable multi-session checkpointing) solves problems a single-user local loop doesn't have, and it fights the "minimum code" rule + disk budget. Steal patterns (typed state, `trim_messages`, SQLite store, `interrupt()`-style confirm gate). |

## What multiple agents independently agreed on

These showed up across ≥2 docs — highest confidence:

1. **Give the LLM dedicated, gated tools — not a raw shell tool.** (claude-agents + coding-agents + prompting) Wrap `actions.py` ops as native function-calling tools; allow-list them; `setting_sources=[]` so the agent can't inherit *this repo's* Claude Code file/shell tools; headless permission mode in the voice loop. → This is the blueprint for **idea #12 (LLM-as-executor)**.
2. **Keep deterministic-parse-first; the LLM is the fallback, not the router.** (langchain + claude-agents) Cheaper and lower-latency than model-as-router. Vox's current design is right.
3. **Keep `[OPEN]/[DONE]` as a tag, harden don't replace.** (prompting + voice-turn-taking) But know its real job is *re-engagement after silence*, not deciding when the user finished talking — that's VAD + semantic EOU.
4. **One SQLite store, owned by Vox**, for durable prefs/rules/learning — preferred over the model's opaque memory tool. (claude-agents + langchain) → the substrate for **#14 (self-wiring learning)**.
5. **Push model differences into data, not code.** (coding-agents + claude-agents) Vox's `respond_turn()` provider switch is the right shape; externalize per-model prompt/format/temperature.

## Recommended next steps (prioritized)

**Cheap wins (hours, no new deps):**
- **Content-conditioned silence timeout** — fire fast (~0.2s) on terminal punctuation, wait longer (~1.5s) on no-punctuation / mid-number / trailing filler. Removes ~1s dead time per turn. (`voice-turn-taking.md`)
- **Harden the system prompt** — 2–3 few-shot `[OPEN]/[DONE]` examples, a TTS number/format block (with reason), explicit mis-hear handling, and re-inject brevity + tag rules *last*. (`prompting-best-practices.md`, `coding-agents.md`)
- **A tiny golden-set eval** — 10–20 frozen rows + plain `assert`s over `respond_turn()` (one valid tag, tag stripped, ≤2 sentences, correct `expects_reply`). (`prompting-best-practices.md`)

**Medium (the #12 build — LLM-as-executor):**
- Wrap `actions.py` operations as **native function-calling tools** behind one registry shared by CONTROL + ASSISTANT.
- Add a **3-way `allow`/`ask`/`deny`** permission layer (per-action, with `once`/`always` session grants). (`coding-agents.md`)
- Inject per-turn **`environment_details`** (frontmost app, Arc profile, open tabs) so "switch to the other tab" / "go back" resolve without guessing. (`coding-agents.md`)
- Run it on a **fast tier (Haiku via Messages API)**; reserve the SDK/subscription deep tier for reasoning. (`claude-agents.md`)

**Bigger lifts (later):**
- **Smart Turn v3** (CPU ONNX) for semantic end-of-utterance, if the cheap timeout isn't enough. (`voice-turn-taking.md`)
- **Self-wiring learning + background wiring** (#14/#15): log LLM-resolved fallbacks to the SQLite store, compile to deterministic rules off the hot path.
- **`ClaudeSDKClient`** migration for automatic conversation state. (`claude-agents.md`)

## How this maps to the codebase

- `src/vox/assistant.py` — `respond_turn()` provider switch (keep; externalize model config), `_SYSTEM` (harden), `_split_signal()` (correct already).
- `src/vox/actions.py` — `parse()` + dispatch table → becomes the **tool registry** for #12; the deterministic-first path stays as the fast tier.
- `src/vox/audio.py` — `capture_utterance()` is where the content-conditioned timeout lands.
- `src/vox/core/loop.py` — the state machine (the LangGraph-without-LangGraph) gains the `environment_details` gather + the permission gate.
- *(new)* a SQLite store for learned rules / prefs (#14) — the "checkpointer" idea, framework-free.
