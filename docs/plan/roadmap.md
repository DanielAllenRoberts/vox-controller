# Vox Controller — Roadmap

> **Principle:** thin vertical slices, one feature at a time, no deadline. Each milestone is a working end-to-end slice we can actually use before moving on.

## v1 Goal

A **named voice assistant** that:
- listens for a wake word and transcribes speech locally (Whisper),
- can respond by **voice or text**,
- lets you **mix input/output modality** (speak or type in; hear or read out),
- performs a few **basic host tasks** (e.g. opening apps you name).

> **Where we are (2026-06-17, day one):** M0, M1, **M2 (voice out)** and most of **M4 (LLM brain)** are done — see `features.md`. The assistant went well past the original v1 scope: provider-agnostic small/big brains, an **executor** (the LLM runs commands), screen vision, write/rewrite-at-cursor, barge-in, `small.en` accent model. **The main remaining v1 piece is M3 (modality switching — text input + the four in/out combos).** Open friction: ambient audio bleeding into the mic (no AEC yet — see `issues.md` O7). Wake is still stock Whisper phrases (custom "Hey Vox" not trained).

## Milestones (incremental)

### M0 — Listening loop skeleton
Wake word (the assistant's name) → start listening → Whisper transcribes → print the text.
- **Verify:** say the wake word + a phrase, see the correct transcript on screen.
- **Status:** ✅ DONE (2026-06-17). Live wake → transcribe confirmed on-device. Root-cause fix found along the way: pinned `onnxruntime<1.21` — v1.27 silently zeroed openWakeWord's ONNX feature models (Whisper was unaffected as it uses CTranslate2). Wake word is the stock "hey_jarvis"; custom "Hey Vox" to be trained later.

### M1 — Basic action execution
Map simple intents to host actions. First action: **open an app** ("open Safari").
- **Verify:** "open Safari" actually launches Safari; an unknown app fails gracefully.
- **Status:** ✅ DONE — and vastly expanded. The Control layer now does far more than "open app": fuzzy/profile-safe browser tabs, app windows, macOS desktops, Arc profiles, web search, sidebar toggle, back, app-window cycling, smart current-space tab reuse, command chaining ("X and Y"), **dictation** (speak-to-type), quit/restart, and session logging. Full list in `features.md` / `phrases.md`.

### M2 — Voice output (TTS)
Give the assistant a voice; speak confirmations/responses.
- **Verify:** after a command, you hear a spoken confirmation.
- **Status:** ✅ DONE (2026-06-17). macOS `say` (local, instant) via swappable `tts.py`; accented voices (default British "Daniel"); speaks conversational replies/questions/screen-reads but stays quiet on actions; the model can pick a shorter spoken version (`SAY:`). Piper is the future neural upgrade.

### M3 — Modality switching (the configurable I/O feature)
Independently choose **input** (mic or typed) and **output** (voice or text). All four combos:
- voice→voice (hands-free), voice→text (quiet), **text→voice (study mode)**, text→text (classic).
- **Verify:** each of the four modes works; e.g. type a question and hear the answer via headphones.

### M4 — Pluggable AI + intent parsing
Replace hardcoded command matching with **model-based intent classification** behind the provider-agnostic interface (default: Claude Haiku). Any provider swappable via config.
- **Verify:** novel phrasing ("could you launch the browser") still opens the right app.
- **Status:** 🟡 LARGELY DONE (2026-06-17). Multi-turn chat + a provider-agnostic **small/big brain** layer (Haiku→Opus on the Claude subscription, or any API / local LLM). An **executor** lets the brain *run* Vox's own commands on a miss (not just chat), with environment context (running apps/tabs), clarification memory, and chatter-ignore. LLM text commands (write / make-pretty) and screen vision shipped. Design note: we kept **deterministic-first** parsing with LLM escalation (cheaper/faster) rather than routing every utterance through a model — the better fit. Remaining: optional tiered cascade + the teachable-rules/learning layer (backlog).

## Backlog (post-v1, ordered loosely)

- **Teachable rules engine** — "whenever I say X, do Y" → persistent rule.
- **Tiered cascade** — rules → fast model → deep model.
- **Learning/logging layer** — capture every interaction for later training.
- **Containerized agentic execution** — OpenCode-backed code tasks in a sandbox.
- **Remote / phone interface** — local-first WebSocket; Tailscale suggested for anywhere-access.
- **Terminal-first + web UI** — keep the whole thing runnable from the terminal (`uv run vox`), and add a local **web UI that attaches to the running daemon** to observe/control it (live transcripts, rules, logs, settings) — paperclip / OpenClaw style. The web UI is a *view onto the same process*, not a separate app.
- **Intent caching** — compile hot intents into local rules to cut API use.
- **Personalized fine-tuning** — voice + command models tuned to the user.
