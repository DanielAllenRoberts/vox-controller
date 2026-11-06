# Feedback round 1: the user's first hands-on test of Vox.app (2026-11-06)

Every note from the first real test, as written down at the time, with status. Nothing here gets
dropped; items move to ☑ only once built AND checked in the running app.

Legend: ☐ todo · ◐ in progress · ☑ done · 💬 needs a decision from the user

## Bugs
- ◐ **Reminders page didn't show a reminder Vox had set** (it fired on time). Cause: the page loaded
  once and never refreshed; one-off reminders are deleted after firing. Fix: pages reload on appear,
  on app activation and on ⌘R (review finding #9, in progress).
- ☐ **~1.5 s between "hey vox" and the ready sound.** Measured: 0.5 s end-of-speech wait + ~0.6 s idle
  Whisper pass. Plan: a whole-utterance Vosk check of the wake phrases first (3 ms), so a confident
  match wakes instantly; Whisper stays the fallback. Measure on the Voice Lab recordings.
- ☐ **Personality page: picking a character resizes the top card and shoves the grid down.** Needs
  a layout that doesn't move (fixed-height detail, or side-by-side).
- ☐ **Command switches show grey when ON.** They should be green.
- ☐ **Memory saved odd long-term facts** (e.g. how to refresh a page). Research how good memory
  systems decide what's long-term vs daily (MemPalace, ideas #28/#55) and tighten what gets promoted.
- ☐ **"Refresh the page" should be able to press ⌘R.** Vox has `press` (ideas #61); make sure the brain
  knows it can send keyboard shortcuts, and can look up an app's shortcuts when it doesn't know one.

## Design
- 💬 **Not different enough from the old dashboard; Home isn't pretty.** "Recent" card is misshaped
  next to the others. Home should be a simple overview / starting place. Pick a visual style first.
- 💬 **Conversation looks like Apple Messages, grey.** Wants Vox's own spark and colour, and to SEE
  actions in the chat (what got clicked, opened, typed).

## Features
- ☐ **Testing tracker in Insights:** every feature with a status (untested / works / broken) and a
  comment box the user can fill in, replacing the to-test.md checklist.
- ☐ **Commands page reorganised:** start with a grid of apps that have commands (with counts), click
  in for details. Collapse the long "Open GitHub / Open Gmail…" list. Add **blocking an app** so Vox
  can't open it, instead of listing every site it can open. Less scrolling.
- ☐ **Prompts in the database + a Prompts editor:** every prompt Vox sends, viewable and editable by
  the user (and by me on request), never by Vox itself. Show what was actually sent per prompt type.
- ☐ **Web search for the brain:** answer questions and find app tutorials from the web (Clicky's power).
- ☐ **Onboarding: choose a voice** (list, preview button speaking preset text, no AI call).
- ☐ **Onboarding: get to know you:** look at installed apps, infer interests, ask a few personalised
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
- ☐ **ChatGPT / OpenAI as a brain option** alongside Claude and DeepSeek.
- ☐ **Expand the task board** (more than lists + cards; scope to discuss).

## Liked (keep)
- Hold Right ⌥ to talk: fast, will use it constantly.
- Sidebar status (which brain, paused).
- Personality page's changing text and character tiles.
- Vocabulary page as it is.
