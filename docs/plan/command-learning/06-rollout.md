# 06 — Rollout: phases and verification gates

> Each phase is a thin vertical slice with a gate that must pass before the next starts. The ordering
> is chosen so that **the system is observable long before it is powerful** — you get to watch what it
> *would* learn before it learns anything.

## Phase 0 — Fix resolution ordering *(prerequisite, no learning)* — ✅ BUILT 2026-07-31

Make `command_cache.resolve()` deterministic and explainable: collect all matches, rank by the
precedence table in [04](04-resolution-and-safety.md), add the ambiguity fall-through.

**Why first:** with 49 curated commands this is invisible; the moment learned rows exist it's a silent
wrong-action bug. Fixing it afterwards means debugging it under exactly the conditions that make it
hard to reproduce.

**What landed:** `command_store.match_sort_key()` / `rank_matches()` / `collect_matches()` — pure,
testable functions shared by *both* resolvers, so the dev CLI and the runtime cache can't drift.
`command_store.resolve()` and `command_cache.resolve()` now collect every match and rank once. A true
ambiguity returns `None` and logs `AMBIGUOUS … falling through to the LLM`.

> **Gate — PASSED** (`scripts/command_learning_gate0.py`):
> 150/150 seeded phrases still resolve to their own command · 17/17 coverage battery · a learned row
> claiming a builtin's phrase loses 100/100 times (deterministic) · a true ambiguity falls through
> instead of guessing · the runtime cache and the dev resolver agree on all 150.

**Worth knowing, found while testing:** every one of the 150 seeded phrases is `match_type='contains'`
— there is not a single `exact` phrase in the shipped DB. Substring matching makes collisions *more*
likely than the design assumed, which raises the value of this phase: with `contains` everywhere, the
phrase-specificity tiebreak (longer phrase wins) is what stops a short learned phrase hijacking a
longer builtin one.

## Phase 1 — Shadow mode: observe everything, change nothing — ✅ BUILT 2026-07-31 *(dashboard pending)*

`log_resolution()` wired into all three paths; `command_candidate` populated; `command_learn.observe()`
running with the full never-learn gate and promotion bar — but **`promote()` is never called**.

**What landed:**

| Piece | Where |
|---|---|
| `command_candidate` + `command_candidate_phrase` tables, and the learning columns on `command`/`phrase`/`command_log` | `command_store._LEARN_SCHEMA` + `_migrate()` — idempotent, runs on every `build()` |
| `log_resolution` · `mark_negated` · `find_by_action` · `note_candidate` · `note_usage` · `candidates` · `action_key` | `command_store` |
| The policy layer — `observe` / `is_learnable` / `clears_bar` / `check_negative` / `clean_phrase` | **new** `src/vox/command_learn.py` |
| DB-hit usage counters + evidence row | `dispatch._log_db_hit` |
| Negative-signal hook (one place, sees every utterance) | `dispatch.try_deterministic` |
| The one call that feeds learning | `executor._observe`, on the CLICK and COMMAND branches |
| `learning_mode` switch (`off` / `suggest` / `auto`) | Settings → Commands |

> **Gate — PASSED** (`scripts/command_learning_gate1.py`):
> migration idempotent, 49 commands / 150 phrases intact · three phrasings of the Alex case collapse
> to **one** candidate · the never-learn gate rejects free-text intents, the control plane, and
> unstable args · 3 hits in one day is *not* ready, 3 across two days is · a "no" walks the candidate
> back · **zero** command or phrase rows written, while the evidence trail fills up.

**Two bugs the gate caught, both fixed:**

1. `normalize()` strips apostrophes, so "Alex's" arrived as `alex s` — meaning "open Alex's chat"
   and "open alexs chat" were being stored as *two* phrases when they're plainly the same words.
   `clean_phrase()` now re-joins the possessive. This is the variant-collapse feature failing in
   miniature, and it would have quietly inflated every candidate's phrase list.
2. `check_negative()` double-counted: it called `mark_negated()` (which already walks the candidate
   back) *and* applied its own decrement, so one "no" cost two negatives — a third of the way to a
   permanent block from a single correction. `mark_negated()` now owns the walk-back.

**Still to do in this phase:** the dashboard **Candidates** view (read-only: what it *would* have
learned, with hit counts, spread, phrases and the pass/fail reason). Until that lands, the evidence is
readable from `vox.log`'s `[learn]` lines and `command_store.candidates()`.

**Why this is the most valuable phase:** it produces real data about your actual usage, at zero risk,
and it's the only honest way to tune thresholds. Guessing that 3 hits over 2 days is right is fine;
*checking it against a week of your real utterances* is much better. It also immediately answers "is
the LLM resolving the same thing over and over?" — which is the entire premise of the feature.

> **Gate:** run for **one week** of normal use. Then review the candidate list together and ask: would
> promoting these have been correct? How many are one-offs that correctly stalled? Any that should
> have been learned but weren't? Tune `learning_min_hits` / `learning_min_days` from evidence, not
> intuition. **No promotion code ships until this review happens.**

## Phase 2 — Promotion is live — ✅ BUILT 2026-07-31 *(dashboard UI pending)*

**What landed:** `promote()` · `attach_phrase()` (exact → near-dup → subsumption → cap+evict) ·
`remap()` · `retire()` · `decay()` incl. probation · `_enforce_caps()` · `score()` · `window_hits()`;
auto-promotion wired into `command_learn.observe()`; the explicit paths `remember that` /
`forget that` (in `dispatch._learning_phrase`) and `remap_last()`; one-"no" retirement of a misfiring
learned command via `note_db_hit()` + `check_negative()`; `decay()` at daemon boot; and the review API
(`GET /api/commands/learning`, `POST …/candidates/{id}/promote`, `DELETE …/learned/{id}`).

> **Gate — PASSED** (`scripts/command_learning_gate2.py`): 3 uses in one day auto-saves · the learned
> command then resolves from the DB with no LLM · a 4th phrasing attaches as an alias, not a second
> command · "remember that" saves on one use · "forget that" deletes *and* blocks re-learning (proved
> by 4 further uses not bringing it back) · one "no" disables a learned command · re-mapping repoints
> a learned command and **refuses builtins** · probation deletes an unused command while a proven one
> survives · caps evict the lowest-scoring.

**Two things real shadow data caught before this shipped**, which is exactly what Phase 1 was for:

1. **URLs were unlearnable.** The arg-shape rule rejected any `.`, so `navigate` — the most common
   learnable intent, whose args are overwhelmingly URLs — could never be learned. Seen live:
   `'open go proxies' → navigate — not learnable (arg contains sentence punctuation)`. A dot now only
   reads as prose when the arg also contains spaces, since identifiers don't.
2. **Focus-independent actions were being learned per-app.** "open logic" produced *two* candidates
   (Logic Pro and Slack contexts) for one action, each needing its own three hits. `navigate`,
   `navigate_new` and `app_cycle` do the same thing wherever you say them, so they now learn
   **globally**; everything focus-dependent (click, tab, window, sidebar) stays app-scoped, which is
   what keeps a bad learn's blast radius small.

**Still to do:** the dashboard page itself (the API is live; `Commands.tsx` needs the Learned /
Candidates views), and the spoken confirm — today a `should_confirm` hit *withholds* the save and logs
it rather than asking aloud, and `remember that` is the manual way to take it.

## Phase 2 (original plan) — Suggest mode: promotion with a human in the loop

`learning_mode = "suggest"` (the default). Candidates that clear the bar surface in the dashboard for
one-click approve/reject. Approving calls `promote()`. Voice "remember that" / "forget that" work here
too — the explicit path is fully live.

Also lands: `note_usage()`, `attach_phrase()` on existing commands (the variant collapse — this alone
is a real win, since it enriches your builtin commands), auto-demote on failure, and the caps.

> **Gate:** at least 5 commands promoted through the UI and used successfully via the DB path
> (`resolved_by='db'` in the log, no LLM round-trip). Rejected candidates stay rejected. A deliberately
> broken command (rename its target) auto-demotes after 2 failures.

## Phase 3 — Auto mode + decay

`learning_mode = "auto"` becomes available (not the default): candidates clearing the bar promote
themselves, rate-limited to 10/day, each announced quietly in the log and summarised weekly. Nightly
`decay()` runs.

> **Gate:** two weeks in auto with zero wrong-action incidents; the learned set stays inside the caps
> without manual pruning; demotion and deletion both observed working.

## Phase 4 — Templates

Slot detection from [02](02-aggregation.md). Ships as **suggest-only** regardless of `learning_mode` —
a proposed template is shown with the candidates it would replace and the regex it would install, and
a human approves it.

> **Gate:** a detected template correctly handles a value never said before, and provably does not
> match utterances outside its shape (a negative-case test set built from the real `command_log`).

## Phase 5 — The #52 tie-in: learn from the click overlay

The original `NEXT` on idea #52. When "click X" can't find a target: auto-show the numbered overlay,
you say a number, and the phrase→element mapping is saved as a candidate. Turns a failure into a
teaching moment, which is the most natural learning interaction in the whole system.

Needs the overlay's element identity to be stable enough to replay — worth revisiting after the AX
enumeration fix (2026-07-28), which made the target list far more complete.

> **Gate:** a failed click, taught once via the overlay, resolves directly on the next attempt.

## After this: the queued follow-on

Once Phase 2 lands, the next actionable work is **ideas #56** (self-correcting clicks — "no, that's
wrong" re-picks, records the anti-mapping, and recalls recent commands) and **#57** (third-tier grid
+ coordinate clicking for AX-invisible content). #56 is largely wiring on top of what Phase 1 already
built: `command_log` and `check_negative()` are the hard parts and they exist.

## Sequencing notes

- **Phase 0 and 1 are safe to build back-to-back** — neither changes voice behaviour, and both are
  additive and guarded. That's a good first work session.
- **`command_db_enabled` must be turned on** for any of this to matter; it's currently off. Turning it
  on with the current 49 curated commands is itself a small, worthwhile test — and Phase 0 makes that
  safe.
- Phases 2+ each need a real decision from a human, so they shouldn't be batched.

## Open decisions

**None — all finalised 2026-07-31** (table in the [README](README.md)). Phase 2 is cleared to build:
`promote()`, `attach_phrase()`, `remap()`, `retire()`, `decay()` incl. probation, the explicit
"remember that" / "forget that" / "when I say X I mean Y" voice paths, and the dashboard views.

The Phase 1 gate below is no longer a *decision* gate but it remains worth running: shadow data will
show whether 3-hits-in-2-days is the right number in practice, and it costs nothing to look before
switching promotion on.
