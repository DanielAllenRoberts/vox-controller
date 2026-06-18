# Pipecat — Interaction Flow + TTS Pipeline

Research scope: how pipecat structures the real-time voice loop (speech → STT → LLM → TTS → audio out), how stages connect, how streaming/interruption work, and the latency strategy. Framed for improving **Vox** (local macOS assistant: faster-whisper STT, macOS `say` TTS, DeepSeek/Claude brains, no AEC, can't talk over TTS).

Pipecat is an open-source Python framework (pipecat-ai/pipecat) for real-time voice/multimodal agents. Everything is a **stream of typed frames** flowing through a **pipeline of frame processors**.

---

## 1. Core abstractions

Four primitives (from `docs/getting-started/core-concepts` and the architecture docs):

| Abstraction | Class | Role |
|---|---|---|
| **Frame** | `Frame` (+ subclasses) | Immutable typed data/control packet flowing through the pipeline |
| **FrameProcessor** | `FrameProcessor` | A node. Implements `process_frame(frame, direction)`, emits 0+ frames via `push_frame()` |
| **Pipeline** | `Pipeline` | An ordered list of processors linked head-to-tail |
| **Transport** | `BaseTransport` / `BaseInputTransport` / `BaseOutputTransport` | I/O endpoints (mic/speaker, WebRTC, websocket) |

Processors push frames **DOWNSTREAM** (input→output) or **UPSTREAM** (output→input). Pipelines can nest (`ParallelPipeline`). Driven by a `PipelineTask` + `PipelineRunner`.

### Frame taxonomy (the key design lever)
Three frame base classes, and the difference is **what happens on interruption**:

- **`DataFrame`** — ordered, queued, **cancellable/dropped on interruption**. (audio, text, transcripts)
- **`ControlFrame`** — ordered, queued, also cancellable on interruption. (TTS start/stop markers)
- **`SystemFrame`** — **high priority, bypasses the ordered queue, NOT discarded by interruptions**. This is how interruption signals and raw input audio jump the line for immediate processing.

Concrete frames that matter for the voice loop:

**Audio**
- `InputAudioRawFrame` (SystemFrame) — raw mic audio from transport
- `TTSAudioRawFrame` (DataFrame) — audio chunk produced by a TTS service
- `OutputAudioRawFrame` (DataFrame) — audio queued to the output transport / speaker

**Text / transcripts**
- `InterimTranscriptionFrame` (DataFrame) — **partial** STT result (streaming providers)
- `TranscriptionFrame` (DataFrame) — **final** STT result
- `LLMTextFrame` (DataFrame) — a streamed LLM token/chunk
- `TTSTextFrame` (DataFrame) — the text actually spoken (emitted alongside audio, word-aligned)
- `TextFrame` — generic text

**LLM control**
- `LLMRunFrame` — trigger LLM on current context
- `LLMFullResponseStartFrame` / `LLMFullResponseEndFrame` — bracket one LLM response (lets aggregators know a response stream began/ended)

**Speaking-state SystemFrames (turn-taking signals)**
- `VADUserStartedSpeakingFrame` — VAD definitively detected speech onset
- `UserStartedSpeakingFrame` / `UserStoppedSpeakingFrame` — user turn boundaries
- `BotStartedSpeakingFrame` / `BotStoppedSpeakingFrame` — bot speech boundaries (output transport emits these as audio actually plays)

**Interruption**
- `InterruptionFrame` (SystemFrame) — the canonical interrupt signal. (`StartInterruptionFrame`/`StopInterruptionFrame` are the older names, now **deprecated** in favor of `InterruptionFrame`.)

**Pipeline lifecycle**: `StartFrame`, `EndFrame`.

---

## 2. End-to-end pipeline graph

Canonical voice agent is a linear chain of processors:

```
transport.input()          # BaseInputTransport: mic capture, runs VAD + turn analysis
  -> STT service           # InputAudioRawFrame -> InterimTranscriptionFrame*/TranscriptionFrame
  -> user context aggregator   # LLMUserContextAggregator: folds transcripts into chat context
  -> LLM service           # context -> LLMFullResponseStart + LLMTextFrame* + LLMFullResponseEnd
  -> TTS service           # LLMTextFrame stream -> TTSStarted + TTSAudioRawFrame* + TTSText + TTSStopped
  -> transport.output()    # BaseOutputTransport: mixes/chunks audio, emits Bot{Started,Stopped}SpeakingFrame
  -> assistant context aggregator  # folds the bot's spoken text back into context
```

Stages are connected purely by `push_frame()` between adjacent processors — there is no central router; each processor only knows its next/prev peer. `BaseInputTransport` "handles VAD and turn analysis"; `BaseOutputTransport` "manages audio mixing and chunking."

---

## 3. Streaming — how low latency is achieved

The whole framework is built so audio starts flowing before the previous stage finishes. Three streaming seams:

### (a) STT streaming — two service families
Pipecat splits STT base classes by capability:

- **`STTService`** (streaming base): subclass implements `run_stt()`; processes audio continuously and emits `InterimTranscriptionFrame` (partial) during speech, then a final `TranscriptionFrame`. Used by **Deepgram (`DeepgramSTTService`, `DeepgramFluxSTTService`), AssemblyAI (`AssemblyAISTTService`), Soniox, Speechmatics**. Interim results let downstream logic react before the user finishes.
- **`SegmentedSTTService`**: **requires VAD**. It buffers audio between `VADUserStartedSpeakingFrame` and `VADUserStoppedSpeakingFrame`, then runs STT once on the whole segment → a single (always-final) `TranscriptionFrame`. Keeps a **small pre-roll buffer while idle** to cover the VAD-detection delay (speech that occurred just before VAD fired). Used by **Whisper (`WhisperSTTService`), OpenAI, Groq, Fal Whisper, Moonshine** — i.e. batch/request-based ASR.

**Direct Vox parallel:** faster-whisper is exactly the `SegmentedSTTService` pattern — VAD-gated, segment-in/segment-out, no interim transcripts, needs a pre-roll buffer.

### (b) LLM → TTS token streaming + sentence aggregation
The LLM service streams tokens as `LLMTextFrame`s (bracketed by `LLMFullResponseStartFrame`/`EndFrame`). The TTS service does **text aggregation** before synthesizing, governed by `TextAggregationMode`:

- **SENTENCE mode (default)** — buffer tokens until a sentence boundary (`match_endofsentence`), then synthesize that sentence. More natural prosody, costs ~200–300ms/sentence. Implemented via `SimpleTextAggregator` (and `PatternPairAggregator` for markup). This is the key latency/quality trade: you synthesize the **first sentence** as soon as it completes instead of waiting for the whole LLM response.
- **TOKEN mode** — stream tokens straight to TTS as they arrive; lowest latency, can hurt quality.

(`aggregate_sentences` boolean is the deprecated knob that maps onto these modes.)

### (c) TTS audio chunk streaming + word timestamps
`run_tts()` yields `TTSAudioRawFrame` chunks as the provider returns them (websocket TTS streams audio mid-sentence). Emission order per utterance:
`TTSStartedFrame` → (`TTSTextFrame` + `TTSAudioRawFrame` chunks, word-aligned) → `TTSStoppedFrame` (pushed after `stop_frame_timeout_s` idle).

**Word timestamps are now always-on in `TTSService`** (the old `WordTTSService` / `AudioContextWordTTSService` are deprecated). `add_word_timestamps(word_times: list[tuple[str, float]])` aligns spoken words to audio PTS via `_aggregated_frame_sequencer.process_word()`. This is what makes interruption *accurate*: when the user barges in, pipecat knows **exactly which words were actually spoken** and truncates the LLM context to match (so the bot doesn't think it said sentences the user never heard).

---

## 4. Interruption / barge-in (the part most relevant to Vox)

Enabled by `PipelineParams(allow_interruptions=True)` (default True). Flow:

1. While the bot is speaking, mic audio keeps flowing as `InputAudioRawFrame`s; VAD (and optionally smart-turn) runs continuously in `BaseInputTransport`.
2. On detected user speech, `BaseInputTransport` pushes an **`InterruptionFrame` (SystemFrame)** downstream. Because it's a SystemFrame it **bypasses the ordered DataFrame queue** and is processed immediately by every processor.
3. Each processor's interruption handler **drops/flushes its in-flight DataFrames**:
   - TTS `_handle_interruption()` flushes the text aggregator, stops the audio context task, resets `_serialization_queue`, calls `on_audio_context_interrupted()` for provider cleanup.
   - The output transport stops emitting queued `OutputAudioRawFrame`s → **speaker goes quiet within ms**.
   - The LLM call is cancelled.
4. Context aggregators truncate the assistant message to **only the words actually spoken** (via word timestamps), keeping conversation state honest.

So pipecat's barge-in is structurally: *continuous mic + VAD during bot speech* + *interrupt as a priority SystemFrame that flushes downstream DataFrame queues* + *word-timestamp-accurate context truncation*.

### Why pipecat can talk-over without false triggers — and Vox can't
Vox lacks two things pipecat assumes:

- **AEC / mic-isolation.** Pipecat deployments typically run over WebRTC transports (Daily/LiveKit) where the **client device** does acoustic echo cancellation, so the bot's TTS doesn't get re-heard by the mic. That's the missing piece behind Vox's "speaker audio is transcribed and falsely triggers commands."
- **`STTMuteFilter`** — a processor that **mutes STT input during defined windows** so the bot's own audio / spurious input never reaches STT. Strategies: `FIRST_SPEECH`, `MUTE_UNTIL_FIRST_BOT_COMPLETE`, `FUNCTION_CALL`, `ALWAYS`, `CUSTOM`. It also suppresses `InterimTranscriptionFrame`, interruption, and user-speaking events while muted. This is the software fallback when you don't have hardware AEC.

---

## 5. Turn-taking / endpointing (deciding the user is done)

- **VAD**: recommended **local `SileroVADAnalyzer`** rather than provider-side VAD — "150–200ms faster speech detection (no network round trip)," better interruption handling.
- **Smart Turn detection (semantic VAD)**: pipecat ships an open model **`smart-turn-v2`** (and v3), Wav2Vec2 audio classifier that decides end-of-turn from the **raw waveform, not the transcript** — so it correctly handles trailing "um"/"hmm" instead of cutting the user off. Local inference via **`LocalSmartTurnAnalyzerV2`** (PyTorch, no network; ~360MB, ~12ms inference on an L40S), or hosted via `FalSmartTurnAnalyzer`. BSD-2 licensed.
- **Latency-tuned endpointing**: each STT service has a measured **P99 latency for delivering final transcripts**; turn-stop strategies use it to decide how long to wait after VAD-stop before ending the user turn (avoids both premature responses and dead air).

---

## 6. Latency strategy summary

1. **Pipeline = streaming graph**, not request/response. Frames move via `push_frame()`; partial results propagate immediately.
2. **Local VAD + local semantic turn detection** to cut speech-detection round-trips and end turns at the right instant.
3. **Streaming STT** (interim transcripts) where available; segmented STT (Whisper) gated tightly by VAD with a pre-roll buffer.
4. **Sentence-level aggregation** so TTS starts on the first sentence of the LLM stream instead of the full response (~200–300ms/sentence trade vs. token-mode for raw speed).
5. **Streaming TTS audio chunks** out as they're generated.
6. **Interruption as a priority SystemFrame** that bypasses queues and flushes in-flight DataFrames, plus **word-timestamp-accurate context truncation** so barge-in is both instant and state-correct.
7. **`STTMuteFilter`** + client-side AEC keep the bot from hearing itself.

---

## 7. Takeaways for Vox

1. **Adopt the "interrupt = priority signal that flushes the speaking queue" model for TTS barge-in.** Vox's `say` TTS is a blocking subprocess with no concept of a flushable audio queue. To talk over the reply, restructure TTS so it's (a) chunked per sentence and (b) killable mid-utterance: synthesize/speak sentence-by-sentence from the LLM token stream, run a fast VAD on the mic *while speaking*, and on detected speech **kill the `say` process immediately** and truncate the assistant context to only the sentences already spoken. That's pipecat's flow minus the frame machinery.

2. **The "speaker audio falsely triggers commands" problem is the AEC gap — copy `STTMuteFilter`.** Until Vox has real echo cancellation, gate STT while TTS is playing (pipecat's `MUTE_UNTIL_FIRST_BOT_COMPLETE` / `ALWAYS` strategies). Combined with point 1, you mute by default and only un-mute to listen for a barge-in keyword/VAD spike — far fewer false triggers than feeding all mic audio to whisper while speaking.

3. **Vox's faster-whisper is a `SegmentedSTTService`; treat it as such.** Keep a **small pre-roll audio buffer** before VAD fires (covers clipped word onsets — a likely cause of unreliable barge-in), and accept there are no interim transcripts. If barge-in needs to be faster/more reliable, don't wait for whisper to transcribe — trigger the interrupt on **VAD/turn-detection alone**, then transcribe.

4. **Borrow `smart-turn-v2` for endpointing and barge-in.** It's local, open (BSD-2), small (~360MB), and decides end-of-turn from the waveform — directly fixing "barge-in is unreliable" and "cuts me off / waits too long." Pair it with local Silero VAD. This is a drop-in, offline-friendly upgrade over pause-length heuristics, matching Vox's local-first / open-source direction.

---

## Sources
- Core concepts: https://docs.pipecat.ai/getting-started/core-concepts
- Pipeline & frame processing: https://docs.pipecat.ai/guides/learn/pipeline
- Custom FrameProcessor: https://docs.pipecat.ai/guides/fundamentals/custom-frame-processor
- Frames API/source: https://reference-server.pipecat.ai/en/latest/_modules/pipecat/frames/frames.html
- TTSService source: https://reference-server.pipecat.ai/en/stable/_modules/pipecat/services/tts_service.html
- STTService API: https://reference-server.pipecat.ai/en/latest/api/pipecat.services.stt_service.html
- DeepWiki overview: https://deepwiki.com/pipecat-ai/pipecat
- DeepWiki STT services: https://deepwiki.com/pipecat-ai/pipecat/4.4-speech-to-text-services
- STTMuteFilter: https://docs.pipecat.ai/server/utilities/filters/stt-mute
- Speech-to-text guide: https://docs.pipecat.ai/pipecat/learn/speech-to-text
- Smart Turn v2: https://www.daily.co/blog/smart-turn-v2-faster-inference-and-13-new-languages-for-voice-ai/ , https://huggingface.co/pipecat-ai/smart-turn-v2
- LocalSmartTurnAnalyzerV2: https://reference-server.pipecat.ai/en/latest/api/pipecat.audio.turn.smart_turn.local_smart_turn_v2.html
