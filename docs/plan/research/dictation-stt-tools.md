# Vox — Whisper/Vosk Dictation & Control Tools: Competitive Scan

> A survey of five voice-dictation / voice-control tools (Vibe, SpeechPulse, WhisperTyping, Utterly
> Voice, Vosk) to see what Vox could borrow. **Headline:** most of these *validate* choices Vox has
> already made (local faster-whisper, in-utterance edit commands, context-scoped command grammar, an
> AX-tree click path that's better than their vision hacks). The three genuinely new levers are all
> **Vosk-shaped**: (1) **grammar-constrained recognition** for near-perfect, LLM-free command spotting
> that plugs straight into the command-DB we already built; (2) **streaming partial transcripts** for
> live captions + a self-correcting Whisper loop; and (3) a **typed-argument command grammar** (Utterly
> Voice) that extends the command-DB past fixed phrases. Everything else is a note or a "we already do
> this."

---

## The tools at a glance

| Tool | What it is | License / cost | STT engine | Platform | Relevance to Vox |
|---|---|---|---|---|---|
| **Vibe** (`thewh1teagle/vibe`) | Batch file-transcription GUI | **MIT** (readable code) | **whisper.cpp** (GGML) + Parakeet/Nemotron | Win/Mac/Linux (Tauri) | Cross-platform GPU story (Vulkan/CoreML); `initial_prompt` vocab; model-manager UX |
| **SpeechPulse** | Live dictation + voice commands | Closed, **$99+** one-time | Whisper (likely faster-whisper/CT2) | Win + Apple-Silicon only | 3-way mode model; command grammar; literal/numeral escapes; LLM cleanup pass |
| **WhisperTyping** | Dictation-into-any-app | Closed, $5–30/mo, **cloud-default** | Whisper Large | **Windows only** | **localhost intercept-hook pipeline** + Command API pattern |
| **Utterly Voice** | Dictation + full computer control | Closed but **free/feature-complete**, YAML-driven | **Vosk** (default) / Whisper / cloud | **Windows only** | **Typed-arg command grammar**, mode namespaces, voice macros, escape word |
| **Vosk** (`alphacep/vosk-api`) | Offline streaming STT toolkit (Kaldi) | **Apache-2.0** (code; models vary) | Kaldi | Win/Mac/Linux/Pi/mobile | **Streaming partials + grammar-constrained command recognition + built-in endpointer** |

Full per-tool research (URLs, benchmarks, API shapes) is preserved in the sub-sections at the bottom.

---

## Where Vox already matches or leads (don't re-solve these)

The scan is most useful for what it *rules out*. Vox already has, and in places beats, the commercial tools:

- **Local Whisper STT** — `src/vox/stt/whisper_transcriber.py` (faster-whisper `small.en`, int8). SpeechPulse
  almost certainly runs the same engine; Utterly Voice's own docs put **Vosk at ~5 GB RAM vs Whisper
  <1 GB** in their setup — so our lean local pick is *well* justified, not something to second-guess.
- **In-utterance edit commands** — `actions.dictate()` already does `"literally …"`, delete word/line/
  paragraph, undo/redo, soft vs hard newline, capitalization/spacing across pauses. That's the same
  surface SpeechPulse ("Literal [word]", "New line", "Undo that") and Utterly Voice ("escape …") sell.
- **Context-scoped command grammar** — the command-DB (`command_store.py` / `command_cache.py`, contexts
  `global`/`app`/`site`, `exact`/`contains`/`regex`) is *more* capable than Utterly Voice's flat per-mode
  command files, because it keys on the **focused app** automatically. They switch modes by voice; we
  switch by what you're looking at.
- **AX-tree clicking** — `actions.click` over the native accessibility tree is **semantic and
  deterministic**. Utterly Voice's "Show / Screen Analyzer" does *image analysis* and its own macro docs
  warn the numbered labels are non-reproducible between runs. Our path is the better one; keep it primary.
- **Custom-vocabulary biasing** — `command_hotwords` (faster-whisper `hotwords=`) already covers the
  "train new words" pitch, at least for command vocabulary.
- **LLM compose/rewrite** — the executor's compose/rewrite (backlog #10) is SpeechPulse's/WhisperTyping's
  "AI modes".
- **Semantic turn detection** — `turn_detector.py` (smart-turn-v3) already beats raw-silence endpointing;
  Vosk's built-in endpointer is a *sidegrade*, not an upgrade (see below).

**Takeaway:** none of the closed tools are architectural peers for our local-STT layer. Vibe (MIT) and
Vosk (Apache-2.0) are the only two with reusable *code*; the rest are pattern inspiration only.

---

## Borrowable ideas, ranked

### Tier 1 — genuinely new, strong fit

#### A. Vosk **grammar-constrained recognition** for command mode  ⭐ best fit
**What:** Vosk can restrict the decoder to a JSON phrase list (`vosk_recognizer_new_grm` /
`KaldiRecognizer(model, rate, grammar_json)`), plus an `[unk]` token for anything out-of-grammar. The
decoder can then only emit paths inside your phrase set, so acoustically-ambiguous speech *snaps* to the
nearest valid command instead of a free-text mis-transcription — and it runs faster than full Whisper.

**Why it's the standout:** we **already have the phrase inventory** sitting in SQLite. Every enabled
command's phrases for the current context are already loaded in memory by `command_cache`. Compiling
those into a Vosk grammar is nearly free, and it turns command recognition from "Whisper transcribes
free text → normalize → substring-match → maybe LLM" into "constrained recognizer returns the exact
command or `[unk]`." High-confidence in-grammar hit → run it deterministically, no LLM round-trip;
`[unk]`/low-confidence → fall back to the existing faster-whisper + dispatch + LLM path. You can even
inject the **currently-visible AX element labels** into the grammar so "click <label>" is constrained to
what's actually on screen.

**Maps to:**
- `src/vox/command_cache.py` — expose the active phrase set (base + focused-app slice) as a flat list to
  compile into grammar JSON; re-compile on focus change / cache `invalidate()`.
- New `src/vox/stt/vosk_recognizer.py` (grammar recognizer) behind the `stt/base.py` interface.
- `src/vox/dispatch.py` — a fast pre-pass: if the grammar recognizer returns a confident in-grammar
  phrase, resolve via `command_cache.resolve()` and skip Whisper entirely for that utterance.
- `src/vox/config.py` — gate behind a flag (mirror `command_db_enabled`), default off.

**Caveats:** grammar mode only works with Vosk's **small "lookahead" (dynamic-graph) models** (~50 MB,
~300 MB RAM), not the large static ones; and it can only constrain to words already in the model lexicon
(no brand-new coinages without rebuilding the graph). Both are fine for command phrases. Model licensing
must be audited before bundling (some Vosk models are AGPL/CC — most are Apache-2.0).

**Effort:** medium. New dependency (`pip install vosk`, prebuilt wheels — light) + one recognizer class +
a dispatch pre-pass + grammar compilation from the cache. Fully additive and gated.

---

#### B. Vosk **streaming partial transcripts** → live captions + self-correcting loop
**What:** Vosk is frame-streaming (`AcceptWaveform` per ~0.25 s chunk → `PartialResult()` updates live,
`Result()` on endpoint). Whisper is batch-per-utterance, so we can't show text until the turn ends. The
documented hybrid pattern: **show Vosk partials instantly, then reconcile/replace with the Whisper
transcript once the utterance completes** — zero-latency display + Whisper-grade final text.

**Why:** biggest *UX* win in the scan. It makes dictation and the dashboard feel real-time, and it's the
natural substrate for the **queued "live conversation viewer" (#43)**. Right now the dashboard only sees
finalized turns.

**Maps to:**
- `src/vox/stt/base.py` — today the `Transcriber` Protocol is batch-only (`transcribe(audio)->str`). Add
  an optional **streaming** interface (`feed(chunk)` → partial/final events) so a Vosk backend can emit
  partials without breaking the Whisper backend.
- `src/vox/core/loop.py` / `src/vox/audio.py` — the capture loop feeds chunks to the streamer as they
  arrive (it already reads frame-by-frame).
- `dashboard/src/hooks/useConversationStream.ts` + `pages/Conversation.tsx` — render partials as they
  update, then swap to the Whisper-final text.

**Caveats:** running Vosk continuously alongside Whisper adds a warm model (~300 MB for the small model);
disk/RAM budget matters (see `disk-space-constraint` note). Do it only when a dictation/live view is
active, not always-on, unless we also adopt (A).

**Effort:** medium–large (touches the STT interface, loop, and dashboard). Best done *after* (A), since
both want the same streaming Vosk recognizer + interface change.

---

#### C. **Typed-argument command grammar** (Utterly Voice model) → command-DB past fixed phrases
**What:** Utterly Voice defines commands in data with four argument shapes: no-arg, **trailing
utterance-arg** ("scroll down *three*"), **optional-arg-with-default** ("page down" = 1, "page down
*four*" = 4), and **variable/rest-of-utterance** ("title *brave new world*" → "Brave New World"). Args
must be in the same utterance, immediately after the command word.

**Why:** our command-DB deliberately punted parameterised commands to the code parser (`actions.parse`,
"decision #2" in `command-db.md`) — so "search X", "open <arbitrary>", "tab by name" still live in
Python. This is the clean spec for letting **users** define parameterised commands as data, in the
dashboard, without touching code. It's the missing half of the command-DB vision and pairs with the
queued **Commands page** work.

**Maps to:**
- `src/vox/command_store.py` — extend the schema: a `phrase.match_type` like `template` plus an
  argument-capture spec (e.g. `"scroll down {n:number}"` → intent `scroll`, arg from `{n}`). The `param`
  column already exists and is unused — this is what it's for.
- `src/vox/command_cache.py` / `dispatch.py` — resolver learns to capture and pass the argument.
- `dashboard/src/pages/Commands.tsx` — a GUI command-builder that writes the grammar (avoids Utterly
  Voice's raw-YAML learning curve — we have a web UI, use it).

**Effort:** medium. Schema + resolver + one dashboard form. No new runtime deps.

---

### Tier 2 — worth doing, medium value

#### D. Formalize a **pluggable + streaming recognizer interface**
We already have `stt/base.py` as a Protocol — half the job. Extending it to (i) a streaming variant and
(ii) an explicit backend registry (faster-whisper / Vosk-grammar / Vosk-stream / whisper.cpp / cloud)
is the enabler for A, B, and G. Utterly Voice's pluggable recognizers validate the shape. Keep
faster-whisper the default. **Do this as the foundation for Tier 1.**

#### E. Optional **local-LLM punctuation/cleanup pass** for dictation
SpeechPulse and WhisperTyping both bolt an LLM cleanup stage after raw ASR ("make this pretty" without
changing the words). This is **backlog #10** already; the scan just confirms it's table-stakes for
dictation-heavy users. Keep it local (Ollama or our existing model) to preserve the offline promise, and
make it a toggle (auto-punctuation vs verbatim). Maps to `actions.dictate()` / the executor.

#### F. **Speaker-ID gating** (Vosk `spk` model, ~13 MB, language-independent)
Vosk returns an x-vector per utterance; compare cosine distance to an enrolled profile to **restrict
activation to a known voice**. New personalization/security capability (relates to #40 "learn your
name"). You build the enrollment/matching yourself — small, self-contained. Note for later.

#### G. Benchmark **whisper.cpp + CoreML/Vulkan** for the cross-platform GPU story (#20)
Vibe deliberately stayed on whisper.cpp (not faster-whisper) to get **Vulkan on Win/Linux/AMD/Intel +
CoreML on Apple Silicon** from one codebase — real numbers: "RTX 3060 transcribed 1 hour in 2.5 min."
faster-whisper's GPU path is CUDA-centric; CPU-only elsewhere. If cross-platform (#20) becomes real,
benchmark whisper.cpp+CoreML vs faster-whisper on Apple Silicon for our latency budget before committing.
A **Parakeet-TDT English fast-path** (Vibe ships it) is another low-latency option for dictation-only.
Slots behind the recognizer interface (D).

---

### Tier 3 — notes / nice-to-have

- **Voice macros with counters + sleeps** (Utterly Voice): record a keystroke/click sequence by voice,
  replay by name with a repeat count. Lightweight user-programmability; relates to self-wiring learning
  (#14). **But** don't record vision-labeled clicks (non-deterministic) — only record stable AX
  identifiers, which is exactly what our AX path gives us.
- **localhost intercept-hook pipeline** (WhisperTyping): model dictation as `STT → replacements →
  hook(intercept?) → AI mode → inject`, where a single `intercept` boolean decides "this was a command,
  suppress typing." We already have a web server; this is a clean way to let external tools extend
  command handling over HTTP, and to keep both `verbatim` (raw) and `text` (cleaned) payloads around.
  Architecture inspiration, not a must-do.
- **Numbered-overlay / mouse-grid click fallback** (Utterly Voice) for apps that don't cooperate with the
  AX tree; and **reuse Vimium** for web element selection instead of building DOM detection from scratch
  (relates to #37 real-website control).
- **Small UX borrows from SpeechPulse:** a `"numeral 5"` escape alongside our `"literally …"`; an
  explicit commands-only / dictation-only / both toggle; an optional **push-to-talk** hotkey for
  low-latency dictation bursts (we're wake-word+VAD today).

---

## Explicitly NOT recommended

- **Don't replace faster-whisper with Vosk for dictation.** Vosk small-model free-text WER is materially
  worse than Whisper, with no built-in punctuation/casing (English/RU/DE punctuation models only). Vosk's
  edge is latency/streaming/**constrained commands**, not raw accuracy. Layer it in; don't swap.
- **Don't adopt Vosk's endpointer to replace smart-turn-v3.** It's a lateral move — our semantic turn
  detector is already better than silence-based endpointing. (If we run Vosk for A/B anyway, its endpoint
  signal is a free bonus, but it's not a reason on its own.)
- **Don't copy the closed/cloud/Windows-only postures** (WhisperTyping cloud-default, SpeechPulse
  CUDA-only + Apple-Silicon-only, both Windows-first). These are the exact limitations Vox's local-first,
  cross-platform direction is trying to beat.
- **Don't build recordable macros on vision-labeled coordinates** — Utterly Voice's own docs warn the
  labels vary run-to-run. Prefer stable AX identifiers.

---

## How this maps to the codebase (quick reference)

| File | Change for which idea |
|---|---|
| `src/vox/stt/base.py` | (D) add a streaming recognizer interface + backend registry — foundation for A/B/G |
| `src/vox/stt/vosk_recognizer.py` *(new)* | (A) grammar recognizer, (B) streaming recognizer |
| `src/vox/command_cache.py` | (A) expose active phrase set as grammar; (C) capture args |
| `src/vox/command_store.py` | (C) `template` match_type + typed-arg spec (the unused `param` column) |
| `src/vox/dispatch.py` | (A) grammar pre-pass before Whisper; (C) pass captured args |
| `src/vox/core/loop.py`, `src/vox/audio.py` | (B) feed chunks to the streamer as frames arrive |
| `src/vox/actions.py` (`dictate`) | (E) optional LLM punctuation/cleanup pass; (Tier 3) `numeral` escape |
| `src/vox/config.py` | flags for A / B / E, all default-off and gated |
| `dashboard/src/hooks/useConversationStream.ts`, `pages/Conversation.tsx` | (B) render live partials (#43) |
| `dashboard/src/pages/Commands.tsx` | (C) GUI command-builder writing the typed grammar |

## Suggested sequencing

1. **(D) recognizer interface** — small, unblocks everything else.
2. **(A) Vosk grammar command recognition** — highest ROI, reuses the command-DB we already built, fully
   gated. This is the one to prototype first.
3. **(C) typed-arg grammar** — completes the command-DB (data-defined parameterised commands + dashboard).
4. **(B) streaming partials** — the UX win; ride the interface from (D) and the warm Vosk model from (A).
5. **(E/F/G)** as demand/cross-platform needs surface.

---

## Appendix — per-tool detail

### Vibe (`thewh1teagle/vibe`, MIT)
Tauri desktop GUI; **whisper.cpp/GGML**, GPU via **Vulkan (Win/Linux/AMD/Intel) + CoreML (Mac)**. The
maintainer evaluated faster-whisper and **rejected it** (would lose translation, `initial_prompt`, GGML
models) — added Vulkan to whisper.cpp instead. Also ships **Parakeet-TDT** and Nemotron backends,
diarization, VAD-backed "stable timestamps," CLI + HTTP API w/ Swagger, model-manager + `vibe://download`
URL scheme, Ollama/Claude summaries. It's a **batch file-transcription** tool — not a low-latency
push-to-type loop; borrow *techniques* (GPU story, `initial_prompt` vocab, model UX), not architecture.
Sources: github.com/thewh1teagle/vibe · discussion #185 (faster-whisper vs whisper.cpp/Vulkan) · thewh1teagle.github.io/vibe

### SpeechPulse (closed, $99+, Win + Apple-Silicon only)
Whisper, offline; strong signals it's **faster-whisper/CT2** (CUDA-libs downloader, NVIDIA-recommended).
Most transferable ideas: **explicit 3-way mode** (dictation / commands / both, voice-switchable);
**literal/numeral escape prefixes**; a **command grammar → OS actions** (hotkeys, "scroll up 5 times",
window ops); push-to-talk **and** VAD; "Train New Words" custom vocab; optional **LLM grammar cleanup**
via user-supplied API. Sources: speechpulse.com · /voice-command-guide · /download · /help

### WhisperTyping (closed, $5–30/mo, cloud-default, Windows only)
Whisper Large; global push-to-talk → **virtual-keyboard injection** into the focused field. Key
takeaway: the **Local API** at `localhost:39849` — a **Command API** (control recording/settings/vocab
over HTTP) + a **Transcription Hook** with pipeline `Speech → Transcribe → Replacements & Punctuation →
Hook → AI Mode → Virtual Keyboard`; the hook can reply `{"intercept": true}` to **suppress typing** and
route the utterance as a command, and it carries both `verbatim` and cleaned `text`. Not a
computer-control reference (no AX). Sources: whispertyping.com · /support/local-api · /pricing

### Utterly Voice (closed but free/feature-complete, YAML-driven, Windows only)
**Pluggable recognizers** (Vosk default, Whisper, Azure/Deepgram/Google). Everything is YAML; **every
utterance is parsed against the active command grammar, non-matches are typed**. Command taxonomy: simple
/ utterance-arg / optional-arg-with-default / variable-arg; **`escape <words>`** to type command-colliding
phrases; **modes** = named command-set namespaces with hot **"reload settings"**. **Voice macros**
(record by voice, counters, sleeps, repeat count). UI targeting: Mouse Grid (recursive 3×3), Mouse
Position, "Show" (**vision** analyzer — non-deterministic labels), "Show Links" (**Vimium**). Their own
numbers: **Vosk ≈ 5 GB RAM vs Whisper < 1 GB** — evidence our Whisper pick is the lighter local choice.
Sources: utterlyvoice.com/help/{commands,customize,macros,mouse-control,recognizers}

### Vosk (`alphacep/vosk-api`, Apache-2.0 code; model licenses vary)
Kaldi-based offline STT. Python `pip install vosk` (prebuilt wheels). Small models **~50 MB / ~300 MB
RAM**; large 1–4 GB. **Streaming**: `KaldiRecognizer.AcceptWaveform(chunk)` → `PartialResult()` live,
`Result()` on endpoint (returns 1). **Grammar**: `KaldiRecognizer(model, rate, '["phrase", "[unk]"]')`
constrains the decoder — big command-accuracy + latency win; **only on small lookahead models**, lexicon-
bound. **Word timestamps** (`SetWords`), **N-best** (`SetMaxAlternatives`), **speaker x-vectors**
(`spk` model, ~13 MB), **built-in endpointer** (`set_endpointer_mode`). Accuracy below Whisper on
free-form/noisy/accented/multilingual — so: **Vosk = fast always-on front line (partials + constrained
commands + endpoint), faster-whisper = accuracy backstop.** Sources: github.com/alphacep/vosk-api
(README, `src/vosk_api.h`, `python/example/test_simple.py`) · alphacephei.com/vosk/{models,adaptation}
· deepwiki.com/alphacep/vosk-api/6.3-customization
