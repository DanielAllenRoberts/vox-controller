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
a = m.add('Daniel prefers the Arc browser and dark mode', tags=['preference','browser'])
m.add('Remember to calibrate the microphone RMS threshold', tags=['todo'])
assert m.recall('which browser does Daniel like')[0]['id'] == a['id']  # text overlap
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
