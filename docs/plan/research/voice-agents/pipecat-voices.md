# Pipecat — Voices / TTS research

Scope: how Pipecat (https://github.com/pipecat-ai/pipecat, docs.pipecat.ai) does text-to-speech, which providers it supports, the base TTS abstraction, and how that maps back to improving Vox (currently macOS `say`). Researched 2026-06-18.

---

## 1. How TTS works in Pipecat (the abstraction)

Pipecat is a frame-based streaming pipeline. TTS is just one processor in the pipeline; all providers subclass a common base in `src/pipecat/services/tts_service.py`.

**Core classes:**
- `TTSService` — base class. Handles text aggregation (sentence vs token), filtering, audio generation, frame management. Subclasses implement the abstract `run_tts(text)` coroutine which **yields `TTSAudioRawFrame`** chunks (raw PCM) as they are synthesized — i.e. streaming is built into the contract.
- `WebsocketTTSService` — base for providers that stream over a persistent websocket (Cartesia, ElevenLabs, Rime, etc.).
- `InterruptibleTTSService` — handles interruptions by **reconnecting** the websocket (`_disconnect()` / `_connect()`) when cut off mid-utterance.
- Deprecated: `WordTTSService`, `WebsocketWordTTSService` (word-timestamp handling folded into the base).

**Frame lifecycle per utterance:**
- `TTSStartedFrame` → one or more `TTSAudioRawFrame` (PCM chunks) → `TTSStoppedFrame`.
- Audio is managed via per-synthesis "audio contexts" (queues that preserve ordering) drained by `_audio_context_task_handler()`.

**Word timestamps** (used for accurate transcripts + precise interruption cut points):
- `start_word_timestamps()` sets a PTS baseline; `add_word_timestamps()` queues word/time pairs; `_add_word_timestamps()` emits `TTSTextFrame`s aligned to audio. Providers that return word boundaries (Cartesia WS, ElevenLabs WS, Rime WS) feed this; others don't.

**Voice / settings config (the important pattern for Vox):**
- Modern: each service has a nested `Settings` dataclass, e.g. `CartesiaTTSService.Settings(voice="<voice_id>")`, `KokoroTTSService.Settings(voice="af_heart", language=Language.ES)`.
- Runtime changes: push a `TTSUpdateSettingsFrame(delta=TTSSettings(...))` into the pipeline (you can change voice/model mid-session).
- Deprecated: `set_voice()` / `set_model()` methods.
- `language_to_service_language()` maps Pipecat `Language` enums to each provider's own language codes.
- Output is auto-resampled to the pipeline's configured sample rate, so providers with different native rates interoperate.

**Takeaway:** the abstraction is "a coroutine that streams PCM frames + optional word timestamps, plus a `Settings` object for voice/model." Vox's `say` wrapper is the same shape minus streaming — so this maps cleanly onto Vox if we ever want a pluggable TTS layer.

---

## 2. Interruption / barge-in (most relevant to Vox's weak spots)

This is handled at the **pipeline** level, above the TTS service, and is the part Vox is missing:

- **VAD** (default: **Silero VAD**, open-source, runs locally on CPU, minimal overhead) detects user speech start/stop.
- On speech start, a *turn start strategy* emits a `UserStartedSpeakingFrame` and (if it decides to interrupt) a `StartInterruptionFrame`.
- `StartInterruptionFrame` propagates and tells the TTS service + output transport to **stop synthesis and flush all queued audio frames immediately**; `_handle_interruption()` clears text aggregation, pending frames, and resets word timestamps. Websocket services additionally reconnect.
- **Interruption strategies** gate *when* speech counts as an interrupt (avoids "yeah"/"mm-hmm" backchannel false-cuts):
  - `MinWordsInterruptionStrategy` (min words) and volume-based strategies. **Deprecated since v0.0.99** → replaced by `pipecat.turns.user.MinWordsUserTurnStartStrategy` passed via `PipelineTask(turn_start_strategies=[...])`.

**The bot-hears-itself problem (Vox's #2/#3) — Pipecat's answers:**
1. **Acoustic Echo Cancellation (AEC)** — when using Daily's transport, AEC is done at the media-server/WebRTC layer (browser/Daily handles it). There is **no pure-Python local AEC** in the framework; for local/non-WebRTC setups this is a known gap (issues #188 "Interrupted by itself when speaker on", #670 "Echo cancellation").
2. **Krisp audio filters** — pluggable input filters that strip noise + background/non-primary voices *before* STT and VAD see them:
   - `KrispFilter` (deprecated since v0.0.94) → **`KrispVivaFilter`** (`pipecat.audio.filters.krisp_viva_filter`). Krisp VIVA = "voice isolation": only the intended speaker's voice passes through, so ambient/speaker audio doesn't trigger VAD/STT. Commercial Krisp SDK (license required); example: `examples/foundational/07p-interruptible-krisp.py`.
3. **`STTMuteFilter`** (`pipecat.processors.filters.stt_mute_filter`) — mutes STT input during configurable windows (e.g. while the bot is speaking, or during the first bot turn). This is the simplest "don't transcribe yourself" lever and is essentially **audio ducking**: cheap, no AEC, but it *disables barge-in* during the muted window (user speech in that window is lost).

**Direct Vox mapping:** Pipecat solves Vox's exact three weak spots with (a) `StartInterruptionFrame` to kill in-progress TTS, (b) a Krisp-style voice-isolation input filter so the bot doesn't transcribe itself/ambient, and (c) word-count/volume turn-start strategies to make barge-in reliable. Vox can borrow the *architecture* even without adopting Pipecat: an input filter stage before VAD/STT, a "stop TTS now" signal, and a min-words gate.

---

## 3. TTS providers supported (enumerated)

**Pipecat-maintained (mostly API/cloud):** Async, AWS Polly, Azure, Camb AI, **Cartesia**, **Deepgram**, **ElevenLabs**, Fish Audio, **Google**, Gradium, Groq, Hume, LMNT, Mistral, Neuphonic, NVIDIA (Nemotron Speech), **OpenAI**, **Rime**, Smallest AI, Soniox, Speechmatics, xAI.
**Local/open-source (maintained):** **Kokoro**, **XTTS** (Coqui).
**Built-in (no extra install):** **Piper** (local), Inworld, MiniMax, Sarvam.
**Community-maintained:** Deepdub, Lokutor, Murf AI, Pipecat TTS Cache, Respeecher, Rumik AI, Simplismart, SLNG, Supertonic, Typecast, Uplift AI, Voice.ai.

> Note: **PlayHT** is not currently a first-class maintained service (referenced historically in issues, e.g. #950, but not in the current supported-services list). **Orpheus** and **Sesame CSM** are **not natively supported** — open requests/discussions only (issues #1445 "Kokoro, Orpheus, and CSM Support", #4558 "CosyVoice 3 and Sesame CSM"). They'd need a custom `TTSService` subclass (community CosyVoice attempts hit silences / zero audio chunks).

### Notable providers — detail

| Provider | Type | Streaming | Word timestamps | Latency / quality | License / cost |
|---|---|---|---|---|---|
| **Cartesia** (Sonic) | API | WS (`CartesiaTTSService`) + HTTP | Yes (WS) | ~sub-100–150ms TTFB, top-tier realtime quality; default model `sonic-3.5` | Commercial, usage-priced |
| **ElevenLabs** | API | WS + HTTP | Yes (WS) | Very low latency (Flash/Turbo models), best-in-class quality | Commercial, per-char; pricier |
| **Rime** | API | WS (`RimeTTSService`, recommended) + HTTP | Yes (WS) | Low latency, conversational/natural; built for realtime | Commercial |
| **Deepgram** (Aura) | API | Yes | — | Low latency, solid quality | Commercial |
| **OpenAI** | API | HTTP streaming | No | Good quality, higher latency than Cartesia/11Labs | Commercial |
| **Azure / Google / AWS Polly** | API | Yes | Varies | Enterprise neural voices, moderate latency | Commercial |
| **Kokoro** | **Local** (ONNX Runtime) | Yes (async incremental) | No | Runs on CPU; good quality for size; eliminates network latency | Apache-2.0 model; free/offline |
| **Piper** | **Local** (built-in) | (inference-based) | No | Fast, lightweight; GPU optional (`use_cuda=True`); modest quality | **GPL** (license caution for distribution) |
| **XTTS** (Coqui) | **Local / self-host** | Yes | No | High quality + voice cloning; heavier (GPU recommended) | Coqui Public Model License (non-commercial restrictions — caution) |

---

## 4. Local / offline TTS paths (the part Vox cares about)

Three fully-local, no-API-key options, all of which auto-resample to the pipeline rate:

1. **Kokoro** (`KokoroTTSService`)
   - Install `pipecat-ai[kokoro]` → pulls `kokoro-onnx>=0.5.0`. Runs entirely via **ONNX Runtime on the host**, no network/keys after first download.
   - Models auto-download to `~/.cache/pipecat/kokoro-onnx/`: `kokoro-v1.0.onnx` + `voices-v1.0.bin` (or supply `model_path`/`voices_path`).
   - Voices like `af_heart`; multi-language (EN US/UK, ES, FR, HI, IT, JA, PT, ZH).
   - Streaming, TTFB metrics. **Best balance of quality + simplicity for a local mac path.** Apache-2.0 → safe to ship in an open-source repo.

2. **Piper** (`PiperTTSService` local, or `PiperHttpTTSService` against a `base_url` server)
   - Built-in (no extra dep for core). Fully local/offline. Voices like `en_US-ryan-high`. GPU via `use_cuda=True`.
   - **GPL-licensed** — a real consideration for a public/open-source Vox distribution. Lower quality than Kokoro but very fast/light.

3. **XTTS** (`pipecat-ai[xtts]`, Coqui)
   - Highest quality + **voice cloning**, but heavier (GPU-class), and the Coqui model license has **non-commercial restrictions** — license-risky for an open-source download. Probably overkill for Vox.

---

## 5. Which would best replace/augment macOS `say` for Vox

Vox is local-first, macOS, open-source, hands-free. Recommendation order:

1. **Kokoro (local ONNX)** — best default upgrade over `say`. Fully offline, Apache-2.0 (clean for public repo), CPU-runnable on a Mac, streaming, much more natural than `say`. No API keys, no per-use cost, no privacy concerns. This is the strongest "replace `say`" candidate.
2. **Keep `say` as the zero-dep fallback**, add Kokoro as the quality tier — mirrors Vox's existing small/big tiering philosophy.
3. **Cartesia or Rime (API) as an optional "cloud voice" tier** — if Vox wants best-in-class latency/quality and is willing to take a network dependency + cost. Cartesia Sonic has the lowest realtime latency and word timestamps; Rime is conversational. These are the providers Pipecat itself leans on for production realtime.
4. **Avoid Piper for distribution** (GPL) and **XTTS** (non-commercial license, heavy) unless those tradeoffs are acceptable.

**Bigger win than the voice itself:** adopt Pipecat's *interruption architecture*, which directly fixes Vox's named weak spots:
- A **Krisp-style voice-isolation input filter** (or at minimum an `STTMuteFilter`-style duck) *before* VAD/STT → stops Vox transcribing its own TTS / ambient audio (fixes #2). Note Pipecat has **no pure-local AEC**; Krisp VIVA is commercial. For a free local path, ducking/STT-mute-while-speaking is the pragmatic first step.
- A **"stop TTS now" interrupt signal** (`StartInterruptionFrame` analog) so a new command can cut off the *spoken reply*, not just an in-progress LLM call (fixes #1). With `say` this means killing the `say` subprocess on detected barge-in.
- A **min-words / volume turn-start gate** (`MinWordsUserTurnStartStrategy` analog) so barge-in only fires on real commands, not backchannel/noise (fixes #3).

---

## Sources
- https://docs.pipecat.ai/server/services/supported-services
- https://docs.pipecat.ai/server/services/tts/kokoro
- https://docs.pipecat.ai/server/services/tts/piper
- https://docs.pipecat.ai/server/services/tts/cartesia
- https://docs.pipecat.ai/deployment/pipecat-cloud/guides/krisp-viva
- https://reference-server.pipecat.ai/en/latest/api/pipecat.audio.interruptions.html
- https://reference-server.pipecat.ai/en/latest/api/pipecat.audio.filters.krisp_filter.html
- https://reference-server.pipecat.ai/en/latest/api/pipecat.processors.filters.stt_mute_filter.html
- https://github.com/pipecat-ai/pipecat (README + src/pipecat/services/tts_service.py)
- GitHub issues: #188, #670, #950, #1445, #4558 (echo cancellation, Orpheus/CSM support)
