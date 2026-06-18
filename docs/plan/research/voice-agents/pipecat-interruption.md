# Pipecat — Interruption / Barge-in / Turn-Taking (research)

Source: https://github.com/pipecat-ai/pipecat · docs https://docs.pipecat.ai · turn model https://github.com/pipecat-ai/smart-turn
Researched 2026-06-18. Pipecat = open-source Python framework for real-time voice agents, built on a **pipeline of frame processors**. Audio, transcripts, LLM tokens, TTS chunks all flow as **Frames** through ordered processors (transport-in → STT → context aggregator → LLM → TTS → transport-out). Interruption is implemented as a special frame that propagates through this pipeline.

---

## 1. The big architectural idea: interruption is a frame, not a callback

Everything moves as frames. The relevant control frames:

- `InterruptionFrame` (formerly `StartInterruptionFrame`, now deprecated) — emitted when the user starts speaking / a barge-in is accepted. Travels through the pipeline and tells every processor "stop what you're doing and flush."
- `StopInterruptionFrame` — user stopped speaking.
- `BotInterruptionFrame` — lets app code force an interruption programmatically.
- `UserStartedSpeakingFrame` / `UserStoppedSpeakingFrame` — emitted by the VAD analyzer in the input transport.
- `BotStartedSpeakingFrame` / `BotStoppedSpeakingFrame` — emitted by the output transport around TTS playback.

Because it's a frame, ONE detection event cleanly cancels **both** the in-flight LLM and the TTS playback as it passes through each stage — no manual wiring. This is the cleanest part of their design and the most directly portable idea to Vox (see takeaways).

---

## 2. Detection: how it knows the user STARTED speaking (barge-in trigger)

Two-layer detection. Layer 1 (VAD) always runs; layer 2 (strategy / turn model) is optional and gates reliability.

### Layer 1 — VAD (always on)
- **`SileroVADAnalyzer`** (Silero VAD model) runs inside the input transport on the mic stream, continuously, **even while the bot is speaking** (this is what makes barge-in possible at all).
- Config object **`VADParams`**:
  - `confidence` (default **0.7**) — speech-probability threshold, higher = stricter.
  - `start_secs` (default **0.2**) — speech must persist this long before `UserStartedSpeakingFrame` fires (debounce against blips).
  - `stop_secs` (default **0.2**) — silence this long before `UserStoppedSpeakingFrame` (note: smart-turn docs recommend keeping this short, 0.2s, and letting the turn model decide).
  - `min_volume` (default **0.6**) — volume gate.
- `UserStartedSpeakingFrame` is what kicks off the interruption when `allow_interruptions=True`.

### Layer 2 — Interruption strategies (gate VAD so noise doesn't barge in)
VAD alone fires on ANY speech-like audio (incl. background TV, other people, the bot's own leaked audio). To stop spurious barge-ins, pipecat added **interruption strategies**:
- **`MinWordsInterruptionStrategy(min_words=N)`** — an interruption is only accepted if the user has produced at least N *transcribed words*, not just VAD energy. So the strategy buffers audio/partial transcript and only emits the real interruption once enough actual words land. (Deprecated name as of v0.0.99; the current form is **`MinWordsUserTurnStartStrategy`** passed via `PipelineTask(turn_start_strategies=[...])`.)
- Strategies are pluggable (base interruption-strategy class); you can write custom gates.
- Enabled globally via **`PipelineParams(allow_interruptions=True)`**.

This min-words gate is the single most relevant mechanism for Vox's "ambient audio falsely triggers commands" problem — it requires *linguistic* evidence, not just energy, before acting.

---

## 3. Endpointing: how it knows the user is DONE speaking (end-of-turn)

Three escalating options:

1. **VAD-only endpointing** — `UserStoppedSpeakingFrame` after `stop_secs` of silence. Simple, but a fixed silence timeout is either too eager (cuts people off mid-thought) or too laggy.

2. **Smart Turn (semantic/acoustic end-of-utterance MODEL)** — pipecat's dedicated turn-detection model, analogous to LiveKit's turn-detector.
   - **`LocalSmartTurnAnalyzerV3`** (local ONNX inference, v0.0.85+) wrapped by **`TurnAnalyzerUserTurnStopStrategy`**. There is also a remote/hosted variant.
   - Model: **smart-turn v3** = **Whisper-Tiny encoder + a linear classifier head**, ~8M params. (Earlier v2 used wav2vec2-BERT; they switched to Whisper-tiny for speed/quality.) BSD-2-clause, truly open.
   - Flow: VAD detects a pause → smart-turn analyzes the **most recent ~8 s** of the user's turn audio → classifies **complete vs incomplete** based on intonation + linguistic cues. If "incomplete," it waits (keeps the turn open) instead of letting silence end it.
   - Latency: ~10 ms on fast CPUs, <100 ms typical, ~65 ms on Pipecat Cloud. Runs via ONNX; optional `onnxruntime-gpu`. 23 languages.
   - Config **`SmartTurnParams`**:
     - `stop_secs` (default **3.0**) — fallback: if the model keeps saying "incomplete" but silence exceeds this, end the turn anyway (prevents infinite hang).
     - `max_duration_secs` (default **8.0**) — rolling analysis window.
     - `pre_speech_ms` (default 0.0) — pre-roll buffer.
   - Requires VAD enabled; docs explicitly recommend VAD `stop_secs ≈ 0.2` so the model (not the timeout) makes the real decision.

3. **Min-words / custom turn-start strategies** (section 2) double as endpoint guards on the start side.

---

## 4. Stopping the agent: TTS playback flush + in-flight LLM cancel

When an interruption is accepted, the `InterruptionFrame` propagates and each processor reacts:

### Output transport (TTS playback) — `BaseOutputTransport.handle_interruptions(InterruptionFrame)`
- Cancels the clock task and video task.
- **Resets / cancels the audio task** → `self._audio_queue.reset()` (or cancel+recreate the audio task), which **drops all queued/buffered TTS audio frames immediately** so playback stops mid-word. (`has_uninterruptible` / mixer cases are handled specially so "uninterruptible" prompts survive.)
- Cleans the leftover `_audio_buffer` bytes and emits `BotStoppedSpeakingFrame`.
- Recreates the tasks so the next bot turn can start cleanly.

### Upstream (LLM + STT aggregation)
- The interruption frame also flushes the **LLM response aggregator** and cancels the in-flight LLM generation/streaming, and clears partial TTS-bound text, so the half-finished answer is abandoned (not spoken). Known sharp edges exist here (GitHub issues #2567 pipeline freeze on interruption during context processing, #950 some TTS providers don't interrupt during long completions, #3985 proposal for graceful interruption release) — i.e. cleanly cancelling streaming LLM + streaming TTS atomically is the hard part even for them.

Net effect: one frame → TTS audio buffer dumped + LLM stream cancelled + context reset, all in order.

---

## 5. Echo cancellation: stopping the agent from hearing ITSELF

**Pipecat does NOT ship an acoustic echo canceller. AEC is delegated to the transport / OS / browser layer.** This is a critical finding for Vox.

- **WebRTC transports (Daily cloud, or self-hosted SmallWebRTC)**: AEC is provided by the **browser's native WebRTC audio pipeline** (`webrtc::EchoCanceller3` / WebRTC APM — the same `echoCancellation: true` getUserMedia constraint). The browser delivers an already-echo-cancelled mic stream; pipecat never sees the raw echo. Docs explicitly note AEC "is wired into the WebRTC stack, but it's not available to arbitrary WebSocket streams" — i.e. if you use a raw WebSocket/local transport you **lose** AEC and must provide your own.
- **The audio "filters" in `src/pipecat/audio/filters/` are NOT echo cancellers.** They are noise suppression / voice isolation:
  - `krisp_viva_filter.py` → **`KrispVivaFilter`** (Krisp VIVA SDK) — isolates the primary speaker's voice, removes background noise and *other voices*. (Old `KrispFilter` deprecated.)
  - `koala_filter.py` → Koala (Picovoice) noise suppression.
  - `aic_filter.py` → ai-coustics speech enhancement.
  - `rnnoise_filter.py` → RNNoise noise suppression.
  - These run on the **input** stream and help with ambient noise / other-voice rejection, but they do **not** cancel the bot's own playback (no loudspeaker reference signal). Krisp's *voice isolation* can incidentally reduce some bot leakage by keeping only the dominant speaker, but it is not true reference-based AEC.
- Real AEC needs the loudspeaker output as a **reference signal**; pipecat relies on the transport/device to do that (browser WebRTC APM, or Krisp's full SDK / OS device echo cancellation), not its own pipeline.

So pipecat's answer to "don't hear yourself" = "run on WebRTC and let the browser/Krisp do it," PLUS the software gates (VAD start_secs debounce + min-words strategy + smart-turn) to reject whatever leaks through.

---

## 6. Mapped to Vox (takeaways)

Vox today: faster-whisper STT + Silero-style VAD, macOS `say` TTS (no buffer/stream control), DeepSeek/Claude brains, barge-in only while silent, NO AEC. Pipecat maps as follows:

1. **Adopt the min-words interruption gate (highest ROI, no new deps).** Vox's "ambient audio falsely triggers commands" is exactly what `MinWordsInterruptionStrategy` solves: don't act on VAD energy alone — require N transcribed words from faster-whisper before accepting a barge-in or command. Cheap, local, directly fixes false triggers (weak spot #2) and unreliable barge-in (weak spot #3).

2. **AEC is the real blocker for "talk over the spoken reply" (weak spot #1) — and pipecat punts it to the platform.** On macOS, get a reference-based echo canceller from the OS/transport, not from app code: either use the **macOS Voice Processing audio unit (`kAudioUnitSubType_VoiceProcessingIO`, AUVoiceIO)** which gives system AEC + AGC + noise suppression with the speaker as reference, or wrap mic capture in a WebRTC APM (`webrtc::EchoCanceller3`), or use the Krisp SDK. Without a loudspeaker reference signal, you cannot cleanly let the user talk over `say`. The pipecat filters (noise suppression) will NOT do it. This is an audio-unit task, not an LLM task.

3. **Replace fixed silence-timeout endpointing with a smart-turn model.** smart-turn v3 (Whisper-Tiny encoder + linear head, ~8M params, ONNX, ~10–100 ms CPU, BSD-2, 23 langs) runs locally and decides "user actually finished" vs "mid-thought pause" from intonation, instead of a blunt silence timeout. Pattern: keep VAD `stop_secs` short (~0.2 s) for responsiveness, let the model gate the real end-of-turn, with a `stop_secs≈3.0` hard fallback. Vox could vendor `pipecat-ai/smart-turn-v3` ONNX directly (works without the rest of pipecat).

4. **Make interruption a single signal that flushes the whole chain — but Vox's TTS is the weak link.** Pipecat's clean "one InterruptionFrame cancels LLM + dumps the TTS audio buffer" works because TTS is a controllable streaming buffer it owns. The macOS `say` command is a fire-and-forget subprocess with no mid-utterance flush, so Vox can at best `kill` the `say` process on interruption (already partially possible). To get pipecat-grade barge-in (cut mid-word, instantly), Vox likely needs a **streaming/chunked TTS it controls** (e.g. AVSpeechSynthesizer with buffered output, or a local streaming TTS) so it can drop the unplayed buffer the way `BaseOutputTransport._audio_queue.reset()` does — rather than waiting for `say` to finish a sentence.

### One-line summary of the stack
VAD (Silero, `VADParams`) detects start/stop → interruption **strategy** (`MinWords...`, transcript-gated) decides if it's a real barge-in → smart-turn v3 model decides real end-of-turn → an `InterruptionFrame` propagates and `BaseOutputTransport.handle_interruptions` resets the audio queue (kills TTS) while upstream cancels the LLM stream → **AEC is NOT pipecat's**, it comes from browser WebRTC APM / Krisp / OS device, with noise-suppression filters (Krisp Viva, Koala, ai-coustics, RNNoise) as the input-cleanup layer.
