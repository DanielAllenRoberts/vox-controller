# Vox — Memory Footprint Analysis

> **Why this doc:** Vox was observed using **~2 GB RAM** while running — a lot for something meant to be a "low running" daemon that "pretty much anyone could run on any computer." This is the measured breakdown of where that memory goes, why, and how to bring it under 1 GB. Measured **2026-06-24** on the dev Mac (Apple Silicon, 16 GB). Related: `issues.md` O6 (disk constraint), O3 (`base.en`→`small.en` for accents).

## TL;DR

- The ~2 GB is **two ML model weights**, not Python: **Kokoro neural TTS (~940 MB)** + **Whisper `small.en` (~840 MB)**. Everything else — the Python interpreter, numpy, FastAPI, all three LLM SDKs, pyobjc — is **~180 MB combined**.
- **Python is not the bottleneck.** ~1.8 GB is model weights inside native C++ backends (CTranslate2, onnxruntime). They'd cost the same RAM in Rust/Swift/Go. The lever is **model choice**, not language.
- **Path to < 1 GB:** TTS engine `kokoro` → `say` (−940 MB) and/or Whisper `small.en` → `base.en` (−460 MB).

## Measured breakdown (the live ~2 GB)

| Component | RAM | When it's resident |
|---|---:|---|
| **Kokoro neural TTS** (`kokoro-onnx`, ONNX Runtime) | **~940 MB** | Lazy-loaded on the **first spoken reply**, then cached for the process lifetime. Only active because `tts_engine` was set to `"kokoro"` at runtime (see below). |
| **Whisper `small.en`** (faster-whisper / CTranslate2, int8) | **~840 MB** | **Always** — one model instance serves both wake-word detection *and* transcription. |
| Python + numpy + sounddevice + FastAPI/uvicorn + anthropic/openai/claude-agent-sdk + pyobjc | ~180 MB | Always (the entire non-model "glue" layer). |
| **Total** | **≈ 2.0 GB** | matches the observed figure |

**Second copy in the MCP process:** `mcp/vox_speak_server.py` follows `tts_engine` via `mcp_tts_engine="system"`, so when the IDE assistant speaks out loud it loads its **own** ~900 MB Kokoro in a separate process. (Idle, before it has spoken, it's only ~4 MB.)

### The hidden trigger: a runtime override

`config.py` ships lean defaults — `tts_engine="say"` (the free macOS voice, 0 MB extra) and `wake_backend="whisper"` (reuses the one Whisper model, no second model). But the **dashboard writes runtime overrides** to `data/settings.json` (gitignored), and that file had:

```json
{ "tts_engine": "kokoro", ... }
```

So the live daemon loads Kokoro even though the code default wouldn't. This is why the footprint was higher than the source defaults suggest — the override isn't visible in `config.py`.

## Why it's not a Python problem

| Layer | RAM | Language-dependent? |
|---|---:|---|
| Model weights (Whisper + Kokoro) | ~1.8 GB | **No** — native C++ (CTranslate2, onnxruntime). Same size in any host language. |
| Python interpreter + libraries | ~180 MB | Partly — a Rust/Swift rewrite might save ~100 MB here. |

A full rewrite would cost months, lose the best-in-class Whisper/wake-word/TTS ecosystem, and reclaim only ~100 MB while the models — the actual 90% — stay identical. The project's own `overview.md` decisions log already reached this conclusion ("performance-critical inference runs in native backends … glue-language overhead is negligible"); these measurements confirm it. **Optimize model choice and lazy-loading, not the language.**

## Reduction levers (measured)

Per-tier Whisper cost (apples-to-apples, int8, one process each):

| Whisper model | Disk | RAM added |
|---|---:|---:|
| `tiny.en` | ~75 MB | ~325 MB |
| `base.en` | 141 MB | ~375 MB |
| **`small.en`** (current) | 591 MB | **~836 MB** |

Note the **~300 MB fixed floor** even for `tiny.en` — that's the inference libraries themselves (CTranslate2 + the Silero VAD model that `vad_filter=True` loads via onnxruntime + PyAV). Unavoidable while using faster-whisper; not worth touching (`vad_filter` prevents hallucinations).

TTS:

| TTS engine | RAM added | Notes |
|---|---:|---|
| **`say`** (macOS built-in) | **0 MB** | Subprocess to the OS; premium voices sound good. The code default. |
| `kokoro` (neural) | ~940 MB | Nicer voice; lazy-loaded after first speak. |

**Kokoro can't be cheaply shrunk.** `kokoro_onnx` creates its `InferenceSession` with no options (greedy default arena). Tested disabling onnxruntime's CPU memory arena (`enable_cpu_mem_arena=False`, `enable_mem_pattern=False`): only **−115 MB** (940 → 823). The bulk is the model graph in memory, not the arena. Realistically it's **"neural voice OR small footprint"** until/unless we ship a quantized Kokoro model.

## Footprint by combination

| Config | Footprint | Trade |
|---|---:|---|
| `say` + `base.en` | **~550–600 MB** ✅ | Lightest; "runs on anything." Slightly lower accent accuracy, macOS voice. |
| `say` + `small.en` | ~1.0 GB | Best transcription; macOS voice. Right at the line. |
| `kokoro` + `base.en` | ~1.5 GB | Keeps neural voice; trims ~460 MB. |
| `kokoro` + `small.en` (today) | ~2.0 GB | Both quality upgrades; heaviest. |

## Recommendation

Ship **`say` + `base.en` as the defaults** (~580 MB) so the "anyone can run it" promise holds out of the box, and expose **Kokoro** and **`small.en`** as opt-in *quality upgrades* in the dashboard for users with RAM to spare.

To apply:
- `data/settings.json`: `tts_engine` `"kokoro"` → `"say"` (personal runtime setting; reversible in the dashboard anytime).
- `config.py`: default `whisper_model` `"small.en"` → `"base.en"`.

Both are reversible and low-risk; each is a real quality/footprint trade the user owns.

## Future ideas (keep quality under budget)

- **Quantized Kokoro** (int8 ONNX) — could drop neural TTS toward ~300–450 MB, letting the nice voice fit the budget. Quality needs validation.
- **Unload-when-idle** — drop the Kokoro session from RAM after N minutes of no speech, reload lazily on next speak (trades a reload pause for ~900 MB back while idle).
- **Dashboard "Lite / Quality" preset** — one toggle that flips `tts_engine` + `whisper_model` together, with the live footprint shown next to each.
- **Surface live RSS** in the dashboard's diagnostics so the cost of each toggle is visible.

## How to reproduce these numbers

Per-component attribution and per-model comparison were measured by importing exactly what the daemon imports and reading `psutil` RSS after each step (model weights, Kokoro session, etc.) in the project venv. To re-measure RSS of the live daemon: `ps -o rss= -p <pid>` (KB) while Vox runs, before and after its first spoken reply (to capture Kokoro's lazy load).
