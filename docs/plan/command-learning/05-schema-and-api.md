# 05 — Schema changes and the write API

> What actually has to be built. Additive only — every change below is a new table or a new nullable
> column, so an existing `commands.db` keeps working untouched.

> **Built 2026-07-31 (Phase 1):** both candidate tables, all the added columns, the idempotent
> `_migrate()`, and the observation half of the API — `action_key`, `log_resolution`, `mark_negated`,
> `find_by_action`, `note_candidate`, `note_usage`, `candidates` — plus `vox/command_learn.py`.
> **Not built (Phase 2, deliberately):** `promote`, `attach_phrase`, `retire`, `decay`, and
> `command_step` (sequences — see [07](07-multi-step-actions.md)). The real `data/commands.db` has
> been migrated: 49 commands and 150 phrases intact, candidate tables present and empty.

## Schema changes

### New: `command_candidate`
The holding pen. An action that has been LLM-resolved but hasn't earned a command yet. **Nothing in
this table affects voice behaviour** — it's pure bookkeeping, which is what makes shadow mode possible.

```sql
CREATE TABLE command_candidate (
    id            INTEGER PRIMARY KEY,
    context_id    INTEGER NOT NULL REFERENCES context(id) ON DELETE CASCADE,
    intent        TEXT    NOT NULL REFERENCES intent(name),
    arg           TEXT,
    action_key    TEXT    NOT NULL,   -- context_id|intent|normalize(arg) — the identity from doc 02
    hit_count     INTEGER NOT NULL DEFAULT 0,
    negative_count INTEGER NOT NULL DEFAULT 0,
    distinct_days INTEGER NOT NULL DEFAULT 0,
    first_seen    TEXT    NOT NULL DEFAULT (datetime('now')),
    last_seen     TEXT    NOT NULL DEFAULT (datetime('now')),
    blocked       INTEGER NOT NULL DEFAULT 0,   -- too many negatives / "forget that"
    blocked_until TEXT,
    promoted_id   INTEGER REFERENCES command(id) ON DELETE SET NULL,
    UNIQUE (action_key)
);
CREATE INDEX idx_candidate_key ON command_candidate(action_key);
```

### New: `command_candidate_phrase`
The phrases seen for a candidate, so a promotion arrives with its aliases already clustered.

```sql
CREATE TABLE command_candidate_phrase (
    id           INTEGER PRIMARY KEY,
    candidate_id INTEGER NOT NULL REFERENCES command_candidate(id) ON DELETE CASCADE,
    text         TEXT    NOT NULL,      -- normalized + filler-stripped
    hit_count    INTEGER NOT NULL DEFAULT 1,
    last_used_at TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (candidate_id, text)
);
```

### Altered: `command` — usage + provenance
All nullable / defaulted, so existing rows are unaffected.

```sql
ALTER TABLE command ADD COLUMN hit_count      INTEGER NOT NULL DEFAULT 0;
ALTER TABLE command ADD COLUMN last_used_at   TEXT;
ALTER TABLE command ADD COLUMN fail_count     INTEGER NOT NULL DEFAULT 0;  -- consecutive; reset on success
ALTER TABLE command ADD COLUMN learned_at     TEXT;
ALTER TABLE command ADD COLUMN learned_reason TEXT;  -- 'threshold' | 'explicit' | 'template'
```

### Altered: `phrase` — per-alias usage
Drives phrase eviction and near-duplicate merging ([02](02-aggregation.md)).

```sql
ALTER TABLE phrase ADD COLUMN hit_count    INTEGER NOT NULL DEFAULT 0;
ALTER TABLE phrase ADD COLUMN last_used_at TEXT;
ALTER TABLE phrase ADD COLUMN source       TEXT NOT NULL DEFAULT 'builtin';  -- builtin|user|learned
```

### Altered: `command_log` — the evidence trail
The table exists and is correctly shaped; it just needs the columns the learning decisions depend on.

```sql
ALTER TABLE command_log ADD COLUMN candidate_id INTEGER REFERENCES command_candidate(id) ON DELETE SET NULL;
ALTER TABLE command_log ADD COLUMN ambiguous    INTEGER NOT NULL DEFAULT 0;
ALTER TABLE command_log ADD COLUMN confidence   REAL;     -- STT confidence, for the never-learn gate
ALTER TABLE command_log ADD COLUMN negated      INTEGER NOT NULL DEFAULT 0;  -- negative signal followed
```

`init_schema()` gains an idempotent migration step (`PRAGMA table_info` → add what's missing), matching
how `build()` already treats seeding as idempotent.

## The write API — `command_store`

Everything below is **new public API**. Today the only writer is the private `_add_command()`, called
by `seed()`.

```python
def log_resolution(conn, *, heard, context_kind, context_value, command_id, intent, arg,
                   resolved_by, success, confidence=None, ambiguous=False) -> int:
    """Append one row to command_log. Called for EVERY resolution — deterministic, db and llm alike.
    Returns the log id so a later negative signal can flip `negated`."""

def mark_negated(conn, log_id) -> None:
    """A negative signal arrived within the window — flip the flag and decrement any candidate."""

def note_candidate(conn, *, context_id, intent, arg, phrase) -> dict:
    """Upsert a candidate for this action key, bump hit_count / distinct_days, cluster the phrase.
    Returns the candidate row (so the caller can check it against the promotion bar)."""

def promote(conn, candidate_id, *, reason="threshold") -> int:
    """Create a command (source='learned') from a candidate, with its clustered phrases.
    Enforces the per-context and global caps by evicting the lowest-scoring learned row.
    Returns the new command id."""

def attach_phrase(conn, command_id, phrase, *, source="learned") -> bool:
    """Add an alias to an EXISTING command, applying normalize → exact-dupe → near-dupe →
    subsumption → cap+evict (doc 02). Returns True if a new phrase row was written."""

def find_by_action(conn, context_id, intent, arg) -> dict | None:
    """The action-key lookup that makes variants collapse. THE most important function here —
    it is what stops a second command ever being created for an action that already exists."""

def note_usage(conn, command_id, phrase_id=None, *, success=True) -> None:
    """Bump hit_count / last_used_at on a command (and the phrase that matched); on failure bump
    fail_count and auto-demote at the threshold (F3)."""

def retire(conn, command_id, *, delete=False, block_days=0) -> None:
    """Demote (enabled=0) or delete a learned command; optionally block its action key from
    re-promotion ("forget that")."""

def decay(conn, *, now=None) -> dict:
    """Nightly housekeeping: demote/delete by age, drop stale candidates, trim command_log.
    Returns a summary for the log. Pure function of the clock, so it's testable."""
```

## New module: `vox/command_learn.py`

The policy layer. `command_store` stays a dumb data layer; **every judgment call lives here**, in one
file, so the rules are auditable in one place and unit-testable without a database.

```python
def observe(heard, resolution, *, app, confidence, log_id) -> None:
    """The single entry point, called after the executor acts. Applies the never-learn list, the
    arg-shape rules and the confidence gate; then either attaches a phrase to an existing command,
    or notes a candidate — and promotes if the bar is cleared and learning_mode allows."""

def is_learnable(intent, arg, confidence) -> tuple[bool, str]:
    """The gate from doc 01. Returns (ok, reason) — the reason is logged either way, so 'why didn't
    it learn that?' is always answerable."""

def clears_bar(candidate) -> tuple[bool, str]:
    """hits >= min_hits AND distinct_days >= min_days AND not blocked AND negatives under limit."""

def note_negative(kind) -> None:
    """Called by the loop when a negative signal fires within the window (doc 01)."""
```

## Wiring points

Small and few — the design deliberately keeps the blast radius of the *implementation* small too:

| Where | Change |
|---|---|
| `dispatch.py:88-104` | On a DB hit: `note_usage()` + `log_resolution(resolved_by='db')` |
| `dispatch.py` (parser hit) | `log_resolution(resolved_by='deterministic')` |
| `executor.py` (after a successful action) | `command_learn.observe(...)` — **the one new call that matters** |
| `core/loop.py` | Negative-signal watch: the utterance following an action, within the window |
| `core/loop.py` | "remember that" / "forget that" phrases → explicit promote/retire |
| `web/commands.py` + `server.py` | Candidates queue, approve/reject, learned-command evidence view |
| `scheduler.py` | Nightly `decay()` alongside #28's dream job |

## What the executor must return

The one genuine prerequisite. `command_learn.observe()` needs a **replayable action**, not prose — it
must know `(intent, arg)`, not just that "something worked".

Good news: the executor's contract already produces this. Its system prompt has the model emit a
command line (`open safari`, `click element X`), which goes through `actions.parse()`. So the shape is
already there — `executor.execute()` just needs to *return* the parsed `(intent, arg)` alongside its
message, instead of discarding it.

If `actions.parse()` can't parse what the model emitted, that resolution is **not learnable** — we
can't replay what we can't represent. That's a clean, honest boundary, and it means the learning layer
can never invent an action the deterministic layer couldn't have run itself.
