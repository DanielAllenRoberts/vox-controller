# Memory Store (`src/vox/memory.py`)

> Iteration 5 — the **memory agent** owns `src/vox/memory.py` only. A local-first,
> dependency-free memory store for the voice assistant + dashboard. Follows
> `docs/dashboard/CONTRACT.md` exactly (JSONL path, `Memory` shape, signatures).
> Keyword scoring now; embeddings slot in later behind one seam. The design
> research lives in `research/memory.md`; this is the concise area reference.

## Files touched

| File | Change |
|------|--------|
| `src/vox/memory.py` | Owns the store. `add` / `recall` / `all` / `remove`, JSONL persistence, pluggable keyword scorer. Self-contained and guarded. |
| `docs/dashboard/memory.md` | This doc. |

Nothing else is edited. The module is **additive**: no existing code imports it
yet, so the voice daemon is unaffected whether or not the dashboard is present.
Wiring into the bridge (`GET/POST/DELETE /api/memory`) and the Memory page lands
in a later iteration (see TODOs).

## Public API (CONTRACT)

```python
add(text: str, tags: list[str] | None = None) -> dict
    # append one record; returns {id, ts, text, tags}

recall(query: str, k: int = 5) -> list[dict]
    # up to k best matches, each carrying a `score`;
    # empty/whitespace query -> k most recent (score 0.0)

all() -> list[dict]
    # every memory, newest first (no score)

remove(id: str) -> bool
    # delete by id; True iff a record was removed
```

- `id` = 12-hex slice of `uuid4`. `ts` = epoch seconds (float).
- On-disk record: `{id, ts, text, tags}`. The `Memory` API/TS shape adds the
  optional `score?`, attached **only** by `recall()`.

### Dashboard route mapping (for the later bridge iteration)
- `GET /api/memory?query=&limit=` → `recall(query, k=limit)` when `query` is set,
  else `all()` (truncate to `limit`).
- `POST /api/memory {text, tags?}` → `add(text, tags)`.
- `DELETE /api/memory/{id}` → `remove(id)`.

## Storage

- One flat **`data/memory.jsonl`** (one JSON record per line), under the gitignored
  `data/` runtime dir. Resolved relative to the repo root (`parents[2]`).
- **Append-only** writes for `add` (cheap, line-diffable); `remove` rewrites the
  whole file via a `.tmp` + atomic `replace`. Inspectable and hand-editable —
  the same "plain local files" ethos as OpenClaw / Hermes.

## Scoring (the pluggable seam)

`recall()` ranks every record through one private `_score(query, record) -> float`.
That function is the **only** thing an embedding/hybrid ranker needs to replace —
no change to the public API or the on-disk format.

Current keyword signals (deliberately legible so the Memory page can explain *why*
a memory surfaced):

- **+1 per query token** found in the record text (counting repeats; TF-style).
- **+2** when a query token equals one of the record's `tags` (a strong,
  intentional signal the user/assistant sets).
- **+~0.5 recency tiebreak**, decaying over ~30 days, so fresher memories edge out
  stale ones at equal overlap.

Tokens are lowercased `[a-z0-9]+` with a small stopword list removed. A total
score `<= 0` means "no match" and the record is dropped from results.

## Robustness / guards

- **Process-wide `RLock`** — the voice daemon thread and the FastAPI thread can
  both touch the store; the lock prevents interleaved partial writes.
- **Corrupt/blank JSONL lines are skipped** on read, so a single bad line can never
  crash the always-running daemon.
- No third-party deps; pure stdlib (`json`, `re`, `threading`, `time`, `uuid`).

## How to verify

Self-contained, dependency-free. The snippet points the module at a temp store so
nothing is written into `data/`:

```bash
python3 - <<'PY'
import importlib.util, tempfile, pathlib, shutil
spec = importlib.util.spec_from_file_location('vox.memory', 'src/vox/memory.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
d = pathlib.Path(tempfile.mkdtemp()); m._DATA_DIR = d; m._STORE = d / 'memory.jsonl'
a = m.add('Alex prefers the Arc browser and dark mode', tags=['preference','browser'])
m.add('Remember to calibrate the microphone RMS threshold', tags=['todo'])
assert m.recall('which browser does Alex like')[0]['id'] == a['id']  # text overlap
assert m.recall('todo')[0]['tags'] == ['todo']                         # tag boost
assert m.recall('')[0]['score'] == 0.0                                 # empty -> recent
assert m.recall('xyzzy nonexistent') == []                             # no match dropped
assert m.remove(a['id']) is True and m.remove('nope') is False         # remove
print('memory.py OK'); shutil.rmtree(d)
PY
```

Expected: `memory.py OK`.

## TODOs (later iterations)

- **Bridge + page:** wire `GET/POST/DELETE /api/memory` in `src/vox/web/` and build
  the Memory page (search box, tag chips, score display, add/delete). Match the
  `Memory` TS type in `dashboard/src/lib/api.ts`.
- **Prompt injection (Hermes-style):** on a chat/command turn, `recall(utterance, k=3)`
  above a score threshold and inject a short, delimited "Relevant memory:" block in
  `assistant.py`; add an always-on **pinned** subset (`tags` contains `pinned`).
- **Auto-capture:** let the assistant `add()` on a "remember that …" phrase.
- **Embeddings / hybrid recall:** replace `_score` with an embedding cosine or
  BM25+vector hybrid when keyword recall starts missing paraphrases — **no API or
  on-disk change needed** (that's the seam).
- **Bounding / GC:** optional size/age-based pruning if the log grows.

---

# Memory Store — v2: tiered Markdown (`src/vox/memory.py`)

> **Supersedes the JSONL design above.** `src/vox/memory.py` was redesigned to the
> tiered Markdown store in `MEMORY_DESIGN.md` (v1 of *that* design). The sections
> above are retained for history; this section is the current source of truth for the
> module. Same ownership rule: the memory agent owns `src/vox/memory.py` **only**.
> Design research: `research/memory-tiered.md`.

## What changed

- **Two tiers, both plaintext Markdown** under the gitignored `data/memory/`:
  - **Core** — `data/memory/core.md`: durable, always-relevant facts. **Always
    injected** by `recall()`. May use `##` section headers (skipped on parse).
  - **Daily** — `data/memory/daily/YYYY-MM-DD.md`: dated episodic logs. Recalled by
    relevance (today + yesterday always, then keyword-matched older days).
- **Entries are human-editable Markdown bullets**, one per line:
  ```
  - [2026-06-18T09:12Z] (#prefs #vox) Prefers concise, spoken-style answers.
  ```
  timestamp · optional `#tags` · text. The user can read/hand-edit the files; the
  dashboard "open file location" button reveals them.
- **`id` is a stable line-hash** (`sha1(tier + raw line)[:12]`) — survives edits to
  *other* lines and reordering, so the dashboard can target edit/delete reliably.
- **One-time JSONL migration:** any legacy `data/memory.jsonl` is folded into
  `core.md` once (legacy memories were durable, curated facts), guarded by a
  `data/memory/.migrated-jsonl` marker. Idempotent; the JSONL is then ignored.

## Public API (additive + back-compatible)

```python
add(text, tier="daily", tags=None) -> dict   # append a bullet; returns the entry
recall(query, k=5) -> list[dict]             # ALL core + top-k relevant daily
core() -> list[dict]                         # all core entries (dashboard)
daily(date=None) -> list[dict]               # one day's entries (default today)
dates() -> list[str]                         # all dated logs, newest first
remove(id) -> bool                           # delete by line-hash id
path_for(tier, date=None) -> str             # on-disk path (open-location button)
all() -> list[dict]                          # BACK-COMPAT: core + all daily, newest first
```

Every entry object is `{id, ts, text, tags, tier}` (+ `score` on `recall`/`all` is
only on `recall`). `ts` is now an **ISO-8601 string** (matches the rest of the
dashboard contract); `_ts_seconds` still tolerates the old float-epoch.

### Back-compat shims (so existing callers / the dashboard don't break)
- **`add(text, ["#tag"])`** — the *old* signature passed a list as the 2nd
  positional arg. If `tier` is a list/tuple it's treated as `tags` and the entry
  goes to `daily` (old default). The dashboard `POST /api/memory` (`add(text, tags)`)
  keeps working unchanged.
- **`all()`** is retained and returns core + every daily entry, newest first — what
  the existing `GET /api/memory` list view calls.
- Entry shape is a superset of the old `{id, ts, text, tags}` (adds `tier`), so
  legacy readers are unaffected.

### Dashboard route mapping (for the bridge agent, additive)
- `GET /api/memory/core` → `core()`
- `GET /api/memory/daily?date=` → `daily(date)`
- `GET /api/memory/dates` → `dates()`
- `POST /api/memory {text, tier?, tags?}` → `add(text, tier, tags)` (old
  `{text, tags}` still works via the shim)
- `DELETE /api/memory/{id}` → `remove(id)`
- `POST /api/memory/reveal` → run `open -R` on `path_for(...)`
- existing `GET /api/memory?query=&limit=` keeps working via `recall`/`all`.

## Recall semantics

`recall(query, k)` returns **all core first** (file order, `score` 0.0), then the
selected **daily** entries:
- **today + yesterday** are *always* included (continuity across a day boundary),
  ordered newest-first;
- then **keyword-matched older days**, ranked by `_score`;
- capped at `k` daily entries total. Empty query → core + `k` most recent daily.

This pins the always-load window per the research tweak (matches OpenClaw's
"today + yesterday auto-loaded, older via search").

## Scoring (unchanged seam)

The keyword `_score(query_tokens, entry)` is unchanged in spirit (+1/token overlap,
+2 tag hit, ~+0.5 recency tiebreak) and is still the **only** function an
embedding/hybrid ranker must replace. Markdown stays canonical; any future
SQLite/vector layer is a *rebuildable index* and recall must fall back to a scan.

## Robustness / guards

- **Canonical-store invariant — reads never raise.** Every read path
  (`core`/`daily`/`dates`/`recall`/`all`/`remove`/parse) is wrapped so a missing or
  corrupt file yields an empty result, never an exception. The voice daemon's
  guarded `_memory_block` therefore degrades to "no memories", never breaks a reply.
- **Process-wide `RLock`** — voice thread + FastAPI thread never interleave writes.
- **Writes are best-effort** — a write failure is swallowed (the caller still gets
  its entry dict back); it never crashes the daemon.
- Pure stdlib (`hashlib`, `json`, `re`, `threading`, `time`, `datetime`, `pathlib`).

## How to verify

```bash
python3 - <<'PY'
import sys; sys.path.insert(0, 'src')
from vox import memory as m
e = m.add('I prefer concise spoken answers', tier='core', tags=['prefs'])
d = m.add('Asked about the budget today', tier='daily', tags=['work'])
assert e['tier'] == 'core' and d['tier'] == 'daily'
assert m.add('legacy note', ['legacy'])['tier'] == 'daily'      # positional-tags shim
r = m.recall('budget')
assert any(x['tier'] == 'core' for x in r)                       # core always injected
assert any('budget' in x['text'] for x in r)
assert m.path_for('core').endswith('core.md')
assert m.remove(d['id']) and not m.remove('deadbeef')
print('memory v2 OK')
PY
```

Note: this writes into the real `data/memory/`. The migration of an existing
`data/memory.jsonl` runs automatically and idempotently on first use.

## TODOs (post-v1)
- **Bridge + page redesign** (bridge agent): the new `/api/memory/*` endpoints, the
  Core/Daily two-section Memory page, the auto-capture toggle, and "open location".
- **Auto-capture / recall in the prompt** (assistant agent): parse `MEMORY[core|daily]`
  directives, inject `recall()` into the system prompt; both fully guarded.
- **Dream/consolidation pass (#28):** scheduled big-brain dedupe + promotion of
  recurrent daily signals into core, with `weekly/`/`monthly/`/`dream-log.md` rollups
  (names reserved, not yet created). Embeddings/hybrid recall only at larger scale.
