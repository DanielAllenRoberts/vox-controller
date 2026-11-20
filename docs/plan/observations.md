# Vox — Observations & Edge Cases

> A running log of interesting failures, ambiguities, and ideas found while *using* Vox — so we design real solutions instead of one-off patches. Each entry: what happened, why, and the intended fix.

## 2026-06-17 — "go to Cursor" heard as "go to Casa" → opened casa.com

- **What happened:** Said "go to Cursor"; Whisper transcribed "Casa"; `go to` had no app/alias/domain match, so it *confidently guessed* `https://casa.com` and opened a random site.
- **Root cause — two stacked failures:**
  1. **STT mis-transcription** ("Cursor" → "Casa").
  2. The command layer guesses `.com` for any unknown single word with **no notion of confidence**.
- **Solution A — reduce the mis-hear (bias the STT):** feed Whisper an `initial_prompt` / `hotwords` of our command verbs + the user's installed app names (Cursor, Arc, Safari…). Whisper then favours known terms, so "Cursor" beats "Casa". Cheap, attacks the root cause. *(Not yet implemented.)*
- **Solution B — recover from uncertainty (escalate):** when the deterministic layer can't *confidently* resolve a target, **hand off to the assistant** instead of guessing. The assistant — knowing installed apps, common targets, and habits — reasons "‘Casa' isn't a known site… did you mean *Cursor*?" and confirms/corrects. The OpenClaw-style intelligent fallback.
- **Status:** ✅ improved (2026-06-17). Navigation now acts **only on known targets** (app / known site / real domain) — unknowns **hand off** instead of guessing (no more accidental `casa.com`, no googling your narration). Added explicit **"search X"**. And **hotword biasing** nudges STT toward "Cursor"/"Arc" over "Casa". Full LLM escalation still lands with **M4**.

## 2026-06-17 — Arc / macOS scripting limits found while building navigation

- **Arc tab index is unreliable.** `tabs of front window` returns *all* tabs across spaces/folders (52, mostly `location: pinned`) in an order that doesn't match the visual sidebar. → Tab-by-**name** (now fuzzy) is the reliable path; index isn't.
- **Arc folders/spaces aren't scriptable.** No `spaces` access (`Can't get every space`); tabs only report `location` = pinned/unpinned/topApp, no folder grouping. → Folder/space/profile-scoped nav isn't possible via AppleScript.
- **Window switching can't cross macOS Spaces.** A Cursor process with two windows on different desktops reports `count of windows = 1` to the Accessibility API — the other Space's window is invisible. ⌘`-cycling only works within the current Space.
- **Win:** fuzzy tab matching (difflib) resolves "Moonshark"→Moonshot, "chat upt"→ChatGPT, and partial names — a cheap, reliable improvement (and a first taste of the personalised-matching idea in `ideas.md` #8).

## 2026-06-17 — Ambient audio gets transcribed ("click click click", YouTube outros) 😄

Control mode is a hot mic, so Whisper transcribes *everything* it hears: keyboard clicks → "click click click", clock sounds → "tick tock tick tock", and even a **playing YouTube video's narration** ("if you like this video please subscribe and like…"). All of it correctly **hands off** (no action) thanks to no-guess matching — harmless, just genuinely funny to watch Vox earnestly hand off a YouTuber's outro. The one real risk: a command buried in ambient speech (e.g. reading the hotword list aloud fired "next desktop"). Future mitigation: a confidence / voice-activity gate, or just "stand down" when not actively commanding.

## 2026-06-17 — Hallucinated commands on silence (hotword bias amplified it)

The mic captured background noise (no speech) and Whisper **hallucinated** text — specifically *our hotword list* ("vox quit close exit shut down tab window"), because biasing toward those words makes Whisper reach for them on noise. "shut **down tab**" then parsed → fired "Tab down" with no one speaking. **Fix: `vad_filter=True`** in faster-whisper runs a real speech detector and drops non-speech before transcribing → noise yields empty → no command (verified: silence + hotwords → `''`). Lesson: hotword biasing helps real recognition but worsens noise-hallucination; VAD is the counterweight. A grammar gate (only act on short, clean command utterances) would harden it further — see `ideas.md` #9.

## 2026-07-15 — Dictation: a pause fuses words in Arc's search/address bar ("control on" → "controlon")

- **What happened:** dictating *"…use Cloud Code Remote Control [pause] on a different account"* into **Arc's search bar**, the pause between "Control" and "on" produced **"Controlon"** — no space. Same spacing logic works fine in normal editors.
- **Root cause:** `actions.dictate()` separates chunks across a pause with a **LEADING space** (`_paste((" " if _dictation_active else "") + raw)`, [actions.py:1115](../../src/vox/actions.py)) — chosen because most editors trim *trailing* spaces. But `_paste()` inserts via the **clipboard + ⌘V** ([actions.py:1018](../../src/vox/actions.py)), and Arc's URL/search field **trims *leading* whitespace on paste** — so " on" pastes as "on" and fuses onto the previous chunk. The leading-space strategy fails for the one field type that trims the opposite end.
- **Intended fix:** don't rely on a pasted leading space for the separator — type the gap as a real **space keystroke** (key code 49) into the field *before* pasting the chunk, since a keypress isn't subject to paste-trimming. (Or detect address-bar-like fields and switch strategy.) Needs testing across editors + search bars so we don't double-space normal editors.
- **Status:** ⚠️ logged, not fixed. Part of the broader "dictation robustness across app types" theme.

## 2026-07-15 — Daemon froze after a self-echo barge-in storm (no AEC on speakers)

- **What happened:** mid-conversation on **speakers** (not headphones), Vox spoke a reply, the mic picked up its **own TTS**, barge-in (#19) treated it as the user "cutting in", transcribed Vox's own words, and answered itself — **6 replies in ~1 minute** (11:05:50→11:06:47), each `⤳ you cut in — handling "<Vox's own previous reply>"`. Then the daemon **fully froze** — stopped speaking *and* stopped taking any commands; the user had to restart it. (Focus-watch thread kept logging window changes, so the process was alive but the main audio/loop was wedged.)
- **Root cause:** two stacked issues. (1) **Self-echo** — `audio_aec=False` + speaker output means the mic hears the TTS (the known O7 / AEC #21 problem). (2) The echo storm spawned overlapping barge-in / TTS-kill / re-listen operations that appear to have **deadlocked the audio layer** (PortAudio streams don't like concurrent open/close from stacked turns) — a true hang, not just the loop.
- **Not** `max_turns`: the SDK `max_turns` (assistant.py) caps *internal agent tool-use iterations per single call* and is wrapped in a 45s timeout so a wedged call "never hangs the loop"; the chat turns here ran on the DeepSeek small brain, which doesn't use it at all. Hitting max_turns returns a fallback line, it does not freeze the daemon.
- **Intended fix:** (a) enable `audio_aec` for speaker use (built, flagged off) so the mic stops hearing the TTS — kills the loop at the source; (b) harden the barge-in path so it can't stack overlapping turns / re-entrant TTS-kills (serialize turn handling; ignore mic input during our own TTS unless AEC confirms it's external); (c) a watchdog that re-inits the audio streams if the loop stalls N seconds. Headphones avoid it entirely today.
- **Status:** ⚠️ logged, not fixed. Highest-value fix is enabling AEC + serializing barge-in.

## 2026-08-03 — "how did you refresh the page?" → "That wasn't me" (it had, 24 seconds earlier)

- **What happened:** `'can you refresh the page?'` → the brain returned `CLICK: refresh` → *"Clicked
  Refresh the Page."* — it worked. 24 seconds later, `'how did you refresh the page'` → **"That
  wasn't me — refreshing is a control-mode command. When you say 'refresh' or 'reload,' Vox sends a
  Cmd+R keystroke to the browser through AppleScript. I only handle open conversation and questions
  in assistant mode."**
- **Two failures, and the second is the worse one.** (1) No recall: nothing in the prompt tells the
  brain what actions just ran, so it can't answer "what did you just do?". (2) **Confabulation:** it
  didn't say "I don't know" — it denied the act *and invented a mechanism*. It clicked the browser's
  Reload button via the AX/DOM click path; the Cmd+R-over-AppleScript story is fiction. A user who
  believed it would now have a wrong model of how Vox works.
- **Why it's cheap to fix:** `command_log` (built 2026-07-31) already records every resolution with
  `heard_phrase`, `resolved_intent`, `resolved_arg`, `resolved_by`, `success` and a timestamp. The
  gap is purely that none of it reaches the prompt. Injecting the last ~5 rows into the executor /
  chat context is a query plus a few lines of formatting — this is **exactly part 3 of ideas #56**
  ("What did you just do?" / recent-command recall), which already anticipated it.
- **Design note:** the recall should state what ran *and how it was resolved* (`db` / `parser` /
  `llm` / `click`), because the confabulation was specifically about mechanism, not just about
  whether it happened. Feeding intent+arg without the resolution path would fix the amnesia and
  leave the invented-explanation problem intact.
- **Status:** ⚠️ logged, not fixed. Queued with #56.

## The principle this points to

**Whenever a deterministic action is low-confidence or unmatched → escalate to the assistant.** This is the bridge between CONTROL mode (fast, deterministic) and ASSISTANT mode (LLM reasoning), and it's what makes the system feel smart rather than brittle. (See the tiered cascade in `overview.md`.)

## 2026-11-11 — Command-learning trial: it's learning mis-hears and fragments, not phrasings

Pulled from `grep "\[learn\]" vox.log` and `GET /api/commands/learning` while the trial runs
(`learning_mode = auto`, `learning_min_hits = 1`).

- **A mis-hear got learned twice, pointing somewhere different each time.** "open cloud" (Whisper's
  version of "open Claude") was saved once → cloud.google.com and once → iCloud Drive (#51). "That's
  not what I meant" correctly disabled #51, so the correction path works — but the root cause is the
  mis-hear. **Better fix:** a vocabulary entry (cloud → Claude after "open"), not learning around it.
- **A one-word fragment is one sighting from being learned.** Candidate #11: "win" → previous window
  (in Claude). Only the "words differ from the target → wait for a second sighting" rule holds it back.
  **Knob:** raise `learning_min_hits` to 2, or refuse single-word phrases outright.
- **Rambling sentences became aliases.** "click next song i don't know why its so slow my cpu is
  running at like 200" joined the learned Spotify "next" command. The later 13-word cap catches this
  one; shorter rambles still get through.
- **Doubled phrases** ("open arc open arc", "open obsidian open obsidian") were learned in earlier
  sessions; they've since aged out of the learned list.
- **Idle noise isn't leaking in:** an hour of background video ("thanks for watching!", a 60-word run
  of "the") produced no candidates.


## 2026-11-17 — Onboarding on a second Mac: Kokoro silently stuck on the macOS voice, and the app wouldn't build

Fresh setup on another machine (macOS 27.2, python.org Python 3.12, Command Line Tools only, no Xcode).

- **Kokoro never downloaded, with no sign of why.** Choosing Kokoro in Settings left Vox on the `say`
  voice; `~/.cache/vox/kokoro/` stayed empty. **Root cause:** python.org's macOS Python has no CA
  certificates until its `Install Certificates.command` is run, so `urlretrieve` failed with
  `CERTIFICATE_VERIFY_FAILED` — and the deliberate silent fallback to `say` hid it completely. The same
  failure breaks web search, Spotify and Composio (all `urllib`).
  **Fix:** `vox/__init__.py` points `SSL_CERT_FILE` at certifi's bundle when the interpreter has no CA
  store of its own; `tts.py` now logs the *first* Kokoro fallback with its reason (still falls back).
- **Vox.app wouldn't build with the Command Line Tools on macOS 27.** Three stacked problems:
  1. CLT 26.2 on macOS 27 → `Package.swift` failed to link (`Undefined symbols … Package.__allocating_init`).
     Updating to CLT 27.2 didn't fix it: stale Swift 5.10 `*.private.swiftinterface` files from a 2024
     CLT were left under `usr/lib/swift/pm/` (owned by no package) and shadowed the new interfaces.
     Moving them aside fixed the manifest.
  2. The macOS 27 SDK makes SwiftUI's `@State` a macro; the `SwiftUIMacros` plugin ships only with
     Xcode, not the CLT → hundreds of "cannot find '$x' in scope" errors.
  3. The default (swift-build) build system fails with "Unknown error parsing property list".
  **Workaround:** build against the CLT's macOS 26.5 SDK with the native build system — `build.sh` now
  passes `VOX_SWIFT_FLAGS` through (see its header / the README). Installing Xcode avoids 2 and 3.
- **Status:** ✅ SSL + logging fixed; build workaround documented. Longer term the onboarding could
  check for a CA store and a usable toolchain up front instead of failing deep inside.
