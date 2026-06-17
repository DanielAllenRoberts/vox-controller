# Vox — Feature Registry

> Single source of truth for **every capability** — what works today, what's planned, how the pieces fit, and how to demo each. Update this as features land so we never lose track or let features drift apart.

**Status:** ✅ done · 🚧 in progress · 📋 planned (scheduled) · 💡 idea (someday)

## Working today

| Feature | Status | How to see it | Notes |
|---|---|---|---|
| Wake detection (pluggable) | ✅ | `uv run vox` → say **"take control"** or **"Hey Vox"** | **Whisper-wake** default (no training, any phrase); openWakeWord backend optional via `wake_backend` |
| Local speech-to-text | ✅ | spoken words print after the wake word | faster-whisper `base.en`, on-device, **no API / no key** |
| Mic + wake diagnostic | ✅ | `uv run vox-diagnose` | live per-channel level, wake score, Whisper readback, gain sweep |
| Selectable input device | ✅ | `config.py: input_device` / `vox-diagnose <n>` | handles multi-device / interface setups |
| Modular components | ✅ | architecture | wakeword / stt / io behind swappable interfaces |
| Compute / latency monitoring | ✅ | stats line after each utterance in `uv run vox` | per-stage timing, real-time-factor, CPU%, memory (psutil) |
| Mode state machine (idle / control / assistant) | ✅ | `uv run vox` | wake phrase → mode → back to idle; multi-phrase detection |
| Control mode (Dragon-style) | ✅ | say "take control", then commands | continuous — only exits on the sleep phrase (or Ctrl+C) |
| Open / go to (app or known site) | ✅ | "open Cursor", "go to GitHub", "open a new YouTube" | app if installed; known site **reuses a tab in your current space** or makes one ("open new" forces fresh); unknown → hands off |
| Chain two commands | ✅ | "open Arc and search this" | runs both halves of "X and Y" (only when both parse) |
| Search the web | ✅ | "search <query>" in control mode | explicit web search in your browser |
| Switch browser tabs | ✅ | "go to my GitHub tab" (fuzzy), "next tab", "move up 3 tabs" | by name (fuzzy) or ⌘⌥↑↓ relative — **stays in your profile** |
| Go back | ✅ | "go back" | browser/app back (⌘[) |
| Switch app windows | ✅ | "next window", "switch to my work window" | cycles the frontmost app's windows (⌘`); can't cross macOS Spaces (Accessibility perm) |
| Switch desktops / Spaces | ✅ | "swipe right/left", "next space", "go to desktop 2" | Ctrl+→/← — synonyms: desktop / space / screen / "swipe" (the cross-Space window fix) |
| Cycle an app's windows | ✅ | "cursor window", "next cursor window", "switch cursor" | clicks the app's Dock icon — crosses Spaces, any app |
| Switch Arc profile/space | ✅ | "profile two", "next profile" | Ctrl+<n> (absolute) or ⌘⌥←→ (relative) |
| Show/hide tab sidebar | ✅ | "show tabs" / "hide tabs" / "toggle sidebar" | toggles Arc's sidebar (⌘S) |
| Hotword-biased recognition | ✅ | automatic in control mode | nudges STT toward command/app words ("Cursor" > "Casa") |
| Unknown command → handoff | ✅ | any unrecognized input | says "handing off to the assistant" — the M4 escalation hook |
| Mode sound cues | ✅ | sounds on control / assistant / send / sleep | audio feedback without watching the terminal (macOS sounds; swap for custom) |
| Quit by voice | ✅ | say "quit Vox" (idle or in a mode) | exits the program; "vox" required + phonetic variants so idle speech can't trigger it |
| Restart by voice | ✅ | say "restart Vox" | re-execs the process — picks up code changes without manual kill + rerun |
| Session logging | ✅ | output tee'd to `vox.log` | reviewable log of every session (gitignored) |
| Switch modes mid-session | ✅ | "Hey Vox" in control / "take control" in assistant | jump between modes without dropping to idle first |
| Sleep / deactivate | ✅ | say "stand down" in a mode | matched in transcript text |

## In progress / next

| Feature | Status | Milestone / notes |
|---|---|---|
| Assistant mode (LLM) | 🚧 | state + speech capture done; LLM wiring is **M4** (stubbed for now) |
| Custom **"Vox" phrases** | 🚧 | train models → replace `hey_jarvis`/`hey_mycroft` placeholders (Colab; `wake-word-training.md`) |
| User-chosen assistant name | 💡 | let users name it & reference that name — later feature |
| Package power in watts | 💡 | opt-in `powermetrics` reader (needs sudo) — later |

## Planned (from roadmap)

- 📋 Voice output / TTS — **M2** (macOS `say` → Piper; accent-adaptive later)
- 📋 Modality switching — **M3** (voice/text in × voice/text out; e.g. study mode)
- 📋 Pluggable AI providers + intent parsing — **M4** (provider-agnostic; default Claude Haiku)
- 📋 Teachable rules engine — "whenever I say X, do Y"
- 📋 Tiered intent cascade — rules → fast model → deep model
- 📋 Learning / logging layer — capture every interaction for later training
- 💡 Containerized agentic execution — OpenCode-backed code tasks
- 💡 Remote / phone interface — local-first WebSocket (Tailscale optional)
- 💡 Web UI — terminal-first, browser view of the running daemon (paperclip / OpenClaw style)
- 💡 Personalized fine-tuning — voice + command models tuned to the user

## Demo / show-off moments

- **"It's fully local"** — STT runs offline with no API key (faster-whisper). Pull the network and it still works.
- **The live diagnostic** — `vox-diagnose`'s level bar + real-time wake score is a satisfying visual of the pipeline working.
- *(future)* **Study mode** — type a question in public, hear the answer in your headphones.
- *(future)* **Teach by voice** — "whenever I say deploy, run my deploy script" → persists as a rule.

## Integration notes (keep features working together)

- **Audio contract:** everything internal is **16 kHz mono int16** — wake word and STT share this format. New audio features must conform.
- **`onnxruntime` pinned `<1.21`** — newer versions silently zero openWakeWord's feature models. Don't bump without re-running `vox-diagnose`.
- **Python pinned 3.12** — ML wheels (ctranslate2 / onnxruntime) don't support 3.14 yet.
- **I/O as adapters** — input and output are swappable so modality switching (M3) doesn't require rework.
- **Nothing sensitive committed** — secrets in `.env`, runtime data in a local store; both gitignored.
