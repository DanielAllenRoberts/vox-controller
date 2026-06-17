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
├── src/vox/
│   ├── wakeword/     # wake-word detection (openWakeWord)
│   ├── stt/          # speech-to-text (faster-whisper)
│   ├── io/           # output channels (console for now; voice later)
│   ├── core/         # the listen → transcribe loop
│   ├── audio.py      # microphone capture
│   └── config.py     # settings (name, models, thresholds)
├── docs/plan/        # planning docs (overview, roadmap)
├── pyproject.toml
├── .env.example      # env var template (copy to .env)
└── README.md
```

## Getting started

**Requirements:** macOS (Apple Silicon) and [uv](https://docs.astral.sh/uv/). The project pins **Python 3.12** (uv fetches it for you).

```bash
uv sync          # create the venv + install deps
uv run vox       # start Vox: say "Hey Vox", then speak — your words print to the console
```

- First run downloads the wake-word and Whisper models (one-time).
- Press **Ctrl+C** to quit.
- If mic init fails, install PortAudio: `brew install portaudio`.

> **M0 scope:** wake word → local Whisper → transcript printed. No actions yet — opening apps arrives in M1.
> Copy the env template when you reach the AI layer (M4): `cp .env.example .env`.

## Safety (public repo)

This repository is **public**. Secrets live in `.env` (gitignored), all runtime data lives in a local software-managed store (also gitignored), and nothing sensitive is committed. See the data/secrets section of the overview for details.

---

*This README is a living document — updated as the project grows.*
