# 04 — Resolution order, ambiguity, and everything that can go wrong

> The question this answers: *"How do we make sure a single misinterpretation doesn't get baked in and
> then fire forever?"*

> **✅ FIXED 2026-07-31** (Phase 0). The ranking described below is implemented in
> `command_store.match_sort_key()` / `rank_matches()` / `collect_matches()` and used by both
> `command_store.resolve()` and `command_cache.resolve()`. Gate: `scripts/command_learning_gate0.py`.

## The bug that must be fixed before learning is enabled

`command_cache.resolve()` today:

```python
for pool in pools:                      # app slice, then global
    for mt in ("exact", "contains", "regex"):
        for c in pool:                  # ← arbitrary row order
            for p in c["phrases"]:
                if _phrase_hit(...):
                    return hit          # ← FIRST match wins
```

With 49 hand-curated commands this is fine — collisions were designed out by hand. With learned rows
it is not: two commands will eventually both match, and the winner is whichever row SQLite happened to
return first. That is a silent, unpredictable, hard-to-reproduce wrong action — the exact failure mode
this whole design is trying to avoid.

**Resolution must become deterministic and explainable before a single learned row exists.** Collect
*all* matches, then rank by explicit precedence:

| # | Criterion | Rationale |
|---|---|---|
| 1 | **Context specificity** — site > app > global | A Slack-specific command beats a generic one |
| 2 | **Source** — `user` > `builtin` > `learned` | Something a human wrote always beats something inferred |
| 3 | **Match type** — exact > contains > regex | Precision over generality |
| 4 | **Phrase specificity** — longer normalized phrase wins | "open alex chat" beats "open" |
| 5 | **Score** — hits × recency ([03](03-budgets-and-decay.md)) | Proven commands beat speculative ones |
| 6 | **Deterministic tiebreak** — lowest `command.id` | Never arbitrary, even in a true tie |

Rule 2 is the load-bearing one: **a learned command can never override a builtin or a hand-written
one.** Learning can only fill gaps, never rewrite what's already there.

## Ambiguity: refuse to guess

If the top two matches are **different actions** and their ranking is close — same context, same match
type, and score within `learning_ambiguity_margin` (default 20%) — do **not** pick one.

Instead: fall through to the LLM, exactly as if the DB had missed. Slower, correct, and it produces a
fresh resolution that becomes evidence for whichever candidate deserves to win. Logged as
`resolved_by='llm'` with an `ambiguous` flag so the dashboard can surface "these two commands keep
colliding" — which is genuinely useful signal about a bad learn.

The principle: **the cost of being slow is a second; the cost of being wrong is trust.**

## Blast radius

Constraints that hold regardless of what gets learned:

- **`actions_only` stays.** Dispatch only lets the DB run `category='action'` intents; mode and system
  intents (sleep, restart, quit, mode switches) remain in the loop's hardcoded floor. Learning must
  never widen this — it's the safety floor the whole DB path already sits behind.
- **Learned rows are app-scoped**, never global (see [02](02-aggregation.md)). A bad learn can only
  misfire in the one app it came from.
- **Never-learn list** ([01](01-promotion.md)) keeps destructive and free-text intents out entirely.
- **Learned phrases join the Vosk grammar only after promotion *and* one successful DB-resolved use.**
  A bad learn can't degrade recognition before proving itself once.
- **`command_db_enabled` remains the master switch**, and `learning_mode=off` disables writing
  independently of reading. Two switches, because "use what I've taught it" and "keep teaching it" are
  genuinely separate decisions.

## Failure modes

| # | Failure | Mitigation |
|---|---|---|
| F1 | **Mis-heard utterance is learned** ("open Alex's chat" → Alex) | Never learn from low-confidence transcripts; 2-day spread means a one-off mis-hear can't reach the bar; negative signals decrement |
| F2 | **The LLM resolves wrongly but the action "succeeds"** (clicks the wrong thing, no error) | `success` is not enough on its own — the negative-signal window catches the undo/correction that follows. 3 negatives permanently block the action key |
| F3 | **Learned command goes stale** (channel renamed, person left) | Execution failure marks the command; 2 consecutive failures auto-demote it (`enabled=0`) and re-open the candidate |
| F4 | **Collision with a builtin** | Source precedence — builtin always wins. Learned rows can't shadow curated ones |
| F5 | **Two learned commands collide** | Ambiguity margin → fall through to the LLM rather than guess |
| F6 | **Grammar pollution degrades recognition** | Phrase caps, delayed grammar entry, decay. Grammar size is visible in the dashboard |
| F7 | **Runaway learning** (a loop that promotes constantly) | Rate limit: max `learning_max_promotions_per_day = 10`. Exceeding it logs loudly and pauses promotion — a symptom of a bug, not of a productive day |
| F8 | **User can't tell why Vox did something** | Every DB resolution logs the command id, phrase and match type; the dashboard shows each learned command's full evidence chain |
| F9 | **Learning writes while the daemon reads** | Writes go through a short-lived connection off the voice thread, then `command_cache.refresh()` — the same path dashboard edits already use |
| F10 | **Something is learned that shouldn't be, and nobody notices** | Shadow mode first ([06](06-rollout.md)); `suggest` as the default mode; a weekly "what I learned" summary |

## Auto-demotion on failure (F3)

The dead-command problem is worth stating separately because it's the one that erodes trust quietly:
you learn "open the deploy channel", the channel gets archived, and from then on Vox confidently
clicks nothing — or worse, something adjacent.

So execution outcome feeds back:

- `click_index` / `click_element` reporting `press_failed`, or a target that no longer exists →
  record a failure against the command.
- **2 consecutive failures → demote** (`enabled=0`) and re-open the candidate so the LLM path takes
  over again and can relearn the *current* target.
- A single failure between successes is noise (transient focus, a slow window) and is ignored.

This is what makes the system self-healing rather than merely self-wiring — and it's the difference
between a shortcut cache and a liability.

## Correcting a learned command — re-mapping

**Decided 2026-07-31.** The original rule was "the LLM can only ever add; edits and deletes are
human-only". That's relaxed in one specific, high-value way: **you can re-point a learned command by
saying so.**

> "No — when I say *open the deploy channel*, I mean **#deploy-prod**."

Vox rewrites that command's action, keeps its phrases, and confirms. This is the natural repair for
the exact thing that worries people about automatic learning: it learned something slightly wrong, and
you want to fix it in one breath rather than hunt through a settings page.

Rules on re-mapping:

- **Only `source='learned'` rows.** `builtin` and `user` commands are human-authored and stay
  untouchable — an inferred edit must never overwrite something a person wrote by hand.
- **Only on an explicit correction.** A spoken re-mapping ("when I say X I mean Y"), never inferred
  from behaviour. Guessing at a re-map compounds one wrong mapping into another.
- **The previous action is recorded** — so it can be undone, and so it becomes the anti-mapping that
  idea #56 uses to stop the same wrong pick recurring.
- **Re-mapping resets probation.** The new mapping is a fresh guess and gets re-proven like any other.
- **Deleting is still explicit** — "forget that", or the dashboard. Nothing silently removes a command
  except probation and decay.

### Immediate demotion on correction
Also decided: a **correction on a promoted command demotes it at once**, rather than waiting for the
2-consecutive-failure counter in F3. That counter is for *execution* failures (a target that vanished);
a user saying "no, that's wrong" is a stronger and more direct signal, and a learned command doing the
wrong thing is worse than having no command at all. One "no" is enough.

## Observability

Non-negotiable, because an audit trail is what makes any of this acceptable:

- **Per resolution** (`command_log`): heard phrase, context, command id, intent, arg, `resolved_by`,
  success, ambiguity flag.
- **Per learned command**: source utterances, hit count, first/last used, promotion date, why it was
  promoted (which rule), failures, current score.
- **Dashboard** (`Commands.tsx`, which already has a `learned` badge colour): a **Candidates** queue
  showing what *would* be learned with one-click approve/reject; the learned list with evidence and
  delete; and the global `learning_mode` switch.
- **Voice**: "what have you learned?" reads back recent learned commands; "forget that" retires the
  last one.

## Defaults

```
learning_ambiguity_margin        = 0.20
learning_max_promotions_per_day  = 10
learning_demote_after_failures   = 2
```
