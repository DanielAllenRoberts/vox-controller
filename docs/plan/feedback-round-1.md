# Feedback round 1: the user's first hands-on test of Vox.app (2026-11-06)

Every note from the first real test, as written down at the time, with status. Nothing here gets
dropped; items move to ☑ only once built AND checked in the running app.

Legend: ☐ todo · ◐ in progress · ☑ done · 💬 needs a decision from the user

## Bugs
- ◐ **Reminders page didn't show a reminder Vox had set** (it fired on time). Cause: the page loaded
  once and never refreshed; one-off reminders are deleted after firing. Fix: pages reload on appear,
  on app activation and on ⌘R (review finding #9, in progress).
- ☑ **~1.5 s between "hey vox" and the ready sound.** (fast wake built and on: `fast_wake`; caught
  80/108 wake recordings at ~5 ms with 0/195 false wakes; Whisper remains the fallback.) Measured: 0.5 s end-of-speech wait + ~0.6 s idle
  Whisper pass. Plan: a whole-utterance Vosk check of the wake phrases first (3 ms), so a confident
  match wakes instantly; Whisper stays the fallback. Measure on the Voice Lab recordings.
- ☑ **Personality page: picking a character resizes the top card and shoves the grid down.** The card
  is now one fixed shape (one-line tagline, three-line description, voice row always there); "Show More"
  opens a popover instead of growing it.
- ☑ **Command switches show grey when ON.** The system switch goes grey whenever its window isn't in
  front. Vox now draws its own switch, green when on, used everywhere (Settings and menu bar too).
- ☑ **Memory saved odd long-term facts** (e.g. how to refresh a page). Cause: the chat prompt listed
  "standing instructions" as core. Now, following Mem0's tested extraction rules (personal details,
  people, preferences, work, plans, health; never system/assistant text) core is only facts ABOUT THE
  PERSON; how-to notes are demoted to the daily log by a code gate too; "remember to X" is a task (daily),
  "remember that X" is stored self-contained ("The user said: …"); near-duplicate core facts are skipped.
  The two existing "refresh" entries in core were left for the user to delete on the Memory page.
  Next (ideas #28): Mem0-style UPDATE/DELETE when a new fact contradicts an old one, and nightly
  consolidation of daily notes.
- ☑ **"Refresh the page" should be able to press ⌘R.** The router now lists `press <keys>` with the
  standard shortcuts (save, undo, reopen tab, print), and a new `MENU: <item>` directive reads the front
  app's menu bar over AX (every command + its shortcut, ~0.1-0.2 s, no focus change) and chooses the
  matching item, so app-specific commands work without knowing the shortcut. Strict matching ("show
  sidebar" never picks "Show All"). "refresh" still maps to the reload command (Zen has no Reload menu).

## Design
- 💬 **Not different enough from the old dashboard; Home isn't pretty.** "Recent" card is misshaped
  next to the others. Home should be a simple overview / starting place. Pick a visual style first.
- 💬 **Conversation looks like Apple Messages, grey.** Wants Vox's own spark and colour, and to SEE
  actions in the chat (what got clicked, opened, typed).

## Features
- ☑ **Testing tracker in Insights:** every feature with a status (untested / works / broken) and a
  comment box the user can fill in, replacing the to-test.md checklist.
- ☑ **Commands page reorganised:** opens on a grid of apps with counts; click in for details; the
  "Open GitHub / Open Gmail…" commands collapse into one row. **Blocked** list below the grid: Vox won't open
  or switch to those apps/sites, whoever asks (setting `blocked_apps`, enforced in actions).
- ☑ **Prompts in the database + a Prompts editor:** every prompt Vox sends, viewable and editable by
  the user (and by me on request), never by Vox itself. Show what was actually sent per prompt type.
- ☑ **Web search for the brain:** answer questions and find app tutorials from the web (Clicky's power).
- ☑ **Onboarding: choose a voice** (list, preview button speaking preset text, no AI call).
- ☑ **Onboarding: get to know you:** look at installed apps, infer interests, ask a few personalised
  questions, save the answers to memory.

## Round 1b (later notes, same session)
- ☑ **Clicking/pointing inside Vox.app failed** ("click on memory", "point at personality"). Cause:
  sidebar rows' text sits in AXValue and rows have no AXPress, so the click engine couldn't see them.
  Fixed in `ax.py` (also fixes Finder/Mail/Notes/System Settings sidebars).
- ☑ **"can you circle something on the screen" searched for an element named "something on the
  screen"**, then a second greedy pattern read it as an app. Vague targets now go to the brain;
  the app-window pattern is anchored; pointing falls back to looking at the screen.
- ☑ **Browser switched Arc → Zen; "show tabs" opened Arc.** Browser commands now follow the browser
  in front / the Mac's default browser, with per-browser tab control (Zen: ⌥⌘S, ⌃Tab, ⌘1–9, `%` tab search).
- ☑ **"Log this issue" by voice** → `data/issues.jsonl` with context, shown in Testing → Logged issues.
  I check it on every pass (`GET /api/issues`).
- ☐ **Agent task board + background agents** (like Paperclip, Hermes, OpenClaw): a board of agent
  tasks that agents pick up and run in the background, on schedules (cron), straight into Claude Code
  or others. Open an agent's chat from the app. Its own section in Settings. Reuse what exists
  (Claude Agent SDK, Hermes/OpenClaw patterns, Paperclip's delegation) rather than reinvent.
  Research Paperclip first (the user has it starred).
- ◐ **"show clickable" in the Claude app on an artifact table:** many badges read the same number
  (23), and "click 23" hit New chat instead. Hypothesis: elements inside the artifact's embedded web
  frame report coordinates relative to that frame, not the screen, so badges pile up near the
  window's top-left and clicks land there. Waiting for the user to say "ready" with the artifact
  open, then inspect the Claude app's AX frames read-only (pinned pid, no focus change).
- ☐ **Composio** isn't integrated in Vox yet (only planned in ideas #70 step 3: Vox's own Composio
  account as the agent's app layer). Belongs to the agent-system work; add to the test list once built.
- ☑ **ChatGPT / OpenAI as a brain option** alongside Claude and DeepSeek: provider `chatgpt` (OpenAI API,
  `OPENAI_API_KEY`, `max_completion_tokens` with room for reasoning). Model menu read live from OpenAI's
  model list for the key (no guessed model names). Keys can now be added in Settings → Brains. Not yet
  live-tested: no OpenAI key is set (the .env entry is empty). Vision ("look at the screen") still needs Claude.
- ☑ **Expand the task board**: see the Trello-style board entry (deadlines, multi-select, tags, checklists, archive).

## Round 1c
- ☑ **Change settings by voice** (allow-listed: speak replies, voice, learning, auto-typing, thinking,
  screen questions, agent alerts, bubble corner, fast wake). Brains/keys/permissions refused.
- ☑ **Command learning saved nonsense.** New phrase-quality gate: stutters collapse; phrasings the
  parser already understands, >6-word sentences and corrections are never learned; aliases and
  odd leaps need a second sighting. Existing junk candidates: see below.
- ☑ **"What time is it?" → "I don't have a live clock".** The chat brain had no clock (only the command
  brain did). Fixed and verified with a real call.
- ☑ **"Hey vox what time is it" lost the question.** Words after the wake phrase now become the first
  thing assistant mode answers.
- ☑ **Setup: voice picker + get to know you** built (voice previews speak a preset line; questions come from
  the installed apps' names via the small brain, answers saved as long-term memories).

## Round 1d
- ☑ **Media in the background:** "pause Spotify", "next song", "pause the music" control Spotify / Music
  without bringing them forward (AppleScript), with the system media key for anything else. Direct
  command, no brain.
- ☑ **App-scoped notes (the user's idea):** rules/preferences tied to an app, added to the prompt only when
  that app is in front ("in Zen, 'refresh' means press ⌘R"), the same way the command DB loads
  per-app commands. Keeps the main prompt lean. Saved by voice ("from now on in Zen, when I say
  refresh press command R") or on the Rules page.

- ☑ **A proper Trello-style board** (2026-11-06): ⌘-click multi-select with a Move/Archive/Delete bar
  and `POST /api/board/bulk`; paste a list to add one card per line; coloured tags; due dates that set a
  linked reminder (moved/cleared with the card) and show overdue/soon; checklists; archive + restore;
  search; "1 overdue · 3 due this week". Voice and MCP verbs: due, tag, archive, checklist; Vox sees
  deadlines/tags in its board view and today's date, so "what's due this week?" works. Not yet: card
  colours/covers, comments, drag-select.

## Round 1e
- ☑ **Hold-to-talk cut off after ~15 s** (with a click), splitting the sentence. The key now decides; 5-min safety net only.
- ☑ **Logged issues weren't arriving:** Whisper heard "log an issue" as "login issue". Phrase variants accepted,
  plus an ISSUE: directive so any wording works. The lost issue (close Notion / Notion Calendar) recovered and filed.
- ☑ **"close Notion" closed a browser tab:** new quit-app command. **"open Notion Calendar" opened Notion:** a more
  specific installed app now beats a saved command that merely contains a shorter name.
- ☑ **Testing page notes need an obvious Save:** Save button + "Saved" confirmation.
- 💬 **"Are you using the Apple UI skill?"** No such skill is available here; designing from Apple's HIG directly.

- ☑ **Froze after "what's the weather in Cape Town"** (18:34). Native stack sample: the voice loop's main
  thread parked in an unbounded `done.wait()` after an interrupted reply, while speech playback was wedged
  (AirPods mic/output were stalling minutes earlier). Wait is now bounded; `kill -USR1 <pid>` dumps Python
  stacks to the console log for any future hang. Restarted the engine to unfreeze.
- ☑ **Typing cut Vox off mid-reply.** Interruptions now need real voiced speech (Silero: typing 0 ms, short words
  >= 256 ms; threshold 160 ms) and ignore Whisper's noise phrases ("you", "thank you"). Also found: the interrupt
  thresholds were stored as text ("0.6"), so every interruption check raised a TypeError mid-reply, the likely
  trigger for the freeze. Coerced. Stop words ("stop", "wait") bypass the word minimum.
- ☑ **Web search** made urgent by the same request: Vox said it has no live weather access. (Already on the list.)

## Round 1f (issues logged by voice)
- ☑ **Vox heard its own reply as the user** (on speakers): it remembers what it just said and drops a
  transcript that is mostly its own words (4+ words, 80% overlap, while speaking or up to 4 s after). Applies to
  replies, barge-in and the idle wake listener.
- ☑ **Switching to headphones didn't move Vox's voice:** replies now play one sentence at a time through
  `afplay`, which uses whatever output is current. Also removes the PortAudio stream that could wedge.
- ☑ **"Log an issue" with nothing useful** (a lone "i") was saved: issues now need 3+ words.
- ☑ **Setup's questions were music-heavy and didn't say why** they asked: each now names the app ("I saw you
  have Figma: …"), any field.
- ☑ **Setup should be the only window:** the main window hides while Setup runs (first launch and Run Setup
  Again) and comes back at the end. From the menu bar, Open Vox still works if Setup is closed early.
- ☑ **Answer Setup's questions by voice:** a mic button per question records the answer (Vox stops listening
  meanwhile) and transcribes it into the field.
- ⏳ **Vox lowers the volume when it talks** (620b806d): not Vox (no software volume on that output); likely
  AirPods' Conversation Awareness. Waiting to hear which headphones.

## Liked (keep)
- Hold Right ⌥ to talk: fast, will use it constantly.
- Sidebar status (which brain, paused).
- Personality page's changing text and character tiles.
- Vocabulary page as it is.
