# Vox — Feature Registry

> Single source of truth for **every capability** — what works today, what's planned, how the pieces fit, and how to demo each. Update this as features land so we never lose track or let features drift apart.

**Status:** ✅ done · 🚧 in progress · 📋 planned (scheduled) · 💡 idea (someday)

## Working today

| Feature | Status | How to see it | Notes |
|---|---|---|---|
| Wake-word detection | ✅ | `uv run vox` → say **"Hey Jarvis"** | openWakeWord, stock `hey_jarvis` model |
| Local speech-to-text | ✅ | spoken words print after the wake word | faster-whisper `base.en`, on-device, **no API / no key** |
| Mic + wake diagnostic | ✅ | `uv run vox-diagnose` | live per-channel level, wake score, Whisper readback, gain sweep |
| Selectable input device | ✅ | `config.py: input_device` / `vox-diagnose <n>` | handles multi-device / interface setups |
| Modular components | ✅ | architecture | wakeword / stt / io behind swappable interfaces |
| Compute / latency monitoring | ✅ | stats line after each utterance in `uv run vox` | per-stage timing, real-time-factor, CPU%, memory (psutil) |

## In progress / next

| Feature | Status | Milestone / notes |
|---|---|---|
| Custom **"Hey Vox"** wake word | 🚧 | train model → replace `hey_jarvis` (Colab; runbook in `wake-word-training.md`) |
| Open apps by voice | 📋 | **M1** — first real action ("open Safari") |
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
