# Listening better and lighter: mic, AEC, VAD, end-of-turn, STT (2026)

**Question:** how can Vox use less CPU while it listens all the time, stop cutting people off, answer
faster and handle conversation more naturally? This doc covers mic quality, echo cancellation, VAD,
end-of-turn detection, barge-in and on-device STT speed, all checked against real open-source code
and measured on this Mac mini (M4, 4 performance + 6 efficiency cores, 16 GB, macOS 26).

**What it doesn't repeat:** the turn-taking concepts in `voice-turn-taking.md`, the pipecat and
LiveKit flow and interruption layers in `voice-agents/RESEARCH.md` (R1–R7), the Vosk grammar lane in
`dictation-stt-tools.md`, and the CPU-starvation diagnosis in `issues.md` O15–O17. This doc adds
measurements, new 2026 facts, and a list of hotspots in the code.

---

## TL;DR

1. **Most of the "200% CPU" comes from Whisper settings and when Whisper runs. Python isn't the
   cause.** On this machine, `int8` + `beam_size=5` (Vox's current setup) costs **3–4× more CPU per
   utterance** than `float32` + greedy decoding, and it's also *slower* in wall-clock time
   (measurements in §1).
2. **About 99% of idle Whisper passes are wasted.** In the last 2,000 idle transcriptions in
   `vox.log`, only **21** matched a wake phrase. Each wasted pass costs about 5 CPU-seconds on
   `small.en`/int8/beam 5.
3. **smart-turn is three versions behind (v3.0 → v3.2), and v3.2 changed the padding** (zeros now go
   at the *start*). That probably explains the "poorly discriminative" note in `config.py`.
4. **Apple SpeechAnalyzer is real and worth adopting, but only from Swift.** It runs out of process
   on Apple's own model and gives streaming partials, word timings and confidence. Its English
   accuracy is at least as good as Whisper small. It has no custom-vocabulary biasing.
5. **Swift-helper verdict:** for *capture* alone it isn't a big win, because capture costs almost
   nothing. As an **STT lane** (SpeechAnalyzer), it is the one structural change that moves
   transcription off the CPU and removes the transcribe-after-you-stop wait. Do the cheap Python fixes
   first, then build the helper as a narrow STT lane (§7).

---

## 1. Measurements on this machine (2026-11-06)

**faster-whisper 1.2.1 / CTranslate2 4.8.0, `cpu_threads=4`, `vad_filter=True`.** Each figure is the
best of 3 runs while the machine was under its normal load (load average about 3.8). Test clips were
generated with `say`: a 1.9 s command and a 9.0 s sentence.

| model / compute / beam | 1.9 s clip: wall · CPU | 9.0 s clip: wall · CPU |
|---|---|---|
| small.en · int8 · beam 5 (**current default**) | 1.25 s · **4.93 s** | 1.83 s · 7.71 s |
| small.en · int8 · beam 1 | 1.10 s · 4.19 s | 1.40 s · 5.52 s |
| small.en · float32 · beam 5 | 0.89 s · 1.72 s | 1.78 s · 2.90 s |
| small.en · **float32 · beam 1** | **0.63 s · 1.39 s** | **1.01 s · 1.90 s** |
| base.en · float32 · beam 1 | 0.20 s · 0.45 s | 0.35 s · 0.63 s |

- **Why float32 wins on Apple Silicon:** CTranslate2's fp32 path runs on Apple Accelerate, which
  uses the AMX matrix units. Its int8 path runs on generic ARM kernels. The int8 path uses less RAM
  but costs far more CPU. Accelerate does its own threading, so `cpu_threads` matters little for
  fp32: 1 thread gave 0.92 s wall / 1.06 s CPU and 4 threads gave 0.64 s / 1.39 s.
- **Cost of float32:** about 2× RAM for the weights (small.en has ~244M params, so roughly 1 GB in
  fp32).
- **Whisper costs about the same for short and long clips.** faster-whisper pads every segment to a
  30 s window (`pad_or_trim` in `transcribe.py`), so a 1.9 s "open safari" costs almost as much as
  9 s of speech. `vox.log` shows the same pattern: clips under 2 s averaged *longer* STT than
  2–5 s clips.
- **Fallback re-decoding on noise:** faster-whisper's default `temperature=[0.0, 0.2, … 1.0]`
  re-decodes when the output looks like garbage, with up to 5 extra passes at `best_of=5`. Noise and
  mumbling produce exactly that kind of output, so the worst case lands on idle audio.

**Cost of always-on detectors per 80 ms frame (measured, one thread):**

| detector | CPU while listening continuously |
|---|---|
| RMS energy gate (`audio.rms`) | ~3.4 µs/frame, effectively 0% |
| Silero VAD v6 (bundled in faster-whisper) | **~0.2% of one core**, batched; budget ~1% with streaming overhead |
| openWakeWord, 1 model | **~2.3% of one core** |
| Whisper small.en int8 beam 5, per idle trigger | ~5 CPU-s **each time**; at the logged peak of ~146 triggers/hour, ≈ 20% of a core on average, in 400% bursts |

**What `vox.log` shows:** the last 2,000 `idle heard` lines contain 21 matches. They include
hallucinations of the hotword list itself ("amazon netflix calculator terminal finder slack figma
obsidian"). Those lines only count *non-empty* transcripts, so the real number of passes is higher.
The `⏱` lines show `cpu 391%` peaks with `rtf 2.45` on a 1 s clip.

---

## 2. Hotspots in Vox's code (file:line, as of this branch)

| # | Where | What | Fix |
|---|---|---|---|
| H1 | `src/vox/config.py:29` `wake_backend="whisper"` + `wakeword/backends.py:49-54` | Idle runs a full Whisper pass on **every** RMS onset, up to 8 s, and 99% of them are discarded | Gate with VAD and/or a wake pre-check (R2) |
| H2 | `config.py:182-188` (`small.en`, `int8`, 4 threads) + `stt/whisper_transcriber.py:24-25` (no `beam_size`, `temperature`, `condition_on_previous_text`) | Most CPU-expensive setup measured; beam 5 plus the fallback list | `float32`, `beam_size=1`, `temperature=0.0`, `condition_on_previous_text=False` (R1) |
| H3 | `audio.py:482` | Onset is a **single frame** ≥ `speech_rms`, so a keyboard clack or door starts a capture | Require ~200 ms of VAD speech probability (pipecat `start_secs=0.2`) |
| H4 | `audio.py:35` `queue.Queue()` unbounded | While Whisper blocks, frames pile up, and the next onset wait can be met from stale audio (O15/O17) | Timestamp frames and drop backlog older than ~1 s while idle |
| H5 | `tts.py:222` `Kokoro(model_path, voices_path)` | kokoro-onnx builds `InferenceSession` with default options, so intra-op threads = **all 10 cores**. TTS then competes with STT and barge-in | `Kokoro.from_session(...)` with `intra_op_num_threads=2–4` (R3) |
| H6 | `core/loop.py:674-677` `_speak_interruptible` | Every barge-in capture during TTS runs **full Whisper**, while Kokoro is also synthesizing. `_run_interruptible` (line 608) already tries the Vosk lane first | Use `_recognize` (Vosk first) and a VAD gate here too (R6) |
| H7 | `focus_watch.py:52-54` → `actions.py:317` | Spawns `osascript` + System Events **every 1.5 s** (`config.py:412`): ~40–60 ms CPU and a process spawn each time, plus constant wakeups | Ask the AX API in-process (`AXUIElementCreateSystemWide` → `kAXFocusedApplication`, via `vox/ax.py`), which needs no run loop and so avoids the O18 staleness (R5) |
| H8 | `turn_detector.py:35` (`smart-turn-v3.0.onnx`) + `:192` (zeros padded on the right) | v3.0 is outdated. v3.2 is the current reference and pipecat's bundled default, and it **pads zeros at the start**. v3.2 says it fixed "a padding issue during training" | Ship v3.2 and switch to left padding (R4) |
| H9 | `wakeword/backends.py:14` | Imports openwakeword (and onnxruntime) at module load even when `wake_backend="whisper"` | Lazy import. Startup and RAM cost only, not ongoing CPU |

Already right: smart-turn uses `intra_op_num_threads=1`, and faster-whisper's own Silero session is
single-threaded.

---

## 3. Apple SpeechAnalyzer / SpeechTranscriber (macOS 26)

**API shape** (from the [WWDC25 session 277](https://developer.apple.com/videos/play/wwdc2025/277/) and
real usage in [anarlog's `transcribe-speechanalyzer`](https://github.com/fastrepl/anarlog/tree/main/crates/transcribe-speechanalyzer)):

- `SpeechAnalyzer(modules:)` is an actor. You add a `SpeechTranscriber(locale:, transcriptionOptions:,
  reportingOptions: [.volatileResults], attributeOptions: [.audioTimeRange, .transcriptionConfidence])`.
  Audio goes in as an `AsyncStream<AnalyzerInput>` of `AVAudioPCMBuffer`s converted to
  `SpeechAnalyzer.bestAvailableAudioFormat(compatibleWith:)`. Results arrive as an async sequence.
- **Volatile results** arrive "almost as soon as they're spoken" and are later replaced. **Finalized
  results** are final for their range. Calling `finalizeAndFinishThroughEndOfInput()` flushes the
  rest. Per anarlog's code comments, per-word `audioTimeRange` and `transcriptionConfidence` only
  appear on *finalized* results, because a volatile result is one run with no word breakdown.
- **Model:** a system asset installed via `AssetInventory.assetInstallationRequest(supporting:)` and
  then `downloadAndInstall()`. Apple says it "is retained in system storage and does not increase the
  download or storage size of your application, nor … run-time memory … It operates outside of your
  application's memory space." Updates are automatic. Apps can reserve only a limited number of
  locales (`AssetInventory.maximumReservedLocales`). anarlog releases one to make room, polls
  `AssetInventory.status` until `.installed`, and only installs languages the user has added in
  System Settings.
- **[`SpeechDetector`](https://developer.apple.com/documentation/speech/speechdetector)** is a
  built-in VAD module (sensitivity levels; `.medium` recommended) that gates the transcriber "saving
  power otherwise used by attempting to transcribe what is likely to be silence."
- **No custom vocabulary on SpeechTranscriber.** `AnalysisContext.contextualStrings` biases only
  `DictationTranscriber` ([forum thread](https://developer.apple.com/forums/thread/811083),
  [docs](https://developer.apple.com/documentation/speech/analysiscontext/contextualstrings)).
  App names like "Cursor"/"Arc" would rely on Vox's existing `vocab.apply` post-correction plus the
  Vosk grammar lane, not on hotwords.
- **Swift-only.** The symbols are Swift classes and actors (`final class SpeechDetector`, `s:`
  mangled IDs) with no Objective-C bridge, so **PyObjC can't call them.** The only Python route
  today is a Swift→C shim. [`mac-speech-analyzer`](https://pypi.org/project/mac-speech-analyzer/)
  (MIT) is one, but it handles files only; live mic input is "on the roadmap".

**Accuracy and latency evidence:**
- [IraVoice benchmark](https://dev.to/iravoice/apple-speechanalyzer-vs-whispercpp-a-40-speaker-mac-benchmark-40i4)
  (LibriSpeech test-clean, 40 speakers, streamed in real time, M5 Max). **WER 1.98% vs 4.28%** for
  whisper.cpp `small.en`. Median post-speech latency was **125–132 ms vs 122–125 ms**, so roughly a
  tie. The author sells a dictation app built on Apple's engine, and the test is clean read speech
  only.
- [MacStories / MacRumors](https://www.macrumors.com/2025/06/18/apple-transcription-api-faster-than-whisper/):
  file transcription was 55% faster than Whisper large-v3 (via MacWhisper) with no noticeable
  quality difference.
- Not measured anywhere: **CPU cost.** Because the model runs out of process, Vox's `cpu %` would
  stop counting it, but the system still pays for it. Measure with `powermetrics`/Activity Monitor
  on the speech daemon before claiming a win. Accent, short-command and proper-noun accuracy are also
  unmeasured. Test on this user's voice against `small.en` using the replay corpus.

**Would a helper work?** Yes. The protocol: 16 kHz s16le PCM on stdin (32 KB/s, trivial IPC cost),
NDJSON on stdout, one message per result in the form
`{"type":"partial|final","text":…,"start":…,"end":…,"words":[{"w","s","e","conf"}]}`.
anarlog's `LiveSession` already handles format conversion (`AVAudioConverter` into the analyzer
format), and its finalized-vs-volatile handling is the reference implementation to copy.

---

## 4. Echo cancellation and barge-in on macOS

Vox **already has** a voice-processing (VPIO) path: `VPIOMicStream` in `audio.py`, which uses
AVAudioEngine `setVoiceProcessingEnabled(True)` via PyObjC, with ducking set to minimum. It's off
(`audio_aec=False`). What I found:

- **True barge-in needs the playback to be the echo reference.** The case that is documented and
  reliable is **TTS played through the same voice-processed AVAudioEngine** (a player node on the
  engine's output). Kokoro currently plays through a separate `sounddevice.OutputStream`
  (`tts.py:382`) or `afplay`. Whether VPIO also cancels *other* processes' output is **not settled**:
  one Rust crate's README ([sys-voice](https://docs.rs/crate/sys-voice/latest/source/README.md))
  claims it "monitors system output", while the Core Audio mailing list points people to
  ScreenCaptureKit or loopback devices for other-app audio. Treat cross-process cancellation as
  unproven and test it. If it fails, the fix is to play TTS through the same engine, which is a
  natural job for the helper.
- **Gotchas:**
  - Voice processing must be enabled *before* the engine starts, not toggled live
    ([WWDC19 510](https://developer.apple.com/videos/play/wwdc19/510/)).
  - VPIO builds a hidden aggregate device. With Spatial Audio the output appears as 5.1, which is
    probably the source of the "6 ch @ 48 kHz" Vox saw. That setup can fail with `-10875`/`-10879`,
    costing about 2 s per failed start ([Fora Soft write-up](https://www.forasoft.com/ship-log/spatial-audio-vpio)).
  - Ducking of other audio: macOS 14+ `voiceProcessingOtherAudioDuckingConfiguration` (already used).
  - Device changes need `AVAudioEngineConfigurationChange` handling. VPIO's `_restart()` in Vox only
    re-taps.
  - Enabling Voice Processing in one app can cut off another app's input
    ([forum 751100](https://developer.apple.com/forums/thread/751100)), which is a risk alongside
    Zoom.
- **Mic quality matters more than AEC for this user.** A Mac mini has **no built-in mic**, and the
  configured input is AirPods. When a Bluetooth headset's mic is open, macOS switches it to the
  two-way call profile: mono, 16–24 kHz (mSBC / AAC-ELD), with **playback downgraded to call
  quality**. An always-open mic keeps it there permanently. On headphones there's no echo, so AEC is
  moot and barge-in already works. Recommended setups:
  - A wired/USB mic, with AirPods or speakers kept as output only (stays in high-quality A2DP).
  - Speakers + a USB mic + `audio_aec=True`, once TTS playback goes through the VPIO engine.
- Noise suppression (RNNoise/Krisp) is *not* AEC. The prior doc already advises against stacking it
  with VPIO.

---

## 5. VAD and end-of-turn in 2026

- **Pipecat defaults (main branch):** stop strategy `TurnAnalyzerUserTurnStopStrategy(LocalSmartTurnAnalyzerV3)`
  ([`user_turn_strategies.py`](https://github.com/pipecat-ai/pipecat/blob/main/src/pipecat/turns/user_turn_strategies.py)).
  It bundles **`smart-turn-v3.2-cpu.onnx`** and runs it with `intra_op_num_threads=cpu_count` (default
  **1**). It's paired with Silero VAD (`confidence 0.7, start_secs 0.2, stop_secs 0.2,
  min_volume 0.6`), so the VAD reports the pause quickly and the model decides. The CoreML
  smart-turn variant is **deprecated** in favor of the ONNX v3, so the Neural Engine buys nothing for
  a model this small. Pipecat's Silero wrapper resets model state about every 2 s, but only during
  clear non-speech, because "a reset during speech … can end the user's speech early"
  ([`silero.py`](https://github.com/pipecat-ai/pipecat/blob/main/src/pipecat/audio/vad/silero.py)).
  That's a subtle cut-off cause worth copying if Vox adds Silero.
- **Smart Turn v3.2** (Jan 2026, [Daily blog](https://www.daily.co/blog/smart-turn-v3-2-handling-noisy-environments-and-short-responses/)):
  - Trained with café/office noise added, plus a short-utterance set ("yes", "okay" misclassified
    about 40% less often).
  - Fixes a training padding bug. The reference
    [`audio_utils.py`](https://github.com/pipecat-ai/smart-turn/blob/main/audio_utils.py), added in
    the v3.2 commit, **pads zeros at the beginning**.
  - 8 MB int8 on CPU, around 10 ms on a fast CPU, ~65 ms on a cloud vCPU. Drop-in replacement for
    v3.1.
  - **Vox's right padding means the model sees up to ~6 s of trailing silence on a short turn,**
    which pushes every input toward "complete" and fits the "~0.73 even on a pause" note.
- **Silero vs webrtcvad:** Silero is under 1 ms per 30 ms chunk on one thread
  ([README](https://github.com/snakers4/silero-vad)), measured here at ~0.2% of a core. It's already
  installed as part of faster-whisper (`silero_vad_v6.onnx`), so it adds no dependency. webrtcvad
  (a GMM) is cheaper still but much worse on noise. At these costs, Silero is the right gate.
- **LiveKit:** the turn detector plugin (agents 1.5) takes about 400 MB RAM and about 25 ms per
  inference. It reads text and needs an STT transcript, so it fits only after streaming STT exists.
  Not worth it over smart-turn for Vox.
- **Natural conversation patterns these unlock:**
  - Dynamic endpointing (already in Vox: 0.6 s min → 3.0 s max).
  - "Eager" end-of-turn: start the LLM on a likely-complete turn and cancel it if the user keeps
    talking. Pipecat has `eager_user_turn_stop_strategy.py`.
  - With streaming partials (SpeechAnalyzer), endpointing can also use the text: a dangling "and…"
    or "um" means keep waiting.

---

## 6. Keeping idle CPU low: what the light systems do

- **Cascade, cheapest first:** energy → VAD (≈0.2%) → wake model (≈2%) → STT only on a wake hit.
  openWakeWord's README recommends its built-in Silero `vad_threshold` to cut false positives, and
  80 ms (1280-sample) frames, which Vox already uses. Vox idle skips the middle two stages and goes
  straight from energy to Whisper.
- **One thread per small model** (`intra_op_num_threads=1`, `inter_op_num_threads=1`). Pipecat does
  this for Silero and smart-turn, and so does faster-whisper's VAD. Big models get a **budget**, not
  "all cores". On a 4P+6E M4, Whisper fp32 with 2–4 threads plus Kokoro with 2–4 leaves the
  efficiency cores for the rest of the system.
- **Never transcribe stale audio:** drop backlog on the capture side rather than flushing after the
  fact (H4).
- **Avoid process spawns in steady state** (H7). Numpy copies per 80 ms frame are negligible
  (≈µs); they aren't worth optimizing.

---

## 7. Verdict: would moving capture + STT into a native Swift helper be a big win?

**For capture alone, no.** The CPU isn't in capture. A sounddevice callback plus RMS costs
microseconds per frame, CTranslate2 releases the GIL, and the PyObjC VPIO path already works. A
Swift capture process would add a build toolchain, signing/notarization for distribution and an IPC
hop, while saving roughly 0% CPU. Device-change robustness (O9) is a partial argument, but a fresh
process restart already handles it.

**For STT, yes. A helper is the only route to SpeechAnalyzer, and it's the only change that removes
the transcribe-after-you-stop wait.**

- SpeechAnalyzer is Swift-only, so Python can't call it without a helper.
- It runs on Apple's system-managed model outside Vox's process, with no 30 s-window padding and no
  model on Vox's disk.
- Streaming partials mean the transcript is essentially done when the turn ends, about 130 ms
  later, instead of the 0.6–1.8 s whole-utterance Whisper pass that follows today's silence wait.
  That addresses O16, and it removes the CPU-collapse cut-off class (O15/O17).
- Later, the same helper can own **VPIO capture plus TTS playback in one AVAudioEngine**, which is
  the reliable way to get barge-in on speakers.

**The catches:**
- No hotword biasing, so Vox keeps the Vosk grammar lane for commands and Whisper as the portable
  fallback.
- macOS 26 and Apple Silicon only.
- A first-run asset download.
- Accuracy on this user's accent is unproven.

**Sequence:** do R1–R3 first. They're cheap, all Python, and should remove most of the 200%. Then
spike the helper as an STT lane only, keeping capture in Python and piping PCM to it, and A/B it on
the replay corpus.

---

## 8. Prioritized recommendations

Effort: **S** = hours, **M** = 1–3 days, **L** = multi-day. Estimated gains come from the §1
measurements and still need confirming with the live `⏱` log lines.

| # | Change | Expected gain | Effort | Risk |
|---|---|---|---|---|
| **R1** | Whisper: `whisper_compute_type="float32"`, and pass `beam_size=1, temperature=0.0, condition_on_previous_text=False` in `whisper_transcriber.py` (beam 5 could be kept for dictation only) | **~3.5× less CPU per pass** (4.9 → 1.4 CPU-s on a short clip), ~2× faster wall-clock; worst case on noise drops from up to 6 decodes to 1 | S | Low. +~0.7 GB RAM on small.en. Greedy is slightly worse on rare words (the Vosk lane and vocab cover commands). `temperature=0` removes the recovery for real low-confidence speech, so watch empty-hear rates |
| **R2** | Gate idle Whisper: require ~200–300 ms of Silero speech (already bundled) before an idle capture counts, **and** check the start of the capture for a wake word with a Vosk grammar (`["vox","hey vox","fox","box",…,"[unk]"]`) before calling Whisper. The longer-term option is a custom openWakeWord "hey vox" model at ~2% of a core | Cuts the 99% wasted idle passes. Likely the **largest idle-CPU drop** (from roughly a quarter of a core average with 400% bursts to a few %) | S–M | Medium: missed wakes if Vosk mis-hears the name. Keep the mis-hear variants in the grammar and replay `idle heard` logs to measure recall before switching the default |
| **R3** | Thread budget: build Kokoro via `Kokoro.from_session` with `intra_op_num_threads≈2–4`; keep Whisper at 2–4; keep every small model at 1 | Stops TTS from taking all 10 cores while STT or barge-in runs; smoother responses under load | S | Low: first-sentence TTS latency may rise slightly. Measure TTFB |
| **R4** | smart-turn v3.2 + **left padding** + Silero pause detection (`stop_secs≈0.2`); re-test `turn_detection="smart_turn"` as the default for assistant and dictation | Fewer cut-offs mid-thought **and** faster ends on finished turns (O8, dictation cut-offs) | S–M | Medium: v3.0 already disappointed. Validate on the replay corpus. Keep the 3.0 s hard cap |
| **R5** | Replace the 1.5 s `osascript` focus poll with an in-process AX query (`vox/ax.py`) | A steady few % of a core plus System Events load and timer wakeups removed | S | Low–medium: must stay as fresh as O18 requires (AX system-wide focus needs no run loop) |
| **R6** | `_speak_interruptible`: use `_recognize` (Vosk first) and a VAD gate instead of raw Whisper; bound or timestamp the mic queue and drop stale backlog while idle | Cheaper, faster barge-in during TTS; removes the stale-backlog root of O15 | S | Low |
| **R7** | **Spike a SpeechAnalyzer STT helper** (Swift CLI, PCM in, NDJSON out, modeled on anarlog's `LiveSession`) behind `stt/base.py` as an opt-in lane for dictation and assistant | STT moves off Vox's CPU; streaming partials; ~130 ms final latency; better English WER on benchmarks | M (spike) → L (shipping: build, sign, asset download UX) | Medium: Swift build/distribution, macOS 26 only, no hotwords, accent accuracy unknown |
| **R8** | Mic hardware: a wired/USB mic with AirPods as output only, or speakers + USB mic + `audio_aec`, once TTS plays through the VPIO engine (from the R7 helper or a PyObjC player node) | Better SNR → fewer mis-hears; no permanent Bluetooth call-quality playback | none / M | None for hardware. AEC playback routing needs live testing |

**Top 5 in order:** R1 → R2 → R3 → R4 → R7. R1–R3 together should be about a day of work and target
the 200% directly. R4 targets the cut-offs. R7 is the structural latency fix.

---

## 9. Side observation: command learning trial (per CLAUDE.md)

From `grep "\[learn\]" vox.log` (40 lines):

- **A frustrated sentence was learned as a command alias.** `'click next song i don t know why its
  so slow my cpu is running at like 200'` was saved as a *new alias on command #53* (Spotify). Long
  utterances full of chatter shouldn't become aliases, so consider a max-words or "phrase ≈ action
  words" check.
- **A likely mis-hear was learned.** `'first pause'` → click/pause (#53, Spotify). Also,
  `'click on the gmail website'` → tab/gmail looks right.
- The numbering is inconsistent: #53 shows up for both 'first pause' and 'go next song' on different
  days. That may be a DB reset or a reused ID, so it's worth a look in
  `GET /api/commands/learning`.

---

## Sources

- Apple: [WWDC25 277 SpeechAnalyzer](https://developer.apple.com/videos/play/wwdc2025/277/) ·
  [SpeechDetector](https://developer.apple.com/documentation/speech/speechdetector) ·
  [contextualStrings](https://developer.apple.com/documentation/speech/analysiscontext/contextualstrings) ·
  [forum: contextual strings ignored by SpeechTranscriber](https://developer.apple.com/forums/thread/811083) ·
  [forum: Voice Processing in multiple apps](https://developer.apple.com/forums/thread/751100) ·
  [WWDC19 510 AVAudioEngine voice processing](https://developer.apple.com/videos/play/wwdc19/510/)
- [fastrepl/anarlog `transcribe-speechanalyzer`](https://github.com/fastrepl/anarlog/tree/main/crates/transcribe-speechanalyzer) (MIT; Swift via swift-rs)
- [mac-speech-analyzer (PyPI)](https://pypi.org/project/mac-speech-analyzer/)
- Benchmarks: [IraVoice: SpeechAnalyzer vs whisper.cpp](https://dev.to/iravoice/apple-speechanalyzer-vs-whispercpp-a-40-speaker-mac-benchmark-40i4) ·
  [MacRumors / MacStories speed test](https://www.macrumors.com/2025/06/18/apple-transcription-api-faster-than-whisper/)
- [pipecat `user_turn_strategies.py`](https://github.com/pipecat-ai/pipecat/blob/main/src/pipecat/turns/user_turn_strategies.py) ·
  [`local_smart_turn_v3.py`](https://github.com/pipecat-ai/pipecat/blob/main/src/pipecat/audio/turn/smart_turn/local_smart_turn_v3.py) ·
  [`silero.py`](https://github.com/pipecat-ai/pipecat/blob/main/src/pipecat/audio/vad/silero.py) ·
  [`vad_analyzer.py`](https://github.com/pipecat-ai/pipecat/blob/main/src/pipecat/audio/vad/vad_analyzer.py)
- [pipecat-ai/smart-turn](https://github.com/pipecat-ai/smart-turn) ·
  [Smart Turn v3.2 blog](https://www.daily.co/blog/smart-turn-v3-2-handling-noisy-environments-and-short-responses/) ·
  [v3.1 blog](https://www.daily.co/blog/improved-accuracy-in-smart-turn-v3-1/)
- [snakers4/silero-vad](https://github.com/snakers4/silero-vad) ·
  [LiveKit turn detector](https://docs.livekit.io/agents/logic/turns/turn-detector)
- VPIO: [sys-voice README](https://docs.rs/crate/sys-voice/latest/source/README.md) ·
  [Fora Soft: Spatial Audio vs VPIO](https://www.forasoft.com/ship-log/spatial-audio-vpio)
- [FluidInference/FluidAudio](https://github.com/FluidInference/FluidAudio) (Apache-2.0 Swift SDK:
  Parakeet TDT and a streaming Parakeet EOU model on the Neural Engine, used by VoiceInk/Hex/Spokenly).
  It's the Swift-helper alternative if SpeechAnalyzer's lack of hotwords or its accuracy disappoints.
- Bluetooth mic profiles: [mjtsai: why Bluetooth sound is bad on Mac](https://mjtsai.com/blog/2023/12/13/why-is-bluetooth-sound-quality-bad-on-my-mac) ·
  [AirPods Pro AAC-ELD](https://www.ithinkdiff.com/apple-upgraded-airpods-pro-speech-codec-aac-eld/)
- Local: `faster_whisper/transcribe.py` (`pad_or_trim`, `beam_size=5`, temperature fallback),
  `faster_whisper/vad.py` (single-threaded Silero), `kokoro_onnx/__init__.py` (default
  `InferenceSession`, `from_session`).
