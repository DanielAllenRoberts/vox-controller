# Vox Controller — Project Overview

> **Status:** Planning, evolving. Personal side project — **no deadline**, built incrementally one feature at a time, prioritizing doing each part well over speed.

## Vision

An adaptive, voice-controlled command execution system for macOS that **starts simple and becomes increasingly personalized over time**.

It targets the gap between:

- **Basic voice dictation** (e.g. WhisperFlow) — transcribes, but doesn't *act*.
- **Full hands-free OS control** (e.g. Dragon, Talon) — powerful, but heavy and not semantically aware.

Focus: **developer workflows** and **semantic understanding of intent** — understanding what the user wants and doing it.

## Core Principles

1. **Local-first & private** — speech-to-text runs on-device; minimize cloud round-trips.
2. **Speed for the known, intelligence for the novel** — a tiered cascade keeps routine commands instant while still handling new requests.
3. **Learns continuously** — every interaction is data; the system gets cheaper, faster, and more personalized the more it's used.
4. **Teachable by voice** — the user can define new behaviors conversationally, no config files required.
5. **Provider-agnostic AI** — any model from any provider sits behind one common interface; swapping providers is config, not code changes.
6. **Modality-flexible I/O** — input and output channels are chosen independently (voice or text, either direction).
7. **Nothing sensitive in the repo** — runtime data lives in a local store (SQLite or similar); secrets live in `.env`. The repo holds code only.
8. **Containerized execution** — sandbox agentic / code-execution as much as possible.

## Architecture (high level)

### 0. Input / Output Channels (modality)

Input and output are **decoupled and independently configurable**:

| Input | Output | Mode | Example use |
|-------|--------|------|-------------|
| Voice | Voice  | Hands-free | Driving / cooking — full voice loop |
| Voice | Text   | Quiet listen-free | Speak a query, read the answer (no audio out) |
| Text  | Voice  | Study mode | Type in public, hear the answer via headphones |
| Text  | Text   | Classic | Normal typed chat |

Designing I/O as swappable adapters around the core pipeline from the start, even though full switching ships as a later milestone.

### 1. Speech-to-Text (STT)
- **Whisper** running **locally** on the Mac for real-time transcription. Low latency, private, no per-word cost.

### 2. Pluggable AI Provider Layer
- One common interface; **any provider/model** behind it (Claude, OpenAI, local models, etc.).
- Default tiers map to the **current Claude lineup** — Haiku (fast) and Sonnet (deep) — but every tier is swappable via config.

### 3. Tiered Intent-Parsing Cascade
Transcribed text escalates through tiers — stop as soon as one resolves:

| Tier | Handler | Used for |
|------|---------|----------|
| 0 | **Learned rules database** | Previously executed commands & user workflows — instant, no API. |
| 1 | **Fast model** (default Claude Haiku) | Quick intent classification + parameter extraction. |
| 2 | **Deep model** (default Claude Sonnet) | Commands needing deeper reasoning or context. |
| 3 | **Agentic execution** (OpenCode, model-backed) | Code-execution tasks, run in a sandbox. |

### 4. Activation & Lifecycle
- **Wake-word detection** (the assistant has a name) keeps the daemon dormant until called.

### 5. Context & Memory
- Maintains **conversation state** and **project context** across a session.
- Inspiration: **OpenClaw** — a memory/agent layer built on top of OpenCode.

### 6. Teachable Rules Engine
- Define commands by voice: *"whenever I say X, do Y"* → a **persistent rule**, no manual config.
- Frequently-used intents get **cached and compiled into rules**, reducing API dependency, latency, and cost over time.

### 7. Agentic / Code Execution
- **OpenCode** — an open-source framework for running LLMs as agents (what OpenClaw was built on; also used by other tools) — backs sandboxed code execution.
- **Containerized** as much as possible to bound blast radius.

### 8. Remote Access
- **Built local-first** — the phone interface works on the local network out of the box.
- **Tailscale is not part of this project.** It's an optional, *suggested* user-side add-on so the local interface becomes reachable from anywhere. We don't build or depend on it.
- Persistent **WebSocket** connection for low-latency dispatch.

### 9. Interfaces — terminal-first, web UI as a view
- **Runs entirely in the terminal**: clone the repo and `uv run vox` — no GUI required.
- A **local web UI** can attach to the *same running daemon* to observe and control it (live transcripts, active rules, logs, settings) — inspired by tools like **paperclip** and **OpenClaw**, where you run a terminal process and can also view/drive it in the browser.
- Key point: the web UI is a **view/controller onto the running process**, not a separate app — the terminal stays the source of truth.

## Learning Layer (long-term differentiator)

Every interaction is logged: what was said, how it was transcribed, whether execution succeeded, and any user corrections. This feeds two loops:

1. **Personalized STT** — fine-tune lightweight speech models on the user's voice/vocabulary, eventually beating generic Whisper for *this* user.
2. **Personalized command understanding** — as the rules DB grows, routine tasks resolve locally without the LLM layer, trading API cost for local knowledge while staying extensible for novel requests.

## Data & Secrets (public-repo safety)

- **Runtime data** (rules DB, interaction logs, learned models) → a **local store the software manages** (e.g. SQLite), gitignored, **never committed**.
- **Secrets / API keys** → `.env`, gitignored.
- **The repo contains code, schema, and migrations only** — no data, no secrets. Treat everything committed as permanently public.

## Decisions Log

- **Name & wake word:** the assistant is **Vox**; the wake phrase is **"Hey Vox"** (two syllables → more reliable detection than bare "Vox"). M0 uses a stock openWakeWord model to prove the loop; a custom "Hey Vox" model is trained as the follow-up.
- **AI providers:** provider-agnostic by design; defaults to the latest Claude models (Haiku fast / Sonnet deep). Any API usable.
- **Stack:** **Python** for the v1 orchestration layer — best Whisper/openWakeWord ecosystem and fastest path to a modular system. Performance-critical inference runs in **native backends** (whisper.cpp / CTranslate2 / ONNX, with Apple-Silicon acceleration), so glue-language overhead is negligible. Modular boundaries let any hot component be rewritten in a faster language (Rust/C++/Swift) later without touching the rest.
- **Wake word:** start with **openWakeWord** (open source — inspect, adapt, potentially contribute back), behind a modular interface so other detectors can be swapped and benchmarked.
- **Open-source experimentation:** modular interfaces exist specifically so we can try and benchmark multiple open-source STT / TTS / wake-word models over time.
- **OpenCode:** open-source agentic framework (LLMs as agents); **OpenClaw** is built on it. Used for sandboxed code execution.
- **Storage:** software-managed local store (SQLite-style) for all runtime data; secrets in `.env`; nothing sensitive in the repo.
- **Tailscale:** out of scope — local-first, with Tailscale merely suggested for remote reach.
- **Containerization:** sandbox execution wherever practical.
- **Pace:** no deadline; incremental, feature-by-feature.

## Open Questions / To Discuss

- **TTS engine:** macOS `say` as a zero-dep fallback; open-source **Piper** (local, fast) as the modular default — with a longer-term goal of a voice that **adapts to the user's accent/voice over time** (e.g. Coqui / XTTS-style). To benchmark.
- **Rules matching:** exact string, fuzzy, or semantic embeddings — drives the rules-engine design.
- **OpenCode integration boundary:** subprocess, local API, or library.
- **Host vs. sandbox split:** "open app" is host-level (not containerizable); define which actions run on the host vs. in a container.
