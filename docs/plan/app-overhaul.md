# App overhaul — branch `app-overhaul` (off `staging`, 2026-11-06)

Working plan + progress log for the long autonomous session. Every item that ships lands in
[`to-test.md`](to-test.md) until the user has tried it by hand.

## The asks (from the user, 2026-11-06)

1. **Its own app, not a browser tab.** Any framework. Apple-quality design, everything lined up,
   settings that make sense. No design carried over from the old dashboard.
2. **Real onboarding.** No cloning the repo, no terminal. Set everything up from scratch.
3. **Performance.** Lighter, faster, more usable. LLM latency (esp. the Claude SDK / subscription
   path), small brain on basic tasks, mic + listening, conversational patterns, workflows.
   *Flag before any language rewrite.*
4. **Point / circle things on screen** (Clicky-style).
5. *(Nice-to-have)* **Know command vs dictation** without "start typing" (Dragon-style).
6. **Agent system** — named agents that can message each other.
7. Work through the outstanding, achievable backlog.

## Decisions

| Decision | Why |
|---|---|
| **Native SwiftUI app** (`app/`, SwiftPM, no Xcode needed) | Lightest possible shell (~5 MB vs Electron's ~200 MB), real macOS look and feel, and the app becomes the *responsible process* for TCC, so the mic/Accessibility prompts say "Vox", not "Terminal". |
| **The app owns the daemon** (spawns `python -m vox`, restarts it, stops it on quit) | One thing to launch. The menu bar icon shows the daemon state. |
| **Engine bootstrap via bundled `uv`** (ComfyUI-Desktop pattern) | No terminal. The first run creates a venv in `~/Library/Application Support/Vox`, with a progress UI. |
| **Data dir becomes configurable** (`VOX_DATA_DIR`; default stays `<repo>/data` when run from a checkout) | An installed app can't write into its own bundle. |
| **Python stays** for the engine (for now) | See the *Language question* below. It goes to the user before any move. |

## Workstreams & status

Legend: ☐ todo · ◐ in progress · ☑ built (→ to-test.md)

### A. Native app
- ☑ SwiftPM app (`app/`), `app/build.sh` (icon, Info.plist usage strings, ad-hoc sign, `--bundle-engine`), offscreen `--snapshot` renderer (fixtures or `live`)
- ☑ Engine supervisor: spawns via `Process()` (TCC attribution), attaches to an already-running engine, survives self-relaunch, crash backoff, console log
- ☑ Menu bar extra: state, type-to-Vox, last reply, Listening / Speak replies, Open / Settings / Quit
- ☑ Main window, all 10 pages: Home · Conversation · Personality · Commands (+ Learning review) · Vocabulary · Rules · Board · Reminders · Memory · Activity
- ☑ Settings (⌘,): 7 tabs, every engine setting re-homed with a plain-English label + caption; unknown keys fall into Advanced → Other
- ☑ Hold-to-talk (Right ⌥)
- ☑ Permission-lag banner (engine reports its own AX/screen permission view in `/api/status`)

### B. Onboarding / packaging
- ☑ `VOX_DATA_DIR` / `VOX_LOG_FILE` (`src/vox/paths.py`); default unchanged from a checkout
- ☑ Onboarding: welcome (install starts) → mic → accessibility → engine → brain (presets, keys saved via `/api/secrets`, live test via `/api/brain/test`) → try it → done. Install path verified in a scratch dir (46 s warm, 0.8 GB).
- ☑ Permission agreement (see banner above)

### C. Performance
- ☑ Small brain latency. **The root cause was not what todo.md §0b thought:** `deepseek-v4-flash` *thinks*
  silently (53 of 58 output tokens on a bare "click submit"). 12% of small-brain calls hit the 800 cap
  on reasoning alone (median 8.3 s, empty answer, then a second call). Replay of 60 real calls
  (`scripts/replay_router.py`): thinking on p50 1.82 s / p90 4.69 s / 2 empty · off p50 0.93 s / p90 1.27 s / 0 empty.
  Off is more reckless on garbled input (guessed a board delete). Haiku 4.5 was no better (p50 0.76 s,
  but guessed deletes too and dropped the `CHAT:` prefix). The thinking budget can't be bounded (the API
  ignores `budget_tokens` / `reasoning_effort`). → New setting `small_brain_thinking` (default **off**)
  plus an automatic thinking-off retry when reasoning eats the whole budget.
  *Follow-up:* destructive BOARD verbs should confirm on a weak card match (code-level safety, not model caution).
- ☑ Claude SDK brain: pre-warmed one-shot client pool + lean options (`setting_sources=[]`, `tools=[]`, no thinking on the
  small brain). Measured on a Haiku router call: 5.36 s (today) → 1.23 s median. One query per client, so no desync is possible.
  Pre-warmed at daemon start. *Not done:* sentence-streaming into TTS for long big-brain answers.
- ☑ CPU: Whisper `float32` + greedy (4.4 → 1.4 CPU-s per utterance, 1.06 → 0.59 s wall, same transcripts, +0.55 GB RAM),
  Kokoro 4 threads, AX-based focus watcher (~7× fewer osascript spawns), bounded mic queues, idle speech gate (off until measured
  on the user's voice). Next: Vosk wake pre-check (the real idle win), smart-turn v3.2, SpeechAnalyzer helper.
- ☑ smart-turn: **found + fixed a double-sigmoid bug** that made every pause score 0.50–0.73 ("complete"). Upgraded to v3.2 with
  reference left-padding. Synthetic test: 7/8 correct (was undiscriminating). Threshold 0.7 → 0.5 (pipecat default). Default stays `vad` until the user tries it.
- ☑ Typed input path (`POST /api/say`, #68), real `mode` in `/api/status`, pause listening (`POST /api/listening`)

### D. ☑ Pointing overlay (#69.2): `point` intent + parser phrases, `POINT:` directive, MCP `point` tool, `overlay.point()` helper
### E. ☑ Command vs dictation: `auto_dictation` (off by default), `src/vox/auto_dictation.py`, exact-only lookup, risk tiers, scratch that / that was a command, 14 unit tests
### F. ◐ Agent messaging: research done (`research/agent-messaging.md`); feature 1 (hook alerts) built; 2–5 are proposals for the user
### G. Backlog
- ☑ Board: several `BOARD:` lines per turn (todo 1b) with a combined reply; deletes refuse a merely-fuzzy card match.
- ☑ Bridge security: JSON-only writes for every route (CSRF).
- ☑ Agent alerts via Claude Code hooks (`/api/agents/event`, research/agent-messaging.md #1).
- ☑ Hold-to-talk (Right ⌥) in Vox.app + `/api/ptt` + capture support.
- ☑ Parser greediness: no-argument commands need ≤ 6 words once polite wrappers are stripped (todo.md carried item).
- ☑ Vision click label sanity check (plain-label requests confirm when the picked badge's label disagrees).
- Learning guardrails: **not changed (trial rule)**. Findings go to the user instead.

## Language question: answer, no rewrite needed
Measured, not assumed (`research/listening-and-stt-2026.md`): the CPU went on Whisper's decode settings
(int8 + beam 5) and on idle mode transcribing every noise, not on Python. Fixing the settings cut per-utterance
CPU by about 3×. LLM latency is network/model time; Python adds nothing measurable. **The one place a different
language pays off** is Apple's on-device SpeechAnalyzer (macOS 26), which is Swift-only. A small Swift STT helper
(PCM in, JSON lines out) would move transcription onto the Neural Engine and give streaming partials. That's an
*optional lane*, not a rewrite. Proposed, not built.

## Log
- 2026-11-06: code review (high) over the whole diff → 10 findings, all fixed: supervisor double-recovery, typed input dropped
  mid-call by the blip gate, point regex hijacking searches, "Vox," prefix losing punctuation, hold-to-talk stuck after
  out-of-order requests (now serialized + 90 s engine-side expiry + release on quit), SDK pool churn on one-off chat
  prompts (warm only recurring prompts; router pinned), dashboard/abort floor checks in text fields, MCP vs engine
  data-dir split in the installed layout, per-utterance settings reads in the text-context pool, duplicate CSRF checks.
- 2026-11-06: research filed: `research/app-onboarding-packaging.md`, `research/command-vs-dictation.md`, `research/agent-messaging.md`.
- 2026-11-06: **security:** the new routes require a JSON content type (a text/plain POST is a CORS simple request any web page can send). Older POST/PATCH routes (`/api/settings`, `/api/commands/...`) have the same gap → fix globally in the security pass.
- 2026-11-06: pushed `pc-controls` → `staging` (5dc65f3), branched `app-overhaul`.
