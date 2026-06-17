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
| Dictation (speak-to-type) | ✅ | "Vox start typing" → click a field → speak → "stop typing" | types at your cursor (frontmost app); "backspace"/"new line"/"delete" keywords; Tink/Sosumi start/stop sounds; auto-exits on a long pause (toggle `dictation_exit_on_silence`) |
| Assistant chat (LLM) | ✅ | "Hey Vox" → multi-turn chat | **provider-agnostic small/big brains**: Claude subscription (SDK/CLI, no key) · Anthropic/OpenAI/DeepSeek API · **local LLM** (Ollama/LM Studio via `llm_base_url`). Small brain answers and defers complex turns to the big brain (`[BIG]`). Keeps context until "stand down". ideas #17 |
| Big brain / small brain (tiered models) | ✅ | set `small_brain_*` / `big_brain_*` in `config.py` | small = fast/cheap default (e.g. Haiku) for chat + command execution; big = powerful (e.g. Opus on Claude Max) — the small brain emits `[BIG]` to hand complex turns up. Each brain is any provider. ideas #17 |
| Local / offline LLM | ✅ | brain `provider="openai"` + `llm_base_url="http://localhost:11434/v1"` | run a brain on a local OpenAI-compatible server (Ollama, LM Studio) — a fully offline assistant |
| Conversation continuation (LLM-judged turn-taking) | ✅ | "Hey Vox", then ask it something open-ended | The model tags each reply **[OPEN]** (expects you to reply) or **[DONE]** (natural close); on [OPEN] Vox waits patiently instead of dropping to idle. No hand-tuned heuristic — a timer remains only as a safety cap. Tag is stripped before display |
| One-shot command | ✅ | "Vox, open Safari" (from idle) | runs a single command without entering control mode |
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
| Unknown command → LLM escalation | ✅ | any unrecognized control command | a command that doesn't parse is sent to the assistant (LLM) and its answer is spoken — ask questions mid-commands without leaving control mode |
| Mode sound cues | ✅ | sounds on control / assistant / send / sleep | audio feedback without watching the terminal (macOS sounds; swap for custom) |
| Quit by voice | ✅ | say "quit Vox" (idle or in a mode) | exits the program; "vox" required + phonetic variants so idle speech can't trigger it |
| Restart by voice | ✅ | say "restart Vox" | re-execs the process — picks up code changes without manual kill + rerun |
| Session logging | ✅ | output tee'd to `vox.log` | reviewable log of every session (gitignored) |
| Switch modes mid-session | ✅ | "Hey Vox" in control / "take control" in assistant | jump between modes without dropping to idle first |
| Sleep / deactivate | ✅ | say "stand down" in a mode | matched in transcript text |

## In progress / next

| Feature | Status | Milestone / notes |
|---|---|---|
| LLM text commands | 🚧 | "write this" / "make this pretty" — compose/clean text via the LLM (builds on chat + dictation) |
| LLM-as-executor (runs commands, not just explains) | 🚧 | control-mode escalation hands the utterance to the **small brain**, which runs the matching Vox action (action-first, quiet cue) instead of saying "I can't". Provider-agnostic — works on your Claude subscription, an API, or a local LLM (no native tool-calling needed). ideas #12 |
| Action-first / silent success | 💡 | execute with just a sound cue; speak only when ambiguous or asked — seamless; ideas #13 |
| Self-wiring command learning | 💡 | capture LLM-resolved fallbacks → **learned rules** (instant next time), wired up in the background; ideas #14–15 |
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
