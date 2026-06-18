# Research — tiered agent memory (sanity-check of MEMORY_DESIGN.md v1)

> Inputs: web research on **OpenClaw** (open-source agent) + general LLM agent-memory
> literature (MIRIX, MemGPT/Letta-style core memory, the 2026 "Memory for Autonomous LLM
> Agents" survey). Goal: validate and lightly improve `docs/dashboard/MEMORY_DESIGN.md`
> (the v1 contract). This doc is **advisory** — it does not change the contract by itself.
> Build agents should treat the "Concrete tweaks" section as proposed deltas to the v1 design,
> all additive and guarded; the voice daemon must run unchanged if memory/web is missing.

## 1. What OpenClaw actually does (and how it maps to v1)

OpenClaw's memory is strikingly close to our v1 design — same instincts, a few extra moves
worth borrowing.

| OpenClaw | Vox v1 (MEMORY_DESIGN.md) | Verdict |
|---|---|---|
| `MEMORY.md` — durable facts/preferences/decisions, **always loaded** | `core.md` — always injected | Same idea. Good. |
| `memory/YYYY-MM-DD.md` daily notes; **today + yesterday auto-loaded**, older via search | `daily/YYYY-MM-DD.md`; recall = today + keyword-matched recent | Same. v1 should pin "today + yesterday always-load" explicitly (see tweaks). |
| Plain Markdown is the **source of truth**; "if it's not on disk it doesn't exist" | Plaintext Markdown, user-editable, transparent | Same philosophy. Strong match. |
| Storage backend is **SQLite (default)** providing keyword + vector search **as an index over the Markdown** | Keyword scoring now, "pluggable for embeddings" | Key nuance: SQLite is an *index*, not the store. Markdown stays canonical. See §2. |
| `memory_search` (hybrid: vector + keyword) and `memory_get` (file/line range) | `recall(query,k)` keyword now | Aligned; v1's pluggable note covers the upgrade path. |
| **Pre-compaction memory flush**: before context summarization, a silent turn writes important context to today's note | (not in v1) | Worth a lightweight analog. See tweaks. |
| **Dreaming**: opt-in, scheduled cron, scores candidates (recall frequency, query diversity, score gates), promotes high-signal items to `MEMORY.md`, logs to `DREAMS.md` | "dream" consolidation explicitly **out of scope for v1** (#28) | v1 is right to defer it; capture the design so v1 leaves room. See §4. |
| `MEMORY.md` **kept closed in group/shared chats** (privacy boundary) | (single-user local) | Not relevant to single-user Vox; note for future multi-context. |

**Headline:** v1 is well-aligned with a battle-tested public design. The main gaps are (a)
being explicit that SQLite, if used, is an *index over* canonical Markdown — not a replacement;
(b) pinning the always-load window (today+yesterday); (c) a small pre-compaction/flush analog;
(d) writing down the dream-pass contract now so the v1 layout doesn't paint us into a corner.

## 2. Markdown vs SQLite — the resolved answer

Both OpenClaw and the general literature converge on the same split, and it matches our public-repo
transparency goal:

- **Canonical store = Markdown.** Human-readable, user-editable, Git-friendly, no lock-in, and
  the thing the dashboard "Open file location" button reveals. The user can read and trust exactly
  what's kept. This is a product feature, not just an implementation detail — keep it.
- **SQLite (or any vector store) = an optional, rebuildable *index*** over that Markdown for fast
  keyword/semantic recall at scale. It must be **derivable** from the Markdown (drop the DB, re-scan
  the `.md` files, rebuild). If the index is missing or stale, recall **degrades to a Markdown scan**,
  never errors.

For v1's scale (one user, tens-to-hundreds of daily entries) a plain **keyword scan of Markdown is
entirely sufficient** — no SQLite, no embeddings needed yet. v1's "keyword scoring now, pluggable for
embeddings" is the correct call. The only doc tweak is to state the invariant: **Markdown is canonical;
any future SQLite/vector layer is a rebuildable index and recall must fall back to a scan.**

OpenClaw's default hybrid weighting (≈70% semantic / 30% keyword) is a useful reference for *if/when*
we add embeddings, but it is explicitly **post-v1**.

## 3. Tiered memory — core vs daily/episodic (literature view)

The agent-memory literature (MIRIX, MemGPT/Letta, the 2026 survey) frames the same two tiers in
standard terms, which sharpens our capture rules:

- **Core memory** = high-priority, **always-in-context** facts. Split conceptually into a *persona*
  block (the assistant's identity/tone — in Vox this is the **personality** system, already separate)
  and a *human* block (durable facts about the user). Our `core.md` is the human block. Keep it
  **small and high-signal** — the literature and OpenClaw both stress this is a *cheat sheet, not a
  journal*. OpenClaw's practical rule of thumb: **keep core under ~100 lines.**
- **Episodic memory** = time-stamped events with recency/importance — exactly our `daily/` logs.
  These are transient and contextual; they are the **raw material** that consolidation later distills
  into durable (semantic/core) facts.
- **Semantic memory** = consolidated, deduped general knowledge ("user prefers DD/MM/YYYY", derived
  from three episodic corrections). In v1 this doesn't get its own tier — consolidated facts simply
  get **promoted into `core.md`**. That's the right simplification for v1; the dream pass (#28) is the
  machinery that does the promotion later.

**Good vs bad core entries** (borrow into the dashboard help text and the model's capture prompt):
- Good: durable preferences with rationale, standing instructions ("always X / never Y"), long-term
  projects, corrections learned after a mistake.
- Bad / belongs in daily instead: raw logs, one-off requests, transient meeting notes, anything that
  loses relevance in a week, duplicates of what's already stored, and **anything secret** (tokens,
  keys — plaintext, public-repo-adjacent).

This is consistent with v1's capture rules; the tweak is to make the **good/bad heuristics explicit**
in the prompt and dashboard so the model and user converge on a clean `core.md`.

## 4. Consolidation / "dream" pass — design to leave room for (still post-v1)

v1 correctly defers this, but here is the concrete contract so the v1 layout doesn't block it:

- **Trigger:** opt-in, **scheduled** (cron/idle), big-brain. Never on the hot path of a reply.
  Default **off**. (OpenClaw ships it disabled by default.)
- **Inputs:** recent `daily/*.md` entries (a sliding window, e.g. last N days) + current `core.md`.
- **Scoring → promotion:** promote a daily signal to core only if it clears gates — **recurrence**
  (seen across multiple days), **recall frequency** (actually retrieved in conversations), and a
  significance score. Avoids promoting noise.
- **Operations:** dedupe core, resolve contradictions (newer/most-recurrent wins), and write
  **weekly/monthly/total rollups** (idea #28's "navigable second brain").
- **Auditability:** write what it did to a review log (OpenClaw uses `DREAMS.md`). For Vox, a
  `data/memory/dream-log.md` keeps the same transparency the rest of the system has, and the dashboard
  can surface "what the last consolidation changed."
- **Layout implication for v1:** the chosen directory layout already supports this
  (`core.md` + `daily/` leaves room for `weekly/`, `monthly/`, a `dream-log.md`). **No v1 change needed**
  beyond reserving those names. Just don't hardcode "only core.md + daily/ exist" anywhere brittle.

## 5. Concrete tweaks proposed for the v1 design (additive, low-risk)

All optional; none change the v1 API surface in a breaking way. Ordered by value.

1. **Pin the always-load window.** Recall should always inject **all of core + today + yesterday's
   daily**, *then* add keyword-matched older days up to `k`. v1 says "today + keyword-matched recent";
   making "yesterday" an unconditional include matches OpenClaw and gives better continuity across a
   day boundary (esp. with the existing 4am-style fresh-session behavior). One-line change to
   `_memory_block` semantics.

2. **State the canonical-store invariant.** Add one line to the API section:
   "Markdown is the canonical store; any future SQLite/vector layer is a **rebuildable index**, and
   recall must fall back to a plain Markdown scan if the index is missing or broken." Protects the
   daemon-never-breaks guarantee and the transparency promise.

3. **Lightweight capture-on-exit / flush analog (optional for v1).** OpenClaw flushes salient context
   to the daily note before compaction. Vox has no long rolling context to compact, but the cheap analog
   is: when a session/dictation ends, allow one **guarded** best-effort `MEMORY[daily]` summary if the
   model emitted one. This is already possible via the existing directive mechanism — just **document it
   as the intended pattern** rather than building new machinery. Must be fully guarded (never blocks the
   reply/exit).

4. **Bake the good/bad heuristics into the prompt + dashboard help.** Add the §3 good/bad lists to the
   capture instructions the model sees and to the Memory page help text, plus an explicit
   **"never store secrets"** line (public-repo hygiene). Tightens what lands in `core.md`.

5. **Soft size hint for core.** Adopt OpenClaw's "core is a cheat sheet, keep it short" guidance.
   Optional, non-enforcing: the dashboard can show a gentle "core is getting long, consider
   consolidating" hint past a threshold (e.g. ~100 lines / ~2k tokens). No hard cap in v1 — just surface
   it. This is the seam where the future dream pass plugs in.

6. **Reserve consolidation file names now.** Note in the layout that `weekly/`, `monthly/`,
   `dream-log.md` under `data/memory/` are reserved for #28 so nothing else claims them. Pure
   documentation; no code.

## 6. What NOT to do in v1 (explicit non-goals, confirmed by research)

- **No embeddings / vector DB yet.** Keyword scan over Markdown is sufficient at single-user scale; the
  literature only needs vectors at large archive sizes. Keep the interface pluggable (already in v1).
- **No SQLite yet.** Adds a dependency and a sync-with-Markdown burden for no v1 benefit (favor zero new heavy deps).
- **No automated dream pass yet.** Correctly deferred to #28. Just leave room (§4).
- **No multi-context privacy gating** (OpenClaw's group-chat MEMORY.md closing) — Vox is single-user
  local; irrelevant for v1.

## Sources

- [OpenClaw — Memory overview (docs)](https://docs.openclaw.ai/concepts/memory)
- [OpenClaw Memory Architecture — Daily Notes and Long-Term Memory (zenvanriel)](https://zenvanriel.com/ai-engineer-blog/openclaw-memory-architecture-guide/)
- [OpenClaw Memory Masterclass (VelvetShark)](https://velvetshark.com/openclaw-memory-masterclass)
- [We Extracted OpenClaw's Memory System (memsearch) — Milvus](https://milvus.io/blog/we-extracted-openclaws-memory-system-and-opensourced-it-memsearch.md)
- [Memory for Autonomous LLM Agents: Mechanisms, Evaluation, and Emerging Frontiers (arXiv 2603.07670)](https://arxiv.org/html/2603.07670v1)
- [MIRIX: Multi-Agent Memory System for LLM-Based Agents (arXiv 2507.07957)](https://arxiv.org/pdf/2507.07957)
- [Types of AI Agent Memory: Episodic, Semantic, Procedural (Atlan)](https://atlan.com/know/types-of-ai-agent-memory/)
