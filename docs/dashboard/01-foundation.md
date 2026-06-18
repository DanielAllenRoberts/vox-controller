# Iteration 1 — Foundation

> What the first iteration of the Vox Control Center dashboard actually built, how to
> run it, the API it exposes, and what's deliberately stubbed. This is the orientation
> doc; the per-area deep dives are [`backend.md`](./backend.md),
> [`integration.md`](./integration.md), and [`frontend.md`](./frontend.md). The build
> rules everyone follows are in [`CONTRACT.md`](./CONTRACT.md).

Iteration 1 delivers a **runnable end-to-end skeleton**: the voice daemon hosts a
FastAPI bridge, the bridge serves a Vite/React dashboard, and a wake phrase
("open dashboard") opens it. Everything is additive and guarded — the macOS voice
daemon runs exactly as before even if the whole `vox.web` package is missing.

## Architecture

Three pieces, one process for the daemon-hosted path:

```
                  wake: "open dashboard"  ──►  webbrowser.open(http://127.0.0.1:8765)
                          │
  ┌───────────────────────┴───────────────────────────────────────────┐
  │  Voice daemon (existing)                                           │
  │    core/loop.py ── on startup ──► vox.web.server.start_in_background(cfg)
  │    assistant.py ── after each LLM call ──► vox.web.usage.record_usage(...)
  │    assistant.py ── brain provider/model ──► vox.web.settings_store.get(key)
  └───────────────────────┬───────────────────────────────────────────┘
                          │  daemon thread (uvicorn)
  ┌───────────────────────┴───────────────────────────────────────────┐
  │  FastAPI bridge  (src/vox/web/)                                    │
  │    server.py         REST /api/*  +  WS /api/usage/stream          │
  │    usage.py          UsageEvent ledger (data/usage.jsonl) + WS fan-out
  │    settings_store.py override layer over Config (data/settings.json)
  │    axtree.py         read-only macOS AX snapshot                   │
  │    serves dashboard/dist at /  (SPA fallback)                      │
  └───────────────────────┬───────────────────────────────────────────┘
                          │  HTTP /api + WS  (Vite proxies in dev)
  ┌───────────────────────┴───────────────────────────────────────────┐
  │  Frontend  (dashboard/)  Vite + React 18 + TS + Tailwind          │
  │    shadcn/ui + Animate UI, react-query, recharts                  │
  │    AppShell → SideNav + TopBar → 7 pages                          │
  │    Overview = live /api/status;  6 others = titled placeholders   │
  └───────────────────────────────────────────────────────────────────┘
```

**Two ways the backend runs.** In production the daemon starts it automatically on a
daemon thread (`start_in_background`). For frontend dev you run it standalone
(`python -m vox.web.server`) and point Vite's `/api` proxy at it. Either way it binds
`127.0.0.1:8765` by default.

**Guarded by design.** There are no top-level `vox.web` imports in any daemon file.
Startup, usage recording, and settings reads each use a lazy import inside a
`try/except`; a missing or half-built `vox.web` is a silent no-op (debug-logged), so
the voice assistant is never blocked by the dashboard. See
[`integration.md`](./integration.md) for the exact guard at each touch point.

## How to run it

### Backend (auto-starts with the daemon)

When the voice daemon boots, `core/loop.py` calls
`vox.web.server.start_in_background(cfg)` (only if `cfg.dashboard_enabled`, which
defaults to `True`). Nothing extra to do — the bridge is already serving on
`http://127.0.0.1:8765`.

To run the bridge **standalone** (e.g. for frontend dev, or to poke the API without
the daemon):

```bash
uv run python -m vox.web.server      # serves http://127.0.0.1:8765
```

### Frontend (dev server)

```bash
cd dashboard
npm install
npm run dev                          # Vite on http://localhost:5173
```

Vite proxies `/api` (REST **and** the WebSocket) to `127.0.0.1:8765`, so start the
bridge first. For a production build, `npm run build` emits `dashboard/dist`, which the
bridge then serves at `/` with SPA fallback — no separate web server needed.

### Open it hands-free

Say **"open dashboard"** (or "open the dashboard" / "show dashboard" /
"launch dashboard" / "open vox dashboard"). The daemon routes the `"dashboard"` wake
label to `webbrowser.open("http://{dashboard_host}:{dashboard_port}")` and stays idle
(it does not enter a mode).

### Smoke-test the API

```bash
curl -s http://127.0.0.1:8765/api/status   | python -m json.tool
curl -s http://127.0.0.1:8765/api/settings | python -m json.tool
curl -s 'http://127.0.0.1:8765/api/usage/recent?limit=5'
```

## API surface

All REST is under `/api`, JSON, **camelCase** fields. Eighteen routes are mounted in
iteration 1; the personalities and rules routes are wired but return safe placeholders
until their stores land (iters 4 and 6). Full detail in [`backend.md`](./backend.md).

| Method | Path | Returns / body | Iter-1 state |
|--------|------|----------------|--------------|
| GET | `/api/status` | `{running, mode, smallBrain, bigBrain, personality, uptimeSeconds}` | live (`mode` hardcoded `"idle"`) |
| GET | `/api/settings` | `Setting[]` (12 keys, grouped) | live |
| POST | `/api/settings` | body `{key, value}` → `{ok, value}` | live, persists |
| GET | `/api/usage/recent?limit=100` | `UsageEvent[]` (newest first) | live |
| GET | `/api/usage/summary` | `{totals, byModel, byDay}` | live |
| WS | `/api/usage/stream` | one `UsageEvent` per LLM call | live |
| GET | `/api/personalities` | `{active, presets, custom}` | guarded → `{active:null, presets:[], custom:[]}` |
| POST | `/api/personalities/active` | body `{id}` | guarded |
| POST | `/api/personalities/custom` | body `{name, persona, emoji?, suggestedVoice?}` | guarded |
| DELETE | `/api/personalities/custom/{id}` | — | guarded |
| GET | `/api/rules` | `Rule[]` | guarded → `[]` |
| POST | `/api/rules` | body `{text}` | guarded |
| PATCH | `/api/rules/{id}` | body `{enabled?, text?}` | guarded |
| DELETE | `/api/rules/{id}` | — | guarded |
| GET | `/api/memory?query=&limit=` | `Memory[]` | live (wired to `vox.memory`) |
| POST | `/api/memory` | body `{text, tags?}` | live |
| DELETE | `/api/memory/{id}` | — | live |
| GET | `/api/axtree` | `{app, capturedAt, tree}` or `{error}` | live (macOS only; `{error}` off-mac) |

Plus static serving: `/assets/*` and SPA fallback `/{full_path}` → `index.html` when
`dashboard/dist/` exists, otherwise a friendly JSON placeholder at `/`.

### Data shapes

The TS types in `dashboard/src/lib/api.ts` mirror the Python responses exactly:

- `UsageEvent` = `{id, ts, provider, model, brain:"small"|"big", kind:"chat"|"command"|"vision"|"rewrite", inputTokens, outputTokens, costUsd, latencyMs}`
- `Setting` = `{key, label, group, type:"toggle"|"select"|"text", value, options?, help}`
- `Personality` = `{id, name, emoji, tagline, persona, suggestedVoice?, preset}`
- `Rule` = `{id, text, enabled}`
- `Memory` = `{id, ts, text, tags, score?}`
- `AxNode` = `{role, title?, value?, enabled?, children}`

### Settings exposed (12 keys)

Grouped for the (future) Settings page:

- **Brains** — `small_brain_provider`, `small_brain_model`, `big_brain_provider`, `big_brain_model`, `escalate_to_big_brain`, `escalation_mode`
- **Behavior** — `llm_executor_enabled`, `screen_vision_enabled`, `dictation_exit_on_silence`
- **Voice** — `tts_enabled`, `barge_in_enabled`
- **Debug** — `debug`

`settings_store` stores only changed keys in `data/settings.json` and reads merge over
the frozen `Config`. In iteration 1 only the **brain provider/model** keys are read
back by the daemon (in `assistant._brain`), so those take effect on the next LLM call
without a restart. The other flags are surfaced by the API but not yet wired at their
daemon call sites (see gaps).

### Runtime data (gitignored, under `data/`)

- `data/usage.jsonl` — append-only `UsageEvent` ledger.
- `data/settings.json` — changed-key overrides over `Config`.
- `data/memory.jsonl` — managed by `vox.memory`.

## Frontend shell

`dashboard/` is a hand-written Vite + React 18 + TS + Tailwind app (shadcn/ui +
Animate UI authored by hand — no CLI/network was run). The `AppShell` fetches
`/api/status` (5s poll) and shares it with a 240px `SideNav` (animated gradient active
indicator + status dot) and a sticky glass `TopBar` (listening pulse + brain/personality
chips). Seven pages route end-to-end:

- **Overview** — fully working: animated glass cards for status/uptime/personality/
  small-brain/big-brain/bridge, with a graceful offline error card when the bridge is
  down.
- **Token Usage, Settings, Personalities, AX Tree, Rules, Memory** — titled "coming
  soon" placeholders (each notes its delivering iteration) so navigation is real now
  and later iterations only swap a page body in.

Theme is dark-first premium ("AI control center"): zinc-950 base, glassy
backdrop-blur cards, a violet→cyan accent gradient, Animate UI micro-interactions
(sliding number counters, spring page transitions, staggered fade-ins, listening
pulse), all gated by `prefers-reduced-motion`. Full inventory in
[`frontend.md`](./frontend.md).

## Known gaps (carried into later iterations)

- **`/api/status.mode` is hardcoded `"idle"`.** No shared live-daemon-state handle
  exists yet; wire it once one does.
- **Personalities & rules routes are placeholders.** `src/vox/web/personalities.py`
  (iter 4) and `rules.py` (iter 6) don't exist; the routes return empty/safe data and
  will light up automatically when those modules land.
- **Only brain provider/model settings are wired into the daemon.** The other flags
  (`escalate_to_big_brain`, `escalation_mode`, `llm_executor_enabled`,
  `screen_vision_enabled`, `tts_enabled`, `barge_in_enabled`,
  `dictation_exit_on_silence`, `debug`) are exposed by the API but still read from
  `Config` at their call sites — wiring them in `executor.py`/`actions.py`/`tts.py` is
  a later integration task.
- **Usage `kind` is only `"chat"`/`"vision"`.** `"command"`/`"rewrite"` tagging at the
  executor/rewrite call sites is deferred.
- **SDK/subscription token extraction is best-effort.** `claude_sdk` reads
  `ResultMessage.usage` if present; `claude_cli` surfaces no tokens. Both record as
  subscription (cost 0) — refine to the live SDK shape in iteration 2.
- **Pricing in `usage.PRICES` is approximate** and editable as model prices change.
- **Frontend not yet built/installed.** Deps install + production build happen in a
  later iteration; iteration 1 verified the frontend statically (imports resolve,
  exports match) but ran no `npm`.
- **Six of seven pages are placeholders** — Token Usage is next (iteration 2).
