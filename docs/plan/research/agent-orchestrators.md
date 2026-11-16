# Agent task boards: Paperclip, Hermes Agent, OpenClaw, and a v1 for Vox

Researched 2026-11-06 from primary sources: each repo was shallow-cloned at the commit below and its docs
and source were read directly. Star counts and release dates come from the GitHub API on the same day.
This doc follows on from [`agent-messaging.md`](agent-messaging.md) (how Vox talks to running agents),
[`claude-agents.md`](claude-agents.md) (the Agent SDK), [`../hermes-comparison.md`](../hermes-comparison.md),
and ideas #51 (the board), #70 (voice-level agent) and #71 (scheduled agent tasks) in
[`../ideas.md`](../ideas.md).

**The ask:** a board of tasks that background agents pick up and run, including on a schedule. Tasks go
to Claude Code (via the Agent SDK) or to other agents such as Codex. You can open any run's transcript
from the app, and the feature gets its own Settings section. We should reuse patterns that have been
proven elsewhere, not invent new ones.

**Which repos.** All three names are unambiguous, and all three repos are starred on the account that
asked:

| Name | Repo | Commit read |
|---|---|---|
| Paperclip | [`paperclipai/paperclip`](https://github.com/paperclipai/paperclip) | `1485d3de` |
| Hermes Agent | [`NousResearch/hermes-agent`](https://github.com/NousResearch/hermes-agent) | `f1cf4107` |
| OpenClaw | [`openclaw/openclaw`](https://github.com/openclaw/openclaw) | `fc53c551` |

---

## Comparison

| | **Paperclip** | **Hermes Agent** | **OpenClaw** |
|---|---|---|---|
| What it is | A control plane for a "company" of agents: org chart, tickets, budgets, approvals. It doesn't run a model loop itself; it drives other agents. | A self-improving personal agent with its own tool loop, plus cron and a **SQLite kanban** that dispatches work to named agent profiles. | A personal assistant behind a Gateway, reachable from chat apps and native apps. Swappable runtimes, with Claude Code and Codex available as harnesses. |
| License | MIT | MIT | MIT |
| Stack | TypeScript, Node 24, React UI, **PostgreSQL** (an embedded Postgres by default; Drizzle) | Python 3, SQLite (WAL), FastAPI dashboard plugin, desktop app | TypeScript, Node 24, a Gateway daemon, SQLite state DB (Postgres optional), native apps |
| Size and activity | 111.7k stars · created 2026-03 · CalVer releases every 1–2 weeks · 6.5k open issues · **183 schema files, 437 migrations** | 261k stars · created 2025-07 · several releases a week (v0.23.0 on 2026-11-05) · 53k open issues · cron alone is about 20k lines | 394k stars · created 2025-11 · several releases a week plus betas (v2026.11.1 on 2026-11-05) · 7.7k open issues |
| How people use it (from their docs) | Running many Claude Code and Codex agents against goals, in place of "20 open terminals". Routines for recurring jobs. Managing it all from a phone. | A personal agent on a VPS, driven from Telegram or Slack. Cron reports. The kanban for multi-profile pipelines (research → write, implement → review). | A personal assistant in WhatsApp, iMessage and Slack. Reminders and automations. Claude Code and Codex as coding harnesses through ACP. |
| Unit of work | **Issue**, with a single assignee (agent or human), a status, a parent, blockers, comments and documents | **Task card**: one assignee profile, a status, parent→child links, comments, and runs | **Automation job**, plus sessions. A shared "Tasks ledger" and TaskFlow API **were removed**. |
| Pickup | A **heartbeat** wakes the agent (timer, assignment, on-demand, or automation). Wakes are queued in the DB and coalesced. The agent then atomically **checks out** the issue. | A **dispatcher** loop runs every 60s: it reclaims stale claims, promotes ready cards, claims atomically, and spawns a worker process | The Gateway scheduler fires jobs and runs each one in a main, isolated, current or named session |
| Schedules | **Routines** with cron, webhook or API triggers, plus `concurrencyPolicy` and `catchUpPolicy` | `hermes cron` (duration, "every", 5-field cron, or ISO one-shot). Cards also take `scheduled_at`. `/heartbeat` re-prompts an idle session. | `at`, `every`, `cron`, `on-exit`, and `stream`. Heartbeats were **migrated into ordinary jobs**. |
| Retries and failure | Bounded recovery; a "needs attention" state; a board-owned recovery action | `consecutive_failures` circuit breaker (default 2), then auto-block. Rate limits requeue without counting as a failure. A respawn guard. | One-shots retry transient errors. Recurring jobs back off 30s → 1m → 5m → 15m → 60m and auto-disable after repeated errors. |
| Approval gates | Typed approvals: `pending → approved \| rejected \| revision_requested`. Review stages. Connection actions set to Allowed / Ask first / Off. | `approvals.mode` = smart, manual or off. `cron_mode: deny` by default. A fixed hard blocklist plus user `deny` globs. Fails closed on timeout. | Exec approvals (an allowlist plus ask). Lobster workflows halt at a side effect and return a resume token. |
| Budgets | Monthly per company and per agent. Soft alert at 80%, hard stop at 100% (auto-pause). | Iteration budget per worker, with a checkpoint nudge at 90%; `max_runtime_seconds` | Per-run `timeoutSeconds` (60-minute default watchdog for agent turns) |
| Transcript | Run logs stored outside the run row (on disk locally), streamed over WebSocket. The adapter session id is saved per (agent, task). | `state.db` SQLite with sessions, messages and FTS5. Worker sessions are titled after their card. | A per-agent SQLite DB holds session rows and transcripts. The Claude CLI's own JSONL is verified before resume. |
| Runs Claude Code via | The **`claude` CLI** as a subprocess: `--print --output-format stream-json --resume <id>` (or ACP) | A **skill** that teaches Hermes to call `claude -p` (or tmux for interactive use) | A **CLI backend** (`claude-cli`, a warm stdio process plus `--resume`) or **ACP** (acpx) |
| Runs Codex via | The `codex` CLI (or ACP) | **`codex app-server`** as a runtime for OpenAI models; it works on a ChatGPT subscription | **`codex app-server`**, natively |

---

## Paperclip

**What it is.** Paperclip pitches itself as "If OpenClaw is an _employee_, Paperclip is the _company_"
([README](https://github.com/paperclipai/paperclip/blob/1485d3de1b305d9862f724c662b5740ef9ae99db/README.md)).
It's a Node server and React UI. It doesn't contain an agent loop: every agent is an **adapter**
pointing at something else (`claude_local`, `codex_local`, `hermes_local`, `openclaw_gateway`,
`process`, `http`, …). See the [adapters overview](https://github.com/paperclipai/paperclip/blob/1485d3de1b305d9862f724c662b5740ef9ae99db/docs/adapters/overview.md).

**Task model.** The core entity is an `issue`, specified in
[SPEC-implementation §7.6](https://github.com/paperclipai/paperclip/blob/1485d3de1b305d9862f724c662b5740ef9ae99db/doc/SPEC-implementation.md).
It has:

- status: `backlog | todo | in_progress | in_review | done | blocked | cancelled`
- **exactly one assignee**, either an agent or a human
- `parent_id`, first-class blockers, comments, and documents
- `work_mode`: `standard | ask | planning`

Status is not just a label. `in_progress` for an agent-owned issue must be backed by a live run, and
`blocked` must name *who* unblocks it and *how*. The full rules are in
[execution-semantics.md](https://github.com/paperclipai/paperclip/blob/1485d3de1b305d9862f724c662b5740ef9ae99db/doc/execution-semantics.md).

**Pickup and runs.** Agents don't run continuously. They run in **heartbeats**: short windows
triggered by a wakeup source (`timer`, `assignment`, `on_demand`, or `automation`). See the
[agents runtime guide](https://github.com/paperclipai/paperclip/blob/1485d3de1b305d9862f724c662b5740ef9ae99db/docs/agents-runtime.md).

- Wakeups sit in a DB queue (`agent_wakeup_requests`, which has a `coalesced_count` and an
  `idempotency_key`). A wakeup that arrives while the agent is running is merged into the current
  run.
- Each run is a `heartbeat_runs` row with:
  - `invocation_source: scheduler | manual | callback`
  - `status: queued | running | succeeded | failed | cancelled | timed_out`
  - `error`
  - `context_snapshot`
- The agent claims its issue with an **atomic checkout**: a single
  `UPDATE … WHERE status IN (…) AND (assignee IS NULL OR assignee = me)`. A 409 response means "stop,
  pick something else; never retry". See
  [§10.4.1](https://github.com/paperclipai/paperclip/blob/1485d3de1b305d9862f724c662b5740ef9ae99db/doc/SPEC-implementation.md)
  and the
  [heartbeat protocol](https://github.com/paperclipai/paperclip/blob/1485d3de1b305d9862f724c662b5740ef9ae99db/docs/guides/agent-developer/heartbeat-protocol.md).

**Routines (schedules).** A routine fires on cron, webhook or API, and each fire creates a tracked
issue that wakes the assigned agent. Two policies are worth copying
([routines API](https://github.com/paperclipai/paperclip/blob/1485d3de1b305d9862f724c662b5740ef9ae99db/docs/api/routines.md)):

- `concurrencyPolicy`: `coalesce_if_active` (default) / `skip_if_active` / `always_enqueue`
- `catchUpPolicy`: `skip_missed` (default) / `enqueue_missed_with_cap`

**How it runs Claude Code.** The [`claude_local` adapter](https://github.com/paperclipai/paperclip/blob/1485d3de1b305d9862f724c662b5740ef9ae99db/packages/adapters/claude-local/src/server/execute.ts#L853-L880)
spawns `claude --print --output-format stream-json --verbose [--resume <id>] [--max-turns N]
[--append-system-prompt-file …] [--mcp-config … --strict-mcp-config]`. The session id is saved per
(agent, adapter, task) in `agent_task_sessions`. Three resume details are worth copying:

1. It resumes only if the saved id is a valid UUID **and the cwd matches**.
2. If `--resume` fails with "unknown session" or a poisoned transcript, it **retries once with a fresh
   session** and clears the saved id
   ([L1378–1425](https://github.com/paperclipai/paperclip/blob/1485d3de1b305d9862f724c662b5740ef9ae99db/packages/adapters/claude-local/src/server/execute.ts#L1378-L1425)).
3. When the run hits max-turns, it clears the session so the next heartbeat starts clean.

The adapter's `dangerouslySkipPermissions` defaults to **true**.

**Approvals and budgets.** Approvals are typed rows: `hire_agent`, `approve_ceo_strategy`,
`budget_override_required`, and so on, with status `pending → approved | rejected | cancelled`.
Budgets are monthly cents per company and per agent. A soft alert fires at 80%, and at 100% the agent
is auto-paused. Cost is recorded as `cost_events` (provider, model, tokens, cents). See
[costs and budgets](https://github.com/paperclipai/paperclip/blob/1485d3de1b305d9862f724c662b5740ef9ae99db/docs/guides/board-operator/costs-and-budgets.md).

**Transcript.** Full run logs live outside the run row (on disk locally, under `run-logs/` on S3) and
stream to the UI over WebSocket. "Agent Chat" is still experimental.

**Copy:**

- the run row's shape and status vocabulary
- `invocation_source`
- atomic checkout as a single conditional UPDATE
- wake coalescing
- routine concurrency and catch-up policies
- the resume guard (cwd match, fall back to fresh on an unknown session)
- the 80%/100% budget thresholds

**Avoid:**

- Postgres. Even the "embedded" Postgres is a server process.
- Companies, org charts, goals, agent API keys and JWTs.
- The REST "heartbeat protocol" where the *agent* must call checkout, status and comment endpoints.
  That's a lot of prompt to carry on every run.
- `dangerouslySkipPermissions: true` as a default.

The docs folder alone has 152 files of very intricate liveness and recovery semantics. That's what
running thousands of agents for teams costs, and Vox has neither problem.

## Hermes Agent

**What it is.** A Python agent with its own tool loop, memory and skills, a messaging gateway, cron,
and a **SQLite kanban**
([README](https://github.com/NousResearch/hermes-agent/blob/f1cf4107337f118c2b2b4d6d9913edbe5f69d460/README.md)).
Of the three, the kanban is closest to what Vox wants. It's also the one Paperclip itself integrates
with (`hermes_local` / `hermes_gateway`).

**Task model.** Everything lives in one `kanban.db` (WAL)
([schema](https://github.com/NousResearch/hermes-agent/blob/f1cf4107337f118c2b2b4d6d9913edbe5f69d460/hermes_cli/kanban_db.py#L777-L955),
[docs](https://github.com/NousResearch/hermes-agent/blob/f1cf4107337f118c2b2b4d6d9913edbe5f69d460/website/docs/user-guide/features/kanban.md)).

- **`tasks`** has:
  - `status`: `triage | todo | ready | running | blocked | review | done | archived`
  - `assignee` (a profile name), `priority`, `idempotency_key`
  - claim fields: `claim_lock`, `claim_expires`, `worker_pid`, `last_heartbeat_at`, `current_run_id`
  - limits and overrides: `max_runtime_seconds`, `max_retries`, `model_override`, `skills`
  - failure tracking: `consecutive_failures`, `last_failure_error`
  - `block_kind` and `block_recurrences`
  - `session_id`
- **`task_runs`** holds one row per attempt:
  - `status`: `running | done | blocked | crashed | timed_out | failed | released`
  - `outcome`: `completed | blocked | crashed | timed_out | spawn_failed | gave_up | reclaimed`
  - `summary`, `metadata` (JSON), `error`, `started_at`, `ended_at`, `worker_pid`
- **`task_links`** (parent → child), **`task_comments`**, **`task_events`** (an append-only event log
  the UI tails), and **`task_attachments`**.

The split matters: retries, crashes and reviews add *rows to `task_runs`*, while the task keeps one
identity.

**Pickup and runs.** The dispatcher (default every 60s, inside the gateway):

1. reclaims stale claims and dead PIDs,
2. promotes `todo → ready` when all parents are done,
3. atomically claims a task, and
4. spawns the assignee profile with `HERMES_KANBAN_TASK` set.

That environment variable turns on a task-scoped `kanban_*` **toolset**:

- `kanban_show`
- `kanban_heartbeat`
- `kanban_comment`
- `kanban_complete(summary, metadata)`
- `kanban_block(reason, kind)`
- `kanban_request_review`

The worker **must** end with one of the terminal calls (complete, block, or request review). Exiting
cleanly without one is a `protocol_violation`: the worker gets two automatic "you forgot to call
kanban_complete" nudges, and after three consecutive violations the card is auto-blocked. Exit code
75 marks a rate limit, which requeues without counting as a failure. Exit code 78 marks a bad
credential or model, which blocks on the first occurrence.

**Schedules.** `hermes cron` jobs live in `cron/jobs.json` with an `executions.db` ledger
([cron AGENTS.md](https://github.com/NousResearch/hermes-agent/blob/f1cf4107337f118c2b2b4d6d9913edbe5f69d460/cron/AGENTS.md),
[user docs](https://github.com/NousResearch/hermes-agent/blob/f1cf4107337f118c2b2b4d6d9913edbe5f69d460/website/docs/user-guide/features/cron.md)).

- Each job has a prompt, a schedule, an optional `workdir`, a model pin, and `context_from` (which
  feeds job A's last output into job B).
- Output is saved under `cron/output/<job>/`.
- A reply of `[SILENT]` suppresses delivery but keeps the output.
- There's an idle-inactivity watchdog (default 600s idle, not wall-clock).
- The catch-up window is half the period, clamped to 2 minutes–2 hours.
- `next_run_at` advances **before** dispatch, so a crash mid-run means at-most-once.

Cards also take `scheduled_at`.
[`/heartbeat every 10m <prompt>`](https://github.com/NousResearch/hermes-agent/blob/f1cf4107337f118c2b2b4d6d9913edbe5f69d460/website/docs/user-guide/features/heartbeat.md)
re-prompts the *current* session when it's idle, and missed ticks coalesce into one.

**Approvals.** `approvals.mode: smart | manual | off`. In smart mode an auxiliary LLM rates the risk:
it auto-approves low risk, auto-denies obvious danger, and asks about the rest. For headless contexts
there's **`cron_mode: deny`**, also `single_query_mode` and `unattended_mode`. A hard blocklist sits
below even YOLO mode, and user `approvals.deny` globs are applied before any approval. Prompts **fail
closed** on timeout (300s). See
[security.md](https://github.com/NousResearch/hermes-agent/blob/f1cf4107337f118c2b2b4d6d9913edbe5f69d460/website/docs/user-guide/security.md).

**How it runs Claude Code and Codex.**

- **Claude Code** isn't a native worker type. A
  [skill](https://github.com/NousResearch/hermes-agent/blob/f1cf4107337f118c2b2b4d6d9913edbe5f69d460/skills/autonomous-ai-agents/claude-code/SKILL.md)
  teaches Hermes to shell out to `claude -p … --max-turns N` (preferred), or to drive interactive
  `claude` through tmux.
- **Codex** can be the actual runtime for OpenAI models via `codex app-server`, which works on a
  ChatGPT subscription. See the
  [Codex runtime docs](https://github.com/NousResearch/hermes-agent/blob/f1cf4107337f118c2b2b4d6d9913edbe5f69d460/website/docs/user-guide/features/codex-app-server-runtime.md).

**Transcript.** `state.db` holds sessions and messages with FTS5 search. Worker sessions are titled
after their card, so session search finds them.

**Copy:**

- the `tasks` + `task_runs` split and its status and outcome vocabulary
- `consecutive_failures` with a breaker (2–3)
- `last_failure_error` on the card
- the `summary` + `metadata` handoff, with its suggested keys:
  - `changed_files`
  - `verification`
  - `blocked_reason`
  - `residual_risk`
- `idempotency_key` for automation-created cards
- `[SILENT]` for quiet monitors
- `cron_mode: deny`, i.e. unattended runs never wait on a human
- fail-closed approval timeouts
- feeding the previous run's output into the next prompt

**Avoid:**

- a full OS process per worker profile
- the auto-decomposer LLM
- PR completion contracts
- multi-board, multi-home, tenants
- the dispatcher's claim and TTL machinery (Vox runs in one process, so a lock and a startup sweep are
  enough)

The cron AGENTS.md is a catalogue of hardening invariants, each added after a real failure. That's a
good warning about where scheduling complexity goes.

## OpenClaw

**What it is.** A Gateway daemon (the "control plane for sessions, tools, events, and channel
connections") with chat-app channels and native apps
([README](https://github.com/openclaw/openclaw/blob/fc53c551f5e5ab4c79cace24fb71f3e1f503e4c0/README.md)).
Models and harnesses are plugins.

**Task model.** OpenClaw does **not** have a task board. Its unit is the **automation job**, plus
sessions. The automation docs say plainly that *"the shared Tasks ledger, TaskFlow orchestration API,
and TaskFlow Webhooks plugin have been removed"*, and that each runtime now owns its own execution and
completion
([automation index](https://github.com/openclaw/openclaw/blob/fc53c551f5e5ab4c79cace24fb71f3e1f503e4c0/docs/automation/index.md)).
Heartbeat monitors were also folded into ordinary jobs by `doctor --fix`.

**Schedules.** Jobs, definitions and run history live in the Gateway's SQLite state DB
([how it works](https://github.com/openclaw/openclaw/blob/fc53c551f5e5ab4c79cace24fb71f3e1f503e4c0/docs/automation/cron-jobs/how-it-works.md),
[schedules](https://github.com/openclaw/openclaw/blob/fc53c551f5e5ab4c79cace24fb71f3e1f503e4c0/docs/automation/cron-jobs/schedules.md),
[payloads](https://github.com/openclaw/openclaw/blob/fc53c551f5e5ab4c79cace24fb71f3e1f503e4c0/docs/automation/cron-jobs/payloads.md)).

- Schedule kinds: `at`, `every`, `cron` (with tz and auto-stagger), `on-exit`, `stream`.
- The session target is `main`, `isolated` (`cron:<jobId>`, fresh each run), `current`, or
  `session:<name>` (persistent).
- Run history separates execution `status` (`ok | error | skipped`) from `completionStatus`
  (`succeeded | failed | unknown`, covering delivery).
- `NO_REPLY` means silence. `record_result` takes `no_change | progress | done | blocked |
  needs_attention`, and **the last meaningful result is fed into the next run's prompt.**
- **Restart rule:** a run that was active at a crash becomes *interrupted*. Payloads that may have had
  side effects are **not** replayed automatically.
- **Promotion:** when you ask for the same thing several times, the agent offers to schedule it. It
  restates the schedule in plain words ("Every weekday at 07:00 …"), then runs it once immediately as
  a visible test.

**How it runs Claude Code.** There are two paths
([CLI backends](https://github.com/openclaw/openclaw/blob/fc53c551f5e5ab4c79cace24fb71f3e1f503e4c0/docs/gateway/cli-backends.md),
[ACP agents](https://github.com/openclaw/openclaw/blob/fc53c551f5e5ab4c79cace24fb71f3e1f503e4c0/docs/tools/acp-agents.md),
[agent runtimes](https://github.com/openclaw/openclaw/blob/fc53c551f5e5ab4c79cace24fb71f3e1f503e4c0/docs/concepts/agent-runtimes.md)):

- **CLI backend `claude-cli`**:
  - keeps one Claude Code process warm over stdio and resumes from the stored session id after a
    restart
  - **checks that the transcript file exists before resuming**; if it's missing, it clears the binding
    rather than letting `--resume` silently start fresh
  - forks with `--fork-session`
- **ACP (acpx)**: for "harness sessions" with ACP controls, background-task tracking and chat binding.

Codex runs natively through `codex app-server` on ChatGPT OAuth.

**Approvals.**
[Exec approvals](https://github.com/openclaw/openclaw/blob/fc53c551f5e5ab4c79cace24fb71f3e1f503e4c0/docs/tools/exec-approvals.md)
combine policy, an allowlist and an optional ask, and they bind the exact argv and executable that was
approved. For `claude-cli`, OpenClaw checks native Bash commands against the same allowlist. Separately,
[Lobster](https://github.com/openclaw/openclaw/blob/fc53c551f5e5ab4c79cace24fb71f3e1f503e4c0/docs/tools/lobster.md)
pipelines stop at a side effect with
`{status: "needs_approval", requiresApproval: {prompt, resumeToken}}`, and no process waits for the
answer.

**Copy:**

- the restart rule: interrupted runs fail and are never replayed
- fresh-session-plus-last-result for scheduled jobs
- the `NO_REPLY` and `record_result` outcome words
- verifying the transcript before resuming
- "promote a repeated ask into a schedule, then test-run it once"
- the shape of the approval checkpoint: halt, return a token, resume later

**Avoid:**

- ACP, channels and the Gateway
- per-job authority and grant machinery
- the TaskFlow-style generic workflow engine that OpenClaw itself built and then removed

---

## Claude Agent SDK: sessions, resume, approval

Checked against the [sessions guide](https://code.claude.com/docs/en/agent-sdk/sessions.md),
[hooks guide](https://code.claude.com/docs/en/agent-sdk/hooks.md) and
[hooks reference](https://code.claude.com/docs/en/hooks.md), and against the installed
`claude-agent-sdk` 0.2.103 in `.venv`.

**Sessions and resume.**

- Every `ResultMessage` carries `session_id`, success or error. It also carries:
  - `subtype` (`success`, `error_max_turns`, `error_max_budget_usd`, …)
  - `total_cost_usd`, `num_turns`, `result`
  - `permission_denials`, `deferred_tool_use`
- Resume with `ClaudeAgentOptions(resume=id)`. `fork_session=True` branches a session without
  touching the original. `continue_conversation=True` picks the most recent session in the cwd.
- Transcripts are written to `~/.claude/projects/<cwd with non-alphanumerics → "->/<session>.jsonl`
  (or under `$CLAUDE_CONFIG_DIR`). The retention sweep deletes them after **30 days** by default
  (`cleanupPeriodDays`).
- Resume works from any cwd on the **same machine**. For other hosts, use a `session_store` adapter.
  Its key derives from the cwd, so resume from the same cwd.

**Reading transcripts in the app.** `list_sessions()`, `get_session_info()`,
`get_session_messages(session_id, directory=…)`, `rename_session()` and `tag_session()` all ship in
the Python SDK. With these, Vox can render a run's conversation without copying it.

**Limits.** `max_turns`, `max_budget_usd` (the run ends with `error_max_budget_usd`), and
`client.interrupt()` from inside a `ClaudeSDKClient`.

**Approval primitive 1: `can_use_tool`.** This is a callback on `ClaudeSDKClient` that can *await*.
The run pauses in-process until it returns allow or deny. It's simple, but the process stays alive
while it waits, and the wait dies if the daemon restarts.

**Approval primitive 2: PreToolUse `"defer"`.**

1. The hook returns `permissionDecision: "defer"`.
2. The turn ends with `stop_reason: "tool_deferred"` and `deferred_tool_use: {id, name, input}`, and
   nothing executes.
3. Later, Vox resumes **with no prompt**. The same tool call fires `PreToolUse` again, and the hook now
   returns `allow` or `deny`.

There's no timeout. The parked session survives restarts until the 30-day sweep. Caveats:

- It only works when Claude made a **single** tool call in that turn. With parallel calls, `defer` is
  ignored and the call takes the normal permission flow.
- Sending a prompt along with the resume **drops** the deferred call.
- `-p` resumes don't restore the permission mode, so pass it again.

This maps exactly onto OpenClaw's Lobster resume-token pattern.

**Terms constraint.** The SDK overview says: *"Unless previously approved, Anthropic does not allow
third party developers to offer claude.ai login or rate limits for their products, including agents
built on the Claude Agent SDK."* Idea #70 already ran into this. Vox's existing `claude_sdk` brain uses
the local Claude Code login. That's fine for personal use, but a distributed Vox should default agent
runs to an API key, or to spawning the user's own installed `claude` CLI. See the open questions.

**Codex, for the "other agents" half.**
[`codex exec --json`](https://learn.chatgpt.com/docs/non-interactive-mode) emits JSONL events:

- `thread.started` (carries `thread_id`)
- `turn.completed` (carries `usage`)
- `turn.failed`
- `item.*`

Resume with `codex exec resume <id> "<prompt>"`. The sandbox is `read-only` by default; pass
`--sandbox workspace-write` to allow edits. Auth reuses the CLI login (ChatGPT) or `CODEX_API_KEY`.
`-o` writes the final message to a file. There's no mid-run approval hook in `exec` mode, so
the sandbox is the gate.

---

## What Vox should copy (and what it already has)

Vox already has most of the substrate:

- `board_store.py`: SQLite boards, lists and cards, with due dates, a checklist, tags, and a per-card
  scheduler job (`reminder_id`)
- `scheduler.py`: a background tick, recurrence (`daily` / `weekdays` / `weekly` / `every:<n>`), and
  startup catch-up
- a warm `ClaudeSDKClient` pool in `assistant.py`
- `agent_alerts` / `agent_done_alerts` settings
- vox-control MCP tools for `board`, `schedule`, `notify` and `speak`

So the plan is a thin layer, not a new system.

| # | Mechanism | Source | Vox shape |
|---|---|---|---|
| 1 | **Task and run split.** The card is the task; each attempt is a row. | Hermes `tasks` / `task_runs`; Paperclip `heartbeat_runs` | A new `agent_run` table in `board.db` |
| 2 | **Columns are the state machine** (Queued → Running → Needs you → Done) | Hermes `ready → running → blocked/review → done` | A seeded "Agents" board. Dragging a card into Queued runs it. |
| 3 | **Atomic claim** as one conditional UPDATE | Paperclip checkout | `UPDATE … WHERE id=? AND run_lock IS NULL` |
| 4 | **Coalesce** a fire that arrives while the card is already running | Paperclip `coalesce_if_active`, OpenClaw | Record a `skipped` run and don't start a second one |
| 5 | **The scheduler fires, the runner runs** | Paperclip routines → wake; OpenClaw jobs | A new scheduler kind, `agent`, linked from the card like `reminder_id` |
| 6 | **Fresh session plus the last result** for scheduled runs; **resume** for follow-ups | OpenClaw isolated jobs; Hermes `context_from`; Paperclip per-task session | `card.session_id` is reused only for a reply or a resume |
| 7 | **Resume guard**: same cwd, transcript exists, otherwise retry fresh and clear | Paperclip `claude_local`; OpenClaw `claude-cli` | A dozen lines in the Claude adapter |
| 8 | **Summary + metadata handoff** | Hermes `kanban_complete` | `agent_run.summary`, plus `metadata` JSON from the final message |
| 9 | **Quiet results** | Hermes `[SILENT]`, OpenClaw `NO_REPLY` | A final message starting `NO_CHANGE` → no speech or bubble |
| 10 | **Unattended runs never block on a human** | Hermes `cron_mode: deny`; idea #71 | Scheduled runs use the read-only profile, and risky calls are denied with a note |
| 11 | **Fail-closed approval with timeout** | Hermes approvals; OpenClaw exec approvals | `can_use_tool` awaits the user for up to N minutes, then denies |
| 12 | **Breaker** | Hermes `consecutive_failures` (2); OpenClaw auto-disable | 3 failures in a row → pause the schedule, move to Needs you, say why |
| 13 | **Budgets at 80% / 100%** | Paperclip | A per-run `max_budget_usd`, plus a daily cap that pauses new runs |
| 14 | **Restart = interrupted, never replay** | OpenClaw | On startup, `running` → `interrupted`, and the card moves to Needs you |
| 15 | **Adapter = one `run()` function** | Paperclip `execute()` | `claude` (SDK) first, then `codex` (`exec --json`) |

---

## Proposed v1 for Vox (a day or two)

**Scope:**

- Run a card with Claude Code, by hand or on a schedule
- Watch it live
- Open its transcript
- Approve or deny risky actions
- Reply to continue it
- Cap time and cost

Codex is an optional second adapter on day 2. Out of scope: agent-to-agent delegation, parent and child
dependencies, auto-decomposition, and multiple boards.

### Data model (all in `board.db`, additive migrations like `_CARD_COLUMNS`)

**The board.** A seeded board named **Agents**, with lists **Inbox · Queued · Running · Needs you ·
Done**. The list *is* the status, so the existing Board UI works unchanged. Only the runner moves
cards into Running.

**New card columns.** They're NULL for ordinary cards; a card is an agent card iff `agent IS NOT NULL`:

```sql
agent          TEXT     -- 'claude' | 'codex'
agent_cwd      TEXT     -- working dir; default data/agent/work/<card_id>/ (scratch, gitignored)
agent_profile  TEXT     -- 'read_only' | 'edit'   (tool allowlist preset, see Safety)
agent_job_id   TEXT     -- scheduler job that enqueues this card (like reminder_id)
session_id     TEXT     -- last Claude/Codex session, for reply/resume
run_lock       INTEGER  -- agent_run.id while running, else NULL (the atomic claim)
max_turns      INTEGER  -- NULL → setting default
budget_usd     REAL     -- per-run cap; NULL → setting default
timeout_s      INTEGER  -- wall clock; NULL → setting default
fail_streak    INTEGER NOT NULL DEFAULT 0
```

The card `title` + `body` are the prompt, so no separate prompt field is needed.

**New table.**

```sql
CREATE TABLE IF NOT EXISTS agent_run (
  id           INTEGER PRIMARY KEY,
  card_id      INTEGER NOT NULL REFERENCES card(id) ON DELETE CASCADE,
  source       TEXT NOT NULL,   -- manual | schedule | voice | reply | retry
  status       TEXT NOT NULL,   -- queued | running | needs_approval | succeeded | failed
                                --   | timed_out | cancelled | interrupted | skipped
  agent        TEXT NOT NULL,
  session_id   TEXT,
  started_at   TEXT, ended_at TEXT,
  num_turns    INTEGER, cost_usd REAL,
  summary      TEXT,            -- final message (shown on the card)
  metadata     TEXT,            -- JSON handoff: changed_files, verification, blocked_reason, ...
  error        TEXT,
  pending      TEXT,            -- JSON {tool, input, asked_at} while needs_approval
  log_path     TEXT             -- data/agent/runs/<id>.jsonl (streamed events)
);
CREATE INDEX IF NOT EXISTS idx_run_card ON agent_run(card_id);
```

### Run lifecycle (`src/vox/agent_tasks.py`, one module, roughly 350 lines)

1. **Enqueue.** Any of these call `enqueue(card_id, source)`:
   - the user drags the card to Queued
   - the user presses Run
   - a voice command or MCP call
   - a scheduler `agent` job fires

   `enqueue` inserts a `queued` run. If the card already has a `run_lock`, it records a `skipped` run
   instead (coalescing).
2. **Claim.** A single worker thread (sharing the asyncio loop pattern of `_SdkPool`) picks the oldest
   queued run, respecting `agents_max_parallel` (default 1). It claims with
   `UPDATE card SET run_lock=? WHERE id=? AND run_lock IS NULL`, then moves the card to Running.
   Before starting, it checks the daily budget. If the budget is spent, the run fails with "daily
   agent budget reached" and the card moves to Needs you.
3. **Build the prompt.** It combines:
   - the card title and body
   - the checklist
   - the last 1–2 run summaries (bounded, about 2k characters), so scheduled runs can say what changed
   - a short footer: *"End with a 2–4 sentence summary. If nothing changed since the last run, reply
     with NO_CHANGE. If you're blocked, start with BLOCKED: and say what you need."*

   This is the Hermes and OpenClaw completion contract, done with text markers instead of tools.
4. **Run (Claude adapter).** It opens a `ClaudeSDKClient` with:
   - `cwd=agent_cwd`
   - `resume=session_id` only when `source='reply'` (or the card opts into continuing) and the
     transcript file exists
   - `max_turns`, `max_budget_usd`
   - the profile's `allowed_tools` and `disallowed_tools`, plus `can_use_tool`
   - `setting_sources=[]` by default (see open questions)

   The whole run sits inside `asyncio.wait_for(timeout_s)`; on timeout it calls `client.interrupt()`.
   Every message is appended to `log_path` as JSONL, so the app can tail it live. If resuming fails
   with an unknown or poisoned session, it retries once fresh and clears `card.session_id`.
5. **Finish.** It reads the `ResultMessage` and writes `status`, `session_id`, `cost_usd`,
   `num_turns`, `summary` and `error`, then:
   - **Success:** the card moves to Done, or stays put for a scheduled card, and `fail_streak` resets.
   - **`BLOCKED:` or an error:** the card moves to Needs you and `fail_streak` goes up. At 3, the
     schedule job is disabled and Vox says so.

   Then it **notifies**: a bubble always, and speech if `agent_done_alerts` allows it. A `NO_CHANGE`
   result stays silent.
6. **Startup sweep.** Any run still `running` becomes `interrupted`, its card moves to Needs you, and
   it is never auto-replayed.

**Scheduling.** Add `"agent"` to `scheduler.VALID_KINDS`. In `_announce`, an `agent` job calls
`agent_tasks.enqueue(card_id, "schedule")` instead of speaking. The card id goes in the job's `text`
or a new `ref` field. Keep the existing recurrence grammar and catch-up rule (overdue one-shots under
1h fire once, older ones are dropped, recurring jobs roll forward); this matches Paperclip's
`skip_missed`. Board cards already sync a `reminder_id` the same way, so `_sync_agent_job` mirrors
`_sync_reminder`.

**Codex adapter (day 2, behind a setting).** Run `codex exec --json --sandbox <read-only|workspace-write>
-C <cwd> -o <tmp> "<prompt>"` as a subprocess, or `codex exec resume <id> "<prompt>"` for a reply.

- Parse `thread.started` → `session_id` and `turn.completed.usage` → tokens.
- Copy each event line into `log_path`.
- There are no mid-run approvals, so the `read_only` profile maps to `--sandbox read-only` and `edit`
  maps to `workspace-write` inside the scratch cwd only.

### Opening a run's transcript

- **App (Board → card detail → "Runs").** It lists the card's runs with status, source, time, cost,
  turns and the first line of the summary. Clicking a run opens a **transcript view**:
  - **Live:** it tails `log_path` (polling `GET /api/agents/runs/{id}/events?after=<n>`, the same way
    Paperclip falls back to HTTP).
  - **Finished Claude runs:** it reads `get_session_messages(session_id, directory=agent_cwd)`, which
    is the canonical transcript and includes anything the user later added in the terminal.
- **Buttons on a run:**
  - **Reply…** enqueues a `reply` run that resumes `session_id` with the typed text.
  - **Open in Terminal** runs `cd <agent_cwd> && claude --resume <session_id>` (or
    `codex resume <id>`), handing the full interactive session to the user. Per the focus rule, this
    asks before stealing focus.
  - **Stop** cancels the run.
  - **Approve / Deny** appear when the run is `needs_approval`.
- **API (bridge, port 8765):**

  ```
  GET  /api/agents/runs?card=
  GET  /api/agents/runs/{id}
  GET  /api/agents/runs/{id}/events
  GET  /api/agents/runs/{id}/transcript
  POST /api/agents/cards/{id}/run
  POST /api/agents/runs/{id}/approve
  POST /api/agents/runs/{id}/deny
  POST /api/agents/runs/{id}/stop
  POST /api/agents/runs/{id}/reply
  ```

- **MCP (vox-control):** `agent_task(title, prompt, agent="claude", repeat=None, at=None)` creates the
  card (and job) and returns its id. `agent_runs(card)` reads results. Don't reuse the `run_agent` name:
  that's the computer-use tier in `agent.py`.

### Safety gates

- **Tool profiles** (data, not code):
  - **`read_only`** auto-allows `Read`, `Glob`, `Grep`, `WebSearch`, `WebFetch` and the read-only Vox
    MCP tools.
  - **`edit`** adds `Write` and `Edit` *inside `agent_cwd` only* (checked in `can_use_tool` against the
    resolved path), plus `Bash` matching an allowlist of globs (OpenCode/Hermes style, e.g. `git
    status*`, `ls *`, `python -m pytest*`).
  - Everything else goes to `can_use_tool`.
  - Always disallowed: `Bash` matching a deny list (`rm -rf *`, `sudo *`, `git push*`, `curl *|*sh*`),
    the screen-control MCP tools (`click`, `type_text`, `press`) unless the card opts in, and send or
    post tools.
- **Attended runs** (manual, voice, reply): `can_use_tool` sets the run to `needs_approval`, writes
  `pending`, moves the card to Needs you, and bubbles or speaks "<card> wants to run `<cmd>` — approve?".
  It then **awaits** the answer for `agents_approval_timeout` (default 10 min). On timeout it denies,
  telling the agent: *"User unavailable; don't retry. List it under 'needs approval' in your summary."*
  Voice approval reads the full command back and requires an explicit yes (see `agent-messaging.md`
  §3).
- **Unattended runs** (schedule): no waiting. Anything outside the profile is denied with the same
  note, so it lands in the morning summary (idea #71's "queue it for the report").
- **v2 upgrade:** replace the in-process await with PreToolUse `"defer"`, so a pending approval
  survives a daemon restart and doesn't hold a process for hours. It's not in v1 because of the
  single-tool-call caveat and the "resume without a prompt" subtlety.
- **Limits:**
  - per run: `max_turns` (default 30), `max_budget_usd` (default $1), wall clock (default 20 min)
  - per day: `agents_daily_budget_usd` (default $5); at 80% Vox warns once, at 100% it refuses new
    runs
  - the breaker trips at 3 consecutive failures

  On a Claude subscription, `total_cost_usd` is notional, but it's still a useful meter.
- **Isolation:** default `agent_cwd` is a per-card scratch dir under `data/agent/work/` (gitignored).
  Pointing a card at a real repo is explicit, per card.

### Settings section: "Agents"

| Key | Default | Notes |
|---|---|---|
| `agents_enabled` | off | Master switch |
| `agents_default_agent` | `claude` | `claude` / `codex` |
| `agents_auth` | `api_key` | `api_key` (`ANTHROPIC_API_KEY`) / `local_cli` (user's own Claude login); see open question 1 |
| `agents_model` | Sonnet-class | Per-card override later |
| `agents_max_parallel` | 1 | |
| `agents_default_max_turns` | 30 | |
| `agents_default_budget_usd` | 1.00 | Per run |
| `agents_daily_budget_usd` | 5.00 | |
| `agents_default_timeout_min` | 20 | |
| `agents_approval_timeout_min` | 10 | Attended runs |
| `agents_unattended_policy` | `deny` | `deny` / `read_only_only` |
| `agents_bash_allow` / `agents_bash_deny` | see above | Glob lists |
| `agents_workspace_root` | `data/agent/work` | |
| `agents_speak_on_done` | reuse `agent_done_alerts` | |

### Build order and checks

1. **Schema.** Add the card columns and the `agent_run` table, and seed the Agents board. Check: a
   `board_store` selftest round-trips a run row, and existing boards are unchanged.
2. **Runner.** Build the claim, the Claude adapter, the event log and finish handling. Check: a manual
   run of "list the files here and summarise" in a scratch dir reaches Done, with a summary, a session
   id and a cost; stopping it mid-run yields `cancelled`; a 1-turn cap yields `failed` with
   `error_max_turns`.
3. **Approval.** Check: an `edit`-profile run asking for `curl` lands in Needs you; Approve continues
   it; the timeout denies it.
4. **Scheduler.** Add the `agent` kind and `_sync_agent_job`. Check: an `every:60` card fires twice and
   coalesces when overlapping; a startup with a stale `running` row marks it `interrupted`.
5. **API and app.** Build the Runs tab, transcript view, Reply and Open in Terminal. Check: the reply
   resumes with context ("what did you find last time?" answers correctly).
6. **Codex adapter (optional).**

---

## Open questions for you

1. **Auth for Claude runs.** The SDK docs bar third-party products from offering claude.ai login, so
   an open-source Vox shouldn't ship background agents on the subscription by default. Should v1
   default to an **API key**? Or should it shell out to the **user's own `claude` CLI** (Paperclip's
   and OpenClaw's approach), which keeps their login entirely theirs? This also affects the existing
   `claude_sdk` brain.
2. **Board shape.** Should Agents be a **separate board**, or should agent fields live on any card, so
   a Workspace card could be "assigned to Claude"? The separate board is simpler, and its columns can
   double as status.
3. **Repo access.** Should cards be able to point at a real repo (`agent_cwd`) in v1, or only at
   scratch dirs? And should repo runs load that repo's `CLAUDE.md` (`setting_sources=["project"]`)?
4. **Screen control.** May a background agent use the vox-control screen tools (click, type)? It
   collides with "ask before stealing focus" and with the user working live. The suggestion is no by
   default, opt-in per card, and attended runs only.
5. **Session policy.** For scheduled cards, is a fresh session each run plus the last summary right
   (suggested)? Or do you want some cards to keep one growing conversation, like Hermes `/heartbeat`?
6. **Codex in v1 or later?** Which Codex auth do you expect: your ChatGPT login via `codex login`, or
   an API key?
7. **Voice surface.** Should "ask Claude to … in the background" create a card through the router in
   v1? Or should cards come only from the app and MCP at first?
8. **Budget defaults.** Are $1 per run, $5 per day, a 20-minute timeout and 30 turns sensible starting
   points?
9. **Relation to idea #70 (Pi).** Should this board be the place Pi tasks land too, with Pi as a third
   adapter? Or does #70 stay separate?

## Sources

- Paperclip @ `1485d3de`:
  - [README](https://github.com/paperclipai/paperclip/blob/1485d3de1b305d9862f724c662b5740ef9ae99db/README.md)
  - [SPEC-implementation](https://github.com/paperclipai/paperclip/blob/1485d3de1b305d9862f724c662b5740ef9ae99db/doc/SPEC-implementation.md)
  - [execution-semantics](https://github.com/paperclipai/paperclip/blob/1485d3de1b305d9862f724c662b5740ef9ae99db/doc/execution-semantics.md)
  - [agents-runtime](https://github.com/paperclipai/paperclip/blob/1485d3de1b305d9862f724c662b5740ef9ae99db/docs/agents-runtime.md)
  - [heartbeat protocol](https://github.com/paperclipai/paperclip/blob/1485d3de1b305d9862f724c662b5740ef9ae99db/docs/guides/agent-developer/heartbeat-protocol.md)
  - [routines API](https://github.com/paperclipai/paperclip/blob/1485d3de1b305d9862f724c662b5740ef9ae99db/docs/api/routines.md)
  - [costs and budgets](https://github.com/paperclipai/paperclip/blob/1485d3de1b305d9862f724c662b5740ef9ae99db/docs/guides/board-operator/costs-and-budgets.md)
  - [approvals](https://github.com/paperclipai/paperclip/blob/1485d3de1b305d9862f724c662b5740ef9ae99db/docs/guides/board-operator/approvals.md)
  - [adapters overview](https://github.com/paperclipai/paperclip/blob/1485d3de1b305d9862f724c662b5740ef9ae99db/docs/adapters/overview.md)
  - [`claude_local` execute.ts](https://github.com/paperclipai/paperclip/blob/1485d3de1b305d9862f724c662b5740ef9ae99db/packages/adapters/claude-local/src/server/execute.ts)
  - [`agent_task_sessions`](https://github.com/paperclipai/paperclip/blob/1485d3de1b305d9862f724c662b5740ef9ae99db/packages/db/src/schema/agent_task_sessions.ts)
  - [`agent_wakeup_requests`](https://github.com/paperclipai/paperclip/blob/1485d3de1b305d9862f724c662b5740ef9ae99db/packages/db/src/schema/agent_wakeup_requests.ts)
- Hermes Agent @ `f1cf4107`:
  - [README](https://github.com/NousResearch/hermes-agent/blob/f1cf4107337f118c2b2b4d6d9913edbe5f69d460/README.md)
  - [kanban docs](https://github.com/NousResearch/hermes-agent/blob/f1cf4107337f118c2b2b4d6d9913edbe5f69d460/website/docs/user-guide/features/kanban.md)
  - [kanban schema](https://github.com/NousResearch/hermes-agent/blob/f1cf4107337f118c2b2b4d6d9913edbe5f69d460/hermes_cli/kanban_db.py)
  - [cron AGENTS.md](https://github.com/NousResearch/hermes-agent/blob/f1cf4107337f118c2b2b4d6d9913edbe5f69d460/cron/AGENTS.md)
  - [cron docs](https://github.com/NousResearch/hermes-agent/blob/f1cf4107337f118c2b2b4d6d9913edbe5f69d460/website/docs/user-guide/features/cron.md)
  - [heartbeat](https://github.com/NousResearch/hermes-agent/blob/f1cf4107337f118c2b2b4d6d9913edbe5f69d460/website/docs/user-guide/features/heartbeat.md)
  - [security / approvals](https://github.com/NousResearch/hermes-agent/blob/f1cf4107337f118c2b2b4d6d9913edbe5f69d460/website/docs/user-guide/security.md)
  - [claude-code skill](https://github.com/NousResearch/hermes-agent/blob/f1cf4107337f118c2b2b4d6d9913edbe5f69d460/skills/autonomous-ai-agents/claude-code/SKILL.md)
  - [Codex app-server runtime](https://github.com/NousResearch/hermes-agent/blob/f1cf4107337f118c2b2b4d6d9913edbe5f69d460/website/docs/user-guide/features/codex-app-server-runtime.md)
- OpenClaw @ `fc53c551`:
  - [README](https://github.com/openclaw/openclaw/blob/fc53c551f5e5ab4c79cace24fb71f3e1f503e4c0/README.md)
  - [automation index](https://github.com/openclaw/openclaw/blob/fc53c551f5e5ab4c79cace24fb71f3e1f503e4c0/docs/automation/index.md)
  - [how automations work](https://github.com/openclaw/openclaw/blob/fc53c551f5e5ab4c79cace24fb71f3e1f503e4c0/docs/automation/cron-jobs/how-it-works.md)
  - [schedules](https://github.com/openclaw/openclaw/blob/fc53c551f5e5ab4c79cace24fb71f3e1f503e4c0/docs/automation/cron-jobs/schedules.md)
  - [payloads](https://github.com/openclaw/openclaw/blob/fc53c551f5e5ab4c79cace24fb71f3e1f503e4c0/docs/automation/cron-jobs/payloads.md)
  - [managing jobs](https://github.com/openclaw/openclaw/blob/fc53c551f5e5ab4c79cace24fb71f3e1f503e4c0/docs/automation/cron-jobs/managing-jobs.md)
  - [CLI backends](https://github.com/openclaw/openclaw/blob/fc53c551f5e5ab4c79cace24fb71f3e1f503e4c0/docs/gateway/cli-backends.md)
  - [ACP agents](https://github.com/openclaw/openclaw/blob/fc53c551f5e5ab4c79cace24fb71f3e1f503e4c0/docs/tools/acp-agents.md)
  - [agent runtimes](https://github.com/openclaw/openclaw/blob/fc53c551f5e5ab4c79cace24fb71f3e1f503e4c0/docs/concepts/agent-runtimes.md)
  - [exec approvals](https://github.com/openclaw/openclaw/blob/fc53c551f5e5ab4c79cace24fb71f3e1f503e4c0/docs/tools/exec-approvals.md)
  - [Lobster](https://github.com/openclaw/openclaw/blob/fc53c551f5e5ab4c79cace24fb71f3e1f503e4c0/docs/tools/lobster.md)
  - [sessions](https://github.com/openclaw/openclaw/blob/fc53c551f5e5ab4c79cace24fb71f3e1f503e4c0/docs/concepts/session.md)
- Claude Agent SDK:
  - [sessions](https://code.claude.com/docs/en/agent-sdk/sessions.md)
  - [hooks (SDK)](https://code.claude.com/docs/en/agent-sdk/hooks.md)
  - [hooks reference: "Defer a tool call for later"](https://code.claude.com/docs/en/hooks.md)
  - [overview (auth note)](https://code.claude.com/docs/en/agent-sdk/overview.md)
  - installed `claude_agent_sdk` 0.2.103 (`types.py`: `resume`, `fork_session`, `max_budget_usd`,
    `session_store`, `DeferredToolUse`; `_internal/sessions.py`: `get_session_messages`)
- Codex:
  - [non-interactive mode (`codex exec`)](https://learn.chatgpt.com/docs/non-interactive-mode)
  - [`openai/codex`](https://github.com/openai/codex) (Apache-2.0)
