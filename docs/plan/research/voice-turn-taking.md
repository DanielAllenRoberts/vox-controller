# Turn-Taking in Production Voice Agents — Research for Vox

How the best documented voice-agent stacks decide *when the user is done talking* and
*when it's OK to be interrupted*. Goal: improve Vox's turn-taking beyond energy-VAD +
trailing-silence and the current `[OPEN]`/`[DONE]` LLM tagging.

The universal lesson: **raw silence-based VAD is the wrong primary signal.** Everyone
layers a *semantic* end-of-turn (EOU) decision on top of VAD, and dynamically adjusts the
silence timeout based on whether the utterance *sounds/reads* finished.

---

## Concepts (the vocabulary everyone shares)

- **VAD (Voice Activity Detection):** frame-level speech/silence classifier. Cheap, fast,
  language-agnostic. Knows *that* there's sound, not *what* it means. Silero VAD is the de
  facto open model (runs <1ms per 30ms chunk on CPU). Vox's RMS-threshold VAD is the
  crudest tier of this.
- **Endpointing:** the decision "the turn is over → fire the pipeline." Two flavors:
  - *Silence/VAD endpointing*: wait for a pause longer than a fixed threshold. Simple but
    forces a latency/cutoff tradeoff: an 800ms timeout adds ~1s to *every* response, yet a
    short timeout cuts people off mid-thought.
  - *STT endpointing*: the STT provider emits a "finalized" signal from punctuation/grammar
    in the transcript (Deepgram `speech_final`, `UtteranceEnd`). LiveKit calls this **the
    best default for most production agents** — faster than VAD, semantically aware.
- **Semantic EOU / "smart turn":** a *model* predicts turn completion from acoustic
  (intonation, pace, filler words) and/or linguistic content, not silence. Can fire
  *before* the trailing silence even elapses → lowest latency, fewest false cutoffs.
- **Barge-in / interruption:** user talks over the agent. Requires keeping VAD/turn
  detection **active during TTS playback**, then flushing TTS and handing the floor back.
  Target: <150ms from user-speech-onset to TTS stop. Happens in ~1 in 5 calls.
- **Backchanneling:** short "uh-huh"/"yeah" the agent emits to show it's listening — and,
  crucially, the inverse problem: *not* treating the user's "mhm"/"um" as a real turn or a
  real interruption.
- **Filler / "thinking" handling:** "um", "えーと" should *extend* the turn (user isn't
  done), not end it. Transcript-only systems often drop fillers; audio models can keep them.
- **Latency budget (voice-to-voice):** <500ms feels natural, <800ms acceptable, >1500ms
  "broken." Typical budget: VAD/capture ~50ms, STT ~150ms, LLM TTFT ~400ms, TTS first
  chunk ~150ms. **Endpointing delay is pure dead time on top of this**, so the EOU decision
  is one of the highest-leverage latency knobs in the whole pipeline.

---

## Pipecat (pipecat-ai)

A pipeline of frame processors; each turn flows as typed frames (`UserStartedSpeakingFrame`,
`UserStoppedSpeakingFrame`, plus raw `VADUserStarted/StoppedSpeakingFrame`). Turn-taking is
a two-layer design:

1. **Silero VAD** (`SileroVADAnalyzer`) does fast frame-level speech detection. Key
   `VADParams`:
   - `start_secs` (0.2) — speech must persist this long to confirm onset.
   - `stop_secs` (0.2) — silence this long to confirm cessation. **This is the main
     turn-latency knob.**
   - `confidence` (0.7), `min_volume` (0.6).
2. **Smart Turn** (semantic VAD) decides whether the *completed* VAD segment is actually a
   finished thought. Default analyzer in recent versions is `LocalSmartTurnAnalyzerV3`.

```python
vad = SileroVADAnalyzer(params=VADParams(confidence=0.7, start_secs=0.2, stop_secs=0.2))
# Smart Turn runs when VAD detects silence; only then is UserStoppedSpeakingFrame emitted.
```

When Silero detects silence, Smart Turn runs on the buffered turn audio; only if it says
"complete" does the real `UserStoppedSpeakingFrame` fire. Otherwise the agent keeps
listening through the pause. Interruptions are on by default (`enable_interruptions`): user
speech mid-TTS clears pending audio/text and resets for new input.

Tradeoff Pipecat documents: local VAD is ~150-200ms faster than a remote VAD service, but
`stop_secs` must be tuned per acoustic environment.

### Smart Turn — the open-source semantic VAD model (most relevant to Vox)

A standalone, Apache-licensed model that says "has this speaker finished?" **from the raw
16kHz waveform, not the transcript.** It is explicitly trained to recognize fillers ("um",
"hmm", "えーと") that STT drops, capturing intonation/pace. Run pattern: **Silero detects
silence → run Smart Turn on the whole turn (truncated to the last ≤8s) → ≥0.5 prob = done.**

- **v2:** wav2vec2 backbone + linear head, 360MB, 14 languages. Trained on synthetic TTS
  (Google Chirp3) + human recordings; sentences cleaned by Gemini 2.5 Flash, fillers
  inserted by LLM to synthesize *incomplete* utterances. GPU inference 12-75ms — **but CPU
  inference is 410-6272ms, far too slow for a real-time CPU-only loop.**
- **v3 (current):** **Whisper-tiny encoder + linear head, ~8M params, int8-quantized ONNX
  only 8MB (fp32 32MB), ~12ms on CPU.** 23 languages. This is the version that makes
  semantic turn detection viable *without a GPU* — directly relevant to Vox.
- Input: 16kHz mono PCM, ≤8s window, zero-padded **at the beginning** (real audio sits at
  the end). Output: single probability, threshold 0.5. Accuracy ~99% on human English,
  87-97% synthetic-by-language.
- `USE_ONLY_LAST_VAD_SEGMENT=True`: only feed the most recent VAD speech segment to the
  model, not the entire buffered turn — avoids stale context dragging the prediction.

Note: there's no built-in "max turn" — you still need a fallback hard timeout for when the
model never says done (user trails off without a clean ending).

---

## LiveKit Agents

Offers a menu of turn strategies and is explicit about the tradeoffs:

| Mode | What it uses | Tradeoff |
|------|--------------|----------|
| **Turn-detector model** (recommended) | open-weights transformer + Silero VAD | contextual, low latency; needs STT text |
| **STT endpointing** | provider phrase-endpoints (AssemblyAI for semantic) | "best default"; less interruption-responsive without VAD |
| **VAD-only** | Silero silence | simple, language-agnostic, *adds the most latency* |
| **Realtime models** | OpenAI/Gemini server-side | provider-handled, less control |
| **Manual** | `session.commit_user_turn()` etc. | full app control |

### The LiveKit EOU transformer (a different design from Smart Turn)

- **135M-param transformer fine-tuned from SmolLM v2.** Operates on **text, not audio** —
  each transcribed word is appended to its context; uses a **sliding window of the last 4
  turns**, so it's *context-aware* (knows what the agent just asked). English-only.
- It does **not** replace VAD — it **dynamically shortens/extends the VAD silence timeout**
  using the model's probability. High "not done" prob → extend the wait; high "done" prob →
  fire early.
- Results: **−85% unintentional interruptions**; only 3% of the time wrongly says "not
  over." Inference ~50ms.

### Endpointing & interruption config

- `EndpointingOptions`: `min_delay` / `max_delay` bound the wait after speech; dynamic
  endpointing adapts to per-session pause stats.
- `InterruptionOptions`: `mode="adaptive"` (default — distinguishes real interruptions from
  backchannels) vs `"vad"`; `min_duration`, `min_words` gate what counts as an interruption
  (filters out "mhm").
- **False-interruption handling:** VAD fires but STT returns empty (cough, background) →
  after `false_interruption_timeout` with no transcript, optionally
  `resume_false_interruption=True` to continue speaking from where it left off.

Two design ideas worth stealing: (1) gate interruptions on `min_words`/`min_duration`, not
raw energy; (2) the dynamic-timeout-from-model-probability pattern.

---

## Vapi / Retell / Deepgram (config-level patterns)

**Deepgram** (streaming STT — the endpointing primitives):
- `endpointing=<ms>`: VAD-based; emits `speech_final=true` after that much silence.
- `utterance_end_ms` (+ required `interim_results=true`): watches gaps between *finalized
  words* and emits an `UtteranceEnd` message. Interim results land ~every 1s, so values
  <1000ms add nothing. Recommended logic: fire on `speech_final=true`; else fire on
  `UtteranceEnd` if no preceding `speech_final`. This is "STT endpointing" done concretely.

**Vapi** (`startSpeakingPlan` / `stopSpeakingPlan`):
- Start (when to *respond*): `waitSeconds` (0.4 default) final delay; smart-endpointing via
  LiveKit (English) using a wait-vs-confidence curve, or transcription-based:
  ```json
  "transcriptionEndpointingPlan": {
    "onPunctuationSeconds": 0.1,   // sentence looks complete → respond fast
    "onNoPunctuationSeconds": 1.5, // ambiguous → wait longer
    "onNumberSeconds": 0.5
  }
  ```
  The key insight: **the silence timeout is conditioned on transcript content** (punctuation
  ⇒ short, mid-number/no-punctuation ⇒ long).
- Stop (interruption): `numWords` (0=pure VAD ~50-100ms; >0 requires N transcribed words ⇒
  more accurate, +200-500ms), `voiceSeconds` (0.2), `backoffSeconds` (1.0 — block output
  after a user interruption).

**Retell** (turn-taking model + tunable knobs):
- A turn-taking model using prosody (pitch/intonation/timing) + semantics + context;
  recognizes rising intonation (question, not done) vs final statement.
- `interruption_sensitivity` 0-1 (lower ⇒ needs longer/more words to interrupt; 0 ⇒ never).
- `enable_backchannel` + frequency + word list ("yeah", "uh-huh"); more on longer utterances.
- `reminder_trigger_ms` (default 10000) + `reminder_max_count` (default 1): re-prompt when
  the user goes silent — a re-engagement pattern Vox could use in ASSISTANT mode.

---

## How this applies to Vox

Vox is CPU-only local Whisper, latency-sensitive, with energy-VAD + trailing-silence and a
new `[OPEN]`/`[DONE]` LLM tag. The biggest gap: turn-end is decided by **fixed silence
alone**, so it both cuts people off and feels laggy, and the `[OPEN]`/`[DONE]` tag only
predicts the *agent's* next move, not *when the user is done*. Prioritized:

1. **Make the trailing-silence threshold content-conditioned (cheap win, highest ROI).**
   Copy Vapi's pattern: after Whisper transcribes a segment, if it ends in terminal
   punctuation/looks like a complete clause, fire fast (~0.2-0.3s); if it ends mid-word, on
   a filler, on a number, or with no punctuation, extend the wait (~1.0-1.5s). This alone
   removes most premature cutoffs with zero new models.

2. **Replace RMS-threshold VAD with Silero VAD (cheap win).** It's a tiny CPU model
   (<1ms/chunk), far more robust to noise than an energy threshold, and is the shared
   foundation every framework builds on. Use it for both onset and silence gating
   (`start_secs`~0.2, `stop_secs`~0.2 as a starting point, then tune).

3. **Add Smart Turn v3 as the semantic EOU gate (medium lift, the real upgrade).** It's the
   only credible *audio* turn model that runs on CPU (~12ms, int8 ONNX, 8MB). Wire it like
   Pipecat: Silero detects silence → run Smart Turn on the last ≤8s of turn audio → ≥0.5 =
   done, else keep listening. This directly fixes the "talked over me during a pause"
   problem and, unlike Whisper, keeps fillers. Keep a hard max-turn fallback timeout (e.g.
   ~8-10s) since the model has no built-in cap.

4. **Repurpose `[OPEN]`/`[DONE]` for re-engagement, not user-EOU (cheap win).** They're a
   property of the *agent's* reply, so use them like Retell's reminder: after a `[OPEN]`
   reply, if the user stays silent for N seconds, re-prompt or extend listening; after
   `[DONE]`, end the turn and stop the mic sooner. Don't use them to decide when the *user*
   finished — that's what VAD+Smart Turn is for.

5. **Gate interruptions/barge-in on words+duration, not energy (medium lift, only if Vox
   ever talks over TTS).** Keep VAD active during any spoken output; require a minimum
   speech duration AND ≥1 real transcribed word before treating it as a true barge-in
   (LiveKit `min_words`/`min_duration`, Vapi `numWords`). Implement false-interruption
   handling: if VAD fires but Whisper returns empty/noise, resume instead of aborting. Adds
   robustness against coughs/background and the user's own "mhm".

6. **Set explicit latency budgets and prefer streaming where possible (medium lift).** Target
   <800ms perceived. Every 100ms of silence timeout is pure dead time, which is exactly why
   #1 and #3 (firing as soon as the turn *reads/sounds* done, before the full silence
   window) matter. If feasible, feed Whisper incrementally rather than only after full
   silence.

7. **Borrow LiveKit's dynamic-timeout-from-probability idea if you skip Smart Turn (cheap
   variant of #3).** Even without an EOU model, you can scale the silence timeout by a cheap
   heuristic confidence (punctuation + clause completeness + trailing-filler detection),
   approximating "shorten when confident it's done, extend when not."

8. **Don't over-build (per CLAUDE.md "Simplicity First").** Skip server-side realtime turn
   models, backchanneling TTS, and multilingual EOU — Vox is local/personal. The minimal
   high-value stack is: **Silero VAD + content-conditioned silence timeout + Smart Turn v3 +
   a hard fallback timeout**, with `[OPEN]`/`[DONE]` demoted to re-engagement.

**Cheap wins:** #1, #2, #4, #7. **Bigger lifts:** #3 (Smart Turn integration), #5 (barge-in,
only if needed), #6 (streaming Whisper).

---

## Sources

- Pipecat — Speech Input & Turn Detection: https://docs.pipecat.ai/pipecat/learn/speech-input
- Pipecat — Smart Turn (Cloud guide): https://docs.pipecat.ai/pipecat-cloud/guides/smart-turn
- Smart Turn GitHub: https://github.com/pipecat-ai/smart-turn
- Smart Turn v2 (HF + blog): https://huggingface.co/pipecat-ai/smart-turn-v2 · https://www.daily.co/blog/smart-turn-v2-faster-inference-and-13-new-languages-for-voice-ai/
- Smart Turn v3 (HF): https://huggingface.co/pipecat-ai/smart-turn-v3
- LiveKit — Turn detection & interruptions: https://docs.livekit.io/agents/v1/build/turn-detection
- LiveKit — VAD vs endpointing vs model-based: https://livekit.com/blog/turn-detection-voice-agents-vad-endpointing-model-based-detection
- LiveKit — Transformer EOU model: https://livekit.com/blog/using-a-transformer-to-improve-end-of-turn-detection
- Deepgram — Utterance End: https://developers.deepgram.com/docs/utterance-end
- Deepgram — Endpointing & interim results: https://developers.deepgram.com/docs/understand-endpointing-interim-results
- Vapi — Voice pipeline configuration: https://docs.vapi.ai/customization/voice-pipeline-configuration
- Retell — VAD vs turn-taking endpoints: https://www.retellai.com/blog/vad-vs-turn-taking-end-point-in-conversational-ai
- Retell — Update agent (config params): https://docs.retellai.com/api-references/update-agent
- Latency budgets / barge-in: https://sayna.ai/blog/sub-second-voice-agent-latency-practical-architecture-guide · https://hamming.ai/resources/voice-ai-latency-whats-fast-whats-slow-how-to-fix-it
