# LiveKit Agents — TTS / Voices Research

Scope: ONE topic — how LiveKit's voice-agent framework (`livekit/agents`) does
text-to-speech and voices. Focus on the TTS abstraction, the provider/engine
roster, local/offline paths, voice selection, and how interruption interacts
with TTS playback. Every finding is framed back toward improving **Vox** (our
local macOS hands-free assistant that currently speaks via the `say` command).

Sources are listed at the bottom.

---

## 1. The TTS abstraction (the part worth copying)

LiveKit does NOT bake any single TTS engine in. It defines a **base `TTS`
class** in `livekit-agents/livekit/agents/tts/tts.py` and every provider is a
thin plugin that subclasses it. This is the single most valuable structural
idea for Vox: a pluggable `TTS` interface so `say` is just one backend among
many.

Key classes / methods:

- **`TTS`** — abstract base. Exposes two synthesis modes:
  - `synthesize(text) -> ChunkedStream` — one-shot ("non-streaming"): give it a
    full string, get audio frames back.
  - `stream() -> SynthesizeStream` — incremental ("streaming"): you `push_text(token)`
    as the LLM emits tokens, `flush()` at sentence boundaries, `end_input()` at
    the end. Audio starts coming back before the full text exists.
- **`TTSCapabilities`** — a small struct each plugin sets, with:
  - `streaming: bool` — does the provider support websocket/incremental synth?
  - `aligned_transcript: bool` — does it return word-level timing?
- **`ChunkedStream`** — wraps chunked-HTTP synthesis; buffers input, has retry
  logic, emits `SynthesizedAudio` frames via an async iterator, auto-collects
  latency metrics.
- **`SynthesizeStream`** — persistent connection; segmented output where each
  `flush()` is one synth segment and emits its own metrics.
- **`AudioEmitter`** — coordinates raw bytes -> `rtc.AudioFrame`: `push(data)`,
  `start_segment()` / `end_segment()`, attaches timing + timed-transcript.
- **Adapter pattern** — `_ChunkedStreamFromStream` (a.k.a. `StreamAdapter`)
  lets a streaming-only provider expose the non-streaming API too, so the rest
  of the pipeline never special-cases a provider. The whole point: a uniform
  surface regardless of engine.

**Takeaway for Vox:** define a `TTS` protocol with `speak(text)` plus an
optional streaming `push_text/flush` path and a `capabilities.streaming` flag.
Make `say` the default backend; add Kokoro/Piper backends later without
touching the assistant loop. This is exactly LiveKit's shape and it's small.

---

## 2. Provider roster (40+ plugins)

LiveKit splits TTS into two tiers:

### A. "LiveKit Inference" — curated managed API models (their billing)
- **Cartesia** — Sonic family (`sonic`, `sonic-2`, `sonic-3`, `sonic-3.5`, `sonic-turbo`)
- **Deepgram** — Aura / Aura-2
- **ElevenLabs** — Eleven Flash / Turbo / Multilingual
- **Inworld** — Inworld-TTS v1 / 1.5 / 2
- **Rime** — Arcana / Coda / Mist / MistV
- **xAI** — TTS-1

### B. Open-source plugins (you bring your own API key / endpoint)
40+ plugins. Named in docs/source: Amazon Polly, Azure AI Speech, Google Cloud
(+ Gemini), OpenAI, ElevenLabs, Deepgram, Cartesia, Rime, Inworld, Groq, Hume,
LMNT, MiniMax, Mistral AI, Murf, Neuphonic, NVIDIA, Resemble, Respeecher,
Sarvam, SimpliSmart, Slng, SmallestAI, FishAudio, Gnani, Gradium, **Kokoro**.

Notably the classic open-source local engines the prompt asked about —
**Piper, Coqui/XTTS, Orpheus, Sesame/CSM** — are NOT first-class LiveKit
plugins. The only local-model plugin shipped is **Kokoro**, and even that is
done via the OpenAI plugin (see §4). So LiveKit's "local" story is narrower
than the open-source TTS landscape; it leans on the OpenAI-compatible-endpoint
trick rather than per-engine plugins.

### Notable providers — API vs local, streaming, latency, cost

| Provider | Type | Streaming | TTFB / latency | Quality | Cost (approx) |
|---|---|---|---|---|---|
| **Cartesia Sonic** | API | Yes (ws) | ~40ms model / <100ms TTFB target (188ms P50 in 3rd-party benchmarks) | Very good, real-time-first | ~$0.031/min |
| **ElevenLabs Flash v2.5** | API | Yes (ws) | ~75ms | Best-in-class naturalness | ~$0.05/1k chars |
| **Deepgram Aura-2** | API | Yes | ~90ms optimized (313ms P50 in benchmarks) | Good, enterprise-tuned | ~$0.030/1k chars |
| **OpenAI TTS** | API | Yes | higher (~hundreds ms) | Good, expressive | usage-based |
| **Rime** | API | Yes | low | Good, conversational | usage-based |
| **Azure / Google / AWS Polly** | API | Yes | moderate | Good, many langs/voices | usage-based |
| **Kokoro (82M)** | **LOCAL / open-weight** | Yes (chunked) | ~80ms TTFB on local GPU | Good for size; 6–9 langs | self-host only (~$0.65/1M chars amortized) |

Caveat: latency numbers vary wildly by benchmark/conditions; treat as
order-of-magnitude. For Vox the relevant axis is **local vs cloud**, not the
~30ms differences between cloud vendors.

---

## 3. How voices are selected / configured

Two-part descriptor: **model + voice id**, e.g.
- `cartesia/sonic-3:9626c31c-bec5-4cca-baa8-f8ba9e84c8bc`
- `deepgram/aura-2:apollo`

In plugin form it's constructor args, e.g. `cartesia.TTS(model="sonic-3", voice="<id>")`
or for the local Kokoro case `openai.TTS(base_url=..., model="kokoro", voice="af_alloy")`.

So a voice = (engine, model-version, voice-id). This maps cleanly onto Vox: the
`say` voice "Daniel" is just `voice="Daniel"` under an implicit `model="say"`.

---

## 4. The fully-local / offline path

LiveKit's offline TTS recipe is **the OpenAI-compatible-endpoint trick**, not a
dedicated local plugin:

1. Run **Kokoro-FastAPI** (open-weight Kokoro 82M wrapped in an OpenAI
   `/v1/audio/speech`-compatible server). Default `http://localhost:8880/v1`.
2. Point the **OpenAI plugin** at it:
   ```python
   openai.TTS(base_url="http://localhost:8880/v1", model="kokoro", voice="af_alloy")
   ```
3. That's fully offline once the model is cached. 50+ voices / 9 languages,
   voice-mixing, chunked streaming, ~80ms TTFB on GPU, runs on CPU too (slower).

Docker images (e.g. `hwdsl2/docker-kokoro`) give CUDA accel, offline mode,
persistent cache, all major audio formats. Community projects pair
Whisper STT + Kokoro TTS + Ollama for a 100%-local LiveKit stack
(e.g. `simli-kokoro-whisper-livekit`, `livekit-kokoro`).

**Generalization for Vox:** any local TTS that exposes an OpenAI
`/v1/audio/speech` endpoint (Kokoro-FastAPI, many Piper wrappers, openedai-speech)
becomes a drop-in backend behind one HTTP client. Vox doesn't even need a
"plugin per engine" — one OpenAI-speech-compatible HTTP backend covers Kokoro,
Piper-server, etc.

---

## 5. Interruption / barge-in vs TTS playback (directly hits Vox's weak spots)

This is where LiveKit is most instructive for Vox's three known pain points
(can't interrupt spoken reply; ambient/speaker audio false-triggers;
unreliable barge-in).

- **Turn detection stays active while the agent is speaking.** When user speech
  is detected during TTS output, the agent **cancels the current TTS stream**
  and hands control back to STT immediately. (Vox today can't do this because
  `say` is a blocking subprocess with no cancel + no mic during playback.)
- **`allow_interruptions`** flag — whether TTS playback may be stopped at all.
  Per-`.say()` overridable.
- **`aec_warmup_duration`** — seconds after the agent starts speaking during
  which user audio is ignored, so the agent isn't interrupted by its own echo
  before AEC converges. Directly relevant to Vox's "speaker audio gets
  transcribed" problem.
- **Echo cancellation is explicitly a CLIENT-SIDE concern.** LiveKit's stance:
  AEC happens where the speaker/mic are (browser/SDK `livekit/livekit` WebRTC
  layer provides AEC; native devices' built-in AEC). For devices without AEC,
  the recommended fallback is **push-to-talk**. LiveKit's agent framework does
  NOT do server-side AEC — it relies on the WebRTC client to deliver
  echo-free audio.
- **Adaptive Interruption Handling** (Python Agents v1.5.0+, default): a small
  **audio-encoder + CNN** model classifies the first ~200ms of overlapping
  speech to separate genuine barge-in from backchannel ("uh-huh", "okay") and
  background noise. Metrics: 86% precision / 100% recall at 500ms overlap,
  rejects 51% of false-positive VAD triggers, ~30ms inference, median 216ms
  audio needed. Config: `TurnHandlingOptions(interruption={"mode": "adaptive"})`
  (vs `"vad"`). This runs in LiveKit Cloud.

**Mapping to Vox:**
1. *Can't interrupt spoken reply* — root cause is `say` being blocking + no live
   mic during playback. Fix = a non-blocking/streamable TTS backend you can
   kill mid-utterance (Kokoro chunked stream, or even `say` spawned async with
   a kill switch) + keep VAD/STT running during playback.
2. *Speaker audio false-triggers* — LiveKit's answer is real AEC at the client
   plus an `aec_warmup_duration` guard window. Vox has no AEC today; the
   cheap wins are (a) a "mute-mic-while-speaking" or warmup-guard window, and
   (b) a real AEC (macOS `kAudioUnitSubType_VoiceProcessingIO` / WebRTC APM)
   if we want true talk-over.
3. *Unreliable barge-in* — LiveKit moved past raw VAD to a learned
   acoustic onset classifier to cut false positives ~half. Vox's barge-in could
   borrow the cheap version: require a minimum onset energy/duration before
   treating mic input as an interrupt, rather than any VAD blip.

---

## 6. Which engine best replaces / augments macOS `say` for Vox

Constraints: Vox is local-first, macOS, currently offline TTS via `say`.

- **Keep `say` as default** — zero deps, fully offline, decent system voices.
  Its real limits are (a) blocking subprocess (hard to interrupt) and (b)
  robotic vs modern neural TTS. Both are addressable: spawn async + killable,
  and offer an upgrade path.
- **Best local upgrade: Kokoro (82M) via Kokoro-FastAPI.** It is THE local
  engine LiveKit actually ships, fully offline, ~80ms TTFB, chunked streaming
  (so it's interruptible), good quality for its size, OpenAI-compatible HTTP so
  the integration is a tiny client. Runs on Apple Silicon. This is the
  highest-leverage augmentation: neural voice + interruptible stream + offline.
- **Piper** — even lighter, CPU-friendly, fully offline, lower quality than
  Kokoro; good ultra-low-resource fallback. Not a native LiveKit plugin but
  fits the same OpenAI-speech-endpoint pattern.
- **Cloud (Cartesia Sonic / ElevenLabs Flash / Deepgram Aura-2)** — only if Vox
  ever wants premium voices and accepts an API key + network. Sonic/Flash are
  the latency leaders. Conflicts with Vox's local-first ethos, so treat as
  optional opt-in, not default.

**Recommended path for Vox:** (1) refactor TTS behind a small `TTS` interface
like LiveKit's (`speak()` + optional streaming + `capabilities.streaming`),
keep `say` as default but make it async/killable; (2) add a single
OpenAI-speech-compatible HTTP backend so Kokoro-FastAPI (and Piper-server) drop
in for a neural, interruptible, offline voice; (3) independently, add a
warmup/mute-while-speaking guard and (longer term) real AEC to fix the
false-trigger + talk-over problems — these are orthogonal to which TTS engine
you pick.

---

## Sources
- TTS integrations overview — https://docs.livekit.io/agents/integrations/tts/
- TTS models overview — https://docs.livekit.io/agents/models/tts/
- TTS base class source — https://github.com/livekit/agents/blob/main/livekit-agents/livekit/agents/tts/tts.py
- TTS provider impls (DeepWiki) — https://deepwiki.com/livekit/agents/6.2-tts-provider-implementations
- Kokoro plugin guide — https://docs.livekit.io/agents/models/tts/kokoro/
- Kokoro self-host Docker — https://github.com/hwdsl2/docker-kokoro/
- livekit-kokoro plugin — https://github.com/taresh18/livekit-kokoro
- Local stack example — https://github.com/dwain-barnes/simli-kokoro-whisper-livekit
- Adaptive interruption (docs) — https://docs.livekit.io/agents/logic/turns/adaptive-interruption-handling/
- Adaptive interruption (blog) — https://livekit.com/blog/adaptive-interruption-handling
- Turn detection blog — https://livekit.com/blog/turn-detection-voice-agents-vad-endpointing-model-based-detection
- TTS latency/pricing comparisons — https://deepgram.com/learn/best-text-to-speech-apis-2026, https://www.cekura.ai/blogs/best-tts-for-ai-voice-agents, https://layercode.com/blog/tts-voice-ai-model-guide
