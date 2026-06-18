# Vox Control Center

A local web control center for the **Vox** voice assistant — the macOS hands-free
voice agent in this repo (`src/vox/`). The dashboard gives you a premium, dark-first
window into the running voice daemon: live status and diagnostics, token usage and
cost, runtime settings you can toggle without restarting, personalities, the focused
app's accessibility tree, rules, and long-term memory.

It is **additive**. The dashboard is a FastAPI bridge (`src/vox/web/`) plus a
Vite/React/TypeScript app (`dashboard/`). Every place the voice daemon touches
`vox.web` is a lazy, guarded import inside `try/except`, so **the voice assistant
runs unchanged if `vox.web` is absent, half-built, or broken**. The dashboard is a
convenience layered on top — never a dependency.

---

## What it is

- A single-page web app served locally at `http://127.0.0.1:8765`.
- Backed by a FastAPI bridge embedded in the Python package, started automatically
  by the voice daemon on a guarded background thread.
- Opened hands-free: say **"open dashboard"** (or "show dashboard", "launch
  dashboard", …) and Vox opens it in your browser.
- Bound to loopback only. No runtime data or secrets are committed.

---

## Features

- **Overview** — live daemon status (running, mode, small/big brain provider+model,
  active personality, uptime), a System Health card (CPU %, memory, uptime, Whisper
  model + compute type, active brains), today's cost with a sparkline, a live event
  feed, and quick-action chips.
- **Token Usage + cost** — animated counters for calls/tokens/cost, a cost-over-time
  area chart and tokens-by-model bar chart, a per-model / per-day breakdown, and a
  live feed driven by the usage WebSocket. Subscription (SDK/CLI) calls are shown as
  "subscription" rather than `$0.00`.
- **Cost budget** — set an optional monthly budget in Settings; the Token Usage page
  shows a progress ring (spent / budget / remaining) that shifts color from accent →
  amber (≥80%) → red (≥100%).
- **Settings** — runtime toggles grouped as Brains / Behavior / Voice / Cost / Debug.
  Changes persist as an override layer over the frozen `Config` and most take effect
  on the **next** LLM call without a restart (brain provider/model changes are flagged
  "restart to apply"). Optimistic saves with toast feedback.
- **Personalities** — 8 built-in presets (Posh Butler, Batman, J.A.R.V.I.S., The
  Philosopher, Film-Noir Detective, Surfer, Shakespearean Bard, Sherlock Holmes), each
  with a tight system-prompt persona and a suggested macOS `say` voice. Click a card
  to activate it live; create and delete your own custom personas.
- **AX Tree** — a read-only snapshot of the focused macOS app's accessibility tree:
  searchable, collapsible, with refresh / auto-refresh. Read-only (no UI automation)
  and degrades gracefully off-mac or without Accessibility permission.
- **Rules** — CRUD list of instruction rules that get appended to Vox's system prompt
  when enabled. Add / toggle / inline-edit / delete with optimistic updates.
- **Memory** — long-term memory store with add, tag, and search (keyword scoring now,
  pluggable for embeddings later). Enabled memories are recalled into the live prompt.
- **Command palette** — `⌘K` / `Ctrl+K` fuzzy palette to jump to any page, activate any
  personality, or open the repo.
- **Themes** — dark-first premium theme with a light theme toggle (persisted to
  `localStorage`).
- **Keyboard shortcuts** — `g` then a key navigates between pages, `⌘K`/`Ctrl+K` opens
  the palette, `?` shows the shortcut help overlay, `Esc` closes overlays.

---

## How to run

### Option A — build once, served by the bridge (recommended)

Build the frontend; the FastAPI bridge then serves the built app at
`http://127.0.0.1:8765`, and the running voice daemon auto-starts that bridge.

```bash
cd dashboard
npm install
npm run build      # outputs dashboard/dist/
```

Now start the voice daemon as usual. On startup it calls
`vox.web.server.start_in_background(cfg)` on a guarded daemon thread, so the bridge
comes up alongside the assistant. Then either:

- Say **"open dashboard"** to open `http://127.0.0.1:8765` in your browser, or
- Open `http://127.0.0.1:8765` yourself.

If the frontend hasn't been built yet, the bridge serves a friendly placeholder at
`/` (and the full `/api` surface still works).

### Option B — development (hot reload)

Run the bridge and the Vite dev server separately. Vite serves the UI at
`http://localhost:5173` and proxies `/api` (REST + WebSocket) to the bridge.

```bash
# terminal 1 — FastAPI bridge
uv run python -m vox.web.server          # serves on http://127.0.0.1:8765

# terminal 2 — Vite dev server
cd dashboard
npm run dev                              # http://localhost:5173
```

Open `http://localhost:5173`.

---

## Architecture

```
dashboard/                 Vite + React 18 + TypeScript + Tailwind + shadcn/ui app
  src/pages/*              one page per feature (Overview, TokenUsage, Settings,
                           Personalities, AxTree, Rules, Memory)
  src/components/*         ui/ (shadcn), animate/, layout/, command palette
  src/lib/api.ts           typed fetch client + all data-shape types
  src/hooks/*              useUsageStream (WS), useApi, theme, shortcuts, toast
  dist/                    production build served by the bridge

src/vox/web/               FastAPI bridge (embedded in the Python package)
  server.py                create_app() -> FastAPI ; run(host, port) ;
                           start_in_background(cfg) -> daemon Thread ;
                           python -m vox.web.server ; serves dashboard/dist at /
  usage.py                 token/cost ledger -> data/usage.jsonl ; PRICES ;
                           WS fan-out ; budget_status()
  settings_store.py        SCHEMA + override layer over Config -> data/settings.json
  personalities.py         8 presets + custom CRUD -> data/personalities.json
  rules.py                 rules CRUD -> data/rules.json
  axtree.py                read-only macOS AX snapshot (via osascript)
  diagnostics.py           read-only system/health snapshot

src/vox/memory.py          memory store -> data/memory.jsonl (keyword scoring)
```

The bridge runs on a **daemon thread** started from `core/loop.py`; a missing
dependency, bad config, or a port already in use is swallowed so it can never take
down the voice loop. Per-feature stores (`usage`, `settings_store`, `personalities`,
`rules`, `axtree`, `diagnostics`, `memory`) are imported lazily and per-request, and
return safe empty/`{error}` payloads instead of 500s, so the app boots even when a
store is absent or corrupt. The React app talks to the bridge over REST and receives
live usage events over the WebSocket at `/api/usage/stream` (parsed straight into the
typed `UsageEvent` shape, with reconnect backoff).

The daemon reads runtime settings (brain provider/model, feature flags) back through
`settings_store` with a fallback to the frozen `Config`, which is what lets dashboard
toggles take effect on the next relevant call without a restart.

---

## API surface

The bridge exposes REST under `/api` (JSON, camelCase fields) plus the usage
WebSocket. The complete route list, request/response shapes, and TypeScript types are
the single source of truth in **[`CONTRACT.md`](./CONTRACT.md)**. In brief:

- `GET /api/status`, `GET /api/diagnostics`
- `GET /api/usage/recent`, `GET /api/usage/summary`, `GET /api/budget`,
  `WS /api/usage/stream`
- `GET/POST /api/settings`
- `GET /api/personalities`, `POST /api/personalities/active`,
  `POST/DELETE /api/personalities/custom`
- `GET/POST /api/rules`, `PATCH/DELETE /api/rules/{id}`
- `GET/POST /api/memory`, `DELETE /api/memory/{id}`
- `GET /api/axtree`

See also the per-area docs in this folder: `backend.md`, `frontend.md`, `axtree.md`,
`rules.md`, `memory.md`, `diagnostics.md`, and the build history in `BUILD_LOG.md`.

---

## Security posture

- **Loopback only.** The bridge binds `127.0.0.1` by default
  (`dashboard_host` / `dashboard_port` in `config.py`, defaults `127.0.0.1:8765`). It
  is not exposed to the network.
- **Additive and guarded.** Every `vox.web` touch point in the daemon is a lazy import
  inside `try/except`; the dashboard can be absent or broken and the voice assistant
  runs unchanged. The web server starts on a daemon thread and never propagates a
  failure into the voice loop.
- **AX tree is read-only.** It snapshots the focused app's accessibility tree for
  display; it performs no UI automation.
- **Runtime data stays local.** All runtime state (`data/usage.jsonl`,
  `data/settings.json`, `data/personalities.json`, `data/rules.json`,
  `data/memory.jsonl`) lives under `data/`, which is **gitignored**. No runtime data
  and no secrets are committed. Token pricing in `usage.PRICES` is approximate and
  editable.
