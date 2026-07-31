# 07 — Multi-step actions (sequences)

> The questions this answers: *"Is it set up to handle multiple actions? Can the LLM even do multiple
> actions?"*

## Where things stand today (verified 2026-07-31)

Short answer: **the deterministic parser can chain, the LLM cannot compose, and the command DB cannot
store a sequence.**

| Layer | Multi-action? | Detail |
|---|---|---|
| **Deterministic parser** | ✅ Yes, two-plus | `actions.handle()` splits on ` and ` and runs each half — but *only if every half parses on its own* (`actions.py:61-64`). That guard is what stops "search cats and dogs" being split |
| **LLM executor** | ❌ No | `executor.execute()` takes `raw.splitlines()[0]` — **only the first line** of the model's reply. The system prompt reinforces it: *"output just that command line"*. Every prefixed branch (`TYPE:`, `CLICK:`, `LOOK:`, `SCHEDULE:`, `EDIT:`, `DICTATE`) returns immediately |
| **Command DB** | ❌ No | A `command` row is exactly one `intent` + one `arg`. There is no step table |

One wrinkle worth knowing: because the LLM's single line is handed to `actions.handle()`, a model that
happens to emit `"open slack and next tab"` *will* chain — but only incidentally, and only when both
halves parse deterministically. That's a side effect, not a capability, and it isn't something to rely
on or to learn from.

## Why this matters for learning

The single-action limit bites exactly where the feature is most valuable. The commands worth learning
are frequently two steps:

```
"open Alex's chat"      →  focus Slack        +  click "Alex Fairbairn"
"start my standup"       →  open Obsidian      +  open note "standup"
"go to the deploy logs"  →  focus Arc          +  switch to tab "deploy"
```

Today each of these can only be learned as its *second* step, which silently assumes the right app is
already focused. That assumption holds while you're testing and breaks the first time you say it from
somewhere else — the worst kind of bug, because it looks like it works.

So sequences aren't a nice-to-have bolted on later; they're most of the value. The schema needs to
accommodate them from the start even though the behaviour ships later.

## Schema: `command_step` (additive, no migration pain)

```sql
CREATE TABLE command_step (
    id         INTEGER PRIMARY KEY,
    command_id INTEGER NOT NULL REFERENCES command(id) ON DELETE CASCADE,
    position   INTEGER NOT NULL,          -- 0-based execution order
    intent     TEXT    NOT NULL REFERENCES intent(name),
    arg        TEXT,
    param      TEXT,
    UNIQUE (command_id, position)
);
```

The compatibility trick: **a single-action command has zero step rows** and keeps using its own
`intent`/`arg`, exactly as it does now. A sequence sets `command.intent = 'sequence'` and owns N step
rows. Every existing row and every code path that reads `command.intent` keeps working untouched.

Execution becomes:

```python
steps = load_steps(cmd) or [(cmd.intent, cmd.arg)]   # single-action = a one-step sequence
for intent, arg in steps:
    result = actions.run_intent(intent, arg)
    if failed(result):
        break        # stop-on-failure, no rollback — see below
```

### The action key for a sequence

Identity ([02](02-aggregation.md)) extends cleanly — hash the ordered steps:

```
action_key = context_id | "sequence" | sha1("focus:slack|click:alex fairbairn")
```

So two different phrasings of the same two-step sequence still collapse onto one command, exactly as
they do for single actions. The rule doesn't change; only what goes into the hash.

## Making the LLM emit multiple actions

A small, contained change to `executor.execute()`: read **all** lines of the reply rather than the
first, require every line to parse, and run them in order.

```
open slack
click Alex Fairbairn
```

Constraints, all of which matter:

- **Gated** behind `llm_multi_action_enabled` (default **off**). This widens what a single model
  response can do to your machine, which is a real blast-radius change and deserves its own switch.
- **All-or-nothing parse.** If any line fails `actions.parse()`, the whole reply is rejected rather
  than half-run. Half-executing a plan is worse than not executing it.
- **Cap the length** (`llm_max_actions = 3`). A model emitting eight steps has misunderstood, and the
  cap turns a confused response into a rejected one instead of a rampage.
- **Prefixed branches stay single.** `TYPE:`, `LOOK:`, `EDIT:`, `SCHEDULE:`, `DICTATE` remain
  terminal — they're not composable and shouldn't pretend to be.
- **No mixing** action lines with prefixed branches in one reply.

The system prompt needs a matching edit: today it says *"output just that command line"*, which is
what makes the model emit one action. It would become "one command per line, at most 3".

## Execution semantics: stop on failure, never roll back

**There is no undo.** A click cannot be un-clicked, an app cannot be un-focused. So:

- Steps run **sequentially**, stopping at the first failure.
- The partial result is reported honestly ("opened Slack, but couldn't find Alex's chat") rather than
  presented as success. A sequence that half-worked is exactly the situation where a confident
  "done!" destroys trust.
- A failed step marks the command for the auto-demotion counter in
  [04](04-resolution-and-safety.md) — a sequence whose second step keeps failing is stale and should
  get out of the way.

## Learning a sequence — deliberately conservative

Sequences are more dangerous to learn than single actions: more steps, more ways to be subtly wrong,
and a failure that leaves you somewhere unexpected. So the bar is higher:

1. **Only from explicit chains or explicit teaching.** Either the user said a chained utterance whose
   every step parsed and succeeded, or they said "remember that". A sequence is **never** inferred by
   stitching together separate utterances that happened to occur near each other — that inference is
   attractive, and it is exactly how you'd learn a superstition.
2. **Never a sequence containing a never-learn intent** ([01](01-promotion.md)).
3. **Max 3 steps.**
4. **Suggest-only**, regardless of `learning_mode`. A sequence always gets a human look before it goes
   live.

## Phasing

None of this blocks the work starting now:

| Phase | What lands |
|---|---|
| **0–1** (now) | Single-action only. `command_step` **not** created yet — but the action-key design and `find_by_action()` are written so adding it later is additive |
| **3** | `command_step` table + sequence execution in `run_intent`, for **hand-written** sequences via the dashboard. Proves execution before anything learns them |
| **4** | `llm_multi_action_enabled` — the executor emits multi-line plans |
| **5** | Learning sequences, suggest-only, under the rules above |

The order is deliberate: **execute** sequences reliably, then let the LLM *propose* them, and only then
let the system *remember* them. Each step is only taken once the one below it is boring.
