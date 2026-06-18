# Dashboard backend bridge (`src/vox/web/`)

FastAPI + uvicorn bridge that exposes the voice daemon's state to the dashboard.
Iteration 1 ships the **foundation skeleton**: a runnable server, the usage and
settings stores, and every REST/WS route — with optional modules guarded so the
server always boots and the voice daemon never breaks. Follows
[`CONTRACT.md`](./CONTRACT.md) exactly (paths, routes, shapes, signatures).

## Modules

| File | Responsibility |
|------|----------------|
| `server.py` | `create_app() -> FastAPI`; `run(host, port)`; `start_in_background(cfg) -> Thread`; routes; static dashboard + SPA fallback; CORS; `python -m vox.web.server`. |
| `usage.py` | `record_usage(...)`, `recent(limit)`, `summary()`, `PRICES`, WS subscriber registry + `publish`; persists `data/usage.jsonl`. |
| `settings_store.py` | `SCHEMA`, `get(key)`, `set(key, value)`, `all()`; persists `data/settings.json` as overrides over `Config`. |
| `axtree.py` | `snapshot()` — read-only macOS AX tree (already present). |
| `memory.py` (top-level) | `add/recall/all/remove` — used by the memory routes (already present). |

`personalities.py` and `rules.py` do **not** exist yet (later iterations). Their
routes are guarded and return safe empty/placeholder data until they land.

## REST API (all under `/api`, JSON, camelCase)

| Method | Path | Returns |
|--------|------|---------|
| GET | `/api/status` | `{running, mode, smallBrain, bigBrain, personality, uptimeSeconds}` |
| GET | `/api/settings` | `Setting[]` |
| POST | `/api/settings` | `{ok, value}` (body `{key, value}`) |
| GET | `/api/usage/recent?limit=100` | `UsageEvent[]` (newest first) |
| GET | `/api/usage/summary` | `{totals, byModel, byDay}` |
| WS | `/api/usage/stream` | one `UsageEvent` per call as it happens |
| GET/POST | `/api/personalities`, `/api/personalities/active`, `/api/personalities/custom` | guarded (empty until impl) |
| DELETE | `/api/personalities/custom/{id}` | guarded |
| GET/POST | `/api/rules` · PATCH/DELETE `/api/rules/{id}` | guarded (empty until impl) |
| GET/POST | `/api/memory?query=&limit=` · DELETE `/api/memory/{id}` | wired to `vox.memory` |
| GET | `/api/axtree` | `{app, capturedAt, tree}` or `{error}` |

## Key decisions

- **Server always boots.** Optional modules are imported lazily per-request via a
  guarded helper; a missing module yields safe defaults (`[]`, `{active:None,…}`,
  `{error:…}`) instead of a 500. `create_app()` itself imports only `usage` and
  `settings_store`, which always exist.
- **Daemon-safe startup.** `start_in_background(cfg)` runs uvicorn on a daemon
  thread and swallows every exception (bad port, missing dep) so `core/loop.py`
  can call it non-fatally. It reads `dashboard_host`/`dashboard_port` from `cfg`
  via `getattr` (defaults `127.0.0.1:8765`) so it works even before the
  integration agent adds those Config fields.
- **WS fan-out across threads.** `record_usage` is called from the voice-daemon
  thread but subscribers live on the API event loop. Each WS subscriber binds its
  queue to its running loop (`queue._vox_loop`); `usage._publish` delivers via
  `loop.call_soon_threadsafe`, so cross-thread publishes are safe and lossless
  (bounded queue drops oldest on overflow rather than blocking).
- **Settings = override layer.** `data/settings.json` holds only changed keys;
  reads merge over the frozen `Config`. `settings_store.get(key)` is the seam
  `assistant.py`/`executor.py` should read so toggles take effect on the next call
  (keys needing a restart are noted in each setting's `help`).
- **Pricing.** `usage.PRICES` is `$/1M (input, output)` and resolves a model by
  exact id then prefix (so dated snapshots like `claude-haiku-4-5-20251001` match
  `claude-haiku-4-5`). Subscription providers (`claude_sdk`/`claude_cli`) record
  tokens but cost `0`. Unknown models cost `0`.
- **CORS** allows the Vite dev origin `http://localhost:5173` (+ `127.0.0.1`).
- **Static serving.** If `dashboard/dist/` exists it's served at `/` with SPA
  fallback (`/assets` mounted, unknown paths → `index.html`); otherwise `/`
  returns a friendly JSON placeholder. `/api/*` always wins over the SPA catch-all.

## Runtime data (gitignored, under `data/`)

- `data/usage.jsonl` — append-only `UsageEvent` ledger.
- `data/settings.json` — changed-key overrides over `Config`.
- `data/memory.jsonl` — managed by `vox.memory`.

## How to verify

```bash
# 1) Run the bridge standalone
uv run python -m vox.web.server          # serves http://127.0.0.1:8765

# 2) Hit the API
curl -s http://127.0.0.1:8765/api/status | python -m json.tool
curl -s http://127.0.0.1:8765/api/settings | python -m json.tool
curl -s 'http://127.0.0.1:8765/api/usage/recent?limit=5'
curl -s http://127.0.0.1:8765/api/usage/summary

# 3) Toggle a setting (persists to data/settings.json)
curl -s -X POST http://127.0.0.1:8765/api/settings \
  -H 'Content-Type: application/json' -d '{"key":"debug","value":false}'

# 4) Guarded routes return safe placeholders (no 500) before later iterations
curl -s http://127.0.0.1:8765/api/rules           # []
curl -s http://127.0.0.1:8765/api/personalities   # {"active":null,"presets":[],"custom":[]}
```

The WS stream (`/api/usage/stream`) emits one `UsageEvent` whenever
`usage.record_usage(...)` is called from anywhere in the process.

## TODOs for later iterations

- **Integration agent (iter 1+):** add `dashboard_*` fields to `Config`, wire
  `start_in_background(cfg)` into `core/loop.py`, and call
  `usage.record_usage(...)` after each provider call in `assistant.py` (reading
  brain provider/model via `settings_store.get`).
- **Iter 4 (personalities):** add `src/vox/web/personalities.py` with `all()`,
  `set_active(id)`, `add_custom(...)`, `remove_custom(id)` — routes are already
  wired and will light up automatically.
- **Iter 6 (rules):** add `src/vox/web/rules.py` with `list_rules()`,
  `add_rule`, `update_rule`, `remove_rule` — routes already wired.
- **`/api/status.mode`** is hardcoded to `"idle"`; wire it to the live daemon
  mode once a shared state handle exists.
- **Pricing** in `usage.PRICES` is approximate — refresh as model prices change.
```
