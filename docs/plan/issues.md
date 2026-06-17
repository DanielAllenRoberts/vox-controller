# Vox — Issues Log

> Running log of problems we hit and how they were resolved, so nothing gets lost. Newest first.
> Status: 🔴 open · 🟡 partial / mitigated · ✅ resolved. (Started **2026-06-17** — day one, so most dates are the same.)

## Open / known limitations

| # | Date | Issue | Status | Notes |
|---|------|-------|--------|-------|
| O1 | 2026-06-17 | Can't interrupt Vox's **spoken** reply (talk over the TTS) | 🔴 | Needs acoustic echo cancellation (AEC) so Vox doesn't hear itself — see `ideas.md` #21. Barge-in (#19) only covers *LLM-call* interruption, where Vox is silent. |
| O2 | 2026-06-17 | Echo/feedback when using speakers (no headphones) | 🟡 | `mic.flush()` after TTS stops the *feedback loop*; true talk-over still needs AEC (#21, native macOS Voice Processing). |
| O3 | 2026-06-17 | Wild mis-transcriptions of short phrases ("go to sleep" → "courtesy") | 🟡 | Accent + short utterance. Upgraded `base.en` → `small.en` to reduce; can't catch every garble. |
| O4 | 2026-06-17 | Abandoned barge-in call still finishes in the background | 🟡 | Python can't kill a thread; a quick *action* it was about to run may still complete. Slow calls (chat/compose/vision) abandon cleanly. |
| O5 | 2026-06-17 | Arc "favorites"/pinned tabs outside the current space aren't reused | 🟡 | `tabs of front window` spans profiles (jumps you) so we stay current-space-only. Reaching favorites safely needs probing Arc's scripting model. |
| O6 | (ongoing) | Disk ~98% full (~4.5 GB free) | 🔴 | Be frugal with deps/models. `small.en` took ~590 MB. |
| O7 | 2026-06-17 | **External audio (a video on the speakers) is transcribed and triggers commands/LLM** | 🟡 | Root cause: no echo cancellation — the mic hears *all* system + room audio. Mitigated by a single-word/filler gate before escalation, and now by **keyword-gated escalation** (`escalation_mode="keywords"`, ideas #23) — only utterances with a trigger word ("write", "vox", "make this"…) reach the brain, so ambient speech is ignored. The real fix is **AEC** (#21, native macOS Voice Processing cancels all speaker output incl. video). Headphones avoid it today. |
| O8 | 2026-06-17 | Barge-in (interrupt the LLM) feels unreliable | 🟡 | Logic is correct, but fast Haiku calls finish before you can speak, and ambient audio floods the interrupt-listener. Firms up with AEC (#21) + reserving barge-in for slow calls. |

## Resolved

| Date | Issue | Cause | Fix |
|------|-------|-------|-----|
| 2026-06-17 | Couldn't cut off a wrong LLM handoff with a new command (had to wait for the response) | Barge-in only listened for *stop* phrases mid-call | Mid-call, a clear command / mode-switch now cancels the LLM and runs instead (control + assistant); chatter/fuzzy speech is still ignored so a video doesn't thrash it |
| 2026-06-17 | Single words / fillers ("and", "uh") from background audio triggered the LLM | No length/noise gate before escalation | Ignore 1-word and all-filler utterances in control mode (unless answering a clarification) |
| 2026-06-17 | SDK "Reached maximum number of turns" (chat & vision) | `max_turns` cap too tight (1 / 4) | Raised to 6 (chat) / 8 (vision) — ceilings, bounded by the 45s/90s timeouts |
| 2026-06-17 | Vox "stops listening", goes dead-quiet, restart-by-voice ignored | Loop hung on a call with no timeout, or the mic stream silently died | Self-healing mic stream (restart on 3s stall) + timeouts on every blocking call (SDK 45s, vision 90s, AppleScript 20s, TTS 30s) |
| 2026-06-17 | Restart-by-voice not working | Mis-transcribed ("vox restart", "restart fox") — no matching variant | Added phonetic/word-order variants to `restart_phrases` |
| 2026-06-17 | Poor recognition of the user's accent on short commands | `base.en` Whisper model too weak | Upgraded to `small.en` (pre-cached to avoid restart-interrupted downloads) |
| 2026-06-17 | Mic feedback loop — Vox heard & re-processed its own TTS | Mic queue kept filling during the blocking `say`; backlog processed as "speech" | `mic.flush()` after every spoken reply |
| 2026-06-17 | Chatter filter ignored *real* questions | `IGNORE` instruction too aggressive | Made it conservative — a question is never chatter; when unsure, don't ignore |
| 2026-06-17 | "Write me X" asked *where* to write | Brain didn't know `TYPE` inserts at the cursor | Prompt: TYPE always inserts at the cursor, never ask |
| 2026-06-17 | Screen-vision descriptions vague/wrong (saw "Finder", not the real app) | Downscaled too hard (1024px) + ran on the small brain | 1568px + big brain (Opus) for `look` |
| 2026-06-17 | "go to sleep" not recognised ("go ahead and sleep") | Missing phrase variant | Added variants to `sleep_phrases` |
| 2026-06-17 | Idle one-shot fired on ambient noise ("CursorArc…") | Hotword list began with "vox", so noise regurgitated it and tripped the one-shot | Removed "vox" from `command_hotwords` |
| 2026-06-17 | Greedy "switch X" matched whole sentences (no escalation) | `app_cycle` regex captured to end-of-line | Tightened to 1–2 app-like words + filler reject; also escalate to the brain when a deterministic command *fails* |
| 2026-06-17 | Model download appeared to "stop the system" | Repeated restarts interrupted the `small.en` download before it finished | Pre-downloaded/cached it once in the background |
| (pre) | openWakeWord scored 0.000 on all audio | `onnxruntime` ≥ 1.21 silently zeros the feature models | Pinned `onnxruntime>=1.17,<1.21` |
| (pre) | Tab reuse jumped to another Arc profile | `tabs of front window` spans profiles | Reuse only tabs in the current space |
| (pre) | Hallucinated commands on silence/noise | No VAD + hotwords biasing toward the command list | `vad_filter=True` + trimmed hotwords to proper nouns only |
| (pre) | Dictation dropped spaces ("justwanttotest") | `keystroke` injects too fast | Switched to clipboard paste |
