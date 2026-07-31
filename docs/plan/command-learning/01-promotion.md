# 01 — What counts as a command?

> The question this answers: *"How do we know whether something is a one-off, or a real command worth
> keeping forever?"*

## The principle

**A command is a habit, not an event.**

Doing something once tells you nothing. An assistant spends most of its life on requests that will
never recur — "what's this article about", "write me a reply to Sam", "open the invoice I just
downloaded". If every successful LLM resolution became a command, a week of normal use would leave
hundreds of rows, nearly all of them dead weight that make recognition *worse* (see
[04-resolution-and-safety.md](04-resolution-and-safety.md)).

So the write path is split in two, and the split is the whole point:

| Stage | Cost | Written on | Affects behaviour? |
|---|---|---|---|
| **Observation** (`command_log`) | ~1 row per utterance | *every* resolution | No |
| **Candidate** (`command_candidate`) | 1 row per distinct action | first LLM resolution of that action | No |
| **Learned** (`command`, `source='learned'`) | 1 row + aliases | passing the promotion bar | **Yes** |

Observation is free and total. Promotion is rare and earned. You can run the first two forever and
never change a single behaviour — which is exactly what Phase 1 does.

## The promotion bar

A candidate is promoted only when **all** of these hold:

### 1. Repetition — ≥ 3 clean resolutions inside a rolling window
Defaults `learning_min_hits = 3`, `learning_window_days = 2`. The same `(context, intent, arg)` has
been LLM-resolved three times within any two-day window. A thing said once is an event; a thing said
three times is a habit.

Note this counts *actions*, not phrases. Three different phrasings of the same action count as three
hits toward one command (and contribute three aliases). That's intentional: it means the system learns
*faster* for things you ask in varied ways, which is precisely where the deterministic parser is
weakest and the learning is worth most.

### 2. A rolling window, NOT calendar-day spread
**Decided 2026-07-31 (revised).** An earlier draft required the hits to land on ≥ 2 *distinct days*,
on the theory that a same-day burst is usually you repeating yourself because it didn't work.

That was the wrong instrument. Three uses in one afternoon *is* a real habit, and making you wait
until tomorrow to feel the benefit is exactly the kind of friction that makes a feature seem dead.
The concern it was aimed at — learning your own mistakes — is better handled by the mechanism that
actually detects mistakes: the **negative-signal path** (§3). A correction walks the candidate back,
enough corrections block it outright, and `window_hits` ignores negated rows entirely.

So repetition is counted in a rolling window and same-day promotion is allowed. The safety net moved
from *delaying* the learn to *expiring* it — see **probation** in
[03-budgets-and-decay.md](03-budgets-and-decay.md). Promote eagerly, retire ruthlessly: a wrong learn
costs 14 days and cleans itself up, while a missed learn costs permanent friction.

### 3. Clean success — executed, and not contradicted
Every contributing hit must have `success = 1` **and** no negative signal within the following window
(default 20 s):

| Negative signal | Why it counts |
|---|---|
| "no", "stop", "cancel", "undo", "that's wrong", "not that" | Explicit rejection |
| ⌘Z within the window | Undid what we just did |
| The *same phrase* said again | The first attempt didn't do what was wanted |
| A *different* command issued immediately | Course-correction |
| Mode switch to sleep/abort | Gave up |

A negative signal doesn't just skip the hit — it **decrements** the candidate and records a
`negative` count. A candidate with any negatives at all needs a clean streak to recover, and one that
accumulates 3+ negatives is **blocked** from ever promoting (recorded, so the dashboard can show
"tried to learn this, kept getting it wrong" — useful diagnostic information in its own right).

### 4. Novelty — the deterministic parser missed it every time
If `actions.parse()` already handles it, there is nothing to learn and a learned row would only add a
collision risk. Candidates are only created on the LLM-escalation path.

### 5. A learnable intent (see the never-learn list below)

### 6. A stable argument
The arg must look like a durable identifier, not a payload. Rejected if it:
- exceeds 6 words or 60 characters,
- contains sentence punctuation (`.`, `?`, `!`) or a newline,
- is purely numeric or looks like a date/time,
- differs from the *heard phrase* only by filler (i.e. the "arg" is really just the whole utterance).

**Rationale:** `click_element("Alex Fairbairn")` is an identifier and will recur. `compose("an email
to Alex about the invoice")` is a payload and never will.

## Automatic by default — and when it asks anyway

**Decided 2026-07-31:** `learning_mode` defaults to **`auto`**. Learning should not hand you a queue
of admin to work through; a system that only gets faster once you've done paperwork mostly doesn't get
faster. So a candidate that clears the bar is saved silently, logged, and visible in the dashboard.

Vox asks first in exactly two situations (`command_learn.should_confirm`):

1. **`learning_confirm` is on** — the toggle for "ask me every time", off by default.
2. **The mapping is a leap AND the evidence is thin.** If no word in what you said resembles the
   thing it resolved to, *and* it's only just cleared the minimum hits, it confirms before saving.

The word comparison is deliberately **fuzzy** (`difflib`, ratio ≥ 0.6), because the two cases that
must NOT trigger a prompt are inflections ("alexs" → "Alex") and sound-alikes ("alec" → "Alex",
the exact thing this click path exists to handle). Both read as unrelated under exact matching. The
tradeoff is a rare over-ask — "open get up" → `github` scores below the threshold and would confirm
once — which is the safe direction to fail, and it stops asking as evidence accumulates.

## The explicit override — user intent beats statistics

Saying **"remember that"** / **"save that as a command"** / **"learn that"** right after a successful
action promotes it **immediately**, bypassing hits, spread and novelty (never the never-learn list).

This matters more than the automatic path. It turns learning from something that happens *to* you into
something you can *do*, deliberately, at the moment you know a thing is worth keeping — and it's the
only path that can capture a genuinely useful command you'll use weekly but never three times in two
days.

The inverse must exist too: **"forget that"** / **"unlearn that"** immediately retires the command
that last resolved, and blocks its action key from re-promotion for 30 days (otherwise it just comes
straight back).

## The never-learn list

Excluded regardless of how often they recur:

| Category | Examples | Why |
|---|---|---|
| **Free-text payloads** | `compose`, `rewrite`, dictation | The arg *is* the content; it never repeats |
| **Questions / vision** | `LOOK`, `CHAT` | Answers aren't actions; nothing to replay |
| **Control plane** | quit, restart, sleep, mode switches | Already the loop's hardcoded floor (§8a). Learning must never widen what the DB can trigger — `actions_only` stays |
| **Destructive** | close/quit/delete-shaped intents | A mis-fired learned row here is unrecoverable |
| **Scheduler** | timers, alarms, reminders | Already deterministic, and the arg is always novel |
| **Low-confidence input** | Whisper below threshold, Vosk `[unk]` fallthrough | Never learn from words we aren't sure we heard |
| **Already-learned** | action key exists | Attach a phrase instead — see [02-aggregation.md](02-aggregation.md) |

The allowlist is defined **positively** in code — an explicit set of learnable intents, not a
blocklist. A new intent is unlearnable until someone deliberately adds it. Defaulting to "no" is the
only safe direction here.

## Worked examples

| Utterance | Resolves to | Learned? |
|---|---|---|
| "open Alex's chat" ×3 over 3 days, in Slack | `Slack \| click_element \| alex fairbairn` | ✅ Promoted after the 3rd |
| "send Alex a message" (after the above) | same action key | ✅ Added as an **alias**, no new command |
| "write Alex an email about the Q3 numbers" | `compose \| <the email>` | ❌ Never — free-text payload |
| "open the invoice I just downloaded" ×1 | `open_file \| ~/Downloads/inv-8823.pdf` | ❌ One-off; also an unstable arg |
| "necks tab" ×5 in one minute | `tab_arrow \| down:1` | ❌ Deterministic parser already handles it; also fails spread |
| "open the deploy dashboard" ×2, then ⌘Z | — | ❌ Negative signal; candidate decremented |
| "open my standup notes", then "save that as a command" | `Obsidian \| open_note \| standup` | ✅ Immediate — explicit override |

## Defaults

```
learning_mode          = "suggest"   # off | suggest | auto
learning_min_hits      = 3
learning_min_days      = 2
learning_negative_window_seconds = 20
learning_max_negatives = 3           # then blocked from promotion
learning_arg_max_words = 6
```

All live-adjustable from Settings, all read through the existing `_setting()` helper so they apply
without a restart.
