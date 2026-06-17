# Vox — Observations & Edge Cases

> A running log of interesting failures, ambiguities, and ideas found while *using* Vox — so we design real solutions instead of one-off patches. Each entry: what happened, why, and the intended fix.

## 2026-06-17 — "go to Cursor" heard as "go to Casa" → opened casa.com

- **What happened:** Said "go to Cursor"; Whisper transcribed "Casa"; `go to` had no app/alias/domain match, so it *confidently guessed* `https://casa.com` and opened a random site.
- **Root cause — two stacked failures:**
  1. **STT mis-transcription** ("Cursor" → "Casa").
  2. The command layer guesses `.com` for any unknown single word with **no notion of confidence**.
- **Solution A — reduce the mis-hear (bias the STT):** feed Whisper an `initial_prompt` / `hotwords` of our command verbs + the user's installed app names (Cursor, Arc, Safari…). Whisper then favours known terms, so "Cursor" beats "Casa". Cheap, attacks the root cause. *(Not yet implemented.)*
- **Solution B — recover from uncertainty (escalate):** when the deterministic layer can't *confidently* resolve a target, **hand off to the assistant** instead of guessing. The assistant — knowing installed apps, common targets, and habits — reasons "‘Casa' isn't a known site… did you mean *Cursor*?" and confirms/corrects. The OpenClaw-style intelligent fallback.
- **Status:** ✅ improved (2026-06-17). Navigation now acts **only on known targets** (app / known site / real domain) — unknowns **hand off** instead of guessing (no more accidental `casa.com`, no googling your narration). Added explicit **"search X"**. And **hotword biasing** nudges STT toward "Cursor"/"Arc" over "Casa". Full LLM escalation still lands with **M4**.

## 2026-06-17 — Arc / macOS scripting limits found while building navigation

- **Arc tab index is unreliable.** `tabs of front window` returns *all* tabs across spaces/folders (52, mostly `location: pinned`) in an order that doesn't match the visual sidebar. → Tab-by-**name** (now fuzzy) is the reliable path; index isn't.
- **Arc folders/spaces aren't scriptable.** No `spaces` access (`Can't get every space`); tabs only report `location` = pinned/unpinned/topApp, no folder grouping. → Folder/space/profile-scoped nav isn't possible via AppleScript.
- **Window switching can't cross macOS Spaces.** A Cursor process with two windows on different desktops reports `count of windows = 1` to the Accessibility API — the other Space's window is invisible. ⌘`-cycling only works within the current Space.
- **Win:** fuzzy tab matching (difflib) resolves "Moonshark"→Moonshot, "chat upt"→ChatGPT, and partial names — a cheap, reliable improvement (and a first taste of the personalised-matching idea in `ideas.md` #8).

## 2026-06-17 — Ambient audio gets transcribed ("click click click", YouTube outros) 😄

Control mode is a hot mic, so Whisper transcribes *everything* it hears: keyboard clicks → "click click click", clock sounds → "tick tock tick tock", and even a **playing YouTube video's narration** ("if you like this video please subscribe and like…"). All of it correctly **hands off** (no action) thanks to no-guess matching — harmless, just genuinely funny to watch Vox earnestly hand off a YouTuber's outro. The one real risk: a command buried in ambient speech (e.g. reading the hotword list aloud fired "next desktop"). Future mitigation: a confidence / voice-activity gate, or just "stand down" when not actively commanding.

## The principle this points to

**Whenever a deterministic action is low-confidence or unmatched → escalate to the assistant.** This is the bridge between CONTROL mode (fast, deterministic) and ASSISTANT mode (LLM reasoning), and it's what makes the system feel smart rather than brittle. (See the tiered cascade in `overview.md`.)
