# LiveKit Agents — Interruption / Barge-in / Turn-taking

Research date: 2026-06-18. Focus: how LiveKit's voice-agent framework (`livekit/agents`,
transport `livekit/livekit`) detects barge-in, stops TTS, cancels the in-flight LLM, decides
when the user is done speaking, and prevents the agent from hearing its own audio. Framed for
improving **Vox** (local macOS: faster-whisper STT + VAD, wake-word, macOS `say` TTS, DeepSeek/Claude
brains, no AEC).

---

## 0. The big picture / pipeline

LiveKit splits the problem into three independent layers, each swappable:

1. **VAD** — Silero VAD (`livekit-plugins-silero`). Cheap frame-level speech/no-speech. Drives both
   interruption timing and (with the model) end-of-turn timing.
2. **Turn detection (end-of-utterance / EOU)** — a dedicated **semantic turn-detector model** layered
   *on top of* VAD, not a raw silence timer. This is the headline feature.
3. **Noise/echo cancellation** — runs at the *transport* edge (client WebRTC APM + LiveKit Cloud Krisp/
   ai-coustics), NOT inside the agent's STT loop. This is what stops the agent hearing its own TTS.

Orchestration lives in `livekit-agents/livekit/agents/voice/`:
- `audio_recognition.py` — `AudioRecognition` class: fan-out of audio frames to VAD, STT, interruption
  detector, and turn detector; runs EOU detection.
- `agent_activity.py` — `AgentActivity`: owns the current `SpeechHandle`, performs interruption
  (pause/truncate TTS, cancel LLM).
- `agent_session.py` — `AgentSession`: top-level config (`turn_detection=`, `turn_handling=`,
  interruption options), public `session.interrupt()`, `session.commit_user_turn()`,
  `session.clear_user_turn()`.

---

## 1. Turn detection — how it knows the user is DONE speaking

LiveKit supports **5 `turn_detection` modes** (set on `AgentSession`):

| Mode | Value | Mechanism |
|------|-------|-----------|
| Turn-detector model (default, recommended) | `inference.TurnDetector()` | Semantic EOU model + Silero VAD |
| Realtime LLM | `"realtime_llm"` | Server-side detection by OpenAI Realtime / Gemini Live |
| VAD only | `"vad"` | Pure Silero VAD silence — lowest latency, dumbest |
| STT endpointing | `"stt"` | STT provider's own endpointing (Deepgram Flux, AssemblyAI) |
| Manual | `"manual"` | Push-to-talk; `commit_user_turn()` / `clear_user_turn()` |

### The turn-detector model (the interesting part)

Two families:

- **Audio Turn Detector (current, recommended)** — encodes the user's **raw audio** directly, capturing
  *both* semantic meaning and **acoustic cues (intonation, pitch, rhythm)**. No transcript required, so
  it also works with realtime models. Versions: **`v1`** (full model, runs on LiveKit Inference / cloud)
  and **`v1-mini`** (lightweight, CPU-local). Auto-falls back v1→v1-mini when the monthly free allowance
  is exhausted. ~14 languages. Reported **AUC 0.96, ~0.91 precision/recall**.
- **Text Turn Detector (deprecated, removed in SDK v2.0)** — open-weights LM fine-tuned from
  **Qwen2.5-0.5B-Instruct**. Consumes the rolling STT transcript and predicts P(end-of-turn). ~500MB RAM,
  runs locally on shared CPU. Recommended to pair with Silero VAD. 99.3% TPR, 85–96% TNR.

**Key idea vs naive silence timeout:** the model recognizes that "I need to think about that…" with a
pause is *not* the end of a turn, so it won't fire prematurely. It does this by combining the VAD
silence signal with a learned probability.

### How the model and VAD combine (endpointing)

From `audio_recognition.py` (`_run_eou_detection`): VAD `END_OF_SPEECH` arms a timer. The turn-detector
produces `end_of_turn_probability`. The wait length is chosen dynamically:

```
endpointing_delay = self._endpointing.min_delay              # default 0.5s
if end_of_turn_probability < unlikely_threshold:
    endpointing_delay = self._endpointing.max_delay          # default 3.0s
```

So: if the model is **confident** the user is done → wait only `min_delay` (snappy). If the model thinks
the user will **continue** (low prob) → wait up to `max_delay` (patient). `unlikely_threshold` is the
model's confidence knob (scalar or per-language dict; lower = more eager to respond).

`EndpointingOptions` defaults (`turn_handling=TurnHandlingOptions(...)`, supersedes the deprecated
`min_endpointing_delay`/`max_endpointing_delay` ctor args):
- `min_delay = 0.5s`
- `max_delay = 3.0s`
- Python: seconds; Node: ms.
- Python also has **dynamic endpointing**: adapts the delay from observed per-session pause statistics.

---

## 2. Barge-in — how interruption is DETECTED while the agent is talking

Detection is **VAD-first, then gated** by an interruption detector (in `audio_recognition.py` the
`_interruption_task` consumes overlap events; `_OverlapSpeechStartedSentinel` / `_OverlapSpeechEndedSentinel`
track agent/user speech overlap; a `_backchannel_boundary_timer` enforces cooldown).

`InterruptionOptions` (defaults from the turn-handling reference):
- `enabled = True` — master toggle.
- `mode` — **`"adaptive"`** when a turn-detector model + STT with aligned transcripts is configured;
  otherwise falls back to **`"vad"`**. Adaptive analyzes audio to distinguish a *true* interruption from
  **backchanneling** ("uh-huh", "yeah", "right") so the agent doesn't stop for acknowledgements.
- `min_duration = 0.5s` (a.k.a. `min_interruption_duration`) — speech must persist this long to count.
- `min_words = 0` (a.k.a. `min_interruption_words`, needs STT) — require N transcribed words first.
  Gate check in `agent_activity.py`:
  `if len(split_words(info.new_transcript, ...)) < ...interruption["min_words"]:` → don't interrupt.
  (Note: open issue #3515 — `min_words` can dominate over `min_duration`.)
- `discard_audio_if_uninterruptible` — drop buffered user audio while the agent is in a non-interruptible
  utterance.
- `false_interruption_timeout = 2.0s`, `resume_false_interruption = True` — see below.

Per-utterance override: `Agent.say(..., allow_interruptions=False)` / `SpeechHandle.allow_interruptions`.
`user_turn_limit` (`max_words` / `max_duration`) lets the *agent* interrupt a user who monopolizes.

---

## 3. How interruption STOPS the TTS and CANCELS the LLM

In `agent_activity.py`, the current utterance is a **`SpeechHandle`**. On a confirmed interruption:

1. **`SpeechHandle.interrupt()`** marks the speech interrupted and cancels its associated tasks.
2. **Audio output is PAUSED, not hard-stopped** — `_interrupt_by_audio_activity()` calls
   `self._session.output.audio.pause()` (and later `.resume()`), so playback can resume if the
   interruption turns out to be false. This is the false-interruption recovery design.
3. **Conversation history is TRUNCATED to what the user actually heard** — the agent rewrites the
   assistant turn so the LLM context only contains the spoken-so-far prefix, not the unspoken tail. This
   keeps the transcript honest after a cut-off.
4. **In-flight LLM cancellation** — for the streaming-pipeline path the generation coroutine/task is
   cancelled via the task system tied to the `SpeechHandle`; for realtime models it calls
   `self._rt_session.interrupt()` (server-side cancel). Public entry points: `session.interrupt()` and
   `handle = session.say(...); handle.interrupt()`.

### False-interruption recovery

Because step 2 *pauses* rather than stops, LiveKit can recover. `_pause_enabled()` →
`_update_paused_speech()` + `_start_false_interruption_timer()`. If the user goes silent again within
`false_interruption_timeout` (2.0s) and `resume_false_interruption=True`, the paused TTS **resumes**
instead of discarding the reply. A `false interruption` event is emitted. This is what makes barge-in feel
reliable rather than trigger-happy — a cough or "mm-hmm" doesn't kill the whole answer.

---

## 4. Echo cancellation — how the agent doesn't hear ITS OWN audio

This is handled **outside the agent**, at the media-transport edge. LiveKit does NOT do AEC inside the
STT loop — it relies on the WebRTC pipeline plus cloud denoisers. Three layers:

1. **Client-side WebRTC APM (the actual AEC).** `echoCancellation` and `noiseSuppression` are standard
   WebRTC `AudioCaptureOptions` set on the *client* mic capture, running in the browser/native WebRTC
   audio processing module **before** audio is sent to the room. This is the component that removes the
   agent's TTS (played out the user's speakers) from the user's mic feed — the classic AEC reference-signal
   loop lives in the client device/WebRTC, not the agent.
2. **LiveKit Cloud enhanced noise cancellation (Krisp + ai-coustics)** on **inbound** audio to the agent:
   - Krisp plugin `livekit-plugins-noise-cancellation`: **`BVC()`** (Background Voice Cancellation — removes
     *other human speakers*, not just noise), **`NC()`** (standard noise), **`BVCTelephony()`** (SIP/8kHz).
   - ai-coustics plugin `livekit-plugins-ai-coustics`: `QUAIL_VF_S` / `QUAIL_VF_L` (voice-focus / speaker
     isolation), `QUAIL_L`, with `enhancement_level` 0.0–1.0; ships a `VAD()` adapter too.
   - Wired in via `RoomInputOptions(noise_cancellation=noise_cancellation.BVC())`.
3. **Agent built-in AGC** — `AudioInputOptions(auto_gain_control=...)` normalizes inbound levels
   (this is gain, not echo).

Important rule: do **not** stack noise-cancellation models (e.g. Krisp in the frontend *and* in the
agent) — they're trained on raw audio and double-processing degrades results. BVC is what gives clean STT
in multi-speaker rooms; plain WebRTC `noiseSuppression` does not remove other voices.

**Takeaway for the architecture:** LiveKit's AEC depends on a WebRTC stack with a proper render/capture
reference loop. There is no "software AEC inside the Python agent." Krisp/BVC solve *background noise and
background voices*; the *self-echo* (agent hearing its own TTS) is solved by client WebRTC `echoCancellation`
having access to both the playback and capture streams on the same device.

---

## 5. Mapping to Vox (local macOS, no WebRTC)

Vox's weak spots: (1) can't interrupt spoken TTS, (2) speaker/ambient audio is transcribed and false-triggers,
(3) unreliable barge-in. LiveKit's design suggests concrete moves:

1. **Add macOS AEC instead of trying to mute the mic during TTS.** LiveKit's self-echo fix is *device/
   WebRTC AEC with a playback reference*, not muting. On macOS the equivalent is enabling the system
   Voice-Processing I/O audio unit (`kAudioUnitSubType_VoiceProcessingIO`, the AUVoiceProcessing unit) on the
   input — it does AEC + noise suppression against the system output reference. That directly attacks weak
   spot #1 (talk over `say`) and #2 (stop transcribing speaker output). This is the single highest-leverage
   change. If routing `say` through the same device, the VPIO unit can cancel it.
2. **Replace the raw silence timeout with a semantic end-of-turn model.** Vox today ends turns on a fixed
   pause. LiveKit's dynamic `min_delay (0.5s) → max_delay (3.0s)` driven by an EOU probability is the pattern:
   short wait when confident, long wait when the user is likely mid-thought. The **`v1-mini` audio turn
   detector** (CPU-local, transcript-free) or the deprecated-but-open **Qwen2.5-0.5B text** detector on
   faster-whisper transcripts are both runnable locally and would cut both premature cut-offs and laggy ends.
3. **Gate barge-in with `min_interruption_duration` (~0.5s) + `min_interruption_words`, and add
   false-interruption resume.** Vox should require ~0.5s of sustained speech (and optionally ≥1 transcribed
   word) before killing TTS, and — critically — **pause rather than abort** the `say`/LLM so a cough or
   "uh-huh" doesn't discard the reply; resume if silence returns within ~2s. This directly hardens weak
   spot #3. Combine with "adaptive" backchannel filtering so acknowledgements don't interrupt.
4. **Layer detector on VAD, don't replace it; and don't double-denoise.** Keep Silero/your VAD as the cheap
   gate, add the EOU model on top. For noise, pick *one* stage (the OS VPIO unit) rather than stacking
   filters — LiveKit explicitly warns double-processing hurts STT. BVC-style "remove other humans" is only
   needed if Vox runs in shared rooms; for a single-user desktop, AEC + VAD gating covers the real problems.

---

## Sources
- https://docs.livekit.io/agents/build/turns/ (turn detection, endpointing, interruption options)
- https://docs.livekit.io/agents/build/turns/turn-detector/ (audio v1/v1-mini, Qwen2.5-0.5B text detector)
- https://docs.livekit.io/reference/agents/turn-handling-options/ (default values)
- https://docs.livekit.io/transport/media/noise-cancellation/ (BVC/NC/ai-coustics, client WebRTC AEC)
- https://docs.livekit.io/guides/enhanced-noise-cancellation/
- https://github.com/livekit/agents — `livekit-agents/livekit/agents/voice/audio_recognition.py`,
  `agent_activity.py`, `agent_session.py`
- https://blog.livekit.io/using-a-transformer-to-improve-end-of-turn-detection
- https://pypi.org/project/livekit-plugins-noise-cancellation/
- Issue #3515 (min_words vs min_duration), #4325 / #5669 (endpointing delay behavior)
