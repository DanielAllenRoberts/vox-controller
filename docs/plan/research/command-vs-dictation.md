# Command vs dictation, per utterance, with no "start typing"

> **Question:** how do real voice products decide, utterance by utterance, whether speech is a
> **command** or **text to type**, without the user switching modes? Dragon is the reference: you
> just talk and it types, and commands still work.
>
> **Builds on:** `ideas.md` #2 (literal vs AI-task "write") and #9 (conversation vs command),
> `modes.md` (idle/control/assistant/dictation), and `research/dictation-stt-tools.md` (Vosk grammar
> lane, Utterly Voice's "non-matches are typed", SpeechPulse's 3-way mode). Those points aren't
> repeated here.
>
> **Headline:** no shipping product uses an LLM to make this call. Every mature system uses
> **(1) whole-utterance grammar match, (2) the pause that brackets the utterance, (3) a forced-mode
> escape (hotkey or prefix), and (4) a per-utterance undo**. They add **focus context** only to
> choose *which* grammar is active. Vox already has most of the parts. What's missing is the focused
> text-field probe, an exact-only command set for text contexts, risk tiers, and a typed-chunk history.

---

## 1. What the real products do

### Dragon (NaturallySpeaking / Professional)
- **Normal mode ("Dictation & Commands")** is the default. Dictation-only, Command-only, Numbers and
  Spell modes exist for when you want only one ([recognition modes][dragon-modes]).
- **The pause is the main signal.** "Dragon uses the length of the pause between utterances to decide
  whether you're giving a command or dictating." For a command, pause briefly before and after it.
  The pause length is a setting (Options → Commands, "Pause required before commands")
  ([commands entered as text][dragon-pause]). A command embedded in continuous speech is typed.
  On Mac, "if you speak smoothly and continuously, Dragon will interpret your words as dictation,
  even if they include words that might be a command" ([Mac modes][dragon-mac-modes]).
- **The command must be the whole utterance**, and it must match a command grammar. The exceptions
  are argument commands ("Select hello", "Insert before X"). For these you don't pause *after* the
  verb, because the argument is part of the same utterance.
- **Forced overrides:** hold **Ctrl** to force the utterance to be a command. Dragon Medical also
  documents holding **Shift** to force dictation ([dictation not recognized][dragon-shift]).
- **Non-text fields / unsupported apps:** where Dragon lacks "Full Text Control", it opens the
  **Dictation Box**, a scratch editor you dictate into and then *Transfer* to the target. Cancel
  discards ([Dictation Box][dragon-dbox]). So Dragon never sprays text into something it can't edit.
- **Undo:** "Scratch that" deletes the last *utterance*. How much text that is depends on where you
  paused, and it can be repeated. "Undo that" undoes the last command or dictated chunk
  ([take it back][dragon-takeback]). "Select-and-Say" ("select <words>" then speak the replacement)
  is the correction path. It needs Full Text Control, because Dragon has to know the field's text.

### macOS Voice Control
- **Dictation mode is the default:** "Any words you say that aren't Voice Control commands are
  entered as text." **Command mode:** "Words … that aren't commands are ignored and aren't entered
  as text." It exists to avoid "mistakenly entering a Voice Control command as text." **Spelling
  mode** is for passwords and URLs ([Apple: Voice Control commands][apple-vc]).
- It asks you to "pause about half a second between commands". This is the same pause rule as Dragon.
- When Command mode is on, an icon (lozenge) appears **in the text input area**. That's a per-field
  mode indicator ([Apple Community][apple-lozenge]).
- Text editing ("Replace cat with dog", "Delete that", "Undo that", numbered text overlays) is
  shared between Dictation and Spelling modes. "Delete that" removes the last transcribed segment
  ([MacMost tips][macmost]). Commands only match their exact listed wordings.

### Talon (talonhub/community)
- Modes are just flags. `command_mode()`, `dictation_mode()` and **`mixed_mode()`** (which enables
  both flags) are in [`core/modes/modes.py`][talon-modes]. The voice switches ("dictation mode",
  "command mode", "mixed mode") are in [`command_and_dictation_mode.talon`][talon-cdm]. Mixed mode =
  every command rule *plus* the catch-all `<user.raw_prose>` rule from
  [`dictation_mode.talon`][talon-dm]. A full command match wins, and the rest is typed.
- **Anchoring does the safety work.** Control commands are written `^...$`, so they fire only as
  the *entire* utterance. "go to sleep" is `^go to sleep [<phrase>]$` ([`modes_not_dragon.talon`][talon-nd]).
- **Escape hatch:** `^escape <user.text>$` types words that would otherwise be commands. `press <keys>`
  works inside dictation.
- **Inline dictation commands:** `cap` / `no cap` / `no space`, `go left N words`,
  `select left N words`, `clear left N words`, `spell that …`, `formatted …`. Text is inserted via
  `dictation_insert()`, which **peeks at the characters around the cursor** to decide spacing and
  capitalisation ([`text_and_dictation.py`][talon-tad] `dictation_peek`).
- **Undo = phrase history.** Every insertion is pushed onto `phrase_history`. "scratch that" /
  "nope that" sends exactly `len(last_phrase)` backspaces and pops the entry, so repeating it walks
  back one phrase at a time. "select that" selects it ([`phrase_history.py`][talon-ph]).
- No automatic field-based switching ships in community. Users scope `.talon` files by `app:` /
  `title:` contexts, so the context picks *which commands exist*, not whether to type.

### Dragonfly / Caster / Kaldi
- Grammars are activated by **context** (`AppContext` executable/title). `Dictation` elements capture
  free words *inside* a rule. CCR chains several commands in one utterance via a `Repetition`
  element ([Dragonfly CCR][dfly-ccr]). Caster: non-CCR commands need a pause after them, and CCR
  "MergeRules" allow several per utterance ([Caster rules][caster-rules]). The "breathe" wrapper adds
  the pattern **`<0–12 commands> <Dictation>`**: commands first, then the rest of the utterance is
  typed ([dfly-breathe][breathe]).
- The Kaldi backend has two relevant knobs ([Kaldi engine][dfly-kaldi]). First, a **longer VAD tail
  for "complex" (in-dictation) utterances** (`vad_complex_padding_end_ms`): the endpoint itself
  depends on command vs dictation. Second, `expected_error_rate_threshold` drops low-confidence
  recognitions. It can also route `Dictation` elements to a separate "alternative dictation" engine
  (e.g. Whisper), while commands stay on the constrained decoder. That's the same split as Vox's
  Vosk + Whisper lanes.

### Serenade, nerd-dictation, Numen
- **Serenade** is command-first. Text needs `insert` / `system` verbs, and invalid commands show an
  ✗ and do nothing. When unsure, it shows **numbered alternatives**: the first runs, you say a
  number to swap, or "undo". "dictate mode" types everything except undo / repeat / stop
  ([Serenade docs][serenade]).
- **nerd-dictation** is dictation-first. One `nerd_dictation_process(text)` hook can act on keywords
  and return `""` to suppress typing, and `--defer-output` holds output until the end
  ([README][nerd]). That's WhisperTyping's intercept hook again.
- **Numen** (Vosk) is command-first. Free text comes after an explicit **"scribe"** prefix
  ([Numen][numen]).

### Modern AI dictation (Wispr Flow, Superwhisper, VoiceInk, Aqua)
- **Wispr Flow** separates the two by **hotkey, not classification**. Normal dictation never runs
  commands: spoken triggers like "Hey Flow" explicitly don't start Command Mode. **Command Mode** is
  a separate hold-to-talk key that sends the instruction plus the text box contents and selection to
  an LLM. With no editable box focused, the result goes to a notification instead of being pasted
  ([Wispr docs][wispr]). Inline self-correction ("3, no make it 4") is handled by LLM post-processing
  of the *text*, not as a command ([Wispr][wispr-why]).
- **Superwhisper / VoiceInk** pick a **configuration per app or site** (prompt, model, language)
  ([Superwhisper modes][sw-modes], [VoiceInk Power Mode][vi-pm]). VoiceInk's
  [`ActiveWindowService.swift`][vi-aws] matches the frontmost **bundle id**, then the browser URL
  asynchronously, then falls back to a default mode. Its
  [`ModeTriggerWordDetectionService.swift`][vi-trig] switches mode via a **trigger word at the start
  or end** of the transcript (the longest match wins, and the trigger is stripped). Neither app
  runs desktop commands from dictation.
- **Aqua Voice** claims to infer "write vs execute" in context, but documents no mechanism. A
  reviewer found "press Tab key" typed literally when it was used next to Voice Control
  ([9to5Mac][aqua]).

## 2. Signals, ranked by how much products rely on them

| Signal | Who uses it | Notes |
|---|---|---|
| **Whole-utterance grammar match** | Dragon, Voice Control, Talon `^…$`, Utterly Voice | The universal core. Partial or "contains" matches are not used. |
| **Bracketing pause / isolation** | Dragon (tunable), Voice Control (~0.5 s), Caster non-CCR | A command embedded in flowing speech → text. |
| **Forced override** (hotkey / prefix / escape word) | Dragon Ctrl/Shift, Wispr hotkey, Talon `escape`, Numen "scribe", Serenade `insert` | Cheap and unambiguous. Every product has one. |
| **Focus context** (app / title / URL) | Talon, Dragonfly, VoiceInk, Superwhisper | Selects *which grammar* is active. |
| **Is the focused element editable?** | Dragon (Full Text Control → Dictation Box), Wispr (no box → notification) | Decides *where* text can go, not the command decision. |
| **Recogniser confidence** | Kaldi `expected_error_rate_threshold`, Dragon internally | Rejects junk. Doesn't classify. |
| **LLM intent classification** | Only behind an explicit hotkey (Wispr) or undocumented (Aqua) | Nobody does it on the hot path. |

**Failure modes.** *Command typed as text:* it was spoken as part of a sentence, so the fix is
"pause, say it alone" or Ctrl-force, then "scratch that". *Dictation fired as a command:* the risk
is minimised because commands must fill the whole utterance, and fixed with "undo that". Voice
Control's Command mode and Talon's `escape` exist exactly for these.

## 3. Proposed decision procedure for Vox

This is a new **auto mode** inside CONTROL (gated, default off: `auto_dictation_enabled`). It makes
control mode behave like Dragon's Normal mode whenever a text field has focus. ♻ = reuses an
existing Vox piece; ✚ = new.

```
utterance (already segmented by silence/turn detector → Dragon's "pause" rule for free ♻)
│
├─ L0  HARD FLOOR (unchanged ♻ core/loop.py): abort / sleep / quit / restart / mode phrases
│      ("stop typing", "take control"…). Whole-utterance only. Always wins.
│
├─ L1  EXPLICIT OVERRIDES — no guessing
│      • "literally …" / "type …"            → TEXT   (♻ actions.dictate literal escape)
│      • "Vox, …" / "command …" prefix       → COMMAND (normal control dispatch)
│      • optional held key = force command    (✚ Dragon-Ctrl equivalent, later w/ hold-to-talk #69)
│
├─ L2  FOCUS PROBE (✚ ax.focused_text_target(), ~1–5 ms, cached per focus change ♻ focus_watch)
│      AXFocusedUIElement of the frontmost pid →
│        editable = role ∈ _TEXT_INPUT_ROLES (♻ ax.py) OR (AXValue settable AND has
│                   AXSelectedTextRange)  — covers web contenteditable / Electron (Slack, Docs)
│        secure   = role == AXSecureTextField → never auto-type, never log
│      Not editable → CONTROL as today (deterministic → brain escalation ♻). Stop here.
│
├─ L3  TEXT CONTEXT: COMMAND only if the WHOLE utterance is an EXACT command
│      • In-dictation edit words first (♻ actions.dictate specials: "new line", "delete word",
│        "undo"…) + the new history commands below.
│      • Then command_cache.resolve() restricted to: match_type == 'exact' (NOT 'contains' —
│        today 150/151 builtins are 'contains' with 3 slack words, so "please close tab now"
│        matches), source != learned-on-probation, ≤ ~5 words.  (✚ a `text_context=True` flag)
│      • Vosk fast lane (♻ _recognize) may propose; accept only if utterance duration fits the
│        phrase (≲ 1.5× expected) — a long sentence force-aligned onto a command (issues O21)
│        must fall through to Whisper. In text context, Whisper is the arbiter.
│      • Risk gate (below) on the hit.
│
├─ L4  OTHERWISE → TEXT. actions.dictate(text) (♻), and push the chunk onto history (✚).
│      Compose/rewrite intents ("write me…", "make this pretty") keep their explicit verbs (♻ #10).
│
└─ L5  LLM — NEVER on the typing path. Only via L1 "Vox, …" or after an undo ("that was a command").
```

Why this order: L0 and L1 cost nothing and are unambiguous. L2 is one AX call and decides whether
typing is even possible. L3 is an in-memory match. Only L4 costs Whisper, which dictation needs
anyway. Nothing waits on the brain.

### Safety: destructive commands never fire from dictation-looking speech
- **Risk tier per intent** (✚ a static map in `dispatch.py`, later a column on `intent`). `safe` =
  navigate, scroll, switch tab/app. `edit` = delete word/line (reversible with ⌘Z). `destructive`
  = quit app, close window, sign out, empty trash, and **Return in a chat app** ("send"/"submit" in
  `dictate()` today *sends the message*).
- In **text context**, `destructive` needs **all of** the following: an L1 prefix ("Vox, quit Slack"),
  the exact phrase, and Vosk/Whisper agreement. Otherwise Vox asks "Quit Slack?" (♻ the
  "Did you mean X?" confirm in `executor.py`). Learned commands, `contains`/`regex` matches and
  LLM-routed actions can never be destructive from a text context.
- Bare "send"/"enter" in a field whose app is a chat client → keep it, but log it as `destructive`
  so the trial data shows how often it misfires.

### Undo: typed text is always reversible
- ✚ **Chunk history** (Talon's `phrase_history`): for each `dictate()` paste, record
  `(text, pid, focused element ref, len, time)`. Vox pastes one chunk per utterance (♻ `_paste`), so
  each chunk is also one ⌘Z step in most apps.
- **"scratch that"** / "nope that": if the focused element is unchanged and nothing has been typed
  since, select-left `len` characters (verify against `AXValue` when it's readable) and delete. Else
  send ⌘Z. Repeat to walk back. ("scratch N words" already exists ♻.)
- ✚ **"that was a command"**: scratch the last chunk, then run its text through normal control
  dispatch (brain allowed). This is the recovery for a command typed as text.
- ✚ **"type that"** after a `safe` command fired: undo it if Vox has an inverse (tab/app switch → go
  back), then type the words. Not offered for `edit`/`destructive`.
- **Visible state:** show "✎ typing → <App> field" vs "⌘ command" per utterance in the overlay
  (♻ `overlay.py`/`bubble.py`), like Voice Control's in-field lozenge.

### Inline dictation commands
Vox's `dictate()` already covers new line / enter / delete word(s) / line / paragraph / undo /
redo / literally. Worth adding, in Talon's shape (whole-utterance only): `select that`,
`select last N words`, `cap that` / `no caps that`, `go to end`. Use Talon's **cursor peek** for
spacing and capitals instead of the current per-session state; read `AXValue` and
`AXSelectedTextRange` directly, which beats Talon's keystroke peek.

### Build order (each step verifiable)
1. `ax.focused_text_target()` + log `[focus] editable=… role=…` per utterance → verify: compare the
   log against reality in Slack, Arc (Gmail), Cursor, Notes, Finder. Electron and contenteditable
   are the likely misses.
2. `resolve(..., text_context=True)` exact-only + risk map → verify with unit tests: "please close
   tab now" → None; "close tab" → hit; learned and destructive phrases excluded.
3. Chunk history + "scratch that" / "that was a command" → verify with tests on the history ring,
   plus a live check in Notes.
4. Auto mode behind `auto_dictation_enabled`; log every decision as `[route] TEXT|CMD reason=…` so
   misroutes are greppable.

## 4. Notes from the command-learning trial (relevant here)
- `vox.log` shows learned phrases that include conversational lead-ins and rants. One example:
  "no that didn't really work click on the team folder" was saved as a command, and a ~15-word
  complaint about CPU load was attached as an alias of "next song". Neither should become a command
  phrase. Under this design they'd also be excluded from text contexts (too long / learned). The
  `learning_min_hits` and length limits may need tightening.
- The live `data/commands.db` currently holds **no learned commands** (151 builtin phrases only).
  The log, meanwhile, shows repeated saves reusing ids #50–#55, so the DB looks reset between
  sessions. Worth checking that learned commands actually persist.

---
[dragon-modes]: https://www.nuance.com/products/help/dragon15/dragon-for-pc/enx/professionalindividual/Content/DragonBar/dragonbar_recognition_modes.htm
[dragon-pause]: https://www.nuance.com/products/help/dragon/dmpe42/enx/dmpe/Content/tshoot/commands_entered_as_text.htm
[dragon-mac-modes]: https://nuance.com/products/help/dragon/dragon-for-mac6/enx/Content/Introduction/RecognitionModes.html
[dragon-shift]: https://www.nuance.com/products/help/dragon/dmpe42/enx/dmpe/Content/tshoot/dictation_not_recognized.htm
[dragon-dbox]: https://www.nuance.com/products/help/dragon15/dragon-for-pc/enx/dpg-vla/Content/Dictation/using_the_dictation_box.htm
[dragon-takeback]: https://nuance.com/products/help/dragon/dragon-for-mac/enx/Content/Correction/TakeBack.htm
[apple-vc]: https://support.apple.com/guide/mac-help/mh40719/mac
[apple-lozenge]: https://discussions.apple.com/thread/256014358
[macmost]: https://macmost.com/20-voice-control-dictation-tips.html
[talon-modes]: https://github.com/talonhub/community/blob/main/core/modes/modes.py
[talon-cdm]: https://github.com/talonhub/community/blob/main/core/modes/command_and_dictation_mode.talon
[talon-dm]: https://github.com/talonhub/community/blob/main/core/modes/dictation_mode.talon
[talon-nd]: https://github.com/talonhub/community/blob/main/core/modes/modes_not_dragon.talon
[talon-tad]: https://github.com/talonhub/community/blob/main/core/text/text_and_dictation.py
[talon-ph]: https://github.com/talonhub/community/blob/main/core/text/phrase_history.py
[dfly-ccr]: https://dragonfly.readthedocs.io/en/latest/ccr.html
[dfly-kaldi]: https://dragonfly.readthedocs.io/en/latest/kaldi_engine.html
[caster-rules]: https://caster-lexiconcode.readthedocs.io/en/docs/readthedocs/Rule_Construction/Basic_Caster_Rules/Basic_Rules/
[breathe]: https://pypi.org/project/dfly-breathe/
[serenade]: https://serenade.ai/docs/
[nerd]: https://github.com/ideasman42/nerd-dictation
[numen]: https://pkg.go.dev/git.sr.ht/~geb/numen
[wispr]: https://docs.wisprflow.ai/articles/4816967992-how-to-use-command-mode
[wispr-why]: https://wisprflow.ai/why-flow
[sw-modes]: https://ai.superwhisper.com/docs/modes/switching-modes
[vi-pm]: https://tryvoiceink.com/docs/model-or-language-changing-automatically
[vi-aws]: https://github.com/Beingpax/VoiceInk/blob/main/VoiceInk/Infrastructure/SystemIntegration/Context/ActiveWindowService.swift
[vi-trig]: https://github.com/Beingpax/VoiceInk/blob/main/VoiceInk/Features/Modes/Models/ModeTriggerWordDetectionService.swift
[aqua]: https://9to5mac.com/2025/08/15/aqua-voice-shows-just-how-good-mac-dictation-could-be-if-apple-just-tried/
