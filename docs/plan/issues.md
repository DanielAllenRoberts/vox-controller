# Vox — Issues Log

> Running log of problems we hit and how they were resolved, so nothing gets lost. Newest first.
> Status: 🔴 open · 🟡 partial / mitigated · ✅ resolved. (Started **2026-06-17** — day one, so most dates are the same.)

## Open / known limitations

| # | Date | Issue | Status | Notes |
|---|------|-------|--------|-------|
| O1 | 2026-06-17 | Can't interrupt Vox's **spoken** reply (talk over the TTS) | 🔴 | Needs acoustic echo cancellation (AEC) so Vox doesn't hear itself — see `ideas.md` #21. Barge-in (#19) only covers *LLM-call* interruption, where Vox is silent. |
| O2 | 2026-06-17 | Echo/feedback when using speakers (no headphones) | 🟡 | `mic.flush()` after TTS stops the *feedback loop*; true talk-over still needs AEC (#21, native macOS Voice Processing). |
| O3 | 2026-06-17 | Wild mis-transcriptions of short phrases ("go to sleep" → "courtesy") | 🟡 | Accent + short utterance. Upgraded `base.en` → `small.en` to reduce; can't catch every garble. |
| O4 | 2026-06-17 | Abandoned barge-in call still finishes in the background | 🟡 | Python can't kill a thread; a quick *action* it was about to run may still complete. Slow calls (chat/compose/vision) abandon cleanly. |
| O5 | 2026-06-17 | Arc "favorites"/pinned tabs outside the current space aren't reused | 🟡 | `tabs of front window` spans profiles (jumps you) so we stay current-space-only. Reaching favorites safely needs probing Arc's scripting model. |
| O6 | (ongoing) | Disk space is a constraint | 🔴 | Be frugal with deps/models. `small.en` took ~590 MB. |
| O7 | 2026-06-17 | **External audio (a video on the speakers) is transcribed and triggers commands/LLM** | 🟡 | Root cause: no echo cancellation — the mic hears *all* system + room audio. Mitigated by a single-word/filler gate before escalation, and now by **keyword-gated escalation** (`escalation_mode="keywords"`, ideas #23) — only utterances with a trigger word ("write", "vox", "make this"…) reach the brain, so ambient speech is ignored. The real fix is **AEC** (#21, native macOS Voice Processing cancels all speaker output incl. video). Headphones avoid it today. |
| O8 | 2026-06-17 | Barge-in (interrupt the LLM) feels unreliable | 🟡 | Logic is correct, but fast Haiku calls finish before you can speak, and ambient audio floods the interrupt-listener. Firms up with AEC (#21) + reserving barge-in for slow calls. |
| O9 | 2026-06-21 | **"Freezes after a while" / "doesn't idle well" — daemon wedges silently** | 🟡 | **Root cause (diagnosed via `sample`):** the sounddevice/PortAudio **mic stream silently dies** after an audio-device change (e.g. *opening Spotify*, a Bluetooth/headphone switch). The old `_restart()` re-opened the same stream without re-binding the device, so frames never returned and the main thread parked forever in `queue.get` — alive but deaf. Stall warnings went to **stdout, not `vox.log`**, so the log just stopped (the "silent freeze"). **Fix:** non-blocking background re-open (abort, not the deadlock-prone `stop()`; `sd._terminate/_initialize` to re-enumerate devices) **+ a watchdog** (`mic_stall_restart_seconds`, default 12s): if a *previously-working* mic stays starved, raise `MicStreamDead` → clean self-restart (fresh process reliably re-acquires the mic). Guarded by `_ever_healthy` so a never-working mic can't restart-loop. Recovery now logs to `vox.log`. **Pending the user's live acceptance test.** Separately reduced idle CPU/RAM churn: `whisper_cpu_threads` cap, `idle_max_utterance_seconds`, and a `mic.flush()` after idle transcriptions. |
| O11 | 2026-06-24 | **~2 GB RAM while running** — heavy for a "low running" daemon meant to run on any machine | 🟡 | **Diagnosed by measurement** (see `memory-footprint.md`): it's **two model weights**, not Python. **Kokoro neural TTS ~940 MB** (lazy-loaded on first speak; only active because `data/settings.json` set `tts_engine="kokoro"`, overriding the lean `"say"` code default) + **Whisper `small.en` ~840 MB** (always resident; serves wake + transcription). All Python/numpy/FastAPI/LLM-SDK/pyobjc glue is ~180 MB combined — a language rewrite would reclaim only ~100 MB while the native-backend models (90% of RAM) stay identical. **Path to < 1 GB:** `tts_engine` `kokoro`→`say` (−940 MB, the macOS voice is free) and/or `whisper_model` `small.en`→`base.en` (−460 MB). `say`+`base.en` ≈ **~580 MB**. onnxruntime arena tuning barely helps Kokoro (−115 MB only). **Recommendation:** ship `say`+`base.en` as defaults, expose Kokoro + `small.en` as opt-in quality upgrades. **Pending the user's decision on the voice/accuracy trade.** |
| O12 | 2026-08-03 | **Duplicate labels: "click rescrape" silently clicks the FIRST match** | 🔴 | A page with several identically-labelled controls (e.g. a Rescrape button per row) has no disambiguation: `targets.click_label()` takes `next(... == t)` and `ax.click()` likewise stops at its first hit, so you get whichever is first in document order, with no signal that others existed. **Intended fix:** when >1 element matches, show the numbered overlay **filtered to just those matches** ("I found 4 'Rescrape' buttons — say a number") — badges are the only sane disambiguator when the labels are identical. **Better half, now cheap via the DOM:** walk up to each match's nearest row/container and append its text, turning duplicates into "Rescrape — Takealot" / "Rescrape — Makro". That makes the prompt meaningful *and* lets "click rescrape for takealot" resolve directly, skipping the question. Not possible on the AX path. |
| O10 | 2026-06-23 | **Absolute reminder/alarm with a clear time still fails when the task isn't introduced by "to"** — e.g. "remind me at 3:30 PM **that** I have a meeting" → "I couldn't work out a time." | 🔴 | **Not** a time-parse failure (3:30 PM is fine). `_RE_REMIND_AT` / `_RE_ALARM_AT` only capture the task via `\s+to\s+(.+?)` anchored to `$`, so any other connector ("that", "about", "saying") or trailing text breaks the *whole* match → `parse_and_create` returns None → generic "couldn't work out a time". **✅ FIXED (2026-06-23):** broadened the task connector in both regexes via a shared `_TASK_TAIL = (?:\s+(?:to\|that\|about\|saying)\s+(.+?))?$` — kept *required* (not bare trailing text) so "set an alarm for 5 minutes" still doesn't read 5 as a clock. Verified: the reported case + `to`/`about`/`saying` connectors create reminders; alarm forms work; timer path unaffected; regression guard passes. **Also added — the robust fix (2026-06-23):** a **structured SCHEDULE path** — the brain now computes the absolute time itself (it's given `Now:`) and emits `SCHEDULE: <kind> \| <ISO when> \| <text> \| <repeat>`; the executor creates the job directly via `scheduler.create_structured()`, **skipping the fragile English re-parse**. The English regex remains as a backward-compatible fallback. So *any* phrasing now works as long as the model fills the time. **Still future (idea #50):** the AM/PM-ambiguity *follow-up question*. *Minor cosmetic:* `_confirm` still prefixes the body with "to" ("…3:45 pm **to** I have a meeting") regardless of connector — separate, low-priority. |

## Spoken replies cut off mid-word after ~30s — ✅ fixed (2026-08-03)

**Symptom:** the vox-speak MCP voice "randomly" stopped mid-sentence on longer messages, twice.

**Cause:** `tts._speak_say` ran `subprocess.run(cmd, timeout=30)`. On timeout `subprocess.run`
**kills the child**, and the caller's `except Exception: pass` swallowed it — so speech longer than
30 seconds was truncated mid-word with nothing logged anywhere. At `say`'s ~175 wpm that's about
**90 words**. Worse, the MCP server allows `_MAX_CHARS = 1000` (~160 words ≈ 55s), so the layer
above explicitly permitted text the TTS layer would silently cut in half.

**Fix:** the timeout is a guard against a HUNG `say`, not a cap on legitimate speech, so it now
scales with the text (`_say_timeout`: expected duration × 2 + 15s, floor 30s). The Kokoro path had
the same bug with a flat 60s `afplay` cap; there the wav's exact duration is known, so it's derived
(`duration + 15s`, floor 60s).

Measured: a 95-word message needed ~33s and got 30s (truncated) → now 80s. The MCP's own 1000-char
maximum needed ~55s → now 125s.

## "Whenever I say X do Y" had nowhere to go — ✅ TEACH built (2026-08-03)

Asked *"vox whenever I say refresh I want you to refresh the browser that I'm on"*, Vox replied
**"I've saved that as a standing rule."** It had saved **nothing** — the rules store held 0 rules;
all that happened was a `MEMORY[core]` note. Three separate faults behind it:

1. **No teach verb.** The executor had `CLICK` / `TYPE` / `EDIT` / `SCHEDULE` / `LOOK` / `DICTATE`
   and nothing for "from now on X means Y", so it returned an **empty** response and the request
   fell through to the chat brain — which can only talk, and was agreeable about it. **Fixed:** a
   `TEACH: <phrase> | <command>` directive writes a real `source='user'` command (no probation — you
   asked for it explicitly), scoped to the focused app, and refuses to shadow a builtin.
2. **There was no reload command at all.** `parse("reload")` and `parse("refresh the page")` both
   returned `None` — Vox could only refresh by CLICKing the browser's reload button, which is why it
   worked once and then didn't. **Fixed:** a `reload` intent (⌘R), matching only the CANONICAL
   wording ("reload" / "reload the page").
   **"refresh" is deliberately NOT a builtin synonym.** Hardcoding it was tried and backed out on
   the user's call: it hides the very thing we want to exercise, since the point is to prove the LLM
   can add commands. "refresh" must therefore be TAUGHT — `TEACH: refresh | reload` — which makes it
   a real `source='user'` row that then reaches the Vosk grammar via `active_phrases()` by itself.
   The capability is kept because TEACH needs a valid right-hand side to map onto; without a `reload`
   command there is nothing to teach "refresh" to mean.
3. **New intents could never be used.** `command.intent` is a foreign key into the `intent` table,
   which was only ever populated by `seed()` — and `seed()` no-ops on a non-empty DB. So `reload`
   existed in code, parsed fine, and any attempt to save it as a command died with
   `FOREIGN KEY constraint failed`. **Fixed:** `_sync_intents()` now runs every boot from `_migrate`.

**The one-word rule was NOT the blocker,** contrary to first read: in `loop.py`,
`dispatch.try_deterministic()` (which includes the command DB) runs *before* `_looks_like_noise`, so
a registered one-word command fires deterministically. The gate only stops one-word utterances
reaching the LLM — i.e. it blocks one-word *learning*, not one-word *commands*. It needs no change.

**Related, still open:** when the executor returns nothing, the chat brain answers — and its prompt
says *"If asked to do something you can't do from here, briefly say how they'd do it by voice"*.
That's what produced "click on github" → *"That's not a command I know. Say 'go to GitHub'"* when
the tab was open and `CLICK`/`navigate` were both available. The chat brain describes actions it
cannot perform, and has now three times claimed or implied an action it didn't take. Needs its own
fix: it should never claim to have saved/done anything, and an empty executor reply should retry
rather than fall through to chat.

## Set-of-marks vision click (tier 2): real track record — 🔴 fires, but not yet trustworthy

Built 2026-07-31 (#37/#52). Its **entire** history in `vox.log`, checked 2026-08-03:

| When | Attempts | Outcome |
|---|---|---|
| 2026-07-31 14:22–14:25 | 9 | **All failed on `502 Bad Gateway` (cloudflare)** from the vision API — a 3-minute transient outage, not a design fault. The logic never ran. |
| 2026-08-03 14:36 | 1 | Fired properly — and **clicked the wrong button**. |

That single real firing: the label tier gave up (`click pick for 'Later' … → none:None`), vision was
asked for `'Later'`, answered *"the 'Later' button appears to have badge number **11**"*, and the
click returned **`clicked Got it (#11 …)`** — the wrong branch of a Cursor "update available" dialog.

**Two concrete bugs, both cheap:**

1. **No label sanity check.** `click_index` returns the label it clicked, so we *knew* badge 11 said
   "Got it" while the user asked for "Later" — and clicked regardless. When the request is a plain
   label (not a positional description like "the second last message") and the chosen badge's label
   doesn't resemble it, that's a detectable miss: reject, or confirm ("I can see Got it — is that
   the one?"). This is the guard that makes the tier safe to trust.
2. **First-number-wins parsing.** `_click_by_vision` does `re.search(r"\d{1,3}", answer)`. The model
   reasons out loud despite being told to reply with a bare number, so any digit earlier in the
   prose — "I can see 3 dialogs…" — would be clicked instead of the real answer. `_parse_pick` was
   already hardened for exactly this (it scans from the LAST line up); this path wasn't.

**Note for #57 (tier 3, grid + raw coordinates):** tier 2 knows what it clicked and *still* got it
wrong. Tier 3 cannot know — it clicks a point. Fixing these guards first is what makes tier 3 safe
to attempt, and is why #56's correction loop is its real prerequisite.

## "hide clickable" escalated to the LLM (2026-08-03) — ✅ fixed

**Symptom:** saying "hide clickable" often went to the brain instead of dismissing the overlay.

**Root cause — an asymmetry, in two places.** (1) `loop._fast_lane_extra_phrases` deliberately adds
`dispatch._SHOW_CLICKABLE_PHRASES` to the Vosk grammar precisely so mis-hears snap to the real
phrase — but the **hide** phrases were never added. "hide" is short and Whisper clips it: `vox.log`
shows `'hi clickable'` and `'high clickable'`, neither of which contains "hide", so the cancel test
missed and the utterance escalated. (2) The dismissal was only ever checked inside the
`overlay.is_active()` branch, so saying it a beat after the overlay had gone (any utterance dismisses
it, and the helper self-terminates after 45s) also fell through.

**Fix:** a `_HIDE_CLICKABLE_PHRASES` tuple (canonical forms + the two observed mis-hears), added to
the Vosk grammar alongside the show phrases, and handled in `_overlay()` **regardless of overlay
state** — a late "hide clickable" is acknowledged quietly rather than interpreted. "hide the
sidebar" still falls through to the real sidebar command.

## Command DB: "open slack" opened the website, and phrases fired inside sentences (2026-08-03) — ✅ fixed

Two bugs, found from one user report ("I said open Slack and it kept opening the browser").

**1. The site seed froze the app-vs-site decision.** `seed()` built the `navigate` commands from
`actions._SITE_ALIASES` with **`arg=url`** — the already-resolved URL. `actions._navigate()` checks
`_app_exists()` *before* `known_url()`, so the parser had always preferred the installed app; the DB
answered with a URL and that check never ran. Enabling `command_db_enabled` therefore regressed
"open slack" from the Slack app to slack.com — and the same for every installed app in the alias
table (here: Slack, Spotify, Claude, Notion, Trello). **Fix:** seed `arg=name` and let `_navigate()`
decide at runtime, which also makes it correct per-machine. `_migrate_site_args()` rewrites the 25
already-seeded rows (idempotent, exact-URL scoped so learned/user rows are untouched). To force the
site over an installed app, say the domain — "go to slack.com".

**2. `contains` phrases matched inside any sentence.** `_phrase_hit` did a bare `p in t`. Seen live:
*"i said open slack and then you"* — the user **describing the bug to the agent** — matched the
seeded phrase "open slack" and navigated the browser. All 150 seeded phrases are `contains`, so this
was reachable from any of them. **Fix:** word-bounded match (so "open x" can't fire on "open xcode")
plus a budget of 3 extra words, beyond which it falls through to the LLM — the right place to judge
conversational speech. "please open slack for me" still resolves; a sentence that merely mentions a
phrase no longer does. All three learning gates still pass (150/150 seeded phrases resolve).

**Learning-trial note:** the same episode produced candidate #4 = `app_cycle 'slack'` with the phrase
*"opened a web browser instead of the actual app"* — the user's complaint sentence captured as a
command. Nothing was promoted (`learned: 0`, the never-learn gate held), but narration aimed at the
agent is reaching the learner. Candidates #3 and #4 were blocked.

## Browser web-content AX tree collapses intermittently (2026-08-03) — 🟡 mitigated by routing around it

**Symptom:** `show clickable` on a website badged only the browser toolbar — `vox.log` shows Arc
returning 8/8/8/8/13/13 targets while Slack returned 121-132 and Cursor 107.

**Root cause (measured, 85 samples of live browsing):** Chromium builds its web-content AX tree on
demand and **tears it back down**. `AXWebArea` was absent in **47%** of samples, in runs of 25-35s;
on one heavy page (a data table) **80%** of samples. While collapsed the entire page reads as ~12
elements of native window chrome. It is **not** a settle-time issue — the tree was verified stable
at 193 elements across an 11-second sampling series when up, and re-asserting `AXManualAccessibility`
then re-walking does not revive it when down.

**Why the existing rescue never helped:** `ax.targets_with_frames` retries when a walk comes back
below `min(20, best//2)` for that pid. For a browser whose *best ever* reading was itself a collapsed
13, the threshold is 6 — unreachable. The rescue only ever protected apps that had been healthy once.

**Fix:** don't depend on it. `vox/webdom.py` reads page elements from the DOM via the browser's
AppleScript `execute javascript`, and `vox/targets.py` routes browsers to that path (native apps are
untouched and still use AX). The DOM returned correct targets on 43/43 samples including every
AX-down one. See ideas.md #37 for the full measurements and the two design traps found on the way.

**Residual:** needs "Allow JavaScript from Apple Events" per browser (Arc on by default; Chrome and
Safari need the one-off Developer-menu setting, else it falls back to AX). iframes aren't enumerated.

## Click / AX support for Electron apps (2026-06-25) — 🟡 partial: core works, **latency unacceptable**

**Status:** the *mechanism* works (verified live), but it's **too slow to ship** — a click that
isn't an immediate hit can take **~50 s** to fail. All changes are **uncommitted** on `command-db`.

### What was diagnosed (against Slack, an Electron app)
The user said *"click github"* (a Slack channel) and it failed → the brain then turned it into
*"go to github.com"*. Root causes, confirmed by probing Slack's live AX tree:
1. **Electron/Chromium hides its web-content AX tree** until an assistive client sets
   `AXManualAccessibility` on the process. Without it, Slack's window reads as `windows=0` / nearly
   empty — so the old click matcher had nothing to match.
2. **The label isn't pressable.** The "github" chat is an `AXStaticText` whose actions are only
   `AXShowMenu`/`AXScrollToVisible` (no `AXPress`). Its **ancestor `AXRow`/`AXGroup` *do* support
   `AXPress`** — so you must press the nearest pressable ancestor, not the label.
3. **It's deep** (depth 23) — the old matcher capped at depth 14, never reaching it.
4. **The LLM had no screen visibility**, so it guessed "github" was a website.

### What was built (works, but slow)
- `actions._CLICK_SCRIPT` / `click_element` rewritten: set `AXManualAccessibility` first, deep walk
  (depth 32), match label on any role, **press the nearest `AXPress`-able ancestor**, `AXScrollToVisible`
  first, exact-match priority. **Verified live: "click github" → Slack jumped to the github channel.**
- `actions.clickable_targets()` — lists on-screen clickable labels (Electron-aware, node-budgeted).
- `executor`: `_SYSTEM` now routes in-app items (channels/chats/people/sidebar) to `CLICK` not a
  website; `_click_fuzzy()` lists clickables + lets the brain pick when the verbatim click misses;
  CLICK branch = fast `click_element` → fuzzy fallback. `axtree.snapshot` sets `AXManualAccessibility`
  so `LOOK`/the dashboard AX page see Electron content.

### Why it's still bad — the LATENCY (the blocker)
System Events / AppleScript AX traversal of deep Electron trees is **fundamentally slow** (~1 read
per node, thousands of nodes). The *success* path is ~5 s; every **miss is brutal and they STACK**.
Real example from `vox.log` — *"click on alec"* (mis-heard "alex"), 21:09:18 → 21:10:09 = **~51 s**:
1. deterministic `click_element("alec")` in the dispatch hot path → full deep traversal, miss (~slow)
2. escalate → executor `environment_context()` + small-brain LLM → `CLICK: alec`
3. CLICK branch `click_element("alec")` again → full traversal, miss again
4. `_click_fuzzy` → `clickable_targets()` enumeration **~19 s** + LLM pick → `NONE`
5. "I couldn't find a 'alec'…"

Extra problems: the **deep traversal runs in the deterministic hot path** (so even ambient "click…"
speech blocks for seconds); **mis-transcriptions** ("alec"/"alex") should fail *fast*, not crawl;
the fuzzy list was only 18 labels and the brain returned `NONE` (matching/coverage also weak).

### Next session — fix the latency (don't add more features first)
- **The real fix: replace AppleScript AX with `pyobjc` `AXUIElement`** — direct AX API is ~100× faster
  and supports targeted attribute search; turns ~19 s into ~instant. **It's a dependency** (the user
  is cautious about deps + disk) — discuss first. This is almost certainly the right call.
- **Stop the stacking:** if the deterministic click misses, don't re-traverse in the executor *and*
  enumerate. Read the screen **once**, decide once.
- **Don't deep-traverse in the hot path** — keep the dispatch-level click cheap/fail-fast; do the
  expensive Electron walk only in the (already-slow) executor path.
- **Cache `AXManualAccessibility`** per app + drop the 0.6 s settle when already enabled.
- **Fail fast on a clear miss** so a mis-said target returns in ~1 s, not ~50 s.
- Then: broaden fuzzy coverage (>18 labels) and re-test breadth (Discord/Cursor/Notion/native).

## External code-review triage (2026-06-19)

An open-source scanner (free model) flagged ~20 items; each was **verified against the source** before acting. Verdicts:

**Real bugs — FIXED:**
| Ref | Bug | Fix |
|---|---|---|
| C1 | Dashboard's generated MCP config used `-m vox.mcp.speak` (no such module) — the server is `mcp/vox_speak_server.py` | `server._mcp_config()` now emits `mcp/vox_speak_server.py` (matches `mcp/README.md`) |
| C2 | Kokoro streaming TTS: end-of-stream sentinel sent with `put_nowait` → dropped on a full queue → `play()` hangs to the backstop on long replies | `_synth_worker` now uses a blocking `put(None, timeout=5)` so the sentinel is never dropped |
| C10 | **Daemon wedges silently after a reply, with no audio** (2026-07-28, seen on a `LOOK` answer): `_StreamingPlayer.play()` drove the sounddevice stream with `with sd.OutputStream(...)`, whose `__exit__` calls `stop()` → `Pa_StopStream`, which **waits for the buffers to drain** and deadlocks on an audio-device change. It sat *outside* the 60 s in-loop backstop, so the loop froze past every bound, printed nothing after the `🔊` line, and the process needed a kill (a graceful restart couldn't run). Same CoreAudio trap `MicStream` already documents on the input side (`audio.py:139`). | Explicit `stream.start()` + teardown via `abort()` (Pa_AbortStream — immediate, no drain), with `close()` on a daemon thread so a stuck close can't reach the voice loop. **Mitigation without the fix:** turn *Interruptible speaking* off — `speak()` then takes the robust synth→`afplay` path (own process, `timeout=60`). |
| C9 | **Regression from the new single-instance guard:** on restart the new process could see the exiting old process's port still held and refuse to start | Restart spawns with `VOX_RESTART=1`; `main()` skips the guard once for that launch |

**False positives (verified NOT bugs):**
- *RSS "undercount"* (`stats.py`): `rss/1e6` is decimal **MB** — a valid convention, not an error (MiB would be `/1048576`).
- *Log lines "lost" on exit* (`io/console.py`): the file is opened `buffering=1` (line-buffered) → every line flushes immediately.
- *AX-tree parser IndexError on a depth jump* (`web/axtree.py`): the `depth <= len(stack)` guards prevent it — verified with a 0→2 jump, no error.
- *Hardcoded US key codes* (`actions.py`): macOS `key code 51/36/48/126` are **physical-key** codes (layout-independent); `keystroke "z"` is character-based (layout-correct).

**Latent / minor (valid, not urgent — not fixed):**
- `asyncio.run()` in `_claude_sdk`/`_claude_cli` would crash if ever called from a thread with a running loop; today only the daemon thread calls it (no loop). Harden if the dashboard ever calls the brain.
- `data/` path via `parents[N]` is brittle to restructuring (works now). Pairs with a future `VOX_DATA_DIR` env (see ideas: configurable data dir).
- VPIO `device` param is accepted but unused (system default mic) — **documented** in the code, intentional for interface parity.
- Kokoro model download (`tts.py`): no progress/timeout; `.part` is overwritten on retry (not accumulated). UX nicety.

**Dashboard a11y/UX (valid quality improvements, batched for one `dist` rebuild):** `aria-live`/`role="log"` on toasts + Conversation feed; CommandPalette focus/`combobox` semantics + true subsequence fuzzy match; conversation auto-scroll-only-when-at-bottom; WS heartbeat; localStorage read guarded for private-browsing; Scheduler poll only when jobs exist.

**Features flagged** (F1–F10) are already on our roadmap/ideas (per-app commands #36, modality M3, AEC #21, configurable data dir, memory export, wake-word training UI…) — tracked, not bugs.

## Resolved

| Date | Issue | Cause | Fix |
|------|-------|-------|-----|
| 2026-06-18 | In assistant (chat) mode, a genuine command ("next tab", "open X") was sent to the brain as chat instead of running — you stayed stuck talking to the LLM | Assistant mode had no deterministic command watcher (only mode-switch checks ran before everything went to `respond_turn`) | Added a command watcher to `_assistant_mode`: a cleanly-parsed, successful `actions.parse`/`handle` command now runs as an **action** (quiet "did it" cue, stays in chat) instead of going to the LLM; conversational text doesn't parse so it still reaches the brain exactly as before. Complements the mid-call barge-in below. |
| 2026-06-17 | Couldn't cut off a wrong LLM handoff with a new command (had to wait for the response) | Barge-in only listened for *stop* phrases mid-call | Mid-call, a clear command / mode-switch now cancels the LLM and runs instead (control + assistant); chatter/fuzzy speech is still ignored so a video doesn't thrash it |
| 2026-06-17 | Single words / fillers ("and", "uh") from background audio triggered the LLM | No length/noise gate before escalation | Ignore 1-word and all-filler utterances in control mode (unless answering a clarification) |
| 2026-06-17 | SDK "Reached maximum number of turns" (chat & vision) | `max_turns` cap too tight (1 / 4) | Raised to 6 (chat) / 8 (vision) — ceilings, bounded by the 45s/90s timeouts |
| 2026-06-17 | Vox "stops listening", goes dead-quiet, restart-by-voice ignored | Loop hung on a call with no timeout, or the mic stream silently died | Self-healing mic stream (restart on 3s stall) + timeouts on every blocking call (SDK 45s, vision 90s, AppleScript 20s, TTS 30s) |
| 2026-06-17 | Restart-by-voice not working | Mis-transcribed ("vox restart", "restart fox") — no matching variant | Added phonetic/word-order variants to `restart_phrases` |
| 2026-06-17 | Poor recognition of the user's accent on short commands | `base.en` Whisper model too weak | Upgraded to `small.en` (pre-cached to avoid restart-interrupted downloads) |
| 2026-06-17 | Mic feedback loop — Vox heard & re-processed its own TTS | Mic queue kept filling during the blocking `say`; backlog processed as "speech" | `mic.flush()` after every spoken reply |
| 2026-06-17 | Chatter filter ignored *real* questions | `IGNORE` instruction too aggressive | Made it conservative — a question is never chatter; when unsure, don't ignore |
| 2026-06-17 | "Write me X" asked *where* to write | Brain didn't know `TYPE` inserts at the cursor | Prompt: TYPE always inserts at the cursor, never ask |
| 2026-06-17 | Screen-vision descriptions vague/wrong (saw "Finder", not the real app) | Downscaled too hard (1024px) + ran on the small brain | 1568px + big brain (Opus) for `look` |
| 2026-06-17 | "go to sleep" not recognised ("go ahead and sleep") | Missing phrase variant | Added variants to `sleep_phrases` |
| 2026-06-17 | Idle one-shot fired on ambient noise ("CursorArc…") | Hotword list began with "vox", so noise regurgitated it and tripped the one-shot | Removed "vox" from `command_hotwords` |
| 2026-06-17 | Greedy "switch X" matched whole sentences (no escalation) | `app_cycle` regex captured to end-of-line | Tightened to 1–2 app-like words + filler reject; also escalate to the brain when a deterministic command *fails* |
| 2026-06-17 | Model download appeared to "stop the system" | Repeated restarts interrupted the `small.en` download before it finished | Pre-downloaded/cached it once in the background |
| (pre) | openWakeWord scored 0.000 on all audio | `onnxruntime` ≥ 1.21 silently zeros the feature models | Pinned `onnxruntime>=1.17,<1.21` |
| (pre) | Tab reuse jumped to another Arc profile | `tabs of front window` spans profiles | Reuse only tabs in the current space |
| (pre) | Hallucinated commands on silence/noise | No VAD + hotwords biasing toward the command list | `vad_filter=True` + trimmed hotwords to proper nouns only |
| (pre) | Dictation dropped spaces ("justwanttotest") | `keystroke` injects too fast | Switched to clipboard paste |
