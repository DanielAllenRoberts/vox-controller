# Agent-to-agent messaging: what Claude Code offers in late 2026, and what it unlocks for Vox

Researched 2026-11-06 from the official docs. This complements [`../named-agents.md`](../named-agents.md),
whose stage 1 (talking back to a named agent) was blocked on "tmux send-keys". It no longer needs to be.

## What exists

| Mechanism | What it does | Limits |
|---|---|---|
| **Cross-session messaging** — `ListAgents` + `SendMessage` ([docs](https://code.claude.com/docs/en/cross-session-messaging.md)) | Any local Claude Code session can message another by name (`/rename`, `--name`). Delivery goes over a per-session Unix socket and never leaves the machine. An **idle session wakes up and starts a turn**; a busy one reads the message between tool calls. | Plain text only. The receiver's `crossSessionInbound` (`accept` / `hold` / `refuse`) gates delivery. A message can't approve a prompt or run a slash command. There's burst and loop throttling. Cloud sessions can't reply. `notify_when_idle` gives a one-off "went idle" notice. |
| **Channels** — an MCP server declaring `experimental: {"claude/channel": {}}` ([docs](https://code.claude.com/docs/en/channels.md), [reference](https://code.claude.com/docs/en/channels-reference.md)) | **The only official way for an outside process to push into a running interactive session.** It emits `notifications/claude/channel`, which arrives as a channel-tagged message. With `claude/channel/permission` the server also receives that session's permission prompts and can answer them. | Research preview. The session must be started with `--dangerously-load-development-channels server:<name>` (interactive only, ignored under `-p` / the SDK). Undelivered events drop silently. Sender gating is our job. |
| **Agent SDK `ClaudeSDKClient`** ([docs](https://code.claude.com/docs/en/agent-sdk/streaming-vs-single-mode.md)) | A daemon owns a long-lived session, streams user messages in, and can `interrupt()` it. | Only for sessions Vox itself spawns (workers). It can't attach to a terminal session the user opened. |
| **Hooks** ([docs](https://code.claude.com/docs/en/hooks.md)) | `Stop` gets `session_id` + `last_assistant_message`; `Notification` fires on `permission_prompt` / `idle_prompt`. `type: http` can POST to localhost. | One-way out. Hooks can't receive input. `Stop` fires every turn, not just at "done". |
| **Agent teams** ([docs](https://code.claude.com/docs/en/agent-teams.md)) | Lead + teammates with a shared task list, messaging each other. | Experimental flag, interactive only, one team per session. |

A plain tool-only MCP server (vox-control as it stands today) **cannot push**. It only answers calls.

## What it unlocks for Vox: ranked by value ÷ effort

1. **"David needs you" without trusting the model to say so.** A `Notification` hook
   (`permission_prompt`, `idle_prompt`) and a `Stop` hook POST to a new Vox endpoint. Vox maps
   `session_id` → name (`register_agent` already records names) and speaks or bubbles: *"David's
   waiting on a permission."* **Cheap, robust, no preview features.** ⭐ Do first.
2. **Talk back to a named agent by voice.** "Tell David to use the staging DB." A tiny `vox-channel`
   MCP server (one per named session, launched with the dev-channels flag) receives the text from the
   Vox daemon over localhost and emits a channel event. No tmux, no focus steal. *Limit:* it's queued
   to the next turn, so "David, stop" can't interrupt a long tool call. A hard stop only exists for
   SDK-owned workers (`interrupt()`).
3. **Voice approval of permission prompts.** Channel permission relay: Vox reads the command aloud
   and you say "yes". **Safety:** read the full command back, require an explicit yes, and never
   approve from ambient speech. A 5-letter request id is a mis-hear risk, so match on the spoken
   confirmation of *this* prompt, not the id.
4. **Agents asking each other for help.** Already native: `SendMessage to: <name>` +
   `notify_when_idle`. Vox's part is visibility: a "who's talking to whom" strip in the app's
   Agents view, fed by the hooks in (1).
5. **Vox-owned background workers** ("go research X and tell me when it's done") on a warm
   `ClaudeSDKClient`. Same plumbing as the warm big brain (ideas #64), with `allowed_tools` opened up.

## Unverified / gaps
- The messaging socket env vars (`CLAUDE_CODE_MESSAGING_SOCKET` / `_TOKEN`) are exported to a
  session's children, but the wire format beyond the auth line isn't documented. **Don't build on it.**
- The exact `--input-format stream-json` stdin schema wasn't confirmed from the headless docs.
