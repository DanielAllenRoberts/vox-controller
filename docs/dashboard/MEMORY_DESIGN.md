# Vox Memory — tiered Markdown design (v1)

> Human-readable, transparent, **tiered** memory the user can read and manage, that the
> assistant **auto-captures** into and **recalls** from without blowing the context window.
> Realises ideas #27 (Markdown storage), #28 (tiered + dream), #29 (auto-capture). v1 is a
> sensible first pass — the capture *rules* are meant to be tuned with the user. Build agents
> follow this exactly; additive + guarded, never break the voice daemon.

## Tiers & files (under `data/memory/`, gitignored, plaintext Markdown)

- **Core memories** — `data/memory/core.md`: a small, curated set of **durable, always-relevant**
  facts (name, standing preferences, ongoing projects, standing instructions). **Always injected**
  into the prompt. Keep it short and high-signal.
- **Daily memories** — `data/memory/daily/YYYY-MM-DD.md`: dated logs of what happened / was learned
  that day (contextual, transient). Appended through the day; recalled by relevance (today +
  keyword-matched recent days).
- *(Future #28: weekly/monthly/total rollups via a scheduled big-brain "dream" consolidation, and a
  navigable second brain — out of scope for v1, but the layout leaves room for it.)*

## Entry format (one per line, human-editable)

```
- [2026-06-18T09:12Z] (#prefs #vox) Prefers concise, spoken-style answers.
```
timestamp · optional `#tags` · text. A stable line-hash is the entry **id** (so the dashboard can
target edit/delete). `core.md` may use `##` section headers (e.g. `## Identity`, `## Preferences`,
`## Projects`) for readability.

## Capture rules (v1 — first assumption, to refine with the user)

The assistant decides **what** to keep and **where**:
- **Core (important):** durable facts about the user/their world — name, persistent preferences,
  long-term projects, standing instructions ("My name is Dan", "I prefer X", "I'm building Vox").
  Rare, high-signal.
- **Daily:** session/contextual events — what was done, one-off requests, transient notes
  ("Asked about the budget today", "switched to the Batman persona").
- **Mechanism:** the model may append a capture directive to its reply —
  `MEMORY[core]: <fact>` or `MEMORY[daily]: <note>` — which is parsed, stored, and **stripped before
  display/speech**. An explicit "remember that X" → core by default. A light filter skips trivial or
  duplicate lines.
- **Gated by a setting** `memory_autocapture` (toggle, default **on**, easily silenced).

## API — `src/vox/memory.py` (guarded, additive; migrate existing `data/memory.jsonl` into `core.md` once)

- `add(text, tier="daily", tags=[])` → entry dict
- `recall(query, k=5)` → **all core** + top-k relevant **daily** (for prompt injection)
- `core()` · `daily(date=None)` · `dates()` → for the dashboard
- `remove(id)` · `path_for(tier, date=None)` → on-disk path (for "open location")
- Back-compat: keep the old `add/recall/all/remove` shapes working so the existing callers and the
  dashboard don't break; `Memory` API objects still expose `{id, ts, text, tags, score?}` plus a new
  `tier`.

## Recall — `assistant.py` `_memory_block(user_text)` (guarded)

Inject **all core** memories (labelled "what you always remember about the user") + the top relevant
**daily** entries (keyword match). Guarded → empty string if the store is missing/broken (daemon
behaviour unchanged). Also tell the model, in the prompt, that it *can* remember things and the
core-vs-daily rule, so it uses the `MEMORY[...]` directive sensibly.

## Dashboard — Memory page redesign

- Two sections: **Core** (editable curated list) and **Daily logs** (browse by date).
- Add / edit / delete entries; a **toggle** for auto-capture (writes the `memory_autocapture` setting).
- An **"Open file location"** button → reveals `data/memory/` in Finder (bridge runs `open -R`).
- Show the on-disk path (transparency is the point — the user sees exactly what's kept).

## Dashboard — Integrations panel (MCP setup)

A small **Integrations** section/page that surfaces the **vox-speak** MCP (idea #34):
- Generates the editor config (`.cursor/mcp.json` block + the `claude mcp add` command) **for this
  machine** — the bridge fills in the real repo path at runtime via a `GET /api/mcp/config` endpoint.
- **Never commit personal paths** — committed docs use `/ABSOLUTE/PATH/TO/vox-controller`; the real
  path is only ever computed locally and shown in the UI.
- Copy buttons + an "open config location" affordance.

## New bridge endpoints (`server.py`, guarded)

- Memory: `GET /api/memory/core`, `GET /api/memory/daily?date=`, `GET /api/memory/dates`, plus the
  existing add/delete extended with `tier`; `POST /api/memory/reveal` → `open -R data/memory/`.
- `GET /api/mcp/config` → the vox-speak config block with this machine's absolute repo path.

## Out of scope for v1 (note as TODO)
The big-brain **"dream" consolidation** (dedupe, inconsistency-cleanup, weekly/monthly/total rollups,
the indexed navigable second brain) — that's #28, a later pass. v1 just lays the tiered Markdown
foundation + auto-capture + management UI.
