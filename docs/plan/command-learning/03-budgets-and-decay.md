# 03 — Budgets, decay, and the measured cost model

> The question this answers: *"After a week of use I've got hundreds of commands — is that a strain on
> the system, especially loading them all every time I open an app?"*

## The measurement first

Benchmarked on this machine (M-series Mac mini, 2026-07-31) against a copy of the real
`data/commands.db`, synthesising learned commands with 3 phrases each on the Slack context:

| learned commands | total phrases | focus-load (SQLite) | `resolve()` worst case | Vosk grammar rebuild | DB on disk |
|---|---|---|---|---|---|
| 0 *(today)* | 130 | ~0.2 ms | 0.047 ms | 5.6 ms | 60 KB |
| 50 | 280 | 0.3 ms | 0.050 ms | 1.0 ms | 100 KB |
| 200 | 730 | 1.4 ms | 0.054 ms | 1.8 ms | 188 KB |
| 500 | 1630 | 2.2 ms | 0.071 ms | 4.1 ms | 376 KB |
| 1000 | 3130 | 4.5 ms | 0.101 ms | 8.1 ms | 684 KB |

*`resolve()` worst case = a **miss**, which scans every phrase across all three match types — the most
expensive path. Focus-load numbers vary ±1 ms run to run; treat them as "single-digit milliseconds".*

**Conclusion: the load worry is unfounded.** A thousand learned commands costs 4.5 ms once per app per
daemon run, 0.1 ms per utterance, and 684 KB of disk. For scale, the AX tree walk that draws the click
overlay costs ~70 ms — fifteen times more, every single time you use it.

Three structural reasons it stays cheap, all already true in `command_cache.py`:

1. **Resolution never touches SQLite.** Commands are read into `_BASE` / `_APP_CACHE` and matched in
   memory. The hot path has no database in it at all.
2. **Focus load is once per app, then cached** (`on_focus` returns immediately if `app in _APP_CACHE`).
   Switching back and forth between Slack and Cursor all day costs two loads total.
3. **It's text.** 1000 commands is well under a megabyte.

## So why cap anything?

Because the thing that degrades is **precision**, not performance. This is the honest reason for every
limit in this document, and it should be stated as such rather than dressed up as a performance
concern:

### 1. The Vosk grammar gets less discriminating
The fast lane is *grammar-constrained*: it maps what you said onto the nearest phrase in the grammar,
or returns `[unk]`. That's why it can turn "necks tab" into "next tab" — a feature, when the grammar
is 130 curated phrases. At 3130 phrases, that same snapping behaviour has 24× more targets, and the
odds that a mis-heard or unrelated utterance lands *confidently* on some stale learned command rise
sharply. The rebuild cost is trivial (8 ms); the recognition quality is not.

### 2. Resolution collisions become coin-flips
`command_cache.resolve()` returns the **first** phrase that matches, scanning pools in order and
`exact` → `contains` → `regex` within each — but in **arbitrary row order** inside a pool. With 49
curated commands, collisions are rare and were designed out by hand. With hundreds of learned rows,
two commands *will* eventually both match, and today's winner is effectively whichever SQLite handed
back first. See [04-resolution-and-safety.md](04-resolution-and-safety.md) — this must be fixed before
learning is switched on.

### 3. You have to be able to audit it
The learned list is a thing a person needs to read, understand and prune. That caps it at roughly "one
screen you'd actually scroll", not "whatever fits in RAM". A system you can't inspect is one you stop
trusting, and an untrusted learning system is worse than none.

## The budgets

```
learning_max_per_context = 40     # learned commands in any one app
learning_max_total       = 300    # learned commands overall
```

Both are *soft* caps enforced by eviction, not by refusing to learn: a new promotion at the cap evicts
the lowest-scoring existing learned command in that context. New knowledge should always be able to
displace stale knowledge — a cap that blocks learning would make the system worse over time instead of
better.

`builtin` and `user` (hand-made) rows are **never** counted against these caps and never evicted. Only
`source='learned'` is subject to any of this.

## The score

One function, used for eviction, decay and phrase pruning — deliberately simple so it can be explained
in the dashboard:

```
score = hit_count × 0.5 ^ (days_since_last_used / 30)
```

A half-life of 30 days. Ten hits three months ago scores 1.25; three hits this week scores ~2.9. Recent
and modest beats old and heavy — which is what you want from something meant to track how you *actually
work now*.

## Probation — the counterweight to automatic learning

**Decided 2026-07-31.** With `learning_mode = auto` and a same-day-allowed bar, nothing human sits
between a guess and the database. Probation is what makes that safe.

```
learning_probation_days = 14
learning_probation_uses = 2
```

A newly learned command is **on trial**. To graduate it must actually be used — resolved from the DB,
not re-derived — at least `learning_probation_uses` times within `learning_probation_days`. Fail and
it is **deleted**, not demoted: it never earned a place to be demoted from.

This targets precisely the failure mode that eager promotion creates. "I did this three times in one
afternoon" is both the signature of a genuine habit *and* the signature of a one-off task you'll never
touch again. You cannot tell the two apart at promotion time — but you can tell them apart two weeks
later, for free. So don't agonise at the decision point; make the decision cheap to reverse.

**Why not a blanket TTL on everything** (the tempting simpler version — "commands expire after 10–30
days unless used N times"): a command you use every Monday would keep dying and being relearned, which
reads as flakiness rather than housekeeping. Probation applies only to the *unproven*; once a command
has shown it's real, it moves to the far gentler retirement curve below.

**Cost to build: near zero.** `command.learned_at` and `command.hit_count` already exist, so this is
one more query in the nightly `decay()` job and no schema change.

## Decay — how commands die

Run in the same scheduled slot as #28's "dream" consolidation (both are nightly housekeeping over
accumulated state):

| Age since last use | What happens | Reversible? |
|---|---|---|
| 60 days | **Demoted** — `enabled = 0`. Leaves the Vosk grammar and resolution; stays visible in the dashboard, greyed | Yes — one click, or just say it again |
| 180 days | **Deleted**, with a line in the log | No (but it can be relearned) |
| Any time, over cap | **Evicted** — lowest score in that context | No |

Demotion before deletion matters: a command you use twice a year should degrade gracefully, not
vanish. And a demoted command that you *do* say again gets caught by the LLM path, re-promoted
instantly (its candidate history is still there), and re-enabled — so seasonal commands heal
themselves.

**Candidates decay faster:** a candidate that hasn't been hit in 30 days is deleted. Most candidates
never become commands, and that's the system working correctly — they're the record of one-off
requests, and they shouldn't accumulate either.

`command_log` is append-only and the raw evidence trail; it's trimmed on a rolling **90-day** window
(at ~50 utterances/day that's ~4500 rows — a few hundred KB, and it's what makes "why did it learn
this?" answerable).

## What this adds up to

With a promotion bar of 3 hits across 2 days, a 40-per-app cap, and a 60-day demotion, the realistic
steady state is **tens of learned commands per app you use daily, and near-zero for apps you don't** —
a set small enough to read in one sitting, that tracks how you work now rather than how you worked six
months ago.

If real usage shows otherwise, the tuning knob to reach for first is `learning_min_days` (spread), not
the caps — spread is what separates habits from noise, and every measurement above says we have room
to be generous on volume.
