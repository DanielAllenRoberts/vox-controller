# Memory backends: is MemPalace the way? (2026-11-07)

**Verdict: no.** Keep the Markdown files as the source of truth and add a *rebuildable* search index
beside them. Memory is tiny today (about a dozen entries); what helps is better ranking, not a vector DB.
`memory._score()` is already the documented seam for this.

| Option | Storage | Local-only? | Deps / RAM | Transparency | Maturity | Fit |
|---|---|---|---|---|---|---|
| MemPalace | ChromaDB + SQLite knowledge graph | yes | chromadb, grpcio, 80–300 MB model | low | ~7 months old; several launch claims retracted in its own HISTORY.md | poor |
| Mem0 OSS | Qdrant + SQLite | possible (defaults to OpenAI) | Qdrant client + LLM per add | low | mature, Apache-2.0 | duplicates what Vox already does |
| Letta (MemGPT) | Postgres/SQLite server | yes | server owning the agent loop | medium | mature | poor |
| Graphiti (Zep) | Neo4j/FalkorDB/Neptune | yes | graph DB server, LLM-heavy ingest | low | active | poor (heavy) |
| basic-memory | Markdown + SQLite FTS + FastEmbed | yes | fastembed | high | active, **AGPL-3.0** | same design as ours; reference only (licence) |
| **SQLite FTS5 (BM25)** | stdlib sqlite3 index | yes | none | high (rebuilt from .md) | rock solid | **step 1** |
| + small embeddings (model2vec / fastembed bge-small) | vectors in the same SQLite | yes | ~30–130 MB | high | MIT/Apache | **step 2, gated on an eval** |
| sqlite-vec | SQLite extension | yes | tiny | high | pre-1.0 | only past ~50k entries |

## Path
1. FTS5 index `data/memory/index.sqlite`, keyed by the entry id, rebuilt when a file's mtime changes;
   BM25 + porter stemming in `_score()`, keep the tag boost and recency tiebreak, Markdown scan as fallback.
2. A 30–50 item eval (question → expected memory) with recall@5 for keyword vs FTS5 vs hybrid.
3. Embeddings only if FTS5 misses paraphrases; lazy-loaded, behind a setting, 70/30 hybrid.
4. Topic folders (`memory/topics/<topic>.md`) filed by the overnight tidy (#28).

Sources: github.com/MemPalace/mempalace (incl. docs/HISTORY.md), docs.mem0.ai, github.com/letta-ai/letta,
github.com/getzep/graphiti, github.com/basicmachines-co/basic-memory, github.com/asg017/sqlite-vec,
github.com/qdrant/fastembed, pypi.org/project/model2vec.
