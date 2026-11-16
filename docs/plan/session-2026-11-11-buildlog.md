# Build log — session 2026-11-11

Branch `voice-control-ideas` (off `app-overhaul`). **Nothing is committed** — all changes sit in the
working tree for review. Not yet tested by voice: the session paused because there was no mic.

Two threads: a `/loop` to borrow ideas from Apple Voice Control (idea #72), interrupted by a
"Vox crashed" report that turned out to be three separate problems (issues.md, 2026-11-11 section).

## Verification summary

- **Unit tests — PASS.** `tests/test_click_choices.py` 11/11 · `tests/test_show_names.py` 6/6 ·
  `tests/test_auto_dictation.py` 14/14 (unchanged). Run standalone with `.venv/bin/python <file>`;
  pytest isn't installed.
- **Imports — PASS.** `vox.actions`, `vox.executor`, `vox.targets`, `vox.ax`, `vox.dispatch`,
  `vox.agents`, `vox.team`, `vox.overlay`, `vox.core.loop`, `vox.guide`.
- **Terminal-agent delivery — PASS, live.** Sent a two-line message to a test Claude Code session:
  arrived verbatim, sender `vox`, 5.4 s.
- **Scheduler guard — PASS.** The real pasted text no longer matches; "what timers do I have",
  "cancel my alarm", "clear all timers", "delete the reminder about sam" still do.
- **Vox.app — built + rendered.** `app/build.sh` clean; `Vox --snapshot` of the Conversation page
  with a 4,283-character fixture turn renders collapsed with "Show more". The freeze itself was not
  re-created.
- **Overlays — rendered off-screen** against Finder's and Slack's real AX targets (no window drawn).
- **Engine restart:** the engine the user relaunched at 10:55 has the agent, scheduler and
  ambiguous-click code, but not "show names". Quit and reopen Vox.app before voice testing.

---

## Fix: message a registered terminal agent

- **What:** "tell <agent> …" now reaches a Claude Code session that called `register_agent`.
  Previously `team.message()` refused every such agent ("runs in your terminal, so I can't message
  it yet").
- **How:** `agents.session_for(name)` walks up from the agent's MCP-server pid to its `claude`
  process, then matches that pid in `claude agents --json` to get the session name.
  `agents.send(name, text)` runs `claude -p` (installed CLI, not the SDK's older bundled one) with
  `--allowedTools SendMessage --model haiku --strict-mcp-config --setting-sources "" --name vox`,
  subscription env, cwd `data/`, and checks for `SENT`. Busy sessions read it between tool calls.
- **Why this route:** the messaging socket's wire format is undocumented
  (`research/agent-messaging.md`), channels need a dev flag at launch, tmux needs the user to work
  in tmux. A headless session using the official tool needs none of that.
- **Files:** `src/vox/agents.py`, `src/vox/team.py`, `docs/plan/named-agents.md`.

## Fix: scheduler shortcuts fired on long text

- **What:** a pasted page of work notes got "You have no timers, alarms, or reminders set."
- **Root cause:** `_is_schedule_query` / `_is_schedule_cancel` were substring tests with no length
  limit; the cancel test could have deleted reminders from long text.
- **Fix:** whole-word regexes; query/cancel ≤ 12 words; `parse_and_create` only for ≤ 30 words.
- **Files:** `src/vox/dispatch.py`.

## Fix: Vox.app froze on a long message

- **What:** main thread at 100% CPU, engine fine. `sample` showed `LazySubviewPlacements` looping in
  the Conversation page's bottom-anchored `LazyVStack`.
- **Fix:** `Bubble` collapses turns over 600 characters or 10 lines to 8 lines, with "Show more".
- **Files:** `app/Sources/Vox/Views/Pages/ConversationView.swift`. App rebuilt with `app/build.sh`.

## Voice Control iteration 1: ambiguous clicks number the matches

- **What:** "click Send" with two separate Send buttons numbers just those and says "Which one?
  There are 2 called 'Send' — say a number." Closes most of issue O12.
- **How:** `ask_if_ambiguous` on `actions.click_element`, `ax.click`, `targets.click_label`; only
  voice paths set it (`run_intent("click")`, executor `CLICK:`), not the screen agent or MCP `click`.
  A second match must be exact, on screen, non-overlapping (`ax.overlaps`) and ≥ 4 px each way
  (`ax.tangible` — Slack keeps 1-px clipped sticky headers). `targets.offer_choices` reuses the
  existing overlay + number flow. Side fix: a plain click skips a leading 1-px sliver.
- **Measured:** live read-only survey — ~170 Slack targets → one remaining exact duplicate (two
  "active" status icons); Finder, Cursor, Notion, Obsidian, Spotify → none.
- **Files:** `src/vox/ax.py`, `src/vox/targets.py`, `src/vox/actions.py`, `src/vox/executor.py`,
  `tests/test_click_choices.py`.

## Voice Control iteration 2: "show names"

- **What:** "show names" / "show labels" / "show item names" → badges reading "14 Export" on a dark
  plate (numbers-only stay blue). Numbers still work; "hide names" / "hide labels" dismiss.
- **How:** `overlay.show(items, names=True)`; labels one line ≤ 28 chars (`_short`); an overlapping
  name badge steps down a row, up to three (`_nudge`). Phrases added to the Vosk fast lane and the
  in-app Guide.
- **Files:** `src/vox/overlay.py`, `src/vox/dispatch.py`, `src/vox/core/loop.py`,
  `src/vox/guide.py`, `tests/test_show_names.py`.

## Command-learning trial

Observations logged in `observations.md` (2026-11-11): a mis-hear learned twice ("open cloud"), a
one-word fragment one sighting from learning ("win"), rambling sentences as aliases. Suggested knob:
`learning_min_hits` 1 → 2, or refuse single-word phrases.

## Where the rest is

- Comparison + ranked next ideas: [`apple-voice-control-comparison.md`](apple-voice-control-comparison.md), idea #72.
- Hand checklist: top of [`to-test.md`](to-test.md).
- Problems: [`issues.md`](issues.md) — 2026-11-11 section, O12.
