# Memory System — Research & Minimal Design (Iteration 1)

> Foundation doc for `src/vox/memory.py`. Defines the minimal, runnable memory
> store for the Vox voice assistant + dashboard, inspired by OpenClaw and Hermes,
> and grounded in standard agent-memory patterns. Follows `../CONTRACT.md`
> exactly (signatures, JSONL path, `Memory` shape). Keyword scoring now;
> embeddings pluggable later.

Status: **skeleton shipped** (`add` / `recall` / `all` / `remove`, JSONL store,
keyword scorer). Wiring into the daemon + dashboard API lands in iteration 6.

---

## 1. What we studied

### OpenClaw (open source) — `memsearch` / MemTier
- **Two tiers.** *Episodic* = append-only dated logs (running notes/observations,
  read at session start); *semantic* = a curated long-term `MEMORY.md` of stable
  facts/preferences/decisions. An async **consolidation** daemon promotes recurring
  episodic facts up to the semantic tier.
- **Storage = plain files on the local filesystem** (Markdown logs `YYYY-MM-DD.md`
  + `MEMORY.md`, or structured **JSONL** per day in the MemTier variant). The point
  is the same: transparent, hand-editable, git-diffable, dependency-light.
- **Hybrid retrieval.** A `memory_search` tool ranks chunks with **~70% vector +
  ~30% BM25 keyword** weighting — vectors catch paraphrase, BM25 keeps exact tokens
  (versions, error codes) precise. Returns top-K (default 3), truncated (~200 chars).
- **Add/forget are file ops.** Add = append/write; "forget" = delete/edit the file
  and the index rebuilds. No heavyweight CRUD API.

### Hermes Agent — layered, file-backed, always-on
- **Layered & bounded.** Compact always-on facts in `MEMORY.md` (agent notes,
  hard cap ~2,200 chars) + `USER.md` (user profile, ~1,375 chars), full transcripts
  in **session search** (local **SQLite + FTS5** full-text), and one optional
  external semantic/graph provider.
- **Core philosophy:** *memory is not just retrieved on demand — the compact layer
  is always injected into the system prompt.* It stays "transparent, local, and
  inspectable." Bounded size is a feature: it forces curation over hoarding.

### General agent-memory patterns (background knowledge)
- **Episodic vs semantic.** Episodic = time-stamped events ("on 6/17 the mic RMS
  was recalibrated"). Semantic = distilled durable facts ("user prefers Arc + dark
  mode"). Episodic is cheap to append; semantic is curated/consolidated.
- **Keyword vs embedding recall.** Keyword (token overlap / BM25 / FTS5) is exact,
  cheap, zero-dependency, fully explainable — great for a small local store and for
  precise tokens. Embeddings add paraphrase/semantic recall at the cost of a model,
  vectors, and an index. Hybrid (both, weighted) is the production sweet spot once
  the corpus is large enough to need it.
- **When to inject into the prompt.** Two complementary strategies: (a) **always-on**
  — a tiny bounded set of high-value facts in the system prompt every turn (Hermes);
  (b) **on-demand recall** — fetch top-K relevant memories for *this* turn and inject
  them (OpenClaw `memory_search`, classic RAG). Inject sparingly: few items, short,
  clearly delimited, only when score clears a threshold — irrelevant memories hurt
  more than they help.

---

## 2. Design decisions for Vox (and why minimal)

This is a **local-first, single-user, voice** assistant on one Mac. The corpus will
be tens-to-hundreds of short notes, not a knowledge base. So we deliberately start
at the simplest point that satisfies the contract and can grow:

| Decision | Choice | Rationale |
|---|---|---|
| Store format | **One flat `data/memory.jsonl`** (one record per line) | Contract mandates JSONL under `data/` (gitignored). Append-only writes, line-diffable, no DB dependency. Matches OpenClaw/Hermes "plain inspectable files" ethos. |
| Episodic vs semantic | **One flat episodic log now**, `tags` carry intent (`preference`, `todo`, `config`, …) | Two physical tiers + a consolidation daemon is iteration-6+ scope. Tags give us semantic *labels* without a second store; a future consolidator can read these. |
| Recall | **Transparent keyword scorer** (token overlap + tag boost + recency tiebreak) | Cheap, explainable, zero new deps, fits a small corpus, and surfaces a `score` the dashboard can show. The contract's `Memory.score?` is exactly this. |
| Embeddings | **Deferred, behind a single seam** (`_score`) | `recall()` calls one private `_score(query, record)`. Swap it for an embedding/hybrid ranker later with **no change** to the public API or the on-disk format. |
| Bounded / always-on layer | **Not yet** (no prompt injection in iter 1) | Iteration 1 is foundation. Prompt injection + an always-on "pinned facts" subset (Hermes-style) is a later iteration; the `tags` field already lets us mark `pinned`. |
| Concurrency | **Process-wide `RLock`** | The voice daemon and the FastAPI thread can both touch the store; the lock prevents interleaved partial writes. |
| Robustness | **Skip corrupt/blank JSONL lines** on read | A single bad line must never crash the always-running daemon. |

### Why keyword-first is the right call now
With a tiny single-user corpus, embeddings add a model download, a vector index, and
opaque ranking for marginal recall gains. Keyword overlap with a **tag boost** (a
deliberate signal the user/assistant sets) plus a **recency tiebreak** covers the real
use cases — "what browser do I like", "what are my todos", "what did we configure" —
while staying instant and fully explainable. We upgrade to hybrid only when recall
actually misses, and the seam makes that a one-function change.

---

## 3. The contract surface (implemented in `src/vox/memory.py`)

Path & shape are fixed by `../CONTRACT.md`:

- Persists **`data/memory.jsonl`**; on-disk record: `{id, ts, text, tags}`.
- `Memory` (API/TS shape) = `{id, ts, text, tags: string[], score?}` — `score` is
  attached **only** by `recall()`.

```python
add(text: str, tags: list[str] | None = None) -> dict
    # appends one record, returns {id, ts, text, tags}

recall(query: str, k: int = 5) -> list[dict]
    # up to k best matches, each with a `score`; empty query -> k most recent (score 0.0)

all() -> list[dict]
    # every memory, newest first (no score)

remove(id: str) -> bool
    # deletes by id; True if something was removed
```

`id` = 12-hex from `uuid4`. `ts` = epoch seconds (float). The dashboard's
`GET /api/memory?query=&limit=` maps to `recall(query, k=limit)` (or `all()` when no
query); `POST /api/memory {text, tags?}` → `add`; `DELETE /api/memory/{id}` → `remove`.

### Scoring (current `_score`)
For a query and a record: `+1` per query token found in the record text (counting
repeats), `+2` when a query token equals one of the record's tags, and a small
recency bonus (`+~0.5` for the newest, decaying over ~30 days) as a tiebreak. Score
`<= 0` means "no match" and the record is dropped from results. This is intentionally
legible so the Memory page can explain *why* a memory surfaced.

---

## 4. How to verify (this iteration)

The module is self-contained and dependency-free. Quick check (uses a temp store so
no runtime data is written into `data/`):

```bash
python3 - <<'PY'
import importlib.util, tempfile, pathlib, shutil
spec = importlib.util.spec_from_file_location('vox.memory', 'src/vox/memory.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
d = pathlib.Path(tempfile.mkdtemp()); m._DATA_DIR = d; m._STORE = d / 'memory.jsonl'
a = m.add('Daniel prefers the Arc browser and dark mode', tags=['preference','browser'])
m.add('Remember to calibrate the microphone RMS threshold', tags=['todo'])
assert m.recall('which browser does Daniel like')[0]['id'] == a['id']   # text overlap
assert m.recall('todo')[0]['tags'] == ['todo']                          # tag boost
assert m.recall('')[0]['score'] == 0.0                                  # empty -> recent
assert m.remove(a['id']) is True and m.remove('nope') is False          # remove
print('memory.py OK'); shutil.rmtree(d)
PY
```

Expected: `memory.py OK`. (All four behaviors are covered.)

It is **additive**: nothing imports `memory.py` yet, so the existing voice daemon is
unaffected whether or not the dashboard is present.

---

## 5. TODOs for later iterations

- **Iteration 6 (Rules & Memory):** wire `GET/POST/DELETE /api/memory` in
  `src/vox/web/` to `recall`/`add`/`remove`; build the **Memory** page (search box,
  tag chips, score display, add/delete). Match `Memory` TS type in `lib/api.ts`.
- **Prompt injection (Hermes-style):** on a chat/command turn, `recall(utterance, k=3)`
  above a score threshold and inject a short, delimited "Relevant memory:" block into
  the brain prompt in `assistant.py`. Add an always-on **pinned** subset (filter
  `tags` containing `pinned`) for stable facts. Keep it bounded (few short items).
- **Auto-capture:** let the assistant call `add()` itself when the user says
  "remember that …" (deterministic phrase) or when the brain flags a durable fact.
- **Semantic tier / consolidation (OpenClaw-style):** optional background pass that
  dedupes and promotes recurring episodic notes into curated facts.
- **Embeddings / hybrid recall:** when keyword recall starts missing paraphrases,
  replace `_score` with an embedding cosine or a BM25+vector hybrid (e.g. ~70/30),
  guarded by a config flag and a lazy model load. **No API or on-disk change needed** —
  that's the whole point of the seam.
- **Bounding / GC:** optional cap on store size or age-based pruning if the log grows.

---

## Sources
- [We Extracted OpenClaw's Memory System and Open-Sourced It (memsearch) — Milvus](https://milvus.io/blog/we-extracted-openclaws-memory-system-and-opensourced-it-memsearch.md)
- [MemTier: Tiered Memory Architecture … in Long-Running LLM Agents (arXiv)](https://arxiv.org/html/2605.03675v3)
- [How Hermes Agent Memory Works — 3-Layer System Explained](https://hermes-agent.ai/blog/hermes-agent-memory-system)
- [How Hermes Agent Memory Actually Works (And How to Make It Better) — Vectorize](https://vectorize.io/articles/hermes-agent-memory-explained)
- [Hermes Agent Memory System — Rost Glukhov](https://www.glukhov.org/ai-systems/hermes/hermes-agent-memory-system/)
- [Memory Providers | Hermes Agent — Nous Research](https://hermes-agent.nousresearch.com/docs/user-guide/features/memory-providers)

> Web search was available and used for the OpenClaw/Hermes material above;
> general episodic/semantic and keyword-vs-embedding patterns draw on standard
> agent-memory practice.
