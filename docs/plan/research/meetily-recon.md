# Meetily — Technical Recon

> **Recon date:** 2026-07-02 · Source: local shallow clone of `github.com/Zackriya-Solutions/meetily` @ **v0.4.0** (commit `0281737`).
> Purpose: decide what Vox can reuse/learn from to build a **meetings recording + transcription + AI-notes** feature. Companion: [`../meetings.md`](../meetings.md).

## TL;DR

- **License: MIT** (© 2024 Zackriya Solutions). ✅ We can **reuse/adapt code and prompts with attribution**, not just learn from it.
- **What it is:** a standalone, privacy-first desktop app — **Next.js UI + Tauri (Rust) shell** for capture/transcription, plus a **Python FastAPI backend** for AI summaries. Local-first (whisper.cpp + Ollama), with optional cloud LLMs (Anthropic/Groq/OpenAI). macOS + Windows. Active project, v0.4.0, thousands of stars.
- **The one thing worth the whole recon:** Meetily captures **the other participants' audio** on macOS via **ScreenCaptureKit** (screen-recording permission taps the system audio output) and mixes it with the mic. This is exactly the hard problem Vox hasn't solved (`sounddevice` = mic only). Their "diarization" is a pragmatic trick: tag each transcript segment by **source** — `mic` = you, `system` = everyone else.
- **Integration verdict:** ❌ Don't try to embed Meetily-the-app (it's a parallel product: Tauri/Rust + Next.js + a second Python backend — a heavy, different stack). ✅ **Build our own, informed by theirs** — port the *mechanism* (ScreenCaptureKit → Python/pyobjc) and lift the MIT-licensed summary prompts/schemas. Optional middle path: reuse their Rust audio crate as a spawned **sidecar binary**.

---

## Architecture

Two-and-a-half components:

```
┌─────────────────────────── Meetily desktop app ───────────────────────────┐
│  Next.js UI  ──tauri IPC──►  Tauri / Rust core (frontend/src-tauri)         │
│                              • audio capture: mic (cpal) + system (SCKit)   │
│                              • VAD, denoise, resample, mix, chunk           │
│                              • STT in-process: whisper.cpp (whisper-rs) OR  │
│                                Parakeet engine                              │
│                              • local SQLite (sqlx migrations)               │
│                              • LLM provider calls (groq / openrouter)       │
└────────────────────────────────────┬───────────────────────────────────────┘
                                      │ HTTP
                          ┌───────────▼─────────────┐
                          │ Python FastAPI backend  │  backend/app/
                          │ • transcript_processor  │  → structured summaries
                          │ • pydantic-ai Agent     │  Anthropic/Groq/OpenAI/Ollama
                          │ • SQLite (db.py)        │
                          └─────────────────────────┘
              + llama-helper/  (local LLM runner sidecar)
```

Notable: the heavy lifting moved **into the Tauri/Rust app** over time (in-process whisper-rs). The Python backend (`backend/app/main.py`, `transcript_processor.py`, `db.py`) is now mainly the **summary/notes** brain. There's a `backend/whisper.cpp` git submodule (their own fork, `develop` branch) and older `start_whisper_server` scripts — legacy of when transcription ran as a separate whisper-server.

## STT / Transcription

- **Engine:** whisper.cpp via **`whisper-rs`**, run **in-process** inside the Tauri app. Hardware accel via Cargo features: `metal` + `coreml` on macOS (auto), `cuda`/`vulkan`/`hipblas`/`openblas` elsewhere. (`frontend/src-tauri/Cargo.toml`)
- **Alternate engine:** a **Parakeet** engine (`frontend/src-tauri/src/parakeet_engine/` — NVIDIA Parakeet ASR). Pluggable via `audio/transcription/provider.rs` + `worker.rs`.
- **Real-time & streaming:** chunked streaming pipeline — `TranscriptionStatus { chunks_in_queue, is_processing }`, a transcription worker thread, `batch_processor.rs`, `retranscription.rs` (re-transcribe a chunk for accuracy). Not batch-only; it emits live `TranscriptUpdate` events to the UI.
- **VAD:** dedicated `audio/vad.rs`.
- **Contrast with Vox:** Vox uses **faster-whisper** (CTranslate2). Different runtime, similar model. No reason to switch — but their **chunking + VAD + retranscription** loop is a good reference for a meetings-length (hours) stream vs Vox's short command utterances.

## "Diarization" (who said what)

- **No true speaker diarization.** Instead: a `speaker` column on the `transcripts` table with values **`mic`** vs **`system`** (`frontend/src-tauri/migrations/20251110000001_add_speaker_field.sql`).
- Practically: **mic = the local user, system = all remote participants** (single blended channel). Cheap, robust, and good enough for meeting notes. True per-person diarization (pyannote etc.) is *not* attempted.
- **Takeaway for Vox:** adopt the same source-tag model. It's a one-column idea that gives 80% of the value for ~none of the cost.

## Audio capture — the key question (SOLVED)

This is the part worth stealing. On **macOS**:

- **System audio (the other side of the call):** captured with **ScreenCaptureKit**. Evidence:
  - `frontend/src-tauri/check_screen_permission.swift` → `import ScreenCaptureKit`
  - `Info.plist`: `NSScreenCaptureUsageDescription` = *"needs screen recording permission to capture system audio during meetings"* + a system-audio-output usage string.
  - Rust modules: `audio/system_audio_stream.rs`, `audio/system_audio_commands.rs`, `audio/capture/system.rs`, `audio/permissions.rs` (`trigger_system_audio_permission`), wired in `lib.rs` (`init_system_audio_state`, `start_system_audio_capture_command`, `list_system_audio_devices_command`, monitoring/heartbeat + auto-reconnect).
  - **No virtual audio device required** (no BlackHole/Loopback) — ScreenCaptureKit taps the output directly. That's the modern macOS ≥13 approach and the big win: zero install friction for the user.
- **Mic:** cross-platform via **`cpal`** (pinned to a git rev: `RustAudio/cpal @ 51c3b43`).
- **DSP pipeline (Rust, `audio/`):** `nnnoiseless` (RNNoise denoise) → `rubato` (resample) → `realfft` (FFT/level) → `ffmpeg_mixer.rs` (mix mic + system into one stream) → `encode.rs` (WAV) → chunk → transcribe. Plus `buffer_pool.rs`, `incremental_saver.rs` (checkpointed saves), `device_monitor.rs` (hot-plug), `hardware_detector.rs`.
- The `audio/` module is genuinely mature (~40 files: `pipeline.rs`, `recording_manager.rs`, `level_monitor.rs`, `vad.rs`, …). **This is the crown jewel for reuse.**

**Vox implication:** Vox already ships **pyobjc** (`pyobjc-framework-avfoundation`, `pyobjc-framework-cocoa`). The ScreenCaptureKit *mechanism* ports to Python via `pyobjc-framework-screencapturekit` (add `SCStream` with audio enabled + the screen-recording permission + `NSScreenCaptureUsageDescription`). We reimplement the *idea*, not the Rust.

## Summarization / notes / action items

- **Backend:** `backend/app/transcript_processor.py` uses **`pydantic-ai`** `Agent` with swappable providers — **Anthropic, Groq, OpenAI, and local Ollama** (`ollama==0.5.2`). Structured output via pydantic `BaseModel` (typed summary sections — decisions, action items, etc.).
- **Local option:** `llama-helper/` + Ollama → fully local summaries (privacy-first).
- **Takeaway for Vox:** Vox already has anthropic+openai. We don't need pydantic-ai, but we can **lift their summary prompt + output schema verbatim (MIT)** and run it through Vox's existing provider layer. That's the fastest route to good meeting notes.

## Storage & data model

- **SQLite** on both sides: Rust app uses **sqlx migrations** (`frontend/src-tauri/migrations/`, `database/manager.rs`), backend uses `db.py`. Aligns with Vox's SQLite direction ([[vox-open-source-direction]], `command_store.py`).
- **On-disk meeting folders:** timestamped `MeetingName_YYYY-MM-DD_HH-MM/` with a `.checkpoints/` dir for **incremental saves** during long recordings (`audio/audio_processing.rs::create_meeting_folder`, `incremental_saver.rs`). Good pattern for crash-safety on hour-long meetings.

## Maturity

- Active, trending (Trendshift badge), MIT, pre-release **v0.4.0**, macOS + Windows, prebuilt release downloads. Mature audio stack; the codebase shows churn (`*_old.rs`, `lib_old_complex.rs`, `*.backup` files) — i.e. still evolving, so treat their current code as reference, not a stable API.

---

## Recommendations for Vox

### Integration verdict — **build our own, informed by Meetily** (option B)

| Option | What | Verdict |
|---|---|---|
| A. Embed Meetily app | Ship/reuse the Tauri+Next.js app | ❌ It's a whole parallel product & stack (Rust+Next+2nd Python backend). Not a library. |
| B. **Borrow-and-build** | Reimplement capture in Python/pyobjc; lift their prompts/schema (MIT); keep Vox's faster-whisper | ✅ **Recommended.** Keeps Vox single-stack, local-first, one product. |
| C. Rust audio sidecar | Compile their `audio/` crate as a standalone binary Vox spawns & reads a stream from | ⚠️ Middle path. Reuses battle-tested capture, but adds a Rust build to Vox's macOS distribution. Fallback if pyobjc SCKit proves painful. |

### Top takeaways (highest value first)

1. **System-audio capture via ScreenCaptureKit** — the whole reason to do this recon. Port to Python with `pyobjc-framework-screencapturekit` (`SCStream` + audio). Add `NSScreenCaptureUsageDescription` and a screen-recording permission flow. **No virtual audio device needed.** This is the single biggest upgrade to Vox's audio layer (`audio.py` is mic-only today).
2. **Source-tagged "diarization"** — one column: `speaker ∈ {mic, system}`. Mic = user, system = others. Trivial to add, huge for meeting notes.
3. **Mix + chunk + VAD + incremental save** for long streams — Vox's pipeline is tuned for short command utterances; meetings are hours. Reuse their ideas: denoise (RNNoise → Vox could use `nnnoiseless`/webrtcvad equivalents), resample, mix mic+system, chunk for streaming whisper, checkpoint to disk.
4. **Summary prompt + typed schema** (decisions / action items / attendees) — lift from `transcript_processor.py` (MIT) and run through Vox's existing anthropic/openai layer + memory store. Ingest into Vox memory so meetings are queryable by voice later.
5. **Meeting folder + checkpoint data model** — timestamped folder, incremental saves, SQLite `transcripts`/`meetings` tables. Aligns with Vox's existing `command_store` SQLite direction.

### Suggested phased build for Vox

- **Phase 0 — spike:** capture system audio in Python via ScreenCaptureKit (pyobjc), write a WAV. Prove the permission + tap works on this macOS. *(Highest risk; do first.)*
- **Phase 1 — record + transcribe:** mic + system dual-stream → mix → faster-whisper chunked → source-tagged transcript to SQLite + a meeting folder.
- **Phase 2 — notes:** run the (lifted, MIT) summary prompt/schema → decisions/action items → store.
- **Phase 3 — ingest:** land the summary into Vox memory; make it recallable by voice ("what did we decide in the standup?").

### License / attribution note

MIT → we may copy code and prompts. Keep a short `NOTICE`/attribution (Meetily © Zackriya Solutions, MIT) wherever we lift non-trivial code or prompt text. Vox is also open-source, so this is clean.

---

_Recon done from a local clone in the session scratchpad (`.../scratchpad/meetily`, gets cleaned up). whisper.cpp submodule was not fetched. The first recon agent cloned the repo but was killed by a transient server rate-limit before writing; this doc was authored from direct inspection of that clone._
