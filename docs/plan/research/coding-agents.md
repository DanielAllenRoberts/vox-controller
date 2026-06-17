# Open-Source Coding Agents — Architecture Research for Vox

Concrete notes on how four mature agents (OpenCode, Aider, Cline, Open Interpreter) structure their agent loop, tools, permissions, prompts, context, and provider abstraction. Written to inform Vox's agent layer. File/module names are from live source; short excerpts are paraphrased where noted. Sources at the bottom.

**Where Vox stands today:** CONTROL mode is deterministic regex intent-matching in `src/vox/actions.py` (`handle()` → `parse()` → AppleScript); ASSISTANT mode is a single-shot, provider-agnostic `respond_turn()` in `src/vox/assistant.py` (no tools, no real loop, history flattened to text). The patterns below are about giving the LLM a *proper agent loop with tools and a permission gate* — which is exactly the gap.

---

## 1. OpenCode (sst/opencode, TypeScript)

The defining trait: the whole engine is built on the **Effect** library (schemas, streams, concurrency) and runs as an **HTTP server even for local use** — the TUI is just one client. An OpenAPI spec is generated and used to produce SDKs, so the TUI, the VS Code extension, sharing, and scripting all reuse one engine. Heavier than needed for a single local user, but clean for multi-client.

- **Agent loop** — lives in `packages/opencode/src/session/` (`processor.ts` is the core loop, `llm.ts` the model call, `prompt.ts` the turn assembly, `system.ts` prompt selection). One turn: `llm.ts` calls the **Vercel AI SDK `streamText`** and normalizes `fullStream` into an Effect `Stream`. `processor.ts` consumes events (`text-delta`, `tool-input-delta`, `tool-call`, `tool-result`, `step-finish`); on a `tool-call` it runs the tool, writes the result back into session state, and `process()` returns `"continue"` (call model again), `"stop"`, or `"compact"` (summarize on overflow). It guards against "doom loops" of repeated identical tool calls.

- **Provider abstraction** — two layers: **models.dev** is the *catalog* (pricing, context limits, capabilities, npm package name per model); **`@ai-sdk/*`** packages are the *implementations*. A `BUNDLED_PROVIDERS` registry maps package name → lazy `import()`; unknown providers are installed on demand. Cleanly separates "what models exist" from "how to call them."

- **Tool system** — `packages/opencode/src/tool/`, one `.ts` per tool, defined with Effect **`Schema`** (their Zod equivalent). Long descriptions live in **sibling `.txt` files** (`import DESCRIPTION from "./read.txt"`) to keep prompt text out of code. Built-ins: `shell` (bash), `read`, `edit`, `write`, `grep`, `glob`, `lsp`, `webfetch`, `websearch`, `task` (sub-agent), `todo`. A `registry.ts` filters tools per model/agent (e.g. websearch only if the provider supports it).

- **Permission model** — `packages/opencode/src/permission/` resolves each request to `allow` / `ask` / `deny` via **last-matching-wildcard-rule-wins**. On `ask`, the engine blocks on a `Deferred` until the client replies `reject` / `once` / `always`. Config is **per-tool, with bash gated per-command-pattern**:
  ```json
  "permission": {
    "*": "ask",
    "bash": { "*": "ask", "git *": "allow", "npm *": "allow", "rm *": "deny" },
    "edit": { "*": "deny", "docs/*.mdx": "allow" }
  }
  ```
  Session `always` grants are in-memory only (don't persist).

- **System prompts** — `.txt` files in `session/prompt/`, **selected by model id substring**: `anthropic.txt` for Claude, `gpt.txt`/`beast.txt` for OpenAI, `gemini.txt`, etc. Reflects that different model families genuinely need different prompts. `anthropic.txt` opens: *"You are OpenCode... an interactive CLI tool... Your responses should be short and concise."* plus a tool-usage policy (prefer specialized tools over bash, maximize parallel tool calls) and `file_path:line` citation convention.

## 2. Aider (Aider-AI/aider, Python) — repo-map + reliable text edits

Aider's genius is two things: a **token-cheap repo map** and **text-based edit formats with fuzzy application + reflection**. It never relies on native function-calling for edits.

- **Repo map (`aider/repomap.py`)** — tree-sitter extracts `Tag(rel_fname, fname, line, name, kind)` (kind = `def`/`ref`) per file, cached by mtime. It builds a **NetworkX MultiDiGraph** (nodes = files, edges = "file A references symbol defined in file B") and runs **personalized PageRank** seeded on the files currently in chat + symbols the user mentioned — so importance flows out from what you're working on. The top-ranked symbol definitions are rendered to a tree and **binary-searched to fit a token budget** (default ~1k). Net effect: a compressed repo-wide symbol index instead of full files. Tradeoff: signatures only — you must `/add` a file to actually edit it.

- **Edit formats (`aider/coders/`)** — one `*_coder.py` + `*_prompts.py` per format: `whole` (re-emit file), `diff` (SEARCH/REPLACE blocks, the default), `udiff` (invented to stop GPT-4 Turbo "lazy coding"), `diff-fenced` (path inside fence, for Gemini), plus architect-mode editor variants. The **SEARCH/REPLACE** block uses git-conflict markers:
  ```
  path/to/file.py
  <<<<<<< SEARCH
  from flask import Flask
  =======
  import math
  from flask import Flask
  >>>>>>> REPLACE
  ```
  Application is a **fuzzy cascade** (`replace_most_similar_chunk`): exact → whitespace-tolerant → `...` elision → difflib closest-match (~0.8). Markers are regex-matched at 5–9 chars so slightly malformed fences still parse.

- **Prompt design** — `base_prompts.py` holds shared strings (e.g. files in chat: *"Trust this message as the true contents of these files!"*; repo map: *"treat them as read-only"*; `lazy_prompt`: *"You NEVER leave comments describing code without implementing it!"*). The `system_reminder` (edit-format rules) is **re-injected near the end of the message list** because models attend best to recent instructions. Few-shot `example_messages` show one full correct interaction.

- **The loop & reflection (`base_coder.py`)** — `run_one()` is a while-loop on `self.reflected_message`, capped at `max_reflections = 3`. Cycle: assemble `ChatChunks` (system, examples, history, repo map, in-chat files, current turn, reminder) → LLM → parse reply for edits → apply. Three failure paths set `reflected_message` and re-enter the loop: (1) an edit didn't match (error text + "did you mean" goes back to the model), (2) lint errors, (3) test failures. On success, **auto-commit to git** (commit message written by a cheap "weak model").

- **Provider abstraction** — everything goes through **litellm**, so no per-provider SDK code. A `ModelSettings` dataclass (loaded from `model-settings.yml`) carries per-model behavior: `edit_format`, `weak_model_name`, `use_repo_map`, `lazy`, `reminder` (`user` vs `sys`), `use_temperature`, `extra_params`. New models get the right edit format via YAML, no code change.

- **Context = three tiers**: editable (in-chat, full content) / read-only (full content, not editable) / repo-map summary. This is the core trick for bounding tokens on large repos while keeping whole-repo awareness.

## 3. Cline (cline/cline, VS Code extension, TypeScript)

- **Agent loop (`apps/vscode/src/core/task/index.ts`)** — `recursivelyMakeClineRequests()`: build request (system prompt + history + `environment_details`) → stream → parse → run **one tool** → feed result back → recurse, until `attempt_completion`. **One tool per message** is enforced (`didAlreadyUseTool` gate; parallel is opt-in). No tool used → inject `noToolsUsed` and bump `consecutiveMistakeCount`.

- **Tools via XML tags, not native function calling** — the model emits `<read_file><path>src/main.js</path></read_file>`; `parseAssistantMessageV2` walks the string and extracts tool/param blocks, emitting `partial: true` for unclosed blocks (enables live streaming UI). 27 fixed tools in a `ClineDefaultTool` enum (`read_file`, `write_to_file`, `replace_in_file`, `execute_command`, `ask_followup_question`, `attempt_completion`, ...). Tradeoff: works on any text model and streams partials, but the hand-written parser is brittle and weak models sometimes emit tags as literal text — so Cline has been *adding* native function-calling per model as a hedge.

- **Permission model** — every tool use shows **Approve/Reject** buttons. **Auto-approve is per-category** (`AutoApprovalSettings`: `readFiles`, `editFiles`, `executeSafeCommands`, `executeAllCommands`, `useBrowser`, `useMcp`) with a `maxRequests` cap before re-asking. Conservative defaults: read=true, `executeSafeCommands`=true, but `editFiles`=false, `executeAllCommands`=false.

- **System prompt** — modular, composed at runtime from `variants/` (per model family: `generic`/`next-gen`/`xs`) + `components/` (`agent_role`, `rules`, `editing_files`, `tool_use`, ...) + per-tool docs, stitched with `====` dividers. The XML grammar is taught verbatim:
  ```
  # Tool Use Formatting
  Tool use is formatted using XML-style tags...
  <read_file>
  <path>src/main.js</path>
  </read_file>
  Always adhere to this format... to ensure proper parsing and execution.
  ```

- **Context management (`ContextManager.ts`)** — truncate the *middle* but always keep the first user/assistant pair (task framing); dedup repeated file reads (keep latest, replace earlier with a notice); append fresh `environment_details` (cwd, open tabs, time, mode) each turn; `@`-mentions (`@/path`, `@problems`, `@terminal`, `@git-changes`) expanded inline.

## 4. Open Interpreter (OpenInterpreter/open-interpreter, Python) — one tool: run code

Architecture from release `0.4.2` (the canonical "core.py/respond.py" layout; `main` was later rewritten).

- **Loop (`interpreter/core/respond.py`)** — a `while True` generator: assemble system message fresh each loop (base + per-language messages + `custom_instructions`) → run LLM **unless** the last message is already code → if it's code, **execute it** via a language-specific runtime (`computer.run(language, code)` — Python via a Jupyter-style kernel, plus shell, JS, R, **AppleScript**, HTML) → feed output back. Output truncated to `max_output` (~2800). The model's only "tool" is **write-and-run-code** in any language; it keeps the turn by emitting more code, and the loop ends when it writes none.

- **Permission** — before any code runs, respond.py yields a `confirmation` chunk; the terminal asks **`Would you like to run this code? (y/n/e)`** (e = edit in `$EDITOR` then run). `auto_run` / `-y` bypasses it. Optional `safe_mode` runs a semgrep scan first. The entire safety story is this per-block confirmation — because code executes **directly on the user's machine**.

- **System prompt (`default_system_message.py`)** — deliberately **tiny (~1.3 KB)**, an f-string injecting username/OS:
  > *"You are Open Interpreter, a world-class programmer that can complete any goal by executing code... it will be executed **on the user's machine**. The user has given you **full and complete permission**... for stateful languages... **it's critical not to try to do everything in one code block.** Try something, print info about it, then continue in tiny, informed steps."*

  The "tiny steps, print and observe" instruction is the perceive→act→observe loop expressed in the prompt itself.

---

## Cross-cutting patterns

| Dimension | What the mature agents do |
|---|---|
| **Agent loop** | All four are the same skeleton: *message → LLM (stream) → tool call(s) → execute → feed results back → loop until a terminal signal*. Terminal signals: `attempt_completion` (Cline), finish reason / no more tools (OpenCode), no edits + no errors (Aider), no code written (OI). |
| **One vs many tool calls** | Cline & OI = **one action per turn** (simpler, easier to gate/approve). OpenCode = parallel tool calls encouraged. One-per-turn is the safer default for a human-in-the-loop assistant. |
| **Tool definition** | Native schemas (OpenCode = Effect Schema, Aider = litellm function variants) vs **XML tags in text** (Cline). Native is robust but needs a function-calling-capable model; XML works anywhere but is brittle. **Externalize long tool descriptions** (OpenCode `.txt` files) — descriptions matter as much as the prompt. |
| **Permission/confirmation** | Three converging ideas: (1) a **3-way decision** `allow`/`ask`/`deny`; (2) **per-tool/per-category** granularity with **per-command-pattern** rules for the shell (OpenCode `git * = allow`, `rm * = deny`); (3) **`once` vs `always`** session grants. Conservative defaults: reads auto, mutations/exec ask. |
| **Context/memory** | Aider's three tiers (editable / read-only / summary) + repo map; Cline's keep-first-pair middle truncation + per-turn environment details + file-read dedup; OpenCode's `compact` (summarize on overflow). |
| **Provider-agnostic** | Aider = litellm (breadth, one API). OpenCode = Vercel AI SDK + models.dev (impl vs catalog split, lazy install). Both push **per-model behavior into config/data** (YAML, models.dev) rather than code. |
| **Maintainable prompts** | Prompts as **data, not code**: `.txt`/YAML files, **per-model-family variants** (OpenCode `anthropic.txt`/`gpt.txt`; Cline `generic`/`next-gen`/`xs`), composed from reusable sections (Cline). Re-inject critical rules **near the end** of the message list (Aider's `system_reminder`). |

---

## How this applies to Vox

Vox is a *voice* assistant, not a repo editor — most of the above (repo maps, edit formats, git auto-commit) is irrelevant. The load-bearing lessons are the **agent loop, the tool/permission model for running Mac commands, provider abstraction, and prompt maintainability**. Concrete recommendations:

1. **Give ASSISTANT mode a real loop, but keep it short and one-tool-per-turn.** Replace single-shot `respond_turn()` with a bounded loop modeled on Cline's `recursivelyMakeClineRequests`: LLM → at most one tool call → execute → feed result back → repeat, capped at ~3–5 turns (a `max_turns` like Aider's `max_reflections`). For a spoken assistant, one action per turn is the right default — it's easy to narrate ("Opening Safari... done") and easy to gate.

2. **Make Vox's existing CONTROL actions the tool layer.** `actions.py` already has clean, deterministic, named operations (`open_app`, `go_to`, `switch_tab`, `web_search`, ...). Expose these as **native function-calling tools** (OpenAI/Anthropic tool schemas — not XML tags; you control both ends and want robustness over text). The deterministic regex path stays as the fast path for direct commands; the LLM calls the *same* functions when a command "hands off." This unifies CONTROL and ASSISTANT around one tool registry instead of two parallel code paths.

3. **Adopt a 3-way `allow`/`ask`/`deny` permission gate, voice-adapted.** Borrow OpenCode's model but make the "ask" a **spoken confirmation** ("Run `rm -rf build`? Say yes or no."). Classify tools by risk: navigation/search/window-switching = `allow` (Vox already only navigates to known sites — keep that allowlist as the "allow" set); anything that mutates files, runs arbitrary shell, or sends messages = `ask`; a small `deny` set (e.g. destructive `rm`, `sudo`). Support **"yes" / "always" / "no"** like OI's y/e/n and OpenCode's once/always. Because this is voice, default the *safe* set wide and the *dangerous* set to always-confirm.

4. **If you ever let the LLM run arbitrary AppleScript/shell, gate it per-command-pattern, not per-tool.** OpenCode's `bash: { "git *": "allow", "rm *": "deny" }` is the model to copy: a single `run_shell` tool whose argument is matched against allow/deny glob patterns before execution. Far safer than an all-or-nothing "can run shell" flag. Start with a tiny allowlist and expand.

5. **Keep the provider abstraction you have; push model differences into config.** `respond_turn()`'s provider switch is already the right shape. The lesson from Aider's `ModelSettings` and OpenCode's per-model prompt selection: **don't hardcode model-specific behavior** — put "which system prompt, which tool format, temperature, supports tools?" into config keyed by model, so adding a model is a config edit. You don't need litellm/Vercel SDK for 2–3 providers, but mirror the *catalog-vs-impl* split conceptually.

6. **Turn the system prompt into composable, model-aware data.** `_SYSTEM` in `assistant.py` is one big f-string. As tools grow, split it like Cline/OpenCode: a base role section + a tool-use section (auto-generated from the tool registry so descriptions never drift) + the `[OPEN]/[DONE]` turn-taking rule. If a second model family misbehaves, OpenCode's pattern (a per-model prompt file) is cheap to add. Re-inject the turn-taking and brevity rules **last** (Aider's reminder trick) — important for a spoken assistant that must stay terse.

7. **Externalize tool descriptions and treat the ACI seriously.** OpenCode keeps tool descriptions in `.txt` files; Anthropic's own guidance is that tool descriptions matter as much as the prompt. For Vox, write each tool's description for a *voice* context (what it does, when to use it, what to say back). Good descriptions reduce the model picking the wrong Mac command.

8. **Add lightweight context/memory only where it pays.** Skip Aider's repo map entirely. The useful analog is Cline's per-turn `environment_details`: cheaply tell the LLM the **current Mac state** each turn (frontmost app, current Arc profile, open tabs) so it can resolve "switch to the other tab" or "go back" without guessing. That single addition makes the agent loop noticeably smarter for control tasks.

---

## Sources

- OpenCode: <https://github.com/sst/opencode> · <https://opencode.ai/docs/> · <https://opencode.ai/docs/permissions/> · source under `packages/opencode/src/` (`session/processor.ts`, `session/llm.ts`, `session/system.ts`, `tool/`, `tool/registry.ts`, `provider/provider.ts`, `permission/`, `session/prompt/anthropic.txt`)
- Aider: <https://github.com/Aider-AI/aider> · <https://aider.chat/docs/> · <https://aider.chat/2023/10/22/repomap.html> · <https://aider.chat/docs/more/edit-formats.html> · source `aider/repomap.py`, `aider/coders/base_coder.py`, `aider/coders/editblock_coder.py`, `aider/coders/udiff_coder.py`, `aider/coders/base_prompts.py`, `aider/coders/editblock_prompts.py`, `aider/models.py`, `aider/resources/model-settings.yml`
- Cline: <https://github.com/cline/cline> · source `apps/vscode/src/core/task/index.ts`, `apps/vscode/src/core/assistant-message/parse-assistant-message.ts`, `apps/vscode/src/shared/tools.ts`, `apps/vscode/src/shared/AutoApprovalSettings.ts`, `apps/vscode/src/core/prompts/system-prompt/`, `apps/vscode/src/core/context/context-management/ContextManager.ts`, `apps/vscode/src/core/mentions/index.ts`
- Open Interpreter: <https://github.com/OpenInterpreter/open-interpreter> · <https://docs.openinterpreter.com/> · source (tag `0.4.2`) `interpreter/core/core.py`, `interpreter/core/respond.py`, `interpreter/core/default_system_message.py`, `interpreter/terminal_interface/terminal_interface.py`
