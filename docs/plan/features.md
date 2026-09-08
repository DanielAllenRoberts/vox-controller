# Vox — Feature Registry

> Single source of truth for **every capability** — what works today, what's planned, how the pieces fit, and how to demo each. Update this as features land so we never lose track or let features drift apart.

**Status:** ✅ done · 🚧 in progress · 📋 planned · 💡 idea (someday)

## Voice pipeline & core

| Feature | Status | How to see it | Notes |
|---|---|---|---|
| Wake detection (pluggable) | ✅ | `uv run vox` → say **"take control"** or **"Hey Vox"** | **Whisper-wake** default (no training, any phrase); openWakeWord backend optional via `wake_backend` |
| Local speech-to-text | ✅ | spoken words print after the wake word | faster-whisper **`small.en`** (int8, on-device) — **no API / no key**; `base.en` for max speed |
| Speech-correction dictionary | ✅ | dashboard → **Dictionary** | "learn a word" — a user replacement map applied to Whisper's output (whole-word, case-insensitive): fixes homophones/proper nouns (clawed→Claude). `vocab.py`. ideas #54 |
| Semantic turn detection | ✅ | `turn_detection="smart_turn"` | **smart-turn-v3** (Whisper-tiny + classifier, ~8MB ONNX) decides end-of-utterance from intonation, not just silence; falls back to fixed-silence VAD |
| Native AEC mic (echo cancel) | ✅/off | `audio_aec=true` | VoiceProcessingIO (AVAudioEngine) cancels Vox's own TTS from the mic; flagged off for speaker use (ducks other audio). ideas #21 |
| Mic self-recovery + watchdog | ✅ | automatic | re-opens the input stream on a stall (device change / Bluetooth switch); clean self-restart if audio never returns |
| Mic + wake diagnostic | ✅ | `uv run vox-diagnose` | live per-channel level, wake score, Whisper readback, gain sweep |
| Selectable input device | ✅ | `config.py: input_device` / `vox-diagnose <n>` | multi-device / interface setups |
| Compute / latency monitoring | ✅ | stats line after each utterance | per-stage timing, real-time-factor, CPU%, memory (psutil) |
| Modular components | ✅ | architecture | wakeword / stt / io behind swappable interfaces |
| Session logging | ✅ | output tee'd to `vox.log` | reviewable log of every session (gitignored) |

## Modes

| Feature | Status | How to see it | Notes |
|---|---|---|---|
| Mode state machine | ✅ | `uv run vox` | idle → control / assistant / dictation → back; multi-phrase detection |
| One-shot from idle | ✅ | "Vox, open Safari" | a single command, then back to idle — same powers as control |
| Control mode (Dragon-style) | ✅ | "take control", then commands | continuous; exits on the sleep phrase |
| Assistant chat mode | ✅ | "Hey Vox" → multi-turn chat | conversation with spoken replies; also runs commands / compose / vision mid-chat |
| Dictation (speak-to-type) | ✅ | "Vox start typing" → click a field → speak → "stop typing" | types at the cursor via clipboard paste; edit keys ("new line", "delete word/line", "undo", **"literally X"**); auto-exits on long pause |
| Switch modes mid-session | ✅ | "Hey Vox" in control / "take control" in assistant | jump between modes without dropping to idle |
| Sleep / quit / restart by voice | ✅ | "stand down" / "quit Vox" / "restart Vox" | restart re-execs to pick up code changes; quit/restart require "vox" + phonetic variants |
| Barge-in (interrupt the AI) | ✅ | "stop" / "go to sleep" **while it's thinking or speaking** | cancels the LLM call mid-flight; killable streaming Kokoro TTS stops mid-sentence. Toggle `barge_in_enabled`. ideas #19 |
| Escalation policy | ✅ | any unrecognized control command | `escalation_mode` `"auto"` (default) sends misses to the brain; `"keywords"` only on a trigger word (ambient-speech guard). ideas #23 |
| Mode sound cues | ✅ | sounds on control / assistant / send / sleep / dictation | audio feedback without watching the terminal |

## macOS control (drive apps by voice)

| Feature | Status | How to see it | Notes |
|---|---|---|---|
| Open / go to (app or site) | ✅ | "open Cursor", "go to GitHub", "open a new YouTube" | app if installed; known site reuses a tab or makes one |
| Web search | ✅ | "search <query>" | explicit search in your browser |
| Switch browser tabs | ✅ | "go to my GitHub tab", "next tab", "move up 3 tabs" | by name (fuzzy), index, or relative — stays in your profile |
| Go back / close tab | ✅ | "go back" / "close tab" | ⌘[ / ⌘W |
| Switch app windows | ✅ | "next window", "switch to my work window" | cycles the frontmost app's windows (⌘`) |
| Switch desktops / Spaces | ✅ | "swipe right/left", "next space", "go to desktop 2" | Ctrl+→/← |
| Cycle an app's windows | ✅ | "cursor window", "next cursor window" | via the Dock icon — crosses Spaces |
| Arc profile / sidebar | ✅ | "profile two", "show tabs" / "hide tabs" | Ctrl+‹n›; clicks Arc's View menu item |
| Chain two commands | ✅ | "open Arc and search this" | runs both halves when both parse |
| Hotword-biased recognition | ✅ | automatic in control mode | nudges STT toward command/app words |
| **Scroll** | ✅ | "scroll down", "scroll up 3", "scroll to the top", "page down" | CGEvent wheel; top/bottom use ⌘↑/⌘↓. Was agent-tier only. ideas #61 |
| **Press a key combo** | ✅ | "press command S", "press escape", "press command shift 4" | CGEvent (<10ms) not AppleScript (~200ms); spoken digits work ("shift four"). ideas #61 |
| **Right / double click** | ✅ | "right click Submit", "double click 14" | by AX label or overlay badge number. ideas #61 |
| **Drag** | ✅ | "drag 3 to 7", "drag Inbox onto Archive" | either side a badge number or a label. ideas #61 |
| **Set a control's value** | ✅ | "set volume to 30", "set theme to dark" | AX-native — sliders/fields/checkboxes set directly; popups press + pick the menu item. ideas #61 |
| Background input delivery | ✅/off | `input_background_delivery` | posts to a pid (CGEventPostToPid) so Vox drives a window **without raising it or moving your cursor**. App-dependent — Electron often ignores posted mouse events. ideas #61 |

## Clicking & the accessibility tree

| Feature | Status | How to see it | Notes |
|---|---|---|---|
| Click a control by label | ✅ | "click Submit", "click the Log in button" | native AX tree (`ax.py`, zero-dep), fast (~77ms miss); **coordinate-click via CGEvent** (reliable on web/Electron where AXPress no-ops); AppleScript fallback |
| Electron/web support | ✅ | "click #general" in Slack | sets `AXManualAccessibility`, presses the nearest pressable ancestor; disambiguation ("Did you mean Alex?") for mis-heard names |
| **Numbered clickable overlay** | ✅ | "show clickable" → **"click 14"** | Dragon-style: a numbered badge on every clickable element (incl. **text boxes**); say the number to click. Coordinate-based, **spans all displays** (Sidecar), non-capturable window, separate helper process. ideas #52 |
| Screen vision ("look at my screen") | ✅ | "what does this say?" / "what's on my screen" | screenshots the screen, asks a vision model, speaks the answer. Needs Screen Recording perm. ideas #18 |
| AX-tree viewer (dashboard) | ✅ | dashboard → **AX Tree** | inspect the focused app's accessibility tree |

## Assistant / LLM

| Feature | Status | How to see it | Notes |
|---|---|---|---|
| Small / big brains (tiered) | ✅ | `small_brain_*` / `big_brain_*` in config | fast/cheap default; emits `[BIG]` to hand complex turns up. Any provider per brain |
| Provider-agnostic | ✅ | config | Claude subscription (SDK/CLI, no key) · Anthropic/OpenAI/DeepSeek API · **local LLM** (Ollama/LM Studio via `llm_base_url`) |
| Conversation continuation | ✅ | ask something open-ended | model tags `[OPEN]`/`[DONE]`; waits patiently on [OPEN] |
| LLM-as-executor | ✅ | "make the font bigger" (no exact command) | escalation **runs** the matching action (action-first, quiet cue) instead of explaining. ideas #12 |
| Compose / rewrite | ✅ | "write me an email about X" / "make this pretty" | composes & types at the cursor; rewrite edits your **selection** in place. ideas #10 |
| Chatter ignore | ✅ | background talk → no response | brain returns `IGNORE` for non-requests |
| Rules (standing instructions) | ✅ | dashboard → **Rules** | always-on preferences injected into every prompt |
| Timers / alarms / reminders | ✅ | "set a timer for 5 minutes", "remind me at 9 to stretch" | Vox-owned scheduler; spoken/chimed; recurring; dashboard **Scheduler** page + voice cancel. ideas #16 |
| Clarifying follow-ups | 🚧 | "set an alarm for 3" → "morning or afternoon?" | plumbing exists (executor `pending`); not all paths use it. ideas #50 |

## Voice output (TTS) & personalities

| Feature | Status | How to see it | Notes |
|---|---|---|---|
| Voice output (macOS `say`) | ✅ | Vox speaks its 🔊 replies | local, instant; speaks replies/questions, quiet on actions. `tts_enabled` / `tts_voice` / `tts_rate` |
| Kokoro neural TTS | ✅ | `tts_engine="kokoro"` | local neural, 54 voices, lazy-loaded with fallback to `say`. `tts.py` is the swap point. ideas #31 |
| Personalities (presets + custom) | ✅ | dashboard → **Personalities** | Posh Butler, Batman, J.A.R.V.I.S., Surfer… + Default (no persona) + your own. ideas #22 |
| In-dashboard persona editing | ✅ | edit (pencil) / view (eye) on a card | `update_custom` + edit dialog (all fields, both voices); read-only full-text view. ideas #41 |
| **Per-persona voice — change any preset's voice** | ✅ | click a card's voice dropdown | picks from your **installed** `say` voices (`/api/voices`); presets saved as an **override** (stay code-defined); applies live on the next reply. (Kokoro picker on cards: 🚧) |

## Memory

| Feature | Status | How to see it | Notes |
|---|---|---|---|
| Tiered memory (core + daily) | ✅ | dashboard → **Memory** | durable always-injected core facts + dated daily notes, recalled by relevance; human-readable Markdown. ideas #27/#28 |
| Auto-capture | ✅ | "remember that…" or salient facts | the assistant saves via a gated `MEMORY[...]` directive. ideas #29 |
| "Dream" consolidation + second-brain RAG | 💡 | — | scheduled dedupe/roll-up + semantic recall still to build; evaluating **MemPalace** (MIT). ideas #28/#55 |

## Command database

| Feature | Status | How to see it | Notes |
|---|---|---|---|
| App/site-scoped command DB | ✅ | dashboard → **Commands** | SQLite store of voice commands scoped by focused app/site; in-memory cache, boot + focus loads. ideas #36 |
| Live editing | ✅ | toggle / add-phrase on the Commands page | edits refresh the running cache (no restart) |
| Runtime resolution | 🚧 | `command_db_enabled` (default off) | the resolver runs but is gated off pending confidence; the loop keeps hardcoded control-plane defaults as a floor |

## Dashboard (Vox Control Center)

| Feature | Status | How to see it | Notes |
|---|---|---|---|
| Web control center | ✅ | "open dashboard" → `127.0.0.1:8765` | React (Vite) app served by a FastAPI bridge; dark-first premium UI, command palette, keyboard shortcuts |
| Overview / status | ✅ | dashboard → **Overview** | running state, active brains, personality, uptime |
| Live conversation feed | ✅ | dashboard → **Conversation** | the running session's turns (ephemeral, in RAM). ideas #43 |
| **Workspace board (kanban)** | ✅ | dashboard → **Board** | Trello-like columns/cards (To Do/Doing/Done); add/move/delete cards, add lists, search; SQLite-backed. Agent read/write tools: 🚧. ideas #51 |
| Token usage + budgets | ✅ | dashboard → **Token Usage** | per-model spend, month-to-date vs a monthly cap (warn/over) |
| Settings | ✅ | dashboard → **Settings** | live-tunable config (TTS engine/voice, turn detection, brains, toggles) |
| Handbook | ✅ | dashboard → **Handbook** | catalog of voice commands/features, generated from the live phrase config. ideas #33 |
| Diagnostics snapshot | ✅ | `GET /api/diagnostics` | runtime snapshot (platform, process, STT, brains, TTS) — API/data, no dedicated page yet |

## Integrations

| Feature | Status | How to see it | Notes |
|---|---|---|---|
| vox-speak MCP (speak-when-done) | ✅ | dashboard → **Integrations** | an MCP server that speaks a coding agent's finished-work announcements through TTS; per-machine setup block. ideas #34 |
| **Silent notification bubble** | ✅ | MCP `notify`, or `python -m vox.bubble "text"` | a card in a screen corner instead of speaking — stays until you click its ✕, never steals focus (non-activating panel). Settings → **Notifications**. ideas #62 |
| **Named agents (identity)** | ✅ | MCP `register_agent` / `whoami` / `list_agents` | agents take a name, so spoken replies become "David here — …" and bubbles are labelled DAVID. Routing *back* to an agent by name is not built. ideas #39 |
| **One voice at a time** | ✅ | `cat data/speaking.lock` while something speaks | cross-process lock so Vox and every agent take turns instead of talking over each other; times out rather than deadlock. ideas #63 |

## In progress / next (see `ideas.md` for detail)

| Item | Status | Notes |
|---|---|---|
| Click-learning loop | 💡 | "click X" not found → auto-show overlay → pick a number → **save phrase→element to the command DB** → resolves directly next time. Ties #14/#24/#36/#52 |
| Board agent tools + drag-drop | 🚧 | `board_add_card`/`board_search` so the brain uses the board mid-conversation; real DnD. #51 |
| Kokoro voice picker on persona cards | 🚧 | say-voice picker shipped; add the Kokoro-voice picker (backend already supports it) |
| Pluggable + streaming STT | 💡 | Vosk grammar-constrained command recognition · streaming partials/live captions · typed-arg command grammar. #53 · `research/dictation-stt-tools.md` |
| Custom-vocab cloud-STT boost | 💡 | the replacement **Dictionary** shipped (see above); remaining is an optional cloud STT (Deepgram/AssemblyAI) with keyword-boosting for acoustically-novel words. #54/#53 |
| MemPalace memory backend | 💡 | evaluate the MIT semantic-memory lib for the second-brain/dream roadmap. #55 |
| Voice → dashboard control | 🚧 | "switch to Batman", "set my budget to ten dollars", "turn on debug". #30 |
| LLM self-edits its persona | 💡 | on request, the assistant rewrites its own persona. #42 |
| Full control access + intent recovery | 💡 | gated tool-calling executor that *does* multi-step tasks. #26 |
| Cross-platform (Windows / Linux) | 💡 | deferred to much later — UIA + Win32 layered window + SendInput behind the same interfaces. #20 |

## Known issues

- **Mic stall after `say` TTS** (`-10863` PaMacCore) — the `say` engine's output can knock out the PortAudio input stream; it self-heals (~3s re-open) but garbles the next utterance. Candidate fixes: proactively re-open the mic after TTS, or use the native VPIO/AEC capture path. Not started.

## Demo / show-off moments

- **"It's fully local"** — STT (faster-whisper) + optional local LLM (Ollama) + Kokoro TTS run offline, no API key.
- **"show clickable" → "click 14"** — numbered overlay on any app, across displays, clicks reliably.
- **The control center** — open the dashboard and watch the conversation feed, board, token spend, and command DB live.
- **Personalities** — switch to Batman, give him any installed voice, and hear it on the next reply.

## Integration notes (keep features working together)

- **Audio contract:** everything internal is **16 kHz mono int16** — wake word and STT share this. New audio features must conform.
- **`onnxruntime` pinned `<1.21`** — newer versions silently zero openWakeWord's feature models.
- **Python pinned 3.12** — ML wheels (ctranslate2 / onnxruntime) don't support 3.14 yet.
- **Clicking is coordinate-based** — `ax.click*` clicks the element's screen center (CGEvent); AX/CGEvent share the global top-left coord space (no flip). AXPress is only a fallback.
- **The overlay is a separate process** — AppKit never runs in the daemon's blocking audio loop (else the window beachballs it).
- **macOS-only today** — the AX/overlay/click/automation layer uses native macOS APIs; the STT/LLM/dashboard/board/command-DB layers are portable.
- **Nothing sensitive committed** — secrets in `.env`, runtime data (`data/*.db`, `vox.log`) gitignored.
