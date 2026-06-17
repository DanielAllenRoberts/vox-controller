# Claude Agents & the Agent SDK — Research for Vox

Research notes on Anthropic's agent guidance and the `claude-agent-sdk` Python package, written to inform Vox's agent layer (system prompts, tool use, intent routing, memory, tiered cascade). Sources at the bottom.

Vox today (`src/vox/assistant.py`): provider-agnostic `respond_turn()` with four backends — `_anthropic` (Messages API), `_openai`, `_claude_sdk` (Agent SDK `query()`, `allowed_tools=[]`, `max_turns=1`), `_claude_cli` (`claude -p`). History is flattened into a text prompt. No tools, no real memory, single shot.

---

## 1. "Building Effective Agents" — workflows vs agents

The central distinction:

- **Workflows** — LLMs and tools orchestrated through **predefined code paths**. You write the control flow; the model fills in steps. Predictable, debuggable, cheaper.
- **Agents** — the LLM **dynamically directs its own process and tool use**, deciding the trajectory itself. Flexible, but trades latency, cost, and the risk of compounding errors.

> "Agentic systems trade latency and cost for better task performance" — adopt them only when the task genuinely needs it. **Start with the simplest thing (a single well-prompted LLM call) and add complexity only when it demonstrably improves outcomes.**

The foundational building block is the **augmented LLM** — a model with retrieval, tools, and memory. Everything else composes from it.

### The five workflow patterns

| Pattern | What it is | Use when | Tradeoff |
|---|---|---|---|
| **Prompt chaining** | Decompose into a fixed sequence; each call processes the previous output. Optional "gates" validate between steps. | Task splits cleanly into fixed subtasks. | More latency (more calls) for higher accuracy per step. |
| **Routing** | Classify the input, then dispatch to a specialized handler/prompt/model. | Distinct input categories that each benefit from focused handling; or to send easy queries to a cheap model and hard ones to a strong model. | Needs accurate classification; a misroute is a wrong answer. |
| **Parallelization** | Run subtasks concurrently and aggregate. **Sectioning** = independent sub-parts; **Voting** = same task N times for confidence/diversity. | Speed via independence, or multiple perspectives raise confidence. | N× token cost; aggregation logic to write. |
| **Orchestrator–workers** | A central LLM **dynamically** decomposes the task, delegates to workers, synthesizes results. Unlike parallelization, the subtasks aren't known up front. | Complex tasks where you can't predict the subtasks (e.g. how many files a code change touches). | Cost + you must trust the orchestrator's decomposition. |
| **Evaluator–optimizer** | One LLM generates, a second evaluates and gives feedback, loop until good. | Clear eval criteria exist *and* iteration measurably helps (e.g. translation, multi-round search). | Latency of the loop; needs a real quality signal. |

### Autonomous agents

Start from a command or a clarifying discussion, then plan and act independently, using **environmental feedback (tool results) as ground truth** at each step, pausing at checkpoints or when blocked. Use for open-ended problems where the number of steps can't be predicted and no fixed path can be hardcoded. Cost is higher and errors compound, so **sandbox heavily and add guardrails** (e.g. `max_turns`).

### Three core principles

1. **Simplicity** — fewest moving parts that work.
2. **Transparency** — show the agent's planning/steps; don't hide the loop.
3. **Tool documentation / ACI** (agent-computer interface) — invest in tool descriptions as much as the prompt. In Anthropic's SWE-bench agent they spent *more* time tuning tools than the top-level prompt. "Poka-yoke" the design (e.g. require absolute paths so relative-path mistakes are impossible). Keep tool I/O close to formats seen on the internet; give Claude thinking room before output.

Frameworks help you start but add hidden layers — strip abstraction in production for debuggability.

---

## 2. The Claude Agent SDK (`claude-agent-sdk`)

This is **not** the Anthropic Messages API. It drives the **Claude Code CLI** under the hood, which means it runs on the user's **Claude subscription / CLI credentials, no `ANTHROPIC_API_KEY`** (the CLI is auto-bundled with the package). That's exactly why Vox's `_claude_sdk` backend is "no API key" — the cost is "free" against the subscription, at the price of CLI-process latency per call and dependence on the local Claude login.

### Two entry points

- **`query(prompt, options)`** — async generator, one-shot. No custom tools, no hooks, no bidirectional control. This is what Vox uses now.
- **`ClaudeSDKClient(options)`** — async context manager for **interactive, multi-turn** sessions. Supports custom tools, hooks, `interrupt()`, `set_permission_mode()`, and **retains conversation state across `client.query()` calls automatically** (no manual history flattening).

```python
async with ClaudeSDKClient(options=opts) as client:
    await client.query("What's the capital of France?")
    async for msg in client.receive_response(): ...
    await client.query("And its population?")   # context retained
    async for msg in client.receive_response(): ...
```

### `ClaudeAgentOptions` — the fields that matter for Vox

| Field | Notes |
|---|---|
| `system_prompt` | `str`, **or** `{"type":"preset","preset":"claude_code"}` (the full Claude Code coding prompt), **or** that preset `+ "append": "..."`. A plain string (what Vox passes) replaces it entirely — correct for a non-coding assistant. |
| `allowed_tools` | Allowlist that **auto-approves** without prompting. `[]` does **not** mean "no tools" — it means "approve nothing automatically." |
| `disallowed_tools` | Hard block. To truly strip Claude Code's file/bash tools, list them here or pair `allowed_tools` with a denying `permission_mode`. |
| `permission_mode` | `"default"` (prompt), `"acceptEdits"`, `"plan"`, `"dontAsk"` (deny unlisted instead of prompting), `"bypassPermissions"`. For headless Vox use `"dontAsk"` so nothing blocks on a prompt. |
| `max_turns` | Caps agentic round-trips; on hit, `ResultMessage.subtype == "error_max_turns"`. Vox uses `1`. |
| `model` | Model alias/ID override. |
| `mcp_servers` | Dict of SDK (in-process) MCP servers or external stdio configs. |
| `hooks` | `PreToolUse`/`PostToolUse`/etc. → Python callbacks that can `deny`/allow tools, audit, or rewrite. |
| `agents` | Dict of `AgentDefinition` subagents (see below). |
| `setting_sources` | Which filesystem settings load: `["user","project","local"]`. **Omit or set `[]` to ignore repo `.claude/` config** — important so Vox doesn't accidentally inherit this repo's CLAUDE.md/tools. |
| `continue_conversation` / `resume="<session_id>"` | Resume the most-recent or a specific session — built-in cross-turn and cross-restart memory (see §4). |

`exclude_dynamic_sections=True` moves per-session context (cwd, git status) out of the system prompt into the first user message → better prompt-cache reuse.

### Custom tools — in-process, no subprocess

```python
from claude_agent_sdk import tool, create_sdk_mcp_server, ClaudeAgentOptions

@tool("open_app", "Open or focus a macOS app", {"name": str})
async def open_app(args):
    run_control(f"open -a {args['name']}")
    return {"content": [{"type": "text", "text": f"Opened {args['name']}"}]}

server = create_sdk_mcp_server(name="vox", version="1.0.0", tools=[open_app])
opts = ClaudeAgentOptions(
    mcp_servers={"vox": server},
    allowed_tools=["mcp__vox__open_app"],   # name = mcp__<server>__<tool>
)
```

SDK MCP tools run **in the same Python process** — no subprocess overhead, type-safe, single-process debugging. This is the clean way to give the LLM Vox's real Mac commands.

### Subagents (`AgentDefinition`)

Defined via `agents={...}`; Claude auto-delegates based on each subagent's `description` (or you name it explicitly). Key fields: `description` (when to use — required), `prompt` (its system prompt — required), `tools` (restrict; omit = inherit all), `model` (`'haiku'|'sonnet'|'opus'|'inherit'|...`), `effort`, `maxTurns`, `permissionMode`.

Why they matter:
- **Context isolation** — each subagent has a fresh window; only its **final message** returns to the parent (a research subagent can read 30 files; the parent sees one summary).
- **Parallelization** — independent subagents run concurrently.
- **Specialization + tool restriction** — narrow prompt, narrow tool set (e.g. read-only).
- Include `Agent` in `allowed_tools` or delegation falls through / is denied. The parent **may summarize** a subagent's output — instruct it to pass through verbatim if you need the exact text.

For Vox this is heavier than needed near-term, but it's the native form of the orchestrator-workers pattern if a command ever fans out (e.g. "summarize my last 5 emails").

---

## 3. Tool use / function calling best practices

(From the Messages-API path — the `_anthropic` backend — and the ACI guidance.)

- **Schema design.** Clear, specific names (`get_weather`, not `weather`); a per-property `description`; `enum` for fixed value sets; mark only truly-required params in `required`. Descriptions should be **prescriptive about *when* to call** the tool, not just what it does ("Call this when the user asks about current prices…"). Recent Opus models reach for tools conservatively, so trigger conditions in the description give measurable lift.
- **`tool_choice`**: `auto` (default), `any` (must use one), `{"type":"tool","name":...}` (force one), `none`. Add `disable_parallel_tool_use: true` to force at most one call per turn.
- **Parallel calls** are on by default — Claude can emit several `tool_use` blocks in one response; execute all, return all `tool_result`s in **one** `user` message, each with the matching `tool_use_id`.
- **Tool results.** On failure set `is_error: true` with an informative message so Claude can adapt. Always append the full `response.content` (preserving `tool_use` blocks) before adding results.
- **Loop control.** The SDK tool runner (`client.beta.messages.tool_runner` with `@beta_tool`) handles the agentic loop for you; the **manual loop** (loop until `stop_reason == "end_turn"`) is for human-in-the-loop approval / custom logging. Handle `pause_turn` for server-side tools.
- **Bash vs dedicated tools.** A `bash` tool gives breadth but an opaque command string; a **dedicated tool** gives the harness a typed, gateable, auditable, renderable, parallel-safe hook. Promote an action to its own tool when you need to **gate** it (irreversible/external actions like sending a message), enforce **staleness** checks, **render** custom UI, or mark it **parallel-safe**. Rule of thumb: start with bash for breadth, promote when you need control. **For Vox this argues for dedicated, typed tools** (`open_app`, `switch_tab`, `web_search`) rather than a raw shell — they map to existing deterministic commands and can be confirmed/audited.

---

## 4. Context management & memory

Three mechanisms, three jobs:

- **Within a session — context editing**: prune stale tool results / thinking blocks past a threshold. Keeps the transcript lean without summarizing.
- **Near the context limit — compaction** (beta `compact-2026-01-12` on Opus 4.6+/Sonnet 4.6): the API summarizes earlier history server-side into a compaction block. **Critical:** append the whole `response.content` back each turn (not just text) — the compaction block carries the summarized state; dropping it silently loses memory.
- **Across sessions — memory**: a file-backed store. Two flavors: the **memory tool** (`memory_20250818`, model reads/writes a `/memories` dir you back) on the Messages API; and the **Agent SDK's session resume** (`continue_conversation` / `resume="<id>"`) which reloads a prior session's full history, surviving process restarts. Subagent transcripts persist separately and survive main-conversation compaction.

Prompt-cache note: caching is a **prefix match** — keep the system prompt and tool list **byte-stable** and put volatile content (timestamps, the current question) last, or every request misses the cache.

For Vox's "spoken, low-latency, short turns" shape, the relevant levers are: keep a **bounded** rolling history (it already passes `history`), let the SDK client hold session state instead of re-flattening text, and reserve compaction/memory-tool machinery for the eventual teachable-rules/long-memory features.

---

## 5. Prompt engineering for agents

- **System-prompt structure.** Be explicit about role, environment, capabilities, and limits — Vox's `_SYSTEM` already does this well (explains modes, sets length, defines the `[OPEN]/[DONE]` protocol). Recent models follow instructions **literally**, so aggressive language (`CRITICAL: you MUST…`, `If in doubt, use X`) now **over-triggers** — prefer "Use X when…".
- **XML tags** delimit sections cleanly (`<search_first>…</search_first>`, `<examples>…</examples>`) and are the recommended way to structure long agent prompts and few-shot blocks.
- **Examples beat rules.** Positive examples of the desired output (concision, tone) outperform negative "don't do X" instructions.
- **Tool-trigger guidance belongs in the tool's own `description`**, not only the system prompt — prescriptive "call this when…" descriptions measurably raise should-call rate on current Opus models.
- **Turn-taking / structured signals** like Vox's trailing `[OPEN]/[DONE]` tag are a sound pattern; for robustness a tool call or `output_config.format` (structured outputs) is non-spoofable, but the lightweight tag-and-strip approach is fine for a voice loop.

---

## How this applies to Vox

1. **Give the LLM real, *dedicated* tools — but gated, not a raw shell.** Wrap Vox's existing deterministic Mac commands (`open_app`, `goto`, `switch_tab`, `web_search`, `go_back`) as `@tool` functions in an in-process `create_sdk_mcp_server`, exposed via `allowed_tools=["mcp__vox__*"]` + `permission_mode="dontAsk"`. This collapses the CONTROL/ASSISTANT split's awkward "hand-off to the LLM" into one agent that can *act*, while keeping each action typed, auditable, and confirmable. Don't give it `Bash`/`Write`/`Edit` — set `setting_sources=[]` and `disallowed_tools` so it can't inherit this repo's Claude Code tools. Start with the 5–6 highest-value commands, not everything.

2. **Switch the SDK backend from `query()` to `ClaudeSDKClient` for stateful turns.** It retains conversation context automatically — drop the manual `convo = "\n".join(...)` flattening in `_claude_sdk`/`_claude_cli`. Keep one long-lived client per "conversation" (between idle resets) so memory is free and latency drops (no re-sending history as text each turn).

3. **Do intent routing as a cheap classifier first — the routing pattern, made tiered.** Vox's planned cascade (rules → fast model → deep model) *is* Anthropic's routing pattern. Concretely: (a) deterministic rule/regex match for known CONTROL phrases (already exists), (b) on miss, a **Haiku** one-shot classifier returns `{mode, tool?, args?}` via structured outputs, (c) only genuinely open-ended ASSISTANT turns hit the strong model. This keeps the common path sub-second and cheap; reserve Opus/agent-loop for the long tail.

4. **Keep the agent loop short and guard-railed.** For an assistant that should mostly answer or fire one command, keep `max_turns` low (1–3) and handle `ResultMessage.subtype == "error_max_turns"` gracefully. Don't reach for autonomous multi-step agents or subagents until a real use case (e.g. "triage my inbox") needs unpredictable decomposition — that's where orchestrator-workers / `AgentDefinition` subagents earn their cost.

5. **Treat the teachable-rules engine as a *workflow*, not an agent.** "Learn that 'work mode' = open Slack + Calendar + mute notifications" is prompt-chaining/routing over a user-defined rule table, not autonomous reasoning. Store rules as data, match deterministically, and only fall back to the LLM when no rule fires — Anthropic's "simplest thing that works" principle. The LLM's job is to *propose* a rule ("Want me to remember that?"), which the engine persists.

6. **Tune the system prompt for current models and centralize it.** `_SYSTEM` is shared verbatim across all four providers — good. Two refinements: soften any imperative tool language to "use X when…", and when tools land, move per-tool trigger guidance into each tool's `description` rather than bloating `_SYSTEM`. Keep the prompt byte-stable (no interpolated timestamps) so the Messages-API path gets prompt-cache hits.

7. **Use cross-session memory deliberately, not by default.** For "remember my preferences / learned rules," prefer an explicit, inspectable store (a JSON/SQLite the rules engine owns) over the model's opaque memory tool — it's debuggable and the user can edit it. Use the SDK's `resume="<session_id>"` only for short-term "continue our conversation" continuity, not durable knowledge.

8. **Mind the subscription-vs-API tradeoff per backend.** The Agent SDK / CLI backends are free against the Claude subscription but pay **CLI-process startup latency** every call and depend on a local login — best for the deep/agent tier. The Messages API (`_anthropic`) is lowest-latency and supports prompt caching, structured outputs, and Haiku routing — best for the fast classifier tier. A sensible split: **Haiku via Messages API for routing/control, Agent SDK (subscription) for the deep ASSISTANT tier.**

---

## Sources

- Building effective agents — https://www.anthropic.com/engineering/building-effective-agents
- Claude Agent SDK (Python) repo — https://github.com/anthropics/claude-agent-sdk-python
- Agent SDK Python reference — https://code.claude.com/docs/en/agent-sdk/python
- Subagents in the SDK — https://code.claude.com/docs/en/agent-sdk/subagents
- Tool use overview — https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview
- Memory tool — https://platform.claude.com/docs/en/agents-and-tools/tool-use/memory-tool
- Compaction — https://platform.claude.com/docs/en/build-with-claude/compaction
- Context editing — https://platform.claude.com/docs/en/build-with-claude/context-editing
- Prompt caching — https://platform.claude.com/docs/en/build-with-claude/prompt-caching
