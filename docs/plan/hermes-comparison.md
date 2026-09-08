# Hermes Agent vs Vox — recon & what we took

> **Date:** 2026-08-20 · **Subject:** [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) (MIT)
> **Question asked:** does Hermes make Vox irrelevant, and what should we take from it?
> **Answer:** no — but it narrows the gap, and it has desktop primitives we were missing. See
> [ideas.md #61](ideas.md) for the work this produced.

## What Hermes is

An agent you talk to, reachable from a TUI, a desktop app, and messaging gateways (Telegram,
Discord, Slack, WhatsApp, Signal, email). Provider-agnostic, MIT, cross-platform (Linux, macOS,
WSL2, Windows, Termux, Android). One-line curl installer.

It has voice — added ~v0.20.0, and **not mentioned in the README or on the marketing site**, which is
why a first pass over those missed it:

- **Wake word** — three engines: openWakeWord (bundled "hey hermes"), **Sherpa** (open-vocabulary,
  type any phrase, no training), Porcupine. On-device. `confirmation_frames` + `sensitivity` knobs.
  Wake phrases can route to **named profiles** ("hey coder" opens a session in that profile).
- **Voice mode** — faster-whisper local (or Groq/OpenAI cloud, fallback chain `local > groq >
  openai`), Edge TTS default / ElevenLabs premium, sentence-by-sentence streaming, barge-in with
  `barge_in_threshold_multiplier` and `barge_in_grace_seconds`.

## The correction that mattered

The README and website describe terminal + browser control and never mention GUI automation. That is
wrong about the code. `tools/computer_use_tool.py` registers:

> "Universal desktop control via cua-driver (macOS, Windows, Linux). Works with any tool-capable
> model. **Background computer-use: does NOT steal the user's cursor or keyboard focus.**"

`tools/computer_use/backend.py` shows an architecture that is essentially ours:

- `mode='ax'` — accessibility elements only
- `mode='vision'` — screenshot + coordinates
- `mode='som'` (default) — set-of-mark: *"PNG already has numbered overlays drawn by the backend, and
  `elements` holds the matching index → element mapping"*
- escalation: *"True when an AX walk found no actionable elements (act by px instead)"*

That is `ax.py` → the numbered overlay (#52) → coordinate clicking (#57). Same ladder, arrived at
independently. Its `computer_use` actions: capture, click, double_click, right_click, middle_click,
drag, scroll, type, key, set_value, wait, list_apps, list_windows, focus_app, plus eight
`cua_browser_*` actions (navigate, click, type, pointer, dialog, set_input_files, download, state).

## Where Vox still wins

**Latency.** Hermes' `computer_use` is an agentic loop — screenshot, reason, click, re-screenshot.
Seconds and real tokens per action. `ax.click` is a ~77ms deterministic lookup with no model in the
loop, and the whole tiered design (Vosk grammar → command DB → small brain → big brain) exists to
keep control mode responsive. Voice control needs sub-second; an agentic loop cannot do that.

**Voice-native interaction.** Modes (control / dictation / assistant), dictation at the cursor,
"click 14" spoken by a human, the correction dictionary (#54), hotword biasing, smart-turn-v3.
Hermes' voice opens a session; it is not a continuous control surface. On the voice pipeline
specifically **Vox is ahead** — Hermes bolted voice onto an agent, we built a voice system.

That is a real moat, but it is speed and interaction design — *not* "Hermes can't touch the GUI".

## Where Hermes is ahead

- **Reach** — six messaging gateways, five platforms. Vox is macOS + local only.
- **Memory retrieval** — FTS5 full-text search over session history with LLM summarization, plus
  Honcho user modeling. Ours is tiered Markdown; semantic recall (#28) is still unbuilt.
- **Arbitrary shell.** Hermes' terminal tool runs anything across seven backends. Vox has **no**
  general shell execution — every `subprocess` call is a hardcoded utility (`screencapture`, `sips`,
  `open`, `say`), and the agent tier's `run_command` routes to `actions.handle()`, our own parser.
- **Distribution** — one curl command that bundles Python, Node, uv, ripgrep, ffmpeg.

## Decisions

**Taken now (#61):** the desktop primitives that existed in Vox only inside the gated agent tier —
scroll, key combos, right/double click — promoted to deterministic voice commands, plus the ones we
had nowhere: `drag`, `set_value`, and background (no-focus-steal) event delivery.

**Queued, not taken yet:**

- **Wake-phrase → personality routing.** "hey Jarvis" opening a session *in that persona* maps
  straight onto our personalities (#22/#41). Cheapest delight-per-line on this list.
- **One messaging gateway** (Telegram or Signal — not six). Our biggest genuine capability gap;
  unlocks presence-aware reminders (#60) and meeting-notes delivery (#48).
- **Barge-in tunables** — we have `barge_in_enabled` + a poll interval; they have a threshold
  multiplier and a grace window. Small, kills false interrupts.
- **FTS5 + summarization over session history** — we already have SQLite and `vox.log`. Small build,
  serves #28 without waiting on MemPalace (#55).
- **Their install story** — the weak link for the open-source direction is `uv sync` plus manual
  macOS permission grants, not the feature set.

**Declined:**

- **cua-driver itself.** MCP-driven, which costs exactly the latency that is now our main
  differentiator. The zero-dep native AX engine is the right call for the fast path. Possibly worth
  it for the vision tier alone, later.
- **Sandbox/terminal backends, subagents, A2A, the 40+ tool surface.** Out of scope; that is Hermes
  being an agent platform, which is not what Vox is for.
- **Chasing general-agent territory** (#38 coding brain, #39 named agents, #26 full control). Hermes
  is MIT, funded and further along there. The niche where it structurally cannot follow is
  sub-second GUI control of a live Mac.

**On giving Vox a shell:** deferred deliberately. An always-on microphone plus arbitrary shell
execution is a different security posture from a typed agent — we have a homophone dictionary (#54)
and a mishear counter (#44) precisely because mis-hears are common. Hermes' approval layer
(`tools/approval.py`, deny rules, allowlists, `path_security.py`, `threat_patterns.py`) was built
*before* the tool. If we do this, the guardrails ship in the same change, scoped to a directory and
an allowlist rather than open.

## Sources

- <https://github.com/NousResearch/hermes-agent>
- <https://hermes-agent.nousresearch.com/docs/user-guide/features/wake-word>
- <https://hermes-agent.nousresearch.com/docs/user-guide/features/voice-mode>
