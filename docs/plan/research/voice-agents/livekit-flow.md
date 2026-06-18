# LiveKit Agents — Interaction Flow + TTS Pipeline

Research date: 2026-06-18. Topic: how the real-time voice pipeline is structured end to end
(speech -> STT -> LLM -> TTS -> audio out), how stages stream/connect, and the latency +
interruption strategy. Framed for improving **Vox** (local macOS hands-free assistant).

Sources are listed at the bottom. Where possible names/defaults are quoted from source or the
SDK reference; some are from LiveKit's own architecture blogs.

---

## 1. The core abstraction: `AgentSession`

In LiveKit Agents **1.0+**, the single orchestrator is **`AgentSession`** (module
`livekit.agents.voice`). It replaced/unified the older **`VoicePipelineAgent`** (cascade
STT->LLM->TTS) and **`MultimodalAgent`** (speech-to-speech) classes. You declare pluggable
components and the SDK wires up streaming, turn detection, and interruptions:

```python
session = AgentSession(
    vad=silero.VAD.load(),          # or defaults to inference.VAD(model="silero")
    stt="deepgram/nova-3:multi",    # plugin instance or "provider/model" string
    llm="openai/gpt-4.1-mini",
    tts=...,                        # TTS plugin
    turn_detection=...,             # multilingual turn-detector model (default)
)
```

Two pipeline shapes share this class:
- **Cascade pipeline**: explicit `STT -> LLM -> TTS` text stages. LiveKit says ~90% of production
  agents in 2026 still use this (lets you pick best-in-class model per stage, redact/inspect text
  between stages, swap a vendor without a rewrite). **This is the shape Vox already is.**
- **Speech-to-speech (S2S)**: OpenAI Realtime / Gemini Live take audio in, emit audio out, no
  explicit text stage. End-to-end ~320–800ms but you lose the text seams.

A second class, **`Agent`**, holds the behavior (instructions, tools, and — importantly — the
overridable pipeline node methods below). `AgentSession` runs an `Agent`.

---

## 2. End-to-end flow as a streaming graph

The conceptual chain is:

```
Audio In -> VAD -> STT -> (turn detection) -> LLM -> TTS -> Audio Out (WebRTC track)
```

The key implementation insight: **each stage is an async generator that consumes an
`AsyncIterable` and yields an `AsyncIterable`**. Stages are connected by async iteration, not by
"call stage, wait, call next stage". This is what makes the pipeline streaming.

### Pipeline "nodes" (overridable, on the `Agent` class)
These are the real seams in the graph (`livekit/agents/voice/agent.py`). Signatures (quoted):

| Node | Input | Output (yields) |
|------|-------|-----------------|
| `stt_node(self, audio: AsyncIterable[rtc.AudioFrame], model_settings)` | mic audio frames | `stt.SpeechEvent` (interim + final transcripts) |
| `llm_node(self, chat_ctx: llm.ChatContext, tools: list[llm.Tool], model_settings)` | chat context + tools | `llm.ChatChunk` / `str` / `FlushSentinel` |
| `transcription_node(self, text: AsyncIterable[str \| TimedString], model_settings)` | LLM text stream | processed text / `TimedString` (for synced captions) |
| `tts_node(self, text: AsyncIterable[str], model_settings)` | streamed LLM text | `rtc.AudioFrame` |
| `realtime_audio_output_node(self, audio: AsyncIterable[rtc.AudioFrame], model_settings)` | S2S model audio | processed audio frames |

Default implementations wrap the third-party plugin via its `.stream()` context manager and forward
input asynchronously while yielding output incrementally. Because each node is an async generator,
**you can override any one of them** to inject logic between stages (e.g. PII redaction between STT
and LLM, or text filtering before TTS) without touching the rest of the graph.

### The data types that flow
- **`rtc.AudioFrame`** — the unit of audio (raw PCM frames) in and out. Same type at both ends.
- **`stt.SpeechEvent`** — STT output, carries `INTERIM_TRANSCRIPT` and `FINAL_TRANSCRIPT` events.
- **`llm.ChatContext`** — full conversation history passed into the LLM (this is how multi-turn /
  tool / handoff context moves forward explicitly).
- **`llm.ChatChunk`** — streamed LLM token deltas.
- **`TimedString`** — text with timing, used so on-screen transcription stays synced to audio
  playout (and so truncation on interrupt can trim the transcript to only what was spoken).
- **`FlushSentinel`** — marker the LLM node can yield to force the TTS to flush a chunk to audio.

---

## 3. How STREAMING works (the latency win)

Naive **sequential** pipeline = each stage fully finishes before the next starts. Latency is
**additive**: `VAD + STT + LLM + TTS` ~ 1000–2000ms+ (often quoted 2–4s).

**Streaming** pipeline runs stages **in parallel, passing partial output downstream as it appears**.
Latency collapses toward `max(VAD, STT, LLM, TTS)` ~ 400–800ms, target **<1s**, "natural" <500ms.

Three streaming mechanisms stacked:
1. **Interim/partial STT transcripts.** Streaming STT (e.g. Deepgram Nova) emits partials in
   <100–200ms instead of waiting for the full utterance. Flows as `SpeechEvent` interim events.
2. **Streaming LLM tokens into TTS.** The LLM yields `ChatChunk` token deltas; `tts_node` consumes
   that text stream and begins synthesizing audio **before the LLM finishes the sentence**. The
   text-stream-in / audio-frame-out contract of `tts_node` is exactly what enables this.
3. **Streaming TTS audio out.** TTS yields `rtc.AudioFrame`s incrementally; they're written to the
   WebRTC audio track as produced, so first-audio lands ~100–300ms after first tokens.

LiveKit's own per-stage budget for <1s total:
- Audio transport: <50ms
- STT first partial: 100–200ms
- LLM time-to-first-token: 200–400ms
- TTS time-to-first-audio: 100–300ms

### Preemptive generation
`preemptive_generation` (default **True** in `TurnHandlingOptions`): the agent starts running the
LLM **before** the user's end-of-turn is fully confirmed, using the current transcript. By default
only the **LLM** runs preemptively; **TTS waits** until the turn is confirmed and speech is
scheduled (`preemptive_tts` default **False**). `max_speech_duration` 10.0s, `max_retries` 3. This
shaves the LLM TTFT off the perceived latency. If the user keeps talking, the speculative
generation is discarded.

---

## 4. Turn detection — when is the user done talking?

LiveKit layers three signals (this is the part Vox does most crudely today):
1. **VAD** (Silero, `silero.VAD.load()` / bundled `inference.VAD(model="silero")`) — cheap, CPU,
   "is there speech" only; can't tell a mid-thought pause from end-of-turn. Gates everything: if VAD
   doesn't fire, the downstream pipeline stays idle (~10–50ms).
2. **STT endpointing** — provider confidence that an utterance is complete.
3. **Model-based turn detector** (`TurnDetector()` / `MultilingualModel`) — a small transformer
   that reads the **transcript semantics** to decide if the turn is actually over (handles
   "umm…" trailing pauses). This is the default `turn_detection`.

Endpointing delays (from `TurnHandlingOptions`):
- `min_endpointing_delay` = **0.5s**
- `max_endpointing_delay` = **3.0s**

The turn detector adjusts the wait inside that window based on how "finished" the transcript sounds.

---

## 5. Interruption / barge-in (the biggest Vox gap)

Config lives in **`TurnHandlingOptions`** (the flat `AgentSession(allow_interruptions=...)` etc. args
are now deprecated aliases into this struct). Exact defaults:

| Field | Default | Meaning |
|-------|---------|---------|
| interruption `enabled` (`allow_interruptions`) | **True** | user can cut off the agent mid-speech |
| interruption `mode` | **"adaptive"** (falls back to **"vad"**) | adaptive when turn detector + aligned STT available |
| `min_interruption_duration` (`min_duration`) | **0.5s** | min detected speech before it counts as interruption |
| `min_interruption_words` (`min_words`) | **0** | optionally require N transcribed words before interrupting |
| `discard_audio_if_uninterruptible` | **True** | drop buffered mic audio while agent is speaking uninterruptibly |
| `false_interruption_timeout` | **2.0s** | if "interruption" detected but no transcript appears within this, treat as false |
| `resume_false_interruption` | **True** | after a false interruption, agent resumes from where it stopped |
| `min_endpointing_delay` / `max_endpointing_delay` | 0.5 / 3.0s | see turn detection |

### How interruption actually executes
On a confirmed interruption the framework: **detects** speech during agent turn -> **cancels the
active TTS playback immediately** -> **flushes queued audio frames** -> **truncates the transcript**
to only what was actually played out (using `TimedString` timing so chat context reflects reality) ->
**restarts the pipeline from STT** for the new utterance. Programmatically each utterance returns a
**`SpeechHandle`** (`session.say(...)` / `session.generate_reply(...)`); it exposes `handle.interrupted`,
`await handle.wait_for_playout()`, `add_done_callback()`, and the session can `interrupt()` it.
Irreversible work can guard itself with `run_ctx.disallow_interruptions()`.

### Adaptive Interruption Handling (directly relevant to Vox false triggers)
Default VAD-only barge-in over-triggers on noise/backchannels ("uh-huh", "yeah"). LiveKit added an
**audio-based interruption-detection model**: an **audio encoder + CNN** that classifies the first
few hundred ms of incoming speech by waveform shape, onset sharpness, duration, and prosody
(pitch/rhythm), trained on real interruptions vs backchannels vs noise. Reported: **86% precision,
100% recall** at 500ms overlap, and it **rejects 51% of VAD-based barge-ins** (false positives
avoided). This is the "adaptive" interruption `mode`.

---

## 6. The agent hearing itself / background speakers (Vox weak spots #2)

Vox today has **no AEC** and transcribes ambient/speaker audio. LiveKit's answers:

- **WebRTC AEC + noise suppression** (`echoCancellation`, `noiseSuppression`) — but these run
  **client-side in the browser** only. For headless agents/telephony there's no browser, so LiveKit
  doesn't rely on this server-side.
- **Krisp noise cancellation** (`livekit-plugins-noise-cancellation`, LiveKit Cloud licensed) —
  runs **locally**, no audio leaves the machine; strips background noise.
- **BVC = Background Voice Cancellation** (a Krisp model, agent-side via the Python/Node plugin) —
  removes **other background speakers**, not just noise. LiveKit reports BVC cut **VAD false-positive
  triggers by 3.5x** on average. Alternative provider: **ai-coustics**.
- Guidance: **do not stack** noise cancellation in both frontend and agent — the models are trained
  on raw audio and double-processing produces artifacts.

So LiveKit's defense-in-depth against "agent triggered by its own output / other voices" is:
front-of-pipeline **BVC/Krisp filter** (remove non-primary speakers + noise) **+** the audio-based
**adaptive interruption model** (reject backchannel/noise barge-ins) **+** `min_interruption_words`
/ `false_interruption_timeout` (require real transcript before committing to an interrupt). Note it
relies on having a clean mic stream per participant via WebRTC; there's no single "AEC of TTS"
module — it's prevented because the agent's TTS goes out on a separate track and the framework
truncates/owns playout state rather than re-listening to it.

---

## Takeaways for Vox

1. **Adopt the async-generator node graph mentally.** Vox's `core/loop.py` should treat STT -> LLM
   -> TTS as three streaming generators, not three blocking calls. The concrete win: pipe DeepSeek
   token deltas straight into the macOS `say` as sentences complete (chunk on sentence boundaries),
   instead of waiting for the full reply. That alone moves Vox from additive to `max()` latency. The
   `say` command can't truly stream, but you can spawn it per-sentence as tokens arrive and kill the
   process to interrupt.

2. **Interrupting the spoken reply (Vox gap #1) = own the playout + kill the TTS process.** LiveKit's
   model is: keep a handle to the speaking process (for Vox, the `say` subprocess), and on a
   confirmed user-speech event, **terminate it and truncate context to what was actually spoken**.
   Vox already barges in on the *LLM call*; extend the same emergency-stop path to also `kill` the
   `say` subprocess. Track "what was spoken so far" so the assistant's chat history matches.

3. **Kill false triggers with a two-gate interrupt, not raw VAD (Vox gap #2 & #3).** Mirror LiveKit's
   defaults: require `min_interruption_duration` ~0.5s AND a non-empty STT transcript before
   accepting a barge-in (`min_interruption_words`/`false_interruption_timeout` pattern). This stops
   ambient noise and short backchannels from firing commands. The heavyweight version is LiveKit's
   audio-encoder+CNN classifier — overkill for v1, but the cheap version (duration + must-have-words
   gate) is most of the benefit.

4. **The real cure for "transcribes its own/ambient audio" is a noise/voice-cancellation front-end.**
   Vox has no AEC. Options without LiveKit Cloud: pause/gate the mic (or hard-drop STT results) while
   the `say` subprocess is active, and add a local noise-suppression / single-speaker filter (e.g. a
   Silero-VAD energy gate, RNNoise, or a BVC-style model) before faster-whisper. Mic-gating during
   TTS is the cheapest fix and removes the self-hearing problem entirely at the cost of not being
   able to barge in over speech — so pair it with a "duck, don't mute" approach if you want both.

---

## Sources
- https://docs.livekit.io/agents/build/ (voice pipeline overview)
- https://livekit.com/blog/voice-agent-architecture-stt-llm-tts-pipelines-explained
- https://livekit.com/blog/sequential-pipeline-architecture-voice-agents
- https://docs.livekit.io/reference/python/livekit/agents/voice/index.html
- https://github.com/livekit/agents/blob/main/livekit-agents/livekit/agents/voice/agent.py (pipeline nodes)
- https://github.com/livekit/agents/blob/main/livekit-agents/livekit/agents/voice/agent_session.py
- https://docs.livekit.io/reference/agents/turn-handling-options/ (TurnHandlingOptions defaults)
- https://livekit.com/blog/adaptive-interruption-handling (audio-encoder+CNN interruption model)
- https://docs.livekit.io/transport/media/noise-cancellation/ + https://pypi.org/project/livekit-plugins-noise-cancellation/ (Krisp / BVC)
- https://docs.livekit.io/agents/build/speech/ (session.say / generate_reply, SpeechHandle)
