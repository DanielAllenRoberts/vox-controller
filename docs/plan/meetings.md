# Meetings & Recording — Idea

> **Status:** Idea / research (opened 2026-07-02). Not yet scheduled.
> Companion docs: [`research/meetily-recon.md`](research/meetily-recon.md) (external recon), [`../audit/`](../audit/) (architecture audit).

## The idea

Extend Vox beyond command/assistant modes into a **meetings / recording** capability:

1. **Capture** a meeting — both the user's mic *and* the other participants' audio (system/output audio).
2. **Transcribe** it locally (privacy-first, matching Vox's local-first STT stance).
3. **Ingest** the meeting into Vox's system — summaries, action items, and decisions flow into memory / notes so Vox can reason over them later.

## Why now

- Vox already runs a local Whisper (`faster-whisper`) STT pipeline, VAD/turn-taking, TTS, and a memory store — a meetings feature reuses most of that stack.
- **Meetily** (https://meetily.ai/, open source) does exactly meeting capture + local transcription + AI notes. We want to:
  - **Learn from / reuse** its voice tech to make *our* STT + audio pipeline better (diarization, system-audio capture, streaming).
  - **Use it** as an on-ramp to get meeting information into Vox.
- If direct integration of their repo isn't feasible (license, stack mismatch), we build our own meetings feature informed by their approach.

## Open questions (to be answered by recon)

- License — can we reuse code, or only learn from it?
- How does Meetily capture **the other side** of a call (system audio) on macOS? This is the hard part Vox doesn't solve yet.
- Real-time streaming vs post-hoc batch transcription?
- Speaker **diarization** — who said what?
- Summarization / action-item extraction approach (local model vs cloud).
- Direct-integration feasibility vs "borrow the ideas".

## Success criteria (draft)

- Record a real meeting on macOS capturing both mic + system audio.
- Produce a transcript + a structured summary (decisions, action items, attendees).
- Land that summary into Vox memory so it's queryable by voice later.

_This doc is a living idea record — recon findings will refine scope before any build._
