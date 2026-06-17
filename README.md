# Vox Controller

An adaptive, voice-controlled command system for macOS — **starts simple and learns your voice and workflows over time**. It sits between basic dictation (transcribe only) and heavy hands-free OS control, with a focus on developer workflows and *understanding intent*, not just words.

Local-first · provider-agnostic · modular · privacy-conscious.

> **Status:** Early development. Built in thin, working slices (see the roadmap). No deadline — a personal side project.

## Core ideas

- **Local-first STT** — Whisper runs on-device for low latency and privacy.
- **Tiered intent parsing** — learned rules → fast model → deep model, so known commands are instant and novel ones still work.
- **Provider-agnostic AI** — any model from any provider behind one interface.
- **Modality-flexible I/O** — choose input (voice or text) and output (voice or text) independently.
- **Teachable & self-improving** — define commands by voice; routine intents get cached into local rules over time.

## Documentation

- [`docs/plan/overview.md`](docs/plan/overview.md) — vision, architecture, decisions log, data/secrets policy.
- [`docs/plan/roadmap.md`](docs/plan/roadmap.md) — v1 goal, milestones (M0–M4), and backlog.

## Project layout

```
vox-controller/
├── docs/plan/        # planning docs (overview, roadmap)
├── .env.example      # env var template (copy to .env)
└── README.md
```
*(Source layout will be added as M0 lands.)*

## Getting started

> Coming together as **M0** (wake word → local Whisper → transcript) is built. Planned stack: **Python**, local **Whisper** STT, **openWakeWord** wake-word detection.

1. Copy the env template: `cp .env.example .env` (no keys needed until the AI layer, M4).
2. _Setup + run instructions land with M0._

## Safety (public repo)

This repository is **public**. Secrets live in `.env` (gitignored), all runtime data lives in a local software-managed store (also gitignored), and nothing sensitive is committed. See the data/secrets section of the overview for details.

---

*This README is a living document — updated as the project grows.*
