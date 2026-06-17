# Vox — Observations & Edge Cases

> A running log of interesting failures, ambiguities, and ideas found while *using* Vox — so we design real solutions instead of one-off patches. Each entry: what happened, why, and the intended fix.

## 2026-06-17 — "go to Cursor" heard as "go to Casa" → opened casa.com

- **What happened:** Said "go to Cursor"; Whisper transcribed "Casa"; `go to` had no app/alias/domain match, so it *confidently guessed* `https://casa.com` and opened a random site.
- **Root cause — two stacked failures:**
  1. **STT mis-transcription** ("Cursor" → "Casa").
  2. The command layer guesses `.com` for any unknown single word with **no notion of confidence**.
- **Solution A — reduce the mis-hear (bias the STT):** feed Whisper an `initial_prompt` / `hotwords` of our command verbs + the user's installed app names (Cursor, Arc, Safari…). Whisper then favours known terms, so "Cursor" beats "Casa". Cheap, attacks the root cause. *(Not yet implemented.)*
- **Solution B — recover from uncertainty (escalate):** when the deterministic layer can't *confidently* resolve a target, **hand off to the assistant** instead of guessing. The assistant — knowing installed apps, common targets, and habits — reasons "‘Casa' isn't a known site… did you mean *Cursor*?" and confirms/corrects. The OpenClaw-style intelligent fallback.
- **Status:** interim — `go to` now **flags low-confidence guesses** in its output (the escalation hook). Full escalation lands with **M4** (LLM behind the assistant); STT biasing can come sooner.

## The principle this points to

**Whenever a deterministic action is low-confidence or unmatched → escalate to the assistant.** This is the bridge between CONTROL mode (fast, deterministic) and ASSISTANT mode (LLM reasoning), and it's what makes the system feel smart rather than brittle. (See the tiered cascade in `overview.md`.)
