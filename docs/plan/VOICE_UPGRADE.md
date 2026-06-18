# Vox voice-loop upgrade — implementation plan & loop log

> Implements the quick/medium/big recommendations from `docs/plan/research/voice-agents/RESEARCH.md`.
> Built in **5 loops**, each: build → verify-what's-verifiable → iterate.
>
> **SAFETY INVARIANT:** every new path is behind a **feature flag with a fallback to today's behavior**.
> With flags at their DEFAULTS, the daemon runs **exactly as now**. I can't drive the mic, so I verify
> `py_compile` / import / model-load / unit-tests / sample synthesis; the *feel* (barge-in
> responsiveness, AEC quality, latency) is the user's **live acceptance test**. Uncommitted on `staging`
> (no-commit rule) — present each loop for review, never commit.

## Feature-flag map (all in `config.py`, read via the guarded `_setting`/`CONFIG` path)
- **Barge-in gates** — ON by default (pure wins). Knobs: `interrupt_min_words`, `interrupt_min_seconds`, `interrupt_slow_calls_only`.
- **`tts_engine`** — `"say"` (default) | `"kokoro"`. Kokoro lazy-loads; ANY error falls back to `say`.
- **`turn_detection`** — `"vad"` (default) | `"smart_turn"`. Lazy-loads the ONNX model; falls back to fixed-timeout VAD.
- **`audio_aec`** — `false` (default) | `true`. VoiceProcessingIO mic path; falls back to the sounddevice mic.

## Loops
1. **Barge-in reliability** (#1 min-words + sustained-duration gate, #2 reserve barge-in for slow calls) — `core/loop.py` `_run_interruptible` + `_looks_like_noise` + `config.py`. Default ON. Targets O7/O8.
2. **Kokoro TTS** (#3) — `tts.py` `speak()` seam, lazy model, fallback to `say`. Opt-in. Better local voice.
3. **Killable streaming TTS** (#4) — sentence-chunked, interruptible playback (the talk-over fix on headphones). Opt-in; builds on #2.
4. **Semantic turn-detection** (#5) — smart-turn-v3 ONNX + dynamic endpointing (0.5→3.0 s). Opt-in.
5. **VPIO/AEC** (#6) + final review — native macOS VoiceProcessingIO mic path, flagged, fallback to sounddevice. **Riskiest; treated as a careful spike — needs live-mic validation by the user.**

## Status

**All 5 loops DONE (final review passed 2026-06-18).** Every touched file compiles; the full
daemon (`vox.core.loop`) and web server (`create_app`) import cleanly; `/api/settings` returns all
7 new Voice settings (typed/validated); at defaults the system behaves as original Vox (no
`AVFoundation`/`kokoro_onnx` loaded, smart-turn deferred); the AEC factory is wired into
`loop.py` and verified end-to-end. Remaining work is **live human acceptance only** (mic+speaker
quality), per the checklist below — code is complete and reviewed.

- Loop 1 — Barge-in reliability: **DONE (code reviewed; awaiting live mic acceptance)**
- Loop 2 — Kokoro TTS: **DONE (default OFF; verified by sample synthesis + fallback)**
- Loop 3 — Killable streaming TTS: **DONE (default OFF; verified streaming synth + <300 ms kill + fallback; gated to tts_interruptible AND tts_engine=="kokoro")**
- Loop 4 — Semantic turn-detection: **DONE (default OFF/"vad"; onnxruntime deferred; model loads + classifies, fixed-silence fallback verified)**
- Loop 5 — VPIO/AEC: **DONE (default OFF; factory wired into loop.py; native VPIO capture yields correct 1280-sample int16 @16kHz frames locally; hard fallback to sounddevice MicStream verified; AEC *quality* needs the user's live mic+speakers)**

### Loop 1 — barge-in reliability

**What changed** (additive + guarded; all knobs read via the existing `_setting`/`CONFIG` path):

- **`config.py`** — three new knobs next to the existing barge-in settings:
  - `interrupt_min_words: int = 1` — a mid-call barge-in needs ≥ this many *transcribed* words.
  - `interrupt_min_seconds: float = 0.4` — and the captured audio must be at least this long.
  - `interrupt_slow_calls_only: bool = True` — only arm the interrupt-listener for SLOW calls.
- **`core/loop.py`**
  - New `_passes_interrupt_gate(audio, text, cfg)` — the **min-words + sustained-duration gate**
    (livekit `min_interruption_duration`/`min_interruption_words` + pipecat `MinWords…`). A captured
    utterance is only treated as a barge-in candidate if it's ≥ `interrupt_min_seconds` of audio
    AND carries ≥ `interrupt_min_words` words. Ambient TV/chatter that leaks one short word no
    longer cancels the in-flight call (O7). Applied in `_run_interruptible` right after transcription,
    before any abort/sleep/quit/redirect dispatch.
  - `_run_interruptible(..., slow=True)` — new `slow` flag. With `interrupt_slow_calls_only` on
    (default), barge-in is **not armed for fast calls** — they finish before the 0.8 s poll fires
    anyway, so arming there only burns a capture window and risks a spurious cancel (O8).
  - **Call sites:** control-mode `executor.execute` is small-brain-first → `slow=False` (fast, not
    armed by default); assistant-mode `respond_turn` is the conversational big-answer path →
    `slow=True` (armed). The truly deterministic commands never reach `_run_interruptible` (gated
    earlier by `actions.parse`/`_looks_like_noise`/`_wants_escalation`), so they're unaffected.

**Defaults improve behavior without breaking the daemon:** no new top-level imports, every knob is
read through the guarded `_setting` fallback, and `barge_in_enabled` still master-gates everything.

**How to test it live**
1. Run Vox, enter ASSISTANT mode, ask a question that yields a long spoken reply, then say
   **"go to sleep"** (or "stop") over it — the call should cancel cleanly. A short cough / one-word
   blip during the reply should **no longer** cancel it (the gate rejects it).
2. In CONTROL mode, fire a quick small-brain command — it should complete without a barge-in capture
   window (snappier; no spurious mid-call cancel). To re-arm barge-in on fast calls, set
   `interrupt_slow_calls_only=false` (or the dashboard equivalent).
3. Tuning: raise `interrupt_min_words`/`interrupt_min_seconds` if ambient audio still interrupts;
   lower them (e.g. `interrupt_min_seconds=0.0`) to restore pre-loop-1 eagerness.

### Loop 2 — Kokoro TTS

**What changed** (additive + guarded; default config = today's Vox, `say` byte-for-byte unchanged):

- **Dependency** — `uv add "kokoro-onnx>=0.5.0"` → resolved **kokoro-onnx 0.5.0**. It's the
  lightweight ONNX distribution: runs on **onnxruntime (1.20.1, within our existing
  `<1.21` pin) — NO PyTorch**, Apple-Silicon-friendly, Apache-2.0. Pulls espeakng-loader
  (bundles the espeak-ng phonemizer lib + data, no system install) and phonemizer-fork.
- **`config.py`** — three new knobs by the TTS settings, read via the guarded `_setting`/CONFIG path:
  - `tts_engine: str = "say"` — `"say"` (default, macOS) | `"kokoro"` (local neural ONNX).
  - `kokoro_voice: str = "af_heart"` — Kokoro voice id (e.g. af_heart, af_bella, am_michael, bf_emma).
  - `kokoro_speed: float = 1.0` — 0.5–2.0; 1.0 = natural pace.
- **`tts.py`** — `speak()` now routes by `tts_engine` (via the new guarded `_setting` helper,
  mirroring assistant/executor):
  - `"say"` → `_speak_say()` — the original `say` command path, unchanged.
  - `"kokoro"` → `_speak_kokoro()` — **lazy**: `kokoro_onnx` is imported only here; the model
    (`kokoro-v1.0.onnx`, ~310MB) + voices (`voices-v1.0.bin`, ~27MB) auto-download once to
    `~/.cache/vox/kokoro/` and the `Kokoro` instance is cached across calls. Synthesizes to a
    float32 PCM array, writes a temp wav (24 kHz mono int16), plays it **blocking** via `afplay`,
    then deletes the temp file. (Loop 3 makes this streaming/killable.)
  - **Fallback invariant:** the whole kokoro path is wrapped in `try/except` in `speak()` — any
    failure (package missing, download error, synth error, playback error) silently falls through
    to `_speak_say()`. The default `"say"` engine never imports or touches kokoro.

**Verification (no live mic needed):**
- `py_compile` clean; importing `vox.tts` on the default config does **not** import `kokoro_onnx`
  (lazy invariant holds).
- Synthesized "Vox local text to speech is now online." with voice `af_heart` → valid wav:
  65024 samples @ 24 kHz mono int16, ~2.71 s, 130 KB (`/tmp/vox_kokoro_sample.wav`), plays via `afplay`.
- Forced-error test: `tts_engine="kokoro"` with a bogus voice → `speak()` does **not** raise and
  falls back to `_speak_say()`.

**How to enable + test live:**
1. Set `tts_engine = "kokoro"` in `config.py` (or via the dashboard settings_store). Optionally
   set `kokoro_voice` / `kokoro_speed`. First spoken phrase triggers the ~353MB one-time download
   to `~/.cache/vox/kokoro/`; subsequent phrases are instant-load.
2. Run Vox and let it speak (e.g. an ASSISTANT-mode reply). You should hear the neural Kokoro
   voice instead of macOS `say`. Set `tts_engine` back to `"say"` (default) to revert exactly.
3. Disk: model + voices total ~353 MB.

### Loop 3 — killable streaming TTS

**What changed** (additive + guarded; default config = today's Vox — `say` + blocking speak + flush,
byte-for-byte unchanged). Implements R5 (sentence-chunked, killable streaming TTS) on top of Loop 2.

- **`tts.py` — streaming Kokoro player.** The Kokoro path no longer synthesizes the whole reply then
  blocks on `afplay`. New flow:
  - `_split_chunks(text)` — splits the reply into sentence/clause chunks on `.!?;:\n`, then hard-wraps
    any chunk > 200 chars at the last space (keeps the first audio fast and `stop()` responsive).
  - `_StreamingPlayer` — a worker thread (`_synth_worker`) synthesizes each chunk with Kokoro and
    pushes its float32 PCM onto a **bounded `queue.Queue`** (None = end-of-stream sentinel); a single
    **`sounddevice.OutputStream`** callback pulls blocks off the queue and writes them to the device.
    Audio therefore **starts after the FIRST sentence** while later chunks are still synthesizing —
    measured ~2x lower time-to-first-audio (~1.1 s vs ~2.4 s for a 5-sentence reply; gap widens with
    length). `play()` BLOCKS until the whole reply has played, preserving `speak()`'s contract.
  - `_speak_kokoro_streaming(text)` — synthesizes chunk 0 up front (gives Kokoro's real 24 kHz sample
    rate AND is reused as the playback *seed* so it isn't synthesized twice), then `player.play(rest,
    seed=...)`. Registers the player in module-global `_ACTIVE_PLAYER` for the duration of the reply.
  - **`stop_speaking()`** (new public fn) — `_ACTIVE_PLAYER.stop()`: sets a stop `Event` (the
    OutputStream callback raises `CallbackStop` on the next ~21 ms block) **and drains the queue** so
    unplayed audio is dropped — pipecat's `_audio_queue.reset()` pattern. `speak()` then returns
    promptly (measured ~250 ms from `stop_speaking()` to return, mid-reply). No-op when idle or on the
    `say`/afplay path (afplay isn't a flushable queue) — guarded, never raises into the caller.
  - **Fallback invariant (3 layers):** `speak()` tries `_speak_kokoro_streaming` → on ANY exception
    falls to the Loop-2 `_speak_kokoro` (synth-whole + afplay) → on ANY exception falls to `_speak_say`.
    The default `"say"` engine never touches any of this. `sounddevice` is already a dep (mic capture);
    no new top-level imports — numpy/sounddevice are imported lazily inside the player.

- **`config.py` — `tts_interruptible: bool = False`** (read via the guarded `_setting`/CONFIG path).
  When ON **and** `tts_engine=="kokoro"`, Vox listens while it speaks and can be talked over.

- **`core/loop.py` — interruptible speaking** (`_assistant_mode` speak path only):
  - New `_speak_interruptible(spoken, …)` — runs `tts.speak()` on a worker thread (still blocking)
    while polling the mic with `capture_utterance` + the Loop-1 `_passes_interrupt_gate` (so ambient
    blips don't cut the voice). On a gated barge-in it calls `tts.stop_speaking()` to cut the voice,
    then returns: `"sleep"` (stop/sleep/abort → go idle), `"quit"`/`"restart"` (→ raise), or
    `("redirect", text)` (a real new utterance → handled as the next turn via the existing `redirect`
    var). Returns `(None, None)` if the reply finished uninterrupted.
  - The assistant speak path now branches: when `tts_interruptible` is ON **and** engine is kokoro →
    `_speak_interruptible` + `mic.flush()`; **otherwise the original `tts.speak(spoken)` +
    `mic.flush()` runs byte-for-byte unchanged** (so default behavior is identical). Control-mode and
    one-shot speak paths are intentionally left as plain blocking `speak()` (short confirmations).

**HEADPHONES-ONLY caveat (important):** Vox has **no echo cancellation yet** (that's Loop 5 / AEC via
VoiceProcessingIO). With `tts_interruptible` ON, on **speakers** the mic hears Vox's own TTS and will
interrupt Vox with its own voice. So talk-over only works cleanly on **headphones**. This is why the
flag stays **OFF by default** until AEC lands — it's the correct mechanism, shipped early to de-risk
Loop 5, but not safe on speakers yet. (Loop comment + this note both call it out.)

**Verification (no live mic needed for the TTS half):**
- `py_compile` clean across `tts.py`/`config.py`/`loop.py`. Lazy invariant holds: importing
  `vox.tts` on the default config does **not** import `kokoro_onnx`; `stop_speaking()` is a safe
  no-op when idle. `_split_chunks` splits sentences correctly.
- Live streaming synth: spoke a multi-sentence reply through the `OutputStream` (real audio out).
  Time-to-first-audio ~1.1 s vs ~2.4 s whole-reply synth (2.1x sooner).
- Kill test: started a ~6 s, 5-sentence reply, called `stop_speaking()` after 1.2 s → `speak()`
  returned in **254 ms** (total elapsed 1.46 s, vs the full ~6 s it would otherwise run). Under the
  "few hundred ms" target.
- Fallback test: forcing `_speak_kokoro_streaming` then `_speak_kokoro` to raise → `speak()` falls
  through to `_speak_say` without raising.

**How to test it live (headphones):**
1. Put on **headphones** (no AEC yet). Set `tts_engine = "kokoro"` and `tts_interruptible = true`
   (in `config.py` or the dashboard settings_store).
2. Enter ASSISTANT mode, ask something with a long spoken reply. While Vox is talking:
   - Say **"go to sleep"** / **"stop"** over it → the voice cuts within a few hundred ms and Vox idles.
   - Say a **new question** over it → the voice cuts and Vox handles the new utterance as the next turn.
   - A short cough / one word should **not** cut it (the Loop-1 interrupt gate rejects blips).
3. Set `tts_interruptible` back to `false` (default) to restore blocking speak + flush exactly. On
   **speakers**, leave it OFF until Loop 5 (AEC) lands, or Vox will interrupt itself.

### Loop 4 — smart-turn endpointing

**What changed** (additive + guarded; default config = today's Vox — fixed `silence_seconds`
end-of-turn, byte-for-byte unchanged). Implements R5 (semantic turn-detection) — replace the blunt
fixed-silence end-of-turn wait with a local model that decides whether the user is actually DONE.

- **Model source** — **`pipecat-ai/smart-turn-v3`**, file **`smart-turn-v3.0.onnx`** (Whisper-Tiny
  encoder + a shallow linear classifier head, ~8M params, **int8 ONNX ~8 MB**, **BSD-2-clause**).
  Input `input_features` = `(1, 80, 800)` log-mel from the last ~8 s of 16 kHz mono audio; output
  `logits` = one value, `sigmoid(logit)` = **P(turn COMPLETE)**. Downloaded **once** via
  `huggingface_hub` to **`~/.cache/vox/smart-turn/`** (no auth needed; ~8 MB).
- **`src/vox/turn_detector.py`** (new) — minimal inference path on **onnxruntime** (already a dep):
  - Preprocessing **mirrors pipecat's `smart-turn/inference.py`** (`WhisperFeatureExtractor(chunk_length=8)`
    → take last 8 s, `do_normalize=True` per-utterance zero-mean/unit-var on the waveform, log-mel,
    pad to 8 s), **reimplemented in pure numpy** (slaney mel filterbank, Hann-windowed STFT, log10,
    `max−8` clamp, `(x+4)/4`) so we avoid the heavy `transformers` dependency. Cross-checked
    numerically against transformers' `WhisperFeatureExtractor` → **max |Δ| ≈ 1.2e-7** (float32 eps),
    identical probabilities. `probability_complete(audio, sr)` returns P in [0,1]; `is_complete()`
    thresholds at 0.5.
  - **LAZY + GUARDED:** `huggingface_hub`/`onnxruntime`/the model are imported/loaded only on first
    `is_complete()` call (session cached). ANY problem (missing pkg, download/model/inference error)
    raises `SmartTurnUnavailable`, which the caller turns into a fixed-silence fallback.
- **`src/vox/config.py`** — three knobs (read via the guarded `_setting`/CONFIG path):
  - `turn_detection: str = "vad"` — `"vad"` (DEFAULT — fixed `silence_seconds`, nothing new loaded) |
    `"smart_turn"` (local model decides end-of-turn).
  - `min_endpointing_delay: float = 0.5` — trailing pause (s) before smart-turn is consulted (livekit `min_delay`).
  - `max_endpointing_delay: float = 3.0` — hard cap (s): end the turn even if the model keeps saying INCOMPLETE.
- **`src/vox/audio.py` — `capture_utterance` endpointing.** A local guarded `_setting` + a lazy
  `_smart_turn_complete(collected, cfg)` helper. In the record loop, when `turn_detection=="smart_turn"`:
  once trailing silence reaches `min_endpointing_delay`, run smart-turn on the audio so far —
  **COMPLETE → end now** (snappy); **INCOMPLETE → keep listening**, re-checking every `min_endpointing_delay`
  of further silence, up to **`max_endpointing_delay`** (hard cap → end anyway). On a model error
  (`None`) it sets `smart_on=False` and reverts to the fixed `silence_limit` for the rest of the
  utterance. When `turn_detection=="vad"` (default) the **original fixed-`silence_seconds` loop runs
  unchanged** — same frame counting, same break condition.

**Verification (no live mic needed):**
- `py_compile` clean across `audio.py`/`config.py`/`turn_detector.py`. **Lazy invariant holds**:
  importing `vox.audio`/`vox.config` on the default config does NOT import `vox.turn_detector`.
- Model loads from `~/.cache/vox/smart-turn/smart-turn-v3.0.onnx` and classifies. Sample P(complete)
  on macOS-`say` clips (synthetic TTS is out-of-distribution, so the gap is modest but ordered the
  right way): **"What time is it right now?" → P ≈ 0.697 (COMPLETE)** vs **"So I was thinking that
  maybe we could possibly go and" → P ≈ 0.503**. Real human mic speech separates far more strongly.
- Feature cross-check vs transformers' `WhisperFeatureExtractor`: **max |Δ| ≈ 1.2e-7**.
- End-to-end `capture_utterance`: with `smart_turn` forced on, a 1.3 s clip ended ~0.5 s after speech
  stopped (model said COMPLETE at the first check). With smart-turn forced to RAISE, it fell back to
  the fixed 0.8 s silence and still ended (no hang). Default `"vad"` ends at exactly `silence_limit`
  (10 frames) — unchanged.
- Probe script: **`scripts/smart_turn_probe.py`** (`uv run python scripts/smart_turn_probe.py`).

**How to enable + test live:**
1. Set `turn_detection = "smart_turn"` in `config.py` (or the dashboard settings_store). Optionally
   tune `min_endpointing_delay` (lower = snappier) / `max_endpointing_delay` (the patience cap).
   First use triggers the one-time ~8 MB download to `~/.cache/vox/smart-turn/`.
2. Run Vox, enter ASSISTANT (or CONTROL) mode and speak. Pause mid-thought ("I want you to… umm…") —
   Vox should **wait** instead of cutting you off at `silence_seconds`; finish a clear sentence and it
   should end **promptly** (~`min_endpointing_delay`). Set `turn_detection` back to `"vad"` (default)
   to restore the fixed-silence behavior exactly.
3. If the model is absent / errors, the daemon keeps running on the fixed-silence path — smart-turn is
   purely additive.

### Loop 5 — VPIO / AEC

**The big, riskiest piece.** A native macOS acoustic-echo-cancellation (AEC) mic path so Vox stops
hearing its own TTS and ambient speaker audio — the one true fix for **O1** (can't talk over Vox on
speakers) and **O7** (speaker/video audio falsely transcribed). This is R7 from RESEARCH.md: route
capture through the **VoiceProcessingIO** audio unit, whose system AEC references the speaker output
and cancels *everything the speakers play* (TTS, music, video) from the mic.

**What changed** (additive + guarded; default config = today's Vox — the sounddevice mic, byte-for-byte
unchanged):

- **Dependencies** — `uv add pyobjc-framework-AVFoundation pyobjc-framework-Cocoa` → resolved
  **pyobjc 12.2** (pulls pyobjc-core + the AVFoundation/Cocoa/CoreAudio/CoreMedia/Quartz frameworks).
  Imported **LAZILY** — `import AVFoundation` happens only inside `VPIOMicStream.__init__`, i.e. only
  when the AEC path is actually taken. Verified: importing `vox.audio` on the default config does
  **not** import AVFoundation.

- **Approach — AVAudioEngine voice processing (the most feasible Python path).** Rather than the raw
  `kAudioUnitSubType_VoiceProcessingIO` AudioUnit (reachable but far more boilerplate from Python),
  Vox uses **`AVAudioEngine`** with **`inputNode.setVoiceProcessingEnabled_error_(True)`** — the
  high-level switch that turns the input node into a VPIO unit (system AEC + AGC + noise suppression).
  A **tap** on the input node (`installTapOnBus_bufferSize_format_block_`) delivers buffers in the
  node's native format (typically **48 kHz float32, multi-channel**); each buffer is resampled to
  **16 kHz mono float32** via an **`AVAudioConverter`**, converted to **int16**, and sliced into exact
  `frame_samples`-length frames. So downstream code (wake, capture_utterance, STT) receives
  **byte-identical frames** to the sounddevice backend.

- **`src/vox/audio.py` — `VPIOMicStream`** — a drop-in `MicStream` replacement with the **same
  interface**: constructor `(sample_rate, frame_samples, device=None)`, a `frames()` generator yielding
  16 kHz mono int16 frames of `frame_samples`, `flush()`, and `__enter__`/`__exit__`. Internals: an
  `AVAudioEngine`, VPIO enabled on the input node, an `AVAudioConverter` to 16 kHz mono, a tap whose
  callback resamples → int16 → a queue (a residual buffer carries partial frames between callbacks so
  every emitted frame is exactly `frame_samples`). `frames()` restarts the engine on a multi-second
  stall (mirrors MicStream). The tap callback is fully wrapped so no exception can escape into
  CoreAudio's render thread.

- **`src/vox/audio.py` — `open_mic_stream(cfg)`** — the factory the daemon now calls. When
  `audio_aec` is true (read via the guarded `_setting`/CONFIG path, so the dashboard can toggle it
  live), it tries `VPIOMicStream`; on **ANY** failure (PyObjC missing, mic permission denied,
  engine/tap/convert error) it logs a warning and **falls back to the sounddevice `MicStream`**, so
  the daemon never loses its mic. Default (`audio_aec` false) returns `MicStream` directly.

- **`src/vox/config.py` — `audio_aec: bool = False`** — `false` = DEFAULT (sounddevice mic, nothing
  native loaded) | `true` = native VoiceProcessingIO capture.

- **`src/vox/core/loop.py`** — the single `MicStream(...)` construction site now calls
  `open_mic_stream(cfg)` (import updated accordingly). Nothing else in the loop changed — both backends
  present the identical context-manager + `frames()` contract.

**Verification (local, no live AEC judgement):**
- `py_compile` clean across `audio.py`/`config.py`/`loop.py`; `vox.core.loop` imports.
- **Lazy invariant holds:** importing `vox.audio` on the default config does NOT import AVFoundation;
  the default factory returns `MicStream` without importing it.
- **Fallback verified:** forcing `VPIOMicStream` construction to raise → `open_mic_stream` returns a
  `MicStream` (no exception escapes).
- **Native capture works on this machine:** `VPIOMicStream` constructs, `setVoiceProcessingEnabled`
  returns success, `isVoiceProcessingEnabled() == True`, the tap fires, the converter resamples
  48 kHz→16 kHz, and `frames()` yields **1280-sample int16 frames @ ~16 k samples/s** — byte-format
  identical to the sounddevice mic. Confirmed both directly and through `open_mic_stream` with the
  flag forced on.

**What still needs LIVE validation by the user (honest limits):**
- **AEC *quality* cannot be judged here** — it requires the user's live mic + speakers playing real
  audio (Vox's TTS, music, a video) while speaking. Local tests only prove the capture path produces
  correct frames with VPIO enabled; they do **not** prove the echo is actually cancelled well enough
  to talk over Vox on speakers. That is the user's acceptance test.
- **Mic-permission behavior** — when VPIO first runs under the real daemon, macOS may prompt for
  Microphone access (and the engine can fail until granted); the fallback covers that, but the
  *intended* behavior (AEC on) needs the permission granted and a real run.
- **Interaction with `tts_interruptible`** — the payoff is enabling Loop 3's talk-over **on speakers**:
  `audio_aec=true` + `tts_engine="kokoro"` + `tts_interruptible=true` should let the user talk over
  Vox without Vox interrupting itself. Whether the AEC is strong enough for that on this hardware is
  the key live test.

**How to enable + test live:**
1. Grant Microphone permission to the terminal/app running Vox (System Settings → Privacy & Security →
   Microphone) — VPIO needs real mic access.
2. Set `audio_aec = true` in `config.py` (or via the dashboard `audio_aec` toggle — it applies on the
   next mic open). On start you should see `🎙️  mic: native VoiceProcessingIO (AEC) backend active`;
   if instead you see the fallback warning, VPIO failed and Vox kept running on the sounddevice mic.
3. Play audio through your **speakers** (not headphones) and speak — Vox should no longer transcribe
   the speaker audio as commands (O7). Then turn on `tts_engine="kokoro"` + `tts_interruptible=true`
   and try talking over Vox's spoken reply on speakers (O1). Tune nothing else; AEC is system-managed.
4. Set `audio_aec` back to `false` (default) to restore the exact sounddevice capture path.
