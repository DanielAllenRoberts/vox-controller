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

---

## Iteration 2 — token-usage capture (backend)

This iteration hardens the token-usage ledger and the SDK token extraction so a
call recorded from the voice thread reaches WS subscribers, persists correctly,
and renders on the Token Usage page. Additive only; the voice daemon's
`vox.web` touch points stay lazy + guarded.

### `usage.py`

- **Subscription calls now record `null` tokens, not 0.** `record_usage(...)`
  accepts `input_tokens`/`output_tokens` of `None` (SDK/CLI subscription calls
  that don't expose counts) and persists `inputTokens: null` / `outputTokens:
  null` with `costUsd: 0` — distinct from a genuine 0-token request, so the UI
  can render "subscription" instead of a misleading 0. Helper:
  `is_subscription_call(provider, in, out)` — true for `claude_sdk`/`claude_cli`
  or when both token counts are `None`.
- **`summary()` is None-safe** — totals/byModel/byDay treat `null` token counts
  as 0 for aggregation (`int(e.get("inputTokens") or 0)`), so a ledger mixing
  subscription and metered calls aggregates without errors. Shape per CONTRACT:
  `{totals:{calls,inputTokens,outputTokens,costUsd}, byModel:[...], byDay:[...]}`.
- **Cross-thread WS fan-out** (unchanged design, verified): `record_usage` runs
  on the voice daemon thread and calls `_publish`, which schedules
  `put_nowait` onto each subscriber queue's bound loop via
  `loop.call_soon_threadsafe`. The WS route binds `queue._vox_loop` on accept.
  Verified end-to-end: a record from a non-loop thread is delivered to a
  subscriber awaiting on the API event loop.
- **Persistence**: append-only JSON Lines under `data/usage.jsonl`, one event per
  line, under a process-wide `RLock`; `recent(limit)` returns newest-first;
  `_read_all` tolerates blank/corrupt lines.

### `assistant.py` — SDK token extraction

- `_sdk_extract_tokens(msg)` pulls `(input_tokens, output_tokens)` from a
  `claude-agent-sdk` **`ResultMessage`** `usage` dict (Anthropic API shape;
  ignores cache fields). The `ResultMessage` is the message that also carries
  `total_cost_usd` and the cumulative `usage`, so the call sites in
  `_claude_sdk` / `_sdk_look` now match on `hasattr(msg, "total_cost_usd")`
  rather than reading `usage` off every message (e.g. per-turn
  `AssistantMessage`). Guarded: any shape mismatch → `None`, which the store
  records as a subscription call (tokens `null`, cost 0). Never breaks a reply.
- `_anthropic` already passes `(resp.usage.input_tokens,
  resp.usage.output_tokens)`; `_openai` passes `(u.prompt_tokens,
  u.completion_tokens)` guarded with a `None` fallback. Unchanged.

### Dev seed (visual QA only)

- `usage.maybe_seed_dev()` seeds ~12 realistic `UsageEvent`s **only when
  `VOX_DEV_SEED=1`** and the ledger is empty (so it can't pollute a real one).
  Mix: `deepseek-chat`, `claude-opus-4-8` (subscription, `null` tokens),
  `claude-haiku-4-5`, spread across 4 days. Called once from `create_app()`,
  fully guarded. **Never seeds in normal operation.**

### How to verify

```bash
# unit-level (no server): seed + summary
VOX_DEV_SEED=1 uv run python -c "from vox.web import usage; print(usage.maybe_seed_dev()); print(usage.summary()['totals'])"

# run the bridge with seed data for the Token Usage page
VOX_DEV_SEED=1 uv run python -m vox.web.server
curl -s 'http://127.0.0.1:8765/api/usage/recent?limit=5'
curl -s  http://127.0.0.1:8765/api/usage/summary   # totals + byModel + byDay

# live feed: open the WS, then trigger a voice call (or any record_usage)
#   ws://127.0.0.1:8765/api/usage/stream  → one UsageEvent per call
```

> Remove `data/usage.jsonl` (gitignored) before seeding a clean QA run — the
> seed is a no-op if real data is already present.

---

## Iteration 3 — settings take effect LIVE

This iteration makes dashboard setting toggles change daemon behaviour **without a
restart** for runtime-read flags, and tightens `settings_store.set` validation.
Strictly additive; all daemon reads are lazy + guarded and fall back to `Config`,
so a missing/broken `settings_store` never changes daemon behaviour.

### `settings_store.py`

- **`SCHEMA`** covers all 12 CONTRACT keys with the right `type`/`group`/`options`/`help`:
  `small_brain_provider`, `small_brain_model`, `big_brain_provider`, `big_brain_model`,
  `escalate_to_big_brain`, `escalation_mode` (Brains); `llm_executor_enabled`,
  `screen_vision_enabled`, `dictation_exit_on_silence` (Behavior); `tts_enabled`,
  `barge_in_enabled` (Voice); `debug` (Debug).
- **`set(key, value)` now VALIDATES against the schema** and coerces:
  - unknown key → raises `SettingError` (a `ValueError` subclass).
  - `toggle` → must be a bool (also accepts the strings `"true"`/`"false"`); else raises.
  - `select` → must be one of the declared option values; else raises.
  - `text` → coerced to `str` (rejects `null`).
  Only the validated/coerced override is persisted to `data/settings.json`; the file
  holds **overrides only** (keys never set keep their `Config` default).
- **`all()`** returns full `Setting[]` descriptors (`key,label,group,type,value,help`,
  plus `options` for selects) with live effective values (override → `Config`).
- **`get(key)`** unchanged: override → `Config` → `None`.

### `server.py`

- `GET /api/settings` → `settings_store.all()`.
- `POST /api/settings` `{key,value}` → `settings_store.set(...)` returning `{ok,value}`
  on success, or **HTTP 400** `{ok:false, error:"<message>"}` when `set` raises
  `ValueError` (unknown key / bad enum / wrong type).

### Daemon wiring — guarded live reads

A module-local `_setting(key, cfg_fallback)` helper (the same lazy+guarded pattern
already in `assistant.py`) was added to `core/loop.py` and `executor.py`. Each tries
`vox.web.settings_store.get(key)` and falls back to the `Config`/`cfg` value when the
store is missing, errors, or returns `None`. Wired in:

| Setting | Read site | Effect |
|---------|-----------|--------|
| `escalation_mode` | `loop._wants_escalation` | next utterance the parser can't handle |
| `barge_in_enabled` | `loop._run_interruptible` | next blocking LLM call |
| `dictation_exit_on_silence` | `loop._dictation_mode` | next long pause in dictation |
| `llm_executor_enabled` | `executor.execute` | next uncertain command |
| `screen_vision_enabled` | `executor.execute` (LOOK branch) | next "read the screen" request |

Brain provider/model are already read live in `assistant.py` (`settings_store.get` →
`Config`); **assistant.py was left untouched.**

### Next-call vs restart

**Take effect on the NEXT relevant action (no restart):**
`escalation_mode`, `barge_in_enabled`, `dictation_exit_on_silence`,
`llm_executor_enabled`, `screen_vision_enabled`, and the brain `*_provider`/`*_model`
(via assistant.py). `escalate_to_big_brain`, `tts_enabled`, and `debug` are read at
their existing `Config` call sites and take effect whenever those sites next read them.

**Restart required:** none of the keys above strictly need a restart for the wired
sites. Schema `help` text still notes "Restart to apply" for the four brain
provider/model fields as a conservative UI hint, since a long-lived in-flight mode
(e.g. an active control session that cached a client) may not pick a change up until
the next idle→mode transition.

### How to verify

```bash
# settings_store validation + persistence (overrides only)
uv run python -c "from vox.web import settings_store as s; \
print(len(s.all())); print(s.set('escalation_mode','keywords')); \
import json,pathlib; print(json.loads(pathlib.Path('data/settings.json').read_text()))"

# HTTP: valid 200, bad enum / unknown key -> 400
uv run python -c "from fastapi.testclient import TestClient; from vox.web import server; \
c=TestClient(server.create_app()); \
print(c.post('/api/settings',json={'key':'tts_enabled','value':False}).status_code); \
print(c.post('/api/settings',json={'key':'escalation_mode','value':'bogus'}).status_code); \
print(c.post('/api/settings',json={'key':'nope','value':1}).status_code)"
# expect: 200 400 400

# daemon guarded fallback (no store needed)
uv run python -c "from vox.core import loop; from vox import executor; \
print(loop._setting('escalation_mode','auto'), executor._setting('llm_executor_enabled',True))"
```

> Remove the test `data/settings.json` afterwards — it is gitignored runtime data.
