# Next up — actionable to-dos

> Working list for discussion, not a commitment. Newest block first. Carried-over items at the
> bottom so nothing from the last few sessions gets lost.

---

## 1. Verify the board actually works

**Status:** built 2026-08-04, **never run live** — `grep -c "decision=BOARD" vox.log` → **0**.
Same for TEACH (`decision=TEACH` → 0). Both were verified against a copy of the DB, never by voice.

Needs a daemon restart first; everything since 2026-08-03 is still unloaded.

**Test script — say these, in order:**

| Say | Expect | Proves |
|---|---|---|
| "what's on my board" | spoken summary of To Do / Doing / Issues | `board_block` reaches the prompt; answer comes back as `CHAT:` |
| "add a card to doing called test the board" | "Added 'test the board' to Doing." | `add_card` |
| "move the test card to done" | "Moved 'test the board' to Done." | fuzzy `find_card` + `move_card` |
| "put a note on the test card that it worked" | "Added a note to 'test the board'." | `note` (append, doesn't overwrite the body) |
| "rename the test card to board verified" | "Renamed it to 'board verified'." | `update_card` |
| "delete the board verified card" | "Deleted 'board verified'." | `delete_card` |
| "make a list called blocked" | "Added a 'blocked' list." | `add_list` |
| "make a board for getprice" | "Created the 'Getprice' board." | `create_board` — the one that didn't exist at all before |
| "move the zzz card to done" | "I couldn't find a card called 'zzz'." | failure path degrades, doesn't crash |

**What to watch in `vox.log`:** `decision=BOARD <verb> | <args> → <result>`. If a board request instead
shows `decision=COMMAND` or a bare chat reply, the model didn't emit the directive — that's a prompt
problem, not a store problem, and the fix is in the v2 draft.

**Known gap:** the dashboard Board page can't create a board or rename/delete a list — those store
functions exist but aren't exposed over HTTP. Voice can do things the UI can't.

---

## 2. Google Calendar — read + write

**Goal:** "what's on today?", "am I free at 3?", "put a meeting with Alex at 4 tomorrow", and the
calendar visible in the dashboard.

**The routing question comes first, because it decides the cost.**

Evidence gathered 2026-08-07:
- Calendar.app lists: `Home, Work, Scheduled Reminders, Birthdays, South African Holidays, Siri
  Suggestions` — that reads like a pure iCloud set.
- `~/Library/Calendars/` is **empty** (no CalDAV bundles).
- → **Google Calendar is probably NOT synced into Apple Calendar.** Not certain; needs one look.

| Option | Cost | Gets us |
|---|---|---|
| **A. Google Calendar API** | OAuth flow, token storage, `google-api-python-client` (~15 MB, and the machine is disk-tight) | Everything, incl. attendees/invites, reliable |
| **B. Apple Calendar (EventKit / AppleScript)** | No auth, no dependency, works today | Only the calendars macOS already has — i.e. **not** Google, on current evidence |
| **C. CalDAV direct** | `caldav` lib + an app password | Google without the full OAuth dance; thinner than A |

**Recommendation:** answer one question first — *do you see your Google calendar inside Calendar.app?*
If yes, **B** is dramatically cheaper and we should take it. If no, **A**, and accept the OAuth work.

**Design notes regardless of route:**
- **Read and write are not equal risk.** Reading is inert. Creating an event with attendees *sends
  invitations to other people* — outward-facing and hard to retract. Writes with attendees should
  confirm out loud before firing; writes to your own calendar probably shouldn't.
- Follows the `BOARD:` pattern: a `CAL:` directive (`add | move | delete`) plus a compact
  agenda block in the prompt so "what's on today" is answered without a round-trip. **Careful:** the
  agenda block has the same context-bloat problem as the board — see the prompts budget. Attach it
  need-based, not always.
- Dashboard page for the calendar view is separate work; the voice path is the valuable half.

**Open questions:** which account(s) to include · does Vox ever need to *accept/decline* invites, or
is create/move/delete enough · read-only first as a slice?

---

## 3. AI-initiated check-ins — Vox starts the conversation, on a schedule

**The idea (user's example):** once a week a cron fires, Vox *asks* "what did you train at gym this
week?", the user answers, and Vox **writes the answer down**. Not a reminder — a reminder just
speaks at you. This opens a conversation and keeps what comes back.

That makes it three parts: **fire on a schedule → ask → capture the reply.**

### What already exists

| Part | Status |
|---|---|
| Recurring schedule, catch-up after sleep, dashboard page | ✅ `scheduler.py` |
| Speaking at the user when a job fires | ✅ `scheduler._announce` |
| Holding context so a reply is understood as an answer | ✅ `loop.pending` — "when the brain asks a question, the next answer gets context" |
| Writing something down | ✅ `memory.add(text, tier, tags)`, and the chat brain already emits `MEMORY[daily]: …` |

So most of it is composable. The genuinely new work is small but fiddly:

### What's missing

1. **A job kind that carries a question, not a reminder.** `VALID_KINDS = ("timer","alarm","reminder")`
   → add one that stores *the question to ask* plus *where the answer goes*.
2. **Arming the loop to expect an answer.** This is the hard part. `_tick()` fires on a background
   thread; `pending` belongs to the voice loop. The scheduler needs to hand off "I just asked
   something — route the next utterance to the brain as an answer to *this*."
3. **Getting Vox listening at all.** If Vox is **idle**, it only listens for wake phrases — so the
   user answers into a void. An AI-initiated question has to put Vox into a listening state for a
   window, then stand back down. Without this the whole feature silently does nothing.
4. **A no-answer path.** If nobody replies (out of the room, headphones off), it needs to time out
   and either drop it or re-ask later — not sit armed indefinitely.

### Decisions needed

- **When is it allowed to interrupt?** Speaking unprompted is the whole point, but firing "what did
  you train?" mid-meeting is bad. Options: only when idle and nothing has been heard for N minutes ·
  defer if speech was detected recently · a quiet-hours window. **I'd start with "only when idle and
  quiet for 2+ minutes, defer up to an hour, then skip."**
- **Where does the answer go?** `memory` daily (exists, Markdown, searchable) is the cheapest and
  probably right for v1. A board card is more visible but clutters the kanban. A dedicated
  journal/notepad store is the "proper" answer and the most work — worth it only if you want to
  *query* it later ("what did I train last week?").
- **Who writes the summary — the brain or a template?** Letting the chat brain emit
  `MEMORY[daily]: trained legs and shoulders` reuses machinery that works, but it decides the
  wording. A structured capture (`{date, question, answer}`) is queryable but rigid.
- **Does the check-in adapt?** "Ask about gym" is fixed. "Ask me about whatever you noticed I've been
  working on" is a different, much more open feature. Start fixed.

### Why this is worth doing carefully

It's the first time Vox speaks **without being spoken to**. Everything until now has been
request-response, so every rough edge has been in front of the user by definition. A background
system that talks unprompted, mishears the answer, and then *writes the mishearing down* has a much
longer failure tail — especially given we already watched the learner cement `"hot tabs"` from one
wrong resolution. Whatever gets captured should be reviewable and easy to correct.

---

## 3b. (Not asked for, noted only) — scheduled tasks that run commands

Distinct from the above: a job that *performs an action* rather than asking a question ("every
morning open my dashboard"). Same missing piece — `_announce(job)` at `scheduler.py:660` is all any
kind does today. Parked unless you want it; the check-in above is the ask.

## Carried over

**From the click/web work**
- **Site-scope browser clicks** — a card learned on Gmail applies to all of Arc, because for a
  browser every site *is* "Arc". `context.kind` already allows `'site'` and the learner has never
  used it. This is the fix for the Gmail reload-button class of bug. *(highest value of the carried
  items)*
- **Duplicate labels (issues.md O12)** — "click rescrape" silently clicks the first match. Fix:
  badge only the matches, plus row-context labels from the DOM.
- **Tier-2 vision: label sanity check** — vision picked badge 11 ("Got it") for a request to click
  "Later" and clicked it anyway. We know the label we clicked; a mismatch on a plain-label request
  should reject or confirm. Range-guard and last-number parsing are done; this isn't.
- **Parser greediness** — `"the next tab in the spreadsheet is broken"` → `tab_arrow down:1`, and it
  fires *before* the noise gate. Argument-taking commands self-validate; the no-argument ones
  (`tab_arrow`, `desktop_move`, `close_tab`, `back`, `reload`, `sidebar`) don't.

**From the learning work**
- **#56 correction loop** — recent-actions memory is done; the correction verbs are not. Now
  load-bearing: at `min_hits=1` a wrong resolution is cemented on the first try, and we've already
  seen it happen ("hot tabs" learned as an alias for *Show tabs*).
- **Dashboard command editing** — voice can now change a taught command (`TEACH:` retargets);
  the UI still can't edit intent/arg.
- **Vosk should snap the mis-hears** — "hot tabs" and "hi clickable" both returned `[unk]` despite
  the phrase being in the grammar. Fixing the recognizer stops these reaching the LLM at all.

**From the prompt work**
- **v2 prompt: decide + test** — draft is at `docs/prompt-v2-draft.md`, 29% smaller, 10/10 tools and
  16/16 commands covered. Open: is `reload` right to expose, per-tool examples or not. **Before
  swapping it in**, build a replay harness over real `vox.log` utterances (the board question,
  "click on github", "hot tabs", "whenever I say refresh") and run both prompts against the live
  small brain. Shorter is not automatically better on a small model.
- **Need-based context** — `board_block` is ~1340 tokens at its 40-card cap and the open-tabs list is
  ~317; both go on *every* action-layer call. Now folded into **ideas #58** (let the brain *query*
  instead of being force-fed), which covers the same ground for commands, board, tabs and calendar
  with one mechanism.

**Also open**
- Chat brain claims actions it can't perform ("I've saved that as a standing rule" — it hadn't).
- Board over MCP (#49) so Claude Code can read/write it.
- Board drag-and-drop; HTTP endpoints for `create_board` / `rename_list` / `delete_list`.
