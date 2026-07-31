# Build log — session 2026-06-19

Integration + verification of the four slices from `session-2026-06-19.md`. Nothing
is committed (public repo) — all changes sit in the working tree for review.

## Verification summary

- **Backend imports — PASS.**
  `uv run python -c "import vox.core.loop, vox.scheduler, vox.web.server, vox.web.conversation, vox.actions"` and
  `uv run python -c "from vox.web import axtree"` both exit 0. Full smoke (incl.
  `vox.executor`) imports cleanly.
- **Dashboard build — PASS.** `npm run build` (`tsc -b && vite build`) succeeds;
  `dashboard/dist/` regenerated (`index-*.js` rebuilt, contains both `Conversation`
  and `Scheduler`). Clean `tsc -b --force` typecheck: no errors.
- **Nav/routes — consistent.** `nav.ts` adds `/conversation` and `/scheduler`;
  `App.tsx` registers both routes pointing at the new pages. Resolve fine.
- **Store gitignored.** `data/reminders.json` is covered by `.gitignore` (runtime
  data never enters the public repo).
- **No new wiring fixes were required** — the four slices integrated cleanly (no
  duplicate routes, missing imports, or nav/route mismatch). Integration was
  verify-only.

---

## Slice: Foundation (env/time context + AX-tree text helper plumbing)

- **What:** focused-app / active-tab / current-time context enrichment in
  `actions.py` (`environment_context`), a `screen_vision_mode` config
  (`auto`|`axtree`|`screenshot`), and the per-kind scheduler sounds.
- **Files changed:** `src/vox/actions.py`, `src/vox/config.py`.
- **Verify:** imports clean; config fields present (`screen_vision_mode`,
  `scheduler_*`, `apple_reminders_mirror`, `sound_reminder`, `sound_timer`).

## Slice: Conversation viewer (idea #43)

- **What:** in-RAM, ephemeral conversation feed mirroring `usage.py` (ring buffer +
  thread-safe publish + async subscriber registry). Loop publishes each turn
  (user utterance, brain reply, inline command) via a guarded `_record_turn`.
  Server exposes `GET /api/conversation/recent` + `WS /api/conversation/stream`.
  Dashboard **Conversation** page renders the running session as a chat.
- **Files added:** `src/vox/web/conversation.py`,
  `dashboard/src/pages/Conversation.tsx`,
  `dashboard/src/hooks/useConversationStream.ts`.
- **Files changed:** `src/vox/core/loop.py` (publish turns),
  `src/vox/web/server.py` (routes), `dashboard/src/lib/api.ts` (`Turn` type +
  `conversationRecent` + `conversationStreamUrl`), `App.tsx`, `nav.ts`.
- **Verify:** `vox.web.conversation` imports; WS route binds the queue to the
  running loop for cross-thread publish; page builds into `dist`. Nothing written
  to disk (ephemeral by design).

## Slice: Scheduler — timers / alarms / reminders (idea #16)

- **What:** Vox-owned scheduler core (`scheduler.py`): unified job model, background
  thread (fires per output policy — reminder→spoken+sound, timer→sound,
  alarm→both), `data/reminders.json` persistence with startup catch-up,
  deterministic-first voice parsing (create + cancel + summary), and an optional
  Apple Reminders mirror (default OFF, guarded). Loop routes scheduler phrases
  before the generic parser in both control and assistant modes. Server exposes
  `GET/POST /api/reminders` + `DELETE /api/reminders/{id}`. Dashboard **Scheduler**
  page lists/creates/cancels jobs.
- **Files added:** `src/vox/scheduler.py`, `dashboard/src/pages/Scheduler.tsx`.
- **Files changed:** `src/vox/core/loop.py` (`_start_scheduler`, `_handle_schedule`),
  `src/vox/config.py`, `src/vox/web/server.py` (CRUD + `_job_to_api`),
  `dashboard/src/lib/api.ts` (`Reminder` type + CRUD), `App.tsx`, `nav.ts`.
- **Verify:** the four create phrasings classify correctly (timer / relative
  reminder / absolute reminder / alarm); cancel/query phrases route to
  `cancel_matching`/`summary` (not the create parser). Thread + firing are fully
  guarded. Store is gitignored.

## Slice: AX-tree vision (idea #2b / ideas #18, #36)

- **What:** `axtree.snapshot_text()` flattens the focused app's AX tree to compact
  indented text (capped at `TEXT_MAXLEN`). Executor's "what's on my screen" path
  honours `screen_vision_mode`: `axtree`/`auto` read the tree first via
  `_look_axtree` (token-light, no image); `auto` falls back to a screenshot if the
  tree is empty/unavailable, `axtree` does not. The tree vision call is logged to
  the usage ledger as `kind="vision_axtree"` (distinct from `vision_screenshot`).
- **Files changed:** `src/vox/web/axtree.py` (`snapshot_text` + `_flatten`),
  `src/vox/executor.py` (`_look_axtree`, mode branch).
- **Verify:** `from vox.web import axtree` imports; `kind="vision_axtree"` plumbs
  through `assistant.complete` → `_record_usage` so it appears on the Token Usage
  page. Fully guarded (AX read shells AppleScript → degrades to None / screenshot).

---

## How to test (live)

Restart the daemon so the scheduler thread arms and the new turn-publishing fires:
look for `[scheduler] timers / alarms / reminders armed` in the startup log.

### Scheduler — voice phrases

Say the wake word, then (control or assistant mode both work):

- **Timer (relative, sound-only):** "set a timer for 10 seconds" → confirms, chimes
  ~10 s later. Good first smoke (short + deterministic).
- **Reminder (relative, spoken):** "remind me to stretch in 1 minute" → speaks
  "Reminding you to stretch" (personalised "Hey <name>" if your name is in core
  memory) + soft chime.
- **Reminder (absolute):** "remind me at 10:55 PM to wind down" → confirms for the
  next 10:55 PM.
- **Alarm (both):** "set an alarm for 7 AM" → sound + spoken line at 7 AM.
- **Recurring:** "remind me every day at 9 AM to take a break" (also "every weekday
  at …", "every Monday at …") → rolls forward after firing.
- **Cancel:** "cancel my timer" (cancels all timers), "cancel the wind down
  reminder" (matches words in the text). "what are my reminders" reads back a
  summary.

Persistence: set a timer, `restart`, and a one-shot that came due while off fires
once with a "While you were away — " prefix (within ~1 h; older ones are dropped).

### Dashboard — new pages (rebuild already done)

The bridge at `:8765` serves `dashboard/dist`, which was rebuilt this session, so
the pages are live there now (no dev server needed). Open the dashboard (voice:
"open dashboard", or browse to the bridge) and use the left nav:

- **Conversation** — the live, ephemeral RAM feed of the running session. Start
  talking; user/assistant bubbles appear live (which brain replied, any command
  inline). A page refresh re-seeds from the in-RAM buffer; **nothing new appears
  under `data/`** (ephemeral by design). The status pill shows live / connecting /
  offline and auto-reconnects across a daemon restart.
- **Scheduler** — lists every active job with a live countdown; create one from the
  form and cancel with the delete button. Voice-created jobs show up here live, and
  cancelling here removes them everywhere (Vox owns them).

### AX-tree vision

Flip the vision mode to test the tree as Vox's eyes:

- In **Settings** (or `config.py`) set `screen_vision_mode` to **`axtree`** — this
  forces the AX-tree path with **no screenshot fallback** (the way to actually test
  the tree). `auto` reads the tree first and falls back to a screenshot if it's
  empty; `screenshot` is the old image-only behaviour.
- Ask "what's on my screen?" (or "what does this say?"). In `axtree` mode the answer
  comes from the focused app's AX tree as text — no image sent.
- **Token cost:** open the **Token Usage** page — the call is tagged
  **`vision_axtree`** (vs `vision_screenshot` for the image path), so you can
  compare token counts / effectiveness over real use. The tree text is capped at
  `TEXT_MAXLEN` (6000 chars) to stay token-light.

> Tip: the AX read shells AppleScript and needs Accessibility permission; if the
> tree is empty in `axtree` mode Vox says it couldn't read the accessibility tree
> (in `auto` it silently falls back to a screenshot).

### Optional: Apple Reminders mirror (phone)

`apple_reminders_mirror` is OFF by default. Turn it on to also push **reminders**
(not timers/alarms) into Apple Reminders so they fire on your iPhone via iCloud.
Guarded — a mirror failure never blocks the local job.
