# Command Learning — the self-wiring command loop

> **Status (2026-07-31):** **Phases 0, 1 and 2 ✅ built** — resolution is deterministic, every
> LLM-resolved action is observed, and commands are **learned automatically** and resolve from the DB
> from then on. `remember that` / `forget that` / one-"no" retirement / re-mapping / probation / caps
> all live. Pending: the dashboard page (its API is live) and a spoken confirm. Phases 3–5 (sequences,
> templates, the #52 overlay tie-in) are design only. Gates:
> `scripts/command_learning_gate{0,1,2}.py`. Implements ideas **#14** (self-wiring command learning),
> **#24** (self-heal → learned fix) and the `NEXT` on **#52**, on top of the command DB (#36).

**The idea in one line:** when you ask for something the parser doesn't know, the LLM works it out and
does it — and Vox *remembers the wiring*, so the next time the same request costs nothing and can't be
mis-heard.

This is the part of Vox that gets better the longer you use it. It's also the part that can quietly
poison itself, so the design is deliberately conservative: **observe everything, promote almost
nothing, and make every promotion reviewable and reversible.**

## Index

| Doc | Answers |
|---|---|
| [01-promotion.md](01-promotion.md) | What actually earns the right to become a command? What must never be learned? |
| [02-aggregation.md](02-aggregation.md) | "Send Alex a message" vs "open Alex's chat" — how variants collapse instead of multiplying |
| [03-budgets-and-decay.md](03-budgets-and-decay.md) | The measured cost model, caps, and how commands die when they stop earning their place |
| [04-resolution-and-safety.md](04-resolution-and-safety.md) | Collision handling, blast radius, and every way this can go wrong |
| [05-schema-and-api.md](05-schema-and-api.md) | DB changes and the write API |
| [06-rollout.md](06-rollout.md) | Phased build, each phase with a verification gate |

## What exists today (verified 2026-07-31)

The **read half** is built and wired; the **write half** does not exist at all.

| Piece | State |
|---|---|
| Schema (`intent`/`context`/`command`/`phrase`/`command_log`) | ✅ Built. `command.source` already accepts `'learned'`; `command_log.resolved_by` already accepts `'llm'` |
| Seed → cache → `resolve()` → `dispatch` | ✅ Built, gated by `command_db_enabled` (**currently off**) |
| Vosk grammar from `command_cache.active_phrases()` | ✅ Built, `vosk_commands_enabled` **on** |
| Dashboard: view, enable/disable, add/delete *phrases on existing commands* | ✅ Built |
| Deterministic resolution ranking + ambiguity fall-through | ✅ Built (Phase 0, 2026-07-31) |
| Observation write API (`log_resolution`, `note_candidate`, `find_by_action`, `note_usage`) | ✅ Built (Phase 1) |
| Policy layer `command_learn.py` (never-learn gate, promotion bar, negative signals) | ✅ Built (Phase 1) |
| **Promotion** (`promote`, `add_learned`, `attach_phrase`) | ❌ Deliberately not built — Phase 2 |
| **Learned commands** | ❌ 0, by design. Shadow mode observes only |
| Dashboard **Candidates** view | ❌ Pending (rest of Phase 1) |

Before this work the LLM re-derived the same answer every single time, at full latency and cost,
forever, and nothing was recorded. It still re-derives — but now the evidence is accumulating, so we
can see exactly what it *would* learn before letting it.

## The core principle

> **Learn the action. Cluster the phrases. Promote on evidence. Decay on silence.**

Four ideas, in the order they matter:

**1. The unit of learning is the *action*, not the phrase.** A command is identified by
`(context, intent, arg)` — never by the words you said. Words are *aliases* that point at an action.
This one decision is what stops the variant explosion the user is right to worry about: "send Alex a
message" and "open Alex's chat" resolve to the same action, so they become **one command with two
phrases**, not two commands. See [02-aggregation.md](02-aggregation.md).

**2. Nothing is learned from a single success.** One-off requests are the overwhelming majority of
what an assistant does, and a thing you asked for once is *by definition* not a command. Every
resolution is logged (cheap, append-only); only repeated, spread-out, uncorrected successes are
promoted. See [01-promotion.md](01-promotion.md).

**3. Learned rows are second-class citizens.** They are app-scoped, capped, decayed, outranked by
hand-made commands, and always visible with the evidence that created them. A learned command should
feel like a cached shortcut, not a permanent edit to the system.

**4. When in doubt, stay slow.** The failure mode we care about is not "Vox was slow", it's "Vox
confidently did the wrong thing." Any ambiguity falls through to the LLM rather than guessing.

## The pipeline

```
utterance
   │
   ├─ deterministic parser hit? ──────────────► run it. Nothing to learn.
   │
   ├─ command DB resolve() hit? ──────────────► run it. Bump the phrase's hit count.
   │
   └─ miss → LLM executor resolves + runs it
                │
                ├─ log the resolution                    (command_log — always, from Phase 1)
                │
                ├─ eligible to learn?                    (never-learn list, arg shape, confidence)
                │      │  no → stop. It stays a one-off.
                │      yes
                ├─ compute the action key                 context | intent | normalize(arg)
                │
                ├─ action already a command?
                │      yes → attach the phrase as an alias (dedup + cap)   ◄── the variant collapse
                │      no  → upsert a CANDIDATE and count the hit
                │
                └─ candidate cleared the promotion bar?
                       yes → promote to command (source='learned'), invalidate the cache
                       no  → wait. It may never be promoted, and that's correct.
```

The important property: **the LLM never writes to the command DB.** It resolves an utterance to an
action, exactly as it does today. The learning layer observes the *outcome* and does the writing
under rules that live in code and are auditable. The model's job is recognition, not schema editing.

## What the measurements changed about this design

The original worry was load cost — "when we open an app it queries all the commands for that app."
Measured on this machine ([03-budgets-and-decay.md](03-budgets-and-decay.md) has the full table):

- **1000 learned commands / 3130 phrases → 4.5 ms focus-load, 0.1 ms resolve, 684 KB on disk.**

Performance is not the constraint, and the design should not pretend otherwise. Loading is a single
indexed query, once per app per daemon run, cached in RAM after that; resolution never touches SQLite.

The constraint is **precision**:

- The Vosk fast lane is *grammar-constrained* — it snaps what you say onto the nearest phrase in the
  grammar or returns `[unk]`. Today that grammar is ~130 phrases. At 3000, the odds that a mis-heard
  utterance lands confidently on some unrelated learned command rise sharply. Bigger grammar, worse
  discrimination.
- `command_cache.resolve()` returns the **first** matching row it scans, in arbitrary row order within
  a pool. With 49 curated commands that's fine. With hundreds of learned rows, collisions become
  likely and the winner is effectively a coin-flip. This must be fixed *before* learning is enabled —
  see [04-resolution-and-safety.md](04-resolution-and-safety.md).
- A human has to be able to look at the learned list and understand it. That caps it at "a page you'd
  actually read", not "whatever fits in RAM".

So the caps in [03-budgets-and-decay.md](03-budgets-and-decay.md) exist to protect **recognition
quality and your ability to audit it** — not to save bytes. Worth stating plainly, because it changes
where the limits should sit and why.

## Design decisions — FINALISED 2026-07-31

The governing principle the answers settled on: **promote eagerly, retire ruthlessly.** A wrong learn
costs 14 days and cleans itself up; a missed learn costs permanent friction. That asymmetry is why the
bar is loose and the expiry is strict — the two only make sense together.

| # | Decision | Setting |
|---|---|---|
| 1 | **Auto-promote by default.** Learning shouldn't create admin. It saves silently and logs it | `learning_mode = auto` |
| 2 | **It asks only when it should** — the toggle is on, or the mapping is a leap *and* evidence is thin | `learning_confirm = off` |
| 3 | **3 clean hits in a rolling 2-day window** — same-day promotion allowed, no waiting for tomorrow | `learning_min_hits = 3`, `learning_window_days = 2` |
| 4 | **Probation replaces the spread rule** as the safety net: unproven commands expire | `learning_probation_days = 14`, `learning_probation_uses = 2` |
| 5 | **Re-mapping allowed on correction** — "when I say X I mean Y" rewrites a *learned* command | [04](04-resolution-and-safety.md) |
| 6 | **One "no" demotes a promoted command** — a correction outranks the failure counter | [04](04-resolution-and-safety.md) |
| 7 | **Learned phrases join the Vosk grammar only after one proven DB-resolved use** | [04](04-resolution-and-safety.md) |

What did **not** change, and shouldn't: the LLM never writes to the DB (the learning layer does, under
code rules); it can only produce actions `actions.parse()` already understands; learned rows are
app-scoped and outrank nothing; the never-learn allowlist is positive; and deleting stays explicit.
