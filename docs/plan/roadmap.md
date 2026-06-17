# Vox Controller — Roadmap

> **Principle:** thin vertical slices, one feature at a time, no deadline. Each milestone is a working end-to-end slice we can actually use before moving on.

## v1 Goal

A **named voice assistant** that:
- listens for a wake word and transcribes speech locally (Whisper),
- can respond by **voice or text**,
- lets you **mix input/output modality** (speak or type in; hear or read out),
- performs a few **basic host tasks** (e.g. opening apps you name).

## Milestones (incremental)

### M0 — Listening loop skeleton
Wake word (the assistant's name) → start listening → Whisper transcribes → print the text.
- **Verify:** say the wake word + a phrase, see the correct transcript on screen.
- **Status:** ✅ DONE (2026-06-17). Live wake → transcribe confirmed on-device. Root-cause fix found along the way: pinned `onnxruntime<1.21` — v1.27 silently zeroed openWakeWord's ONNX feature models (Whisper was unaffected as it uses CTranslate2). Wake word is the stock "hey_jarvis"; custom "Hey Vox" to be trained later.

### M1 — Basic action execution
Map simple intents to host actions. First action: **open an app** ("open Safari").
- **Verify:** "open Safari" actually launches Safari; an unknown app fails gracefully.
- **Status:** ✅ built (2026-06-17). Done as part of the mode state machine — `open <app>` runs in Control mode. Multi-phrase detection, parser, sleep, capture all verified offline; pending a live mic spin.

### M2 — Voice output (TTS)
Give the assistant a voice; speak confirmations/responses.
- **Verify:** after a command, you hear a spoken confirmation.

### M3 — Modality switching (the configurable I/O feature)
Independently choose **input** (mic or typed) and **output** (voice or text). All four combos:
- voice→voice (hands-free), voice→text (quiet), **text→voice (study mode)**, text→text (classic).
- **Verify:** each of the four modes works; e.g. type a question and hear the answer via headphones.

### M4 — Pluggable AI + intent parsing
Replace hardcoded command matching with **model-based intent classification** behind the provider-agnostic interface (default: Claude Haiku). Any provider swappable via config.
- **Verify:** novel phrasing ("could you launch the browser") still opens the right app.

## Backlog (post-v1, ordered loosely)

- **Teachable rules engine** — "whenever I say X, do Y" → persistent rule.
- **Tiered cascade** — rules → fast model → deep model.
- **Learning/logging layer** — capture every interaction for later training.
- **Containerized agentic execution** — OpenCode-backed code tasks in a sandbox.
- **Remote / phone interface** — local-first WebSocket; Tailscale suggested for anywhere-access.
- **Terminal-first + web UI** — keep the whole thing runnable from the terminal (`uv run vox`), and add a local **web UI that attaches to the running daemon** to observe/control it (live transcripts, rules, logs, settings) — paperclip / OpenClaw style. The web UI is a *view onto the same process*, not a separate app.
- **Intent caching** — compile hot intents into local rules to cut API use.
- **Personalized fine-tuning** — voice + command models tuned to the user.
