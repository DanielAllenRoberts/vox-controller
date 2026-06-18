# Voice-Agent Research → Vox

Consolidated findings from **pipecat** and **livekit/agents** across three lenses (flow, interruption, voices), mapped onto Vox's real code. Source detail lives in the six sibling files (`pipecat-*.md`, `livekit-*.md`).

**What Vox is:** local macOS hands-free assistant. faster-whisper `small.en` + energy-VAD (`src/vox/audio.py`), a whisper wake backend (`src/vox/wakeword/backends.py`), three modes (control / assistant / dictation) in `src/vox/core/loop.py`, TTS via the macOS `say` subprocess (`src/vox/tts.py`), two LLM "brains" (DeepSeek small / Claude Opus big).

**The three weak spots this research targets** (from `docs/plan/issues.md`):
- **O1** — can't talk over Vox's spoken TTS (no AEC).
- **O7** — ambient/speaker audio gets transcribed and falsely fires commands/LLM.
- **O8** — barge-in (interrupt the LLM *call*) is unreliable.

---

## Executive summary

- **The two frameworks converge on the same architecture**, and Vox already has the *shape* of it — the gaps are in three specific mechanisms, not the overall design.
- **Vox's barge-in only works because Vox is silent during it.** Both frameworks run VAD/STT *continuously, including while the bot speaks*, and treat interruption as a first-class signal that stops TTS mid-word and cancels the LLM. Vox can't do this because `say` is a fire-and-forget blocking subprocess (`tts.py`) and the mic is deliberately `flush()`ed after speaking — that's the direct cause of O1.
- **Neither framework ships acoustic echo cancellation (AEC).** Both delegate it to the platform: browser/WebRTC `EchoCanceller3` with a playback reference, or Krisp. The macOS-native equivalent is the **VoiceProcessingIO audio unit** (`kAudioUnitSubType_VoiceProcessingIO` / AUVoiceProcessing) — system AEC + AGC + noise suppression that cancels speaker output (incl. video audio) from the mic. **This is the one true fix for both O1 and O7, and it's an audio-I/O task, not an LLM task.** It's an L-effort spike because Vox captures audio via `sounddevice`/PortAudio (`audio.py`), which does not expose VPIO.
- **The cheap, high-ROL win for O7/O8 is a min-words / sustained-duration interrupt gate.** Both frameworks gate barge-in: livekit uses `min_interruption_duration` 0.5 s + `min_interruption_words`; pipecat uses `MinWordsUserTurnStartStrategy`. Vox already has a noise-word filter (`loop._looks_like_noise`) and keyword escalation — extending the same idea to the barge-in listener in `_run_interruptible` is an S-effort change.
- **The barge-in unreliability (O8) is partly self-inflicted:** fast LLM calls finish before the 0.8 s poll loop (`barge_in_poll_seconds`) ever captures an utterance. Both frameworks solve "premature/laggy turn ends" with a **semantic end-of-turn model** — pipecat's `smart-turn-v2/v3` (ONNX, ~8M params, BSD-2) and livekit's audio turn detector `v1-mini` (CPU-local) — replacing fixed silence timeouts with intonation/linguistic detection. M-effort, fits Vox's local-first direction.
- **`say` should be replaced by Kokoro** (open-weight 82M ONNX, Apache-2.0, runs on Apple Silicon, ~80 ms TTFB, **streaming/chunked**). Both frameworks support it; it's the cleanest neural-local upgrade for a public repo. Streaming output is also a prerequisite for *interruptible* TTS — you can drop unplayed chunks the way `_audio_queue.reset()` does, which `say` can't.
- **Sentence-chunked streaming TTS is a quick latency win** independent of engine: speak the LLM reply sentence-by-sentence as tokens arrive instead of waiting for the whole reply, moving Vox from additive latency toward `max(stages)`.
- **Open question — ordering:** AEC (VPIO) is the highest-impact fix but the biggest lift and a hardware/driver spike. The gate + streaming-TTS + Kokoro wins are independently shippable and de-risk the AEC work (you want killable streaming TTS *before* talk-over is useful anyway). Recommended path below sequences them.

---

## 1. Interaction flow — pipecat vs livekit

Both build the same cascade: **mic → VAD → STT → LLM → TTS → speaker**, and both make it *streaming* so end-to-end latency tends toward `max(stage)` rather than the sum.

**pipecat** — everything is a typed **`Frame`** flowing through a linear chain of **`FrameProcessor`s** (`Pipeline`), connected only by `push_frame()`; no central router. The frame's *base class* decides interruption behavior: `DataFrame`/`ControlFrame` are queued and **dropped on interruption**; `SystemFrame` is high-priority, **bypasses the queue, and survives interruption** (this is how the interrupt signal and raw audio get through). STT is split into streaming (`STTService`, emits interim then final) vs **`SegmentedSTTService`** (VAD-gated, buffers between speech-start/stop, one final transcript, keeps a small pre-roll) — **Vox's faster-whisper is exactly the segmented pattern**, including the pre-roll (`audio.py` `preroll_frames`).

**livekit/agents** — `AgentSession` orchestrates pluggable `vad`/`stt`/`llm`/`tts`; each stage is an **async generator** (`AsyncIterable → AsyncIterable`) with overridable nodes on the `Agent` (`stt_node`, `llm_node`, `tts_node`, `transcription_node`). Vox's stack is livekit's **cascade** shape (~90% of their prod). Latency comes from three stacked streams: interim STT partials (<200 ms), LLM token deltas piped mid-sentence into `tts_node`, and TTS audio frames written as produced. `preemptive_generation` (default **True**) even starts the LLM *before* end-of-turn is confirmed.

| Dimension | pipecat | livekit/agents | Vox today |
|---|---|---|---|
| Core abstraction | Typed `Frame`s through `FrameProcessor` pipeline | Async-generator nodes in `AgentSession` | Imperative state machine (`loop.py`) |
| STT pattern | Streaming **or** `SegmentedSTTService` (VAD-gated) | Streaming `stt_node` (interim + final) | Segmented (VAD-gated faster-whisper) ✅ matches |
| LLM→TTS coupling | Token frames aggregated per-sentence (`SENTENCE`/`TOKEN`) | LLM `ChatChunk` deltas piped into `tts_node` | **Blocking**: full reply, then `say` ❌ |
| TTS output | `run_tts()` yields `TTSAudioRawFrame` chunks | `tts_node` yields `rtc.AudioFrame` | One blocking `say` subprocess ❌ |
| Latency model | `max(stage)` via streaming | `max(stage)` via streaming + preemptive gen | Additive (STT → full LLM → full TTS) ❌ |
| Interrupt signal | `InterruptionFrame` (SystemFrame) | `SpeechHandle.interrupt()` | Poll loop in `_run_interruptible` (LLM-call only) ⚠️ |
| AEC | Delegated to transport (WebRTC/Krisp) | Delegated to client/WebRTC APM + Krisp | **None** ❌ |

**Takeaway:** Vox's segmented-STT + pre-roll already matches best practice. The flow gap is the **blocking LLM→TTS seam** — adopting sentence-chunked streaming output is the structural change that unlocks both lower latency *and* interruptible speech.

---

## 2. Interruption & turn-taking (the core problem)

Both frameworks decompose this into **three independent layers**. Vox conflates them.

### Layer A — Voice activity & barge-in *detection*

- **VAD runs continuously, even while the bot speaks.** pipecat: `SileroVADAnalyzer` (`VADParams`: confidence 0.7, start_secs 0.2, stop_secs 0.2). livekit: Silero VAD. This is the first thing Vox lacks during TTS — Vox `flush()`es the mic instead of listening (`loop.py` lines 258/335).
- **Barge-in is *gated*, not raw VAD energy.** This is the fix for false triggers:
  - livekit `InterruptionOptions`: `min_interruption_duration` **0.5 s**, `min_interruption_words` (needs STT), `false_interruption_timeout` **2.0 s**, `mode="adaptive"`.
  - pipecat `MinWordsUserTurnStartStrategy(min_words=N)` — a barge-in is only accepted once N *transcribed words* land.
- **Learned acoustic gates (heavyweight).** livekit's **Adaptive Interruption Handling** (audio-encoder + CNN over the first ~200 ms of overlap, ~30 ms inference) **rejects ~51% of VAD barge-ins** as backchannel/noise. pipecat's `smart-turn` family doubles as this.

### Layer B — End-of-turn (is the *user* done?)

Both replace fixed silence timeouts with a **semantic end-of-turn model** that reads intonation/rhythm/linguistics, with a **dynamic endpointing delay**:

- **pipecat smart-turn**: `LocalSmartTurnAnalyzerV3` — **Whisper-Tiny encoder + linear head, ~8M params, ONNX, ~10–100 ms CPU, BSD-2, 23 langs.** On a VAD pause, classifies the last ~8 s as complete/incomplete. `SmartTurnParams`: `stop_secs` 3.0 hard fallback, recommends VAD `stop_secs ≈ 0.2` so the model decides.
- **livekit turn detector**: `inference.TurnDetector()` — audio detector `v1`(cloud)/`v1-mini`(CPU-local), AUC 0.96, no transcript needed; or the (now-deprecated) text detector = **Qwen2.5-0.5B-Instruct** over the STT transcript (~500 MB, local CPU). Dynamic delay: `min_endpointing_delay` **0.5 s** → if "likely continuing", `max_endpointing_delay` **3.0 s**.

Vox uses a single fixed `silence_seconds` (0.8 control / 1.2 assistant) energy threshold — premature on trailing pauses, laggy when a real pause ends the turn. A local semantic model fixes both.

### Layer C — Stopping the agent (TTS + LLM)

- **pipecat:** `InterruptionFrame` (SystemFrame) propagates through every processor in one signal. `BaseOutputTransport.handle_interruptions()` does `self._audio_queue.reset()` — **dumps buffered TTS audio immediately, cuts mid-word**; the LLM aggregator flushes and cancels the in-flight stream; word timestamps truncate context to exactly the words spoken.
- **livekit:** `SpeechHandle.interrupt()` → `output.audio.pause()` (**pause, not hard-stop**), truncates chat history to what the user actually *heard* (via `TimedString`), cancels the in-flight LLM task. If the user goes silent again within `false_interruption_timeout` (2 s), the paused reply **resumes** — this resume-on-false-trigger is a big part of why barge-in *feels* reliable.

Vox's `_run_interruptible` (`loop.py`) is a CPU-thread + poll-loop version of this — correct in spirit, but: (1) it only covers the **LLM call**, when Vox is silent; (2) Python can't kill the worker thread, so an abandoned quick action may still complete (issue O4); (3) there's no equivalent for stopping `say` because `say` blocks.

### Echo cancellation — **neither framework ships it**

Both explicitly delegate AEC to the platform:
- **WebRTC APM** (`webrtc::EchoCanceller3`, `echoCancellation: true`) on the client device, with the playback stream as the reference signal.
- **Krisp SDK** (`KrispVivaFilter` / `livekit-plugins-noise-cancellation` `BVC()`/`NC()`) — but note: livekit's `BVC` and pipecat's Krisp/RNNoise/Koala filters are **noise suppression / voice isolation on the input**, *not* reference-based echo cancellation. They reduce ambient/other-human voices; they do **not** cancel the agent's own output reliably.
- **`aec_warmup_duration`** (livekit) — ignore the mic for N seconds after the bot starts speaking, a cheap stopgap.

**The macOS-native AEC** both would use on this platform is the **VoiceProcessingIO audio unit** (`kAudioUnitSubType_VoiceProcessingIO`, a.k.a. AUVoiceProcessing) — system AEC + AGC + noise suppression that references the system output, so it cancels *everything the speakers play* (TTS and video/music alike). That is the real fix for both O1 (talk over TTS) and O7 (speaker audio falsely transcribed). It is not reachable through `sounddevice`/PortAudio as currently used in `audio.py`.

---

## 3. Voices / TTS

Both frameworks make TTS a thin pluggable interface (pipecat `TTSService.run_tts()` yielding `TTSAudioRawFrame`; livekit `TTS` base with `synthesize()`/`stream()`), so any engine drops in without touching the loop. Vox already has this seam (`tts.speak()`), just with one backend.

| Engine | Type | Streaming | Licence / cost | Fit for Vox |
|---|---|---|---|---|
| macOS `say` | Local (OS) | No (blocking subprocess) | Free, built-in | Current; zero-dep fallback. Can't be interrupted mid-word |
| **Kokoro** (82M) | **Local ONNX** | **Yes (chunked)** | **Apache-2.0, free** | **Best upgrade** — Apple-Silicon-friendly, ~80 ms TTFB, clean licence for a public repo |
| Piper | Local | Yes | **GPL** | Works, but GPL is awkward for a permissive public repo |
| XTTS / Coqui | Local | Yes | Non-commercial, heavy | Voice cloning, but licence + size rule it out |
| Cartesia (Sonic) | API | Yes + word timestamps | Paid | Optional "quality tier" (mirrors small/big brain); breaks local-first |
| ElevenLabs (Flash/Turbo) | API | Yes | Paid | Best quality, paid; opt-in premium only |
| Deepgram Aura / Rime | API | Yes | Paid | Alternatives to the above |
| Orpheus / Sesame CSM | Local-ish | — | — | Not native in either framework; would need custom integration |

**Local path detail:** livekit doesn't even ship a Kokoro plugin — it runs **Kokoro-FastAPI** behind an OpenAI-compatible endpoint (`openai.TTS(base_url=..., model="kokoro", voice="af_alloy")`). Same trick works for Piper-server. pipecat ships `KokoroTTSService` directly.

**Recommendation:** Kokoro local as the new default, `say` kept as a zero-dependency fallback, cloud (Cartesia/ElevenLabs) as an opt-in premium tier matching Vox's small/big-brain pattern. Disk note (O6): Kokoro is ~few-hundred MB — check the budget, but far smaller than XTTS.

---

## 4. Recommendations for Vox (prioritized)

Effort: **S** ≤ half-day · **M** ~1–3 days · **L** multi-day / spike. Each maps to real files.

### Tier 1 — Quick wins (do first; independently shippable)

**R1 · Gate the barge-in listener (min-words + sustained duration)** — **S, high impact** — fixes O7 & O8.
In `loop._run_interruptible` (`loop.py`), before accepting a captured utterance as an interrupt, require it to be non-trivial: reuse `_looks_like_noise` *and* add a minimum word count / sustained-speech check, mirroring livekit's `min_interruption_duration` 0.5 s + `min_interruption_words` and pipecat's `MinWordsUserTurnStartStrategy`. Add `barge_in_min_words` / `barge_in_min_seconds` knobs to `config.py`. Directly stops ambient audio from thrashing the interrupt listener.

**R2 · Reserve barge-in for slow calls** — **S, medium impact** — fixes O8.
O8's root cause is that fast calls finish before the 0.8 s poll ever fires. Skip the interrupt-listener thread for calls expected to be fast (deterministic-ish executor actions) and only spin it up for chat/compose/vision. Cheap branch in `_run_interruptible` / its callers in `_control_mode` and `_assistant_mode`.

**R3 · `aec_warmup`-style mute-while-speaking is already partly done** — **S, low effort** — partial O2/O7.
Vox's `mic.flush()` after TTS (`loop.py` 258/335) is the crude version. Make it explicit: ignore mic input for a short warmup window when TTS *starts* (livekit's `aec_warmup_duration`) rather than only flushing after. This is a stopgap, **not** a substitute for real AEC — note it can't enable talk-over (O1).

### Tier 2 — Structural upgrades (unlock interruptible speech + better turns)

**R4 · Replace `say` with Kokoro (local ONNX) behind the existing `speak()` seam** — **M, high impact** — O1 prerequisite + quality.
`tts.py` already documents "swap for a neural local TTS later behind this same speak() interface." Add a streaming Kokoro backend (direct ONNX, or Kokoro-FastAPI + OpenAI client per livekit). Keep `say` as fallback. Check disk budget (O6). This is also the prerequisite for R5 — `say` cannot drop unplayed audio.

**R5 · Sentence-chunked, killable streaming TTS** — **M, high impact** — fixes O1 (the talk-over mechanism), needs R4.
Speak the LLM reply sentence-by-sentence as it streams (pipecat `SENTENCE` aggregation / livekit token-deltas-into-tts_node) and hold a handle to the audio so a confirmed barge-in can **drop unplayed chunks mid-utterance** (pipecat `_audio_queue.reset()`) and **truncate chat history to what was actually spoken** (livekit `TimedString`). This is the LLM-call barge-in pattern (`_run_interruptible`) extended to TTS. **Caveat:** without AEC (R7) the mic still hears Vox, so this is only fully usable on headphones until R7 lands — but it's the correct mechanism and de-risks R7.

**R6 · Local semantic end-of-turn model** — **M, medium-high impact** — fixes O8 + premature/laggy turn ends.
Replace the fixed `silence_seconds` energy threshold (`audio.py` `capture_utterance`) with a semantic EOU model on VAD pauses, plus livekit's dynamic `0.5 s → 3.0 s` delay. Vendor **smart-turn-v3 ONNX** (~8M params, BSD-2, ~10–100 ms CPU) or livekit's audio `v1-mini`. Local, small, open — fits Vox's direction. Pair with a real VAD (Silero) replacing the RMS gate for cleaner onsets (helps barge-in reliability too).

### Tier 3 — The real AEC fix (biggest lift, highest ceiling)

**R7 · macOS VoiceProcessingIO audio unit for true AEC** — **L, highest impact** — the only real fix for O1 *and* O7.
Route mic capture through `kAudioUnitSubType_VoiceProcessingIO` (AUVoiceProcessing) so the system cancels speaker output (TTS *and* video/music) from the mic, and play TTS through the same device for the reference signal. This is what both frameworks rely on the platform to provide; on macOS it's native and free. **The lift:** Vox captures via `sounddevice`/PortAudio (`audio.py`), which doesn't expose VPIO — this needs a CoreAudio/AudioUnit (or AVAudioEngine via a small native shim/PyObjC) input path. Spike it as a standalone experiment before committing. Once it lands, R5's talk-over works on speakers, and O7's ambient-audio false triggers largely disappear without keyword-gating.

### Explicitly out of scope / not recommended now
- **Krisp / BVC / RNNoise voice isolation** — these are noise suppression, **not** AEC; they won't cancel Vox's own voice. Only worth it for multi-speaker rooms, which a single-user desktop isn't. Don't stack with VPIO (both frameworks warn double-processing hurts STT).
- **Full framework adoption (pipecat/livekit)** — both assume a WebRTC transport and an async pipeline runtime; porting Vox's imperative `loop.py` state machine wholesale is a rewrite with little payoff. **Borrow the mechanisms, not the runtime.**

### Suggested sequence
R1 + R2 (a day, immediate O7/O8 relief) → R4 → R5 (interruptible neural TTS; O1 on headphones) → R6 (turn quality) → R7 spike (true AEC; O1/O7 on speakers).

---

## Open questions
- **Disk (O6):** Kokoro + smart-turn ONNX together are several hundred MB. Confirm the budget (memory note says ~11–13 GB free as of the dashboard build, may have eased).
- **VPIO via Python:** can VPIO be reached cleanly from Python on Apple Silicon (PyObjC/AVAudioEngine) without a compiled native extension? This determines whether R7 is "hard" or "very hard." Needs a spike.
- **Whisper latency under streaming:** sentence-chunked TTS assumes the LLM streams tokens; DeepSeek (small brain) and the Claude SDK (big brain) streaming behavior through Vox's `assistant`/`executor` layers needs verifying before R5.
- **smart-turn vs Vox's segmented STT:** smart-turn wants raw audio at the VAD pause; confirm it composes with faster-whisper's segmentation rather than fighting it.
