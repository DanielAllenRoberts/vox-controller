# 02 — Aggregation: how variants collapse instead of multiplying

> The question this answers: *"If I say 'send Alex a message' and 'open Alex's chat' and they mean
> the same thing, how do we avoid ending up with hundreds of saved commands for the same sentence with
> slight variation?"*

## The rule that does all the work

> **Identity is the action. Words are aliases.**

A command is keyed by what it *does*, never by what you *said*:

```
action_key = context_id | intent | normalize(arg)
```

Both example phrasings resolve, via the LLM, to the same action:

```
Slack | click_element | alex fairbairn
```

…so they produce **one command with two phrases**, not two commands. The existing schema already
models this exactly — `command` 1—N `phrase` — so no structural change is needed. What's needed is the
discipline in the write path:

```python
key = (context_id, intent, normalize(arg))
existing = find_command_by_action(key)
if existing:
    attach_phrase(existing, heard)   # ← alias. NEVER a second command.
else:
    upsert_candidate(key, heard)     # ← count it; promote later if it earns it
```

**Look up by action before you ever consider writing a command.** Everything else in this document is
refinement on top of that one line.

A useful side effect: aliases can attach to **builtin** commands too. If you keep saying "flick to the
next one" and it resolves to the builtin `tab_arrow(down:1)`, that phrase gets added to the *existing*
command. Your original 49 commands get richer over time without a single new row — which is a much
better outcome than learning a parallel duplicate that then competes with the builtin at resolution
time.

## Phrase admission — stopping alias creep

An action can still accumulate junk aliases if every near-identical utterance is stored. Four rules,
applied in order, before a phrase is attached:

### 1. Normalize
Reuse `command_store.normalize()` (lowercase, strip punctuation, collapse whitespace) — it must stay
the same function the loop matches with. Then strip a leading/trailing filler set:
`please`, `can you`, `could you`, `just`, `for me`, `now`, `vox`, `hey`, `um`, `okay`.

`"Hey Vox, could you open Alex's chat please?"` → `"open alexs chat"`

### 2. Exact-duplicate check
Already present on this command? Bump `hit_count` + `last_used_at` and stop. (Also the natural place
to count usage for decay — see [03-budgets-and-decay.md](03-budgets-and-decay.md).)

### 3. Near-duplicate suppression
Compare against the command's existing phrases with a token-set similarity (`difflib.SequenceMatcher`
on sorted tokens is enough — no new dependency). Above `learning_phrase_similarity = 0.85`, treat as
the same phrase: bump the existing one's count, don't add a row.

Collapses: `"open alexs chat"` / `"open alex chat"` / `"open the alex chat"` → one phrase.

### 4. Subsumption
If an existing phrase is a token-subsequence of the new one, keep the **shorter** one — it's more
general and will match more. If the new one is shorter and subsumes an existing one, replace it.

Collapses: `"open alexs chat"` subsumes `"go and open alexs chat now"`.

### 5. Cap and evict
`learning_max_phrases_per_command = 6`. At the cap, evict the lowest-scoring phrase (same score
function as commands: hits × recency decay). A command that needs more than six ways to say it is
usually a **template** — see below.

## The real bloat vector: parameterised requests

Phrase dedup solves "the same thing said differently". It does **not** solve the case that actually
grows without bound:

```
"open Alex's chat"    → Slack | click_element | alex fairbairn
"open Sarah's chat"    → Slack | click_element | sarah okonjo
"open Mike's chat"     → Slack | click_element | mike chen
```

Three *different* action keys, so three legitimately separate commands — and it grows with your
contact list, your channel list, your repo list. This, not phrasing variance, is how you'd get to
hundreds of rows.

### Detection: same shape, different slot

When **≥ 3 candidates** (default `learning_template_min = 3`) share the same `(context, intent)` and
their phrases differ *only* in the span that corresponds to their arg, that isn't three commands —
it's one command with a hole in it:

```
"open {x}'s chat"  →  Slack | click_element | {x}
```

The detection is mechanical, not model-driven:

1. Group candidates by `(context_id, intent)`.
2. For each, locate the arg's span inside its normalized phrase (the arg text, or its fuzzy match).
3. Replace that span with `{}` to get a *shape*.
4. If ≥ 3 candidates share a shape, emit a **template**.

`"open alexs chat"` + arg `alex fairbairn` → shape `"open {} chat"`. Three people, one shape.

### Storing a template

The schema already reaches this: `phrase.match_type = 'regex'` with a capture group, and the existing
`command.param` column to say where the capture goes.

```
phrase:  ^open (.+?)(?:s)? chat$     match_type=regex
command: intent=click_element  param=$1
```

The payoff is large: **one row that works for people you have never said before**, instead of one row
per person, forever. It's also the same "typed-argument grammar" lever #53 identified from the STT
side — arrived at from the other direction, which is a good sign the shape is right.

### Why it's Phase 3, not Phase 1

Templates are where a wrong generalisation becomes expensive: a sloppy regex could swallow unrelated
utterances and silently hijack them. So the first release learns only **literal** commands, and
templates arrive once there's real candidate data to check the detector against — data Phase 1
produces for free. The schema must not preclude it (it doesn't), and the detector should be built to
*propose* templates in the dashboard for approval before it ever writes one automatically.

Interim mitigation until templates land: the per-context cap in
[03-budgets-and-decay.md](03-budgets-and-decay.md) bounds this, and decay clears out the people you
stopped talking to.

## Cross-context duplicates

The same phrase can legitimately mean different things in different apps — that's the whole point of
app-scoped commands. `"next"` in Spotify and `"next"` in Arc are *supposed* to be two rows.

But an action learned in one app that is genuinely global ("open dashboard") shouldn't be relearned
per app. Rule: **learned commands are always app-scoped, never promoted to global automatically.** If
the same `(intent, arg)` gets learned in ≥ 4 distinct app contexts, the dashboard *suggests*
promoting it to global — a human decision, never automatic. Widening blast radius is exactly the kind
of thing that should require a person.

## Defaults

```
learning_phrase_similarity        = 0.85
learning_max_phrases_per_command  = 6
learning_template_min             = 3      # Phase 3
learning_global_suggest_contexts  = 4      # suggest-only, never automatic
```
