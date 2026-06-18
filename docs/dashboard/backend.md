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
| `axtree.py` | `snapshot()` — read-only macOS AX tree (iter 5: `enabled` field + depth/breadth truncation markers). See [`axtree.md`](./axtree.md). |
| `memory.py` (top-level) | `add/recall/all/remove` — used by the memory routes (already present). |

`personalities.py` landed in iteration 4 (8 presets + custom CRUD; see the
Personalities section below). `rules.py` does **not** exist yet (later iteration); its
routes are guarded and return safe empty/placeholder data until it lands.

## REST API (all under `/api`, JSON, camelCase)

| Method | Path | Returns |
|--------|------|---------|
| GET | `/api/status` | `{running, mode, smallBrain, bigBrain, personality, uptimeSeconds}` |
| GET | `/api/settings` | `Setting[]` |
| POST | `/api/settings` | `{ok, value}` (body `{key, value}`) |
| GET | `/api/usage/recent?limit=100` | `UsageEvent[]` (newest first) |
| GET | `/api/usage/summary` | `{totals, byModel, byDay}` |
| WS | `/api/usage/stream` | one `UsageEvent` per call as it happens |
| GET/POST | `/api/personalities`, `/api/personalities/active`, `/api/personalities/custom` | live (8 presets + custom; 400 on bad id / blank name|persona) |
| DELETE | `/api/personalities/custom/{id}` | live (`{ok}`) |
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

---

## Personalities (iteration 4) — `src/vox/web/personalities.py`

The assistant's *persona*: the in-character flavour layered on top of the base
`_SYSTEM` prompt. Eight fun-but-helpful presets are code-defined; the user can add
custom personas and pick which one is **active**. The active persona drives the live
system prompt in `assistant.respond_turn`.

### Data shape (CONTRACT)

`Personality` = `{id, name, emoji, tagline, persona, suggestedVoice?, preset: bool}`.
`persona` is a tight 2–4 sentence system-prompt instruction that sets a distinctive
voice/character while keeping the assistant genuinely helpful.

### Presets (preset=true, never persisted)

Posh Butler 🤵 (Daniel) · Batman 🦇 (Lee) · J.A.R.V.I.S. 🤖 (Oliver) · The Philosopher 🧠
(Daniel) · Film-Noir Detective 🕵️ (Lee) · Surfer 🏄 (Aaron) · Shakespearean Bard 🎭
(Daniel) · Sherlock Holmes 🔍 (Oliver).

### Public API

- `PRESETS` — the 8 code-defined preset dicts.
- `all() -> {active, presets, custom}` — active is the id string (`""` = none).
- `get_active() -> str` — the active persona **text** (presets+custom resolved), `""`
  if none/unknown. Guarded; never raises. Used by `assistant._active_persona()`.
- `get_active_personality() -> dict|None` — the full active Personality (for
  `suggestedVoice`).
- `set_active(id) -> str` — validates id ∈ presets+custom or `""`; raises `ValueError`
  (→ 400) on unknown id.
- `add_custom(name, persona, emoji?, suggestedVoice?, tagline?) -> Personality` — slug
  id (deduped vs presets+custom), `preset=false`; raises `ValueError` (→ 400) if name
  or persona is blank.
- `remove_custom(id) -> bool` — removes a custom persona; clears active if it was the
  one removed; presets can't be removed (returns False).

### Persistence

Only `{active, custom}` → `data/personalities.json` (gitignored). Presets live in code.
Atomic write (tmp + replace); corrupt/missing file degrades to `{active:"", custom:[]}`.

### Routes (`server.py`)

- `GET /api/personalities` → `all()`
- `POST /api/personalities/active` `{id}` → `{ok, active}`; unknown id → 400 `{ok,error}`.
  On success, if the active persona has a `suggestedVoice` **and** the settings schema
  exposes `tts_voice`, the TTS voice is matched via `settings_store.set` (additive,
  fully guarded no-op otherwise — see `_apply_suggested_voice`).
- `POST /api/personalities/custom` `{name,persona,emoji?,suggestedVoice?}` → Personality;
  missing name/persona → 400 `{ok,error}`.
- `DELETE /api/personalities/custom/{id}` → `{ok}`.

### Live wiring (`assistant.py`)

`_active_persona()` returns the live active persona text: personalities store →
`CONFIG.personality` → `""`. Fully guarded (try/import) so a missing or broken store
reverts to exactly today's behaviour. `respond_turn` builds the system prompt from
`_active_persona()` instead of reading `CONFIG.personality` directly, so flipping the
active persona in the dashboard changes the next reply's character with no restart.

### Verify

```bash
# store: presets + active + custom + validation
uv run python -c "from vox.web import personalities as p; \
print(len(p.all()['presets'])); print(p.set_active('batman')); \
print(p.get_active()[:30]); c=p.add_custom(name='Pirate',persona='Arr, be helpful.'); \
print(c['id'], p.remove_custom(c['id']))"

# HTTP: 200 + 400s
uv run python -c "from fastapi.testclient import TestClient; from vox.web import server; \
c=TestClient(server.create_app()); \
print(c.post('/api/personalities/active',json={'id':'sherlock'}).status_code); \
print(c.post('/api/personalities/active',json={'id':'zzz'}).status_code); \
print(c.post('/api/personalities/custom',json={'name':'','persona':''}).status_code)"
# expect: 200 400 400

# live wiring (guarded fallback)
uv run python -c "from vox import assistant; from vox.web import personalities as p; \
p.set_active('jarvis'); print(assistant._active_persona()[:20]); \
p.set_active(''); print(repr(assistant._active_persona()))"
```

> Remove the test `data/personalities.json` afterwards — it is gitignored runtime data.

---

## Iteration 5 — AX-tree / Rules / Memory routes hardened (server.py)

This iteration fleshed out the remaining write/read routes in `src/vox/web/server.py`
so they are fully functional, validate input, and **never 500** — a missing or
half-built feature module degrades to a safe placeholder, and bad input returns a
helpful `400`. No other module was touched; routes rely only on the signatures the
axtree / rules / memory agents implement per `CONTRACT.md`.

### Shared helpers (new, in `server.py`)
- `_bad_request(msg)` → `400 {ok:false, error}`
- `_not_found(what)` → `404 {ok:false, error:"<what> not found"}`
- `_service_unavailable(what)` → `503 {ok:false, error:"<what> module not available"}`
- `async _json_body(request)` → `(body, None)` on a valid JSON **object**, else
  `({}, JSONResponse-400)`. Guards malformed JSON and non-object bodies so a bad
  payload can't raise out of a route.

### Routes
- **`GET /api/axtree`** → `axtree.snapshot()` (`{app,capturedAt,tree}` or `{error}`).
  Wrapped so even an unexpected raise becomes `{error: ...}` rather than a 500.
- **`GET /api/rules`** → `rules.list_rules()` (or `[]` if the module is absent / read fails).
- **`POST /api/rules`** `{text}` → `rules.add_rule(text.strip())`. `text` must be a
  non-empty string (else 400). Module absent → returns `[]` (rules list stays empty).
- **`PATCH /api/rules/{theId}`** `{text?, enabled?}` → forwards only well-typed,
  known fields to `rules.update_rule(id, **patch)`. `text` must be a non-empty
  string, `enabled` must be a bool, and at least one must be present (else 400).
  Unknown id → 404.
- **`DELETE /api/rules/{theId}`** → `rules.remove_rule(id)`; unknown id → 404, else `{ok:true}`.
- **`GET /api/memory?query=&limit=`** → `memory.recall(query, k=limit)` when `query`
  is present, else `memory.all()` sliced to `limit` (non-positive `limit` = all).
  Read failures degrade to `[]`.
- **`POST /api/memory`** `{text, tags?}` → `memory.add(text.strip(), tags)`. `text`
  must be a non-empty string; `tags` (optional) must be a list of strings (else 400).
  Module absent → 503.
- **`DELETE /api/memory/{theId}`** → `memory.remove(id)`; unknown id → 404, else `{ok:true}`.

### Decisions
- **Guarded imports stay lazy and per-request** (`_try_import` / `_try_import_memory`),
  preserving the daemon guarantee: `server.py`'s only top-level vox imports are
  `config`, `settings_store`, `usage`. Verified the AST has no top-level
  axtree/rules/memory import.
- **Error contract:** read routes never error (return empty/`{error}`); write routes
  return `400` for bad input, `404` for unknown ids, `503` only when a required
  module is missing. Successful creates return the stored record as-is (matching the
  `Rule` / `Memory` shapes), so the frontend can use the response directly.
- **Path params renamed to `{theId}`** to match the CONTRACT's wording for this
  iteration's routes; purely cosmetic (FastAPI binds by name).

### Verify
```bash
uv run python -c "
from fastapi.testclient import TestClient
from vox.web.server import create_app
c = TestClient(create_app())
def show(l,r): print(l, r.status_code)
show('axtree', c.get('/api/axtree'))                                   # 200
show('rules.list', c.get('/api/rules'))                                # 200
show('rules.post.empty', c.post('/api/rules', json={'text':' '}))      # 400
show('rules.post.badjson', c.post('/api/rules', content='x'))          # 400
show('rules.patch.nofields', c.patch('/api/rules/x', json={}))         # 400
show('memory.list', c.get('/api/memory'))                              # 200
show('memory.post.empty', c.post('/api/memory', json={'text':''}))     # 400
show('memory.post.badtags', c.post('/api/memory', json={'text':'h','tags':[1]}))  # 400
r = c.post('/api/memory', json={'text':'__t__','tags':['x']}); show('memory.post.ok', r)  # 200
show('memory.del', c.delete('/api/memory/'+r.json()['id']))            # 200
show('memory.del.missing', c.delete('/api/memory/nope'))               # 404
"
```

> Runtime `data/rules.json` / `data/memory.jsonl` written during testing are
> gitignored — clean up any `__t__` test records afterward.

## Rules + memory in the live prompt (iteration 5) — `src/vox/assistant.py`

Makes the dashboard's **rules** and **memory** actually shape Vox's replies. Iterations
3-4 wired settings/personalities into the system prompt; this layers two more context
blocks on top — **additively and fully guarded**, so a missing or broken `vox.web.rules`
/ `vox.memory` leaves today's behavior EXACTLY unchanged.

> Scope note: this sub-section is the **integration/assistant** agent's part and edits
> `assistant.py` ONLY. The `vox.web.rules` and `vox.memory` stores + their REST routes
> are documented in the server agent's sections above.

### What changed (assistant.py only)

Two new guarded helpers, plus three lines in `respond_turn`:

- `_rules_block() -> str` — lazily imports `vox.web.rules` and calls
  `enabled_rules_text()`. Renders the enabled rules as a labelled block telling the model
  to follow them (they override defaults on conflict). Any import/attribute/call error → `""`.
- `_memory_block(user_text) -> str` — lazily imports `vox.memory` and calls
  `recall(user_text, k=3)`. Renders the hits as a short "Things you remember about the
  user" bullet list (each record's `text`). Empty result or any error → `""`.
- `respond_turn` builds `system` from `_SYSTEM` + `_active_persona()` exactly as before,
  then appends whichever of `_rules_block()` / `_memory_block(text)` are non-empty.

### Why these choices

- **Layered on the existing persona, not replacing it** — order is persona → rules →
  memories, so character framing comes first and concrete instructions/facts follow.
- **Escalation gets it for free** — the small→big `[BIG]` re-call reuses the same
  `system` string, so rules + memories also reach the big brain.
- **k=3 for memory** — small relevant slice (per the task) to keep the spoken prompt
  tight; `recall` already ranks by keyword score and returns each record's `text`.
- **Telemetry/feature reads never break a reply** — both helpers swallow all exceptions,
  matching the existing `_setting` / `_active_persona` / `_record_usage` guard style. The
  helpers light up automatically once the stores hold data; no further assistant change.

### Verify

```bash
# helpers are guarded → '' with no data (today's behavior unchanged)
uv run python -c "from vox import assistant as a; \
print(repr(a._rules_block())); print(repr(a._memory_block('what is my name')))"
# expect: '' ''  (no enabled rules; memory store empty)

# a broken rules module is swallowed (not raised)
uv run python -c "import sys,types; from vox import assistant as a; \
m=types.ModuleType('vox.web.rules'); \
m.enabled_rules_text=lambda: (_ for _ in ()).throw(RuntimeError('boom')); \
sys.modules['vox.web.rules']=m; print(repr(a._rules_block()))"
# expect: ''

# rules block lights up live once an enabled rule exists
uv run python -c "from vox import assistant as a; from vox.web import rules; \
r=rules.add_rule('Always greet the user by name.'); \
print(a._rules_block()); rules.remove_rule(r['id'])"

# memory block renders bullets once a relevant record exists
uv run python -c "from vox import assistant as a; from vox import memory; \
r=memory.add('The user prefers concise answers', tags=['pref']); \
print(a._memory_block('concise answers user prefers')); memory.remove(r['id'])"
# expect: 'Things you remember about the user (use if relevant):\n• The user prefers concise answers'
```

> Any `data/memory.jsonl` / `data/rules.json` written while verifying is gitignored
> runtime data — remove test records with the modules' own `remove*()` APIs (don't
> truncate the files; they may hold real user data).

---

## Iteration 7 — `/api/budget` & `/api/diagnostics` (server.py)

Two additive read-only GET routes, mounted in `create_app()` just before the
static dashboard mount. Both follow the established **guarded lazy-import**
pattern (same shape as `/api/axtree`): import the feature module lazily, and on
*any* failure return a safe default object — never a 500.

### Routes

- `GET /api/budget` → `vox.web.usage.budget_status()`
  - On missing module / missing `budget_status` attribute → `{"error": "budget module not available"}`
  - On exception inside `budget_status()` → `{"error": "budget read failed: <exc>"}`
- `GET /api/diagnostics` → `vox.web.diagnostics.snapshot()`
  - On missing module → `{"error": "diagnostics module not available"}`
  - On exception inside `snapshot()` → `{"error": "diagnostics read failed: <exc>"}`

All paths return **HTTP 200** with a JSON object; the dashboard treats an
`{"error": ...}` body as "feature unavailable / degraded".

### Decisions

- **`/api/budget` uses `_try_import("usage")` + `hasattr` guard** rather than the
  eagerly-imported top-level `usage`. The bridge imports `usage` at module load,
  but `budget_status()` is added by the budget agent in a parallel iteration. The
  `hasattr` check means that if `budget_status` isn't present yet, the route still
  degrades gracefully to the "not available" object instead of raising
  `AttributeError`. Once the budget agent lands `budget_status()`, the route lights
  up automatically with no further change here.
- **`/api/diagnostics` uses `_try_import("diagnostics")`** — that module doesn't
  exist in the eager imports, so the standard guarded lazy import applies.
- Both are read-only GETs with no request body, so no `_json_body` / validation
  helpers are needed. Response shape is owned by the budget/diagnostics agents per
  CONTRACT; this layer is a thin guarded pass-through.
- Mounted **before** `_mount_static(app)` so the SPA catch-all (`/{full_path:path}`)
  never shadows them — consistent with every other `/api/*` route.

### How to verify

```bash
# Missing modules → safe defaults, HTTP 200 (no budget/diagnostics impl present)
uv run python -c "
from fastapi.testclient import TestClient
from vox.web.server import create_app
c = TestClient(create_app())
for p in ('/api/budget', '/api/diagnostics'):
    r = c.get(p); print(p, r.status_code, r.json())
"

# Working + raising implementations both stay HTTP 200
uv run python -c "
import sys, types
from fastapi.testclient import TestClient
import vox.web.usage as u
u.budget_status = lambda: {'limitUsd': 50.0, 'spentUsd': 12.3, 'remainingUsd': 37.7}
d = types.ModuleType('vox.web.diagnostics'); d.snapshot = lambda: {'pythonOk': True}
sys.modules['vox.web.diagnostics'] = d
from vox.web.server import create_app
c = TestClient(create_app())
print(c.get('/api/budget').json(), c.get('/api/diagnostics').json())
u.budget_status = lambda: (_ for _ in ()).throw(RuntimeError('boom'))
d.snapshot = lambda: (_ for _ in ()).throw(RuntimeError('kaboom'))
c2 = TestClient(create_app())
print(c2.get('/api/budget').status_code, c2.get('/api/budget').json())
print(c2.get('/api/diagnostics').status_code, c2.get('/api/diagnostics').json())
"
```

### TODOs / dependencies

- Response shapes for both routes are defined and owned by the **budget** and
  **diagnostics** agents. The corresponding TS types in `dashboard/src/lib/api.ts`
  and the new API routes in CONTRACT.md should be added by the integration agent —
  this server change is intentionally additive and shape-agnostic.

## Iteration 7 — cost budget (`settings_store.py` + `usage.py`)

A monthly spend budget the dashboard can read to render a budget meter and
warn/over states. Backend-only here (no new routes); the integration agent wires
the `/api/usage/budget` route + the `BudgetStatus` TS type.

### `settings_store.py` — new "Cost" setting group

One new schema entry (additive — slotted before the Debug group):

| key | group | type | default | help |
| --- | --- | --- | --- | --- |
| `monthly_budget_usd` | Cost | text | `"0"` | Monthly spend budget in USD; 0 = no budget. |

- **`text`, not a number type** — the `Setting` schema only has `toggle|select|text`
  (CONTRACT), so the budget rides as text and `_coerce` keeps the existing `str(...)`
  validation (rejects `null`). `budget_status()` does the numeric parse/guard.
- **Default "0" = no budget.** `Config` has no `monthly_budget_usd` attribute, so an
  un-set `get("monthly_budget_usd")` returns `None`; `_budget_usd()` treats `None`,
  blank, non-numeric, and negative all as 0.0 → the safe "no budget" default. The
  contract's "default 0" surfaces via `budget_status()`/the meter, not a Config attr.
- SCHEMA validation is unchanged: unknown keys and `null` text still raise
  `SettingError` (→ 400 at the route).

### `usage.py` — `budget_status()`

```py
budget_status() -> {budgetUsd, spentUsd, remainingUsd, percent, state}
```

- `budgetUsd`    — monthly budget from `settings_store.get("monthly_budget_usd")`,
  float-coerced and guarded (0.0 when unset/blank/garbage/negative or the store
  can't be imported/read).
- `spentUsd`     — month-to-date total `costUsd`, summed over events whose `ts`
  falls in the **current UTC calendar month** (`_month_to_date_cost`).
- `remainingUsd` — `budgetUsd - spentUsd` (0.0 when no budget; **may go negative**
  when over budget — the meter shows the overspend).
- `percent`      — `spent/budget*100`, clamped to 0-100 for display (0.0 when no
  budget). `state` is decided from the *raw* (un-clamped) percent so 120% still reads "over".
- `state`        — `none` (budget 0) · `ok` · `warn` (raw% >= 80) · `over` (raw% >= 100).

Guard/None-safety decisions:

- **Lazy import of `settings_store`** inside `_budget_usd()` keeps `usage.py`
  importable standalone and avoids an import cycle; any import/read failure → 0.0.
- **None-safe everywhere** — a missing/garbage `ts` falls back to this month via
  `_month_key`; a `None`/non-numeric `costUsd` is skipped, not summed.
- **No new persistence, no new state** — `budget_status()` is a pure read over the
  existing ledger + settings store. The voice daemon never calls it; it doesn't
  touch `record_usage`, so recording stays best-effort and the daemon is untouched.

### Verify

```bash
# schema: new key present, grouped Cost, in all()
uv run python -c "from vox.web import settings_store as s; \
m=next(x for x in s.SCHEMA if x['key']=='monthly_budget_usd'); print(m['group'], m['type']); \
print('monthly_budget_usd' in {x['key'] for x in s.all()})"
# expect: Cost text  /  True

# validation still rejects unknown keys + null text
uv run python -c "from vox.web import settings_store as s; \
import contextlib
for k,v in [('nope','1'),('monthly_budget_usd',None)]:
    try: s.set(k,v); print('NO RAISE', k)
    except s.SettingError: print('rejected', k)"
# expect: rejected nope  /  rejected monthly_budget_usd

# no budget -> state none, percent 0 (default)
uv run python -c "from vox.web import usage as u; print(u.budget_status())"
# expect: {'budgetUsd':0.0,'spentUsd':<mtd>,'remainingUsd':0.0,'percent':0.0,'state':'none'}

# thresholds (mocked ledger + budget): 50->ok 85->warn 120->over
uv run python -c "
from unittest.mock import patch
from datetime import datetime, timezone
from vox.web import usage as u, settings_store as s
ts=datetime.now(timezone.utc).strftime('%Y-%m-15T12:00:00+00:00')
for spend,want in [(50,'ok'),(85,'warn'),(120,'over')]:
    with patch.object(u,'_read_all',return_value=[{'ts':ts,'costUsd':spend}]), patch.object(s,'get',return_value='100'):
        print(spend, u.budget_status()['state'])"
# expect: 50 ok / 85 warn / 120 over
```

> Any `data/settings.json` override written while verifying is gitignored runtime
> data — clear the `monthly_budget_usd` key via `settings_store.set(... '0')` or by
> editing the file; don't delete the file (it may hold real user overrides).

---

## Memory v2 (tiered) + MCP integration routes — `server.py`

> Added by the bridge-routes agent. Owns `src/vox/web/server.py` only. All routes
> are **additive + guarded**: lazy imports inside `try/except`, safe `{error}`/`[]`
> bodies on a missing/half-built module, HTTP 200 even when a feature isn't wired
> yet. The voice daemon runs unchanged if memory/web is absent. See
> `docs/dashboard/MEMORY_DESIGN.md` for the v1 memory contract these realise.

### New endpoints

| Method | Path | Returns | Notes |
|--------|------|---------|-------|
| GET  | `/api/memory/core` | `Memory[]` | All curated core entries (`memory.core()`). `[]` if the tiered API is absent. |
| GET  | `/api/memory/daily?date=YYYY-MM-DD` | `Memory[]` | `memory.daily(date)`; omitted/empty `date` → module default (latest/today). Unknown date → `[]`. |
| GET  | `/api/memory/dates` | `string[]` | Dates that have a daily log (`memory.dates()`), newest-first per the module. |
| POST | `/api/memory/reveal` | `{ok, path?}` / `{ok:false, error}` | Reveals `data/memory/` in Finder via `open -R <abs path>`. Creates the dir if missing. Off-mac (no `open`) → `{ok:false}`, never 500. |
| GET  | `/api/mcp/config` | `{cursor, claudeAdd, repoRoot}` / `{error}` | vox-speak MCP setup for **this** machine; repo root computed from the server file location, never hardcoded. |

### Extended endpoints (back-compatible)

- **`POST /api/memory`** now accepts an optional **`tier`** (`"core"` / `"daily"`).
  Tier is forwarded only when the underlying `memory.add` advertises a `tier`
  keyword (detected via `inspect.signature`); `tags` is always passed by keyword
  on a tiered module so it can never bind to the `tier` positional slot. On a v1
  store (no `tier` param) the call degrades to `add(text, tags)`. A `TypeError`
  from an unexpected signature also retries the v1 shape. Body:
  `{text, tags?: string[], tier?: "core"|"daily"}`.
- **`DELETE /api/memory/{id}`** unchanged at the call site but now deletes **across
  tiers** — `memory.remove(id)` in v2 searches every tier; v1 searches its single
  ledger. Missing id → 404.

### `GET /api/mcp/config` shape

```jsonc
{
  "cursor": {                         // the .cursor/mcp.json mcpServers block, as an object
    "vox-speak": {
      "command": "uv",
      "args": ["run", "python", "-m", "vox.mcp.speak"],
      "cwd": "<ABS REPO ROOT>"        // real path, computed at runtime
    }
  },
  "claudeAdd": "claude mcp add vox-speak --cwd <ABS REPO ROOT> -- uv run python -m vox.mcp.speak",
  "repoRoot": "<ABS REPO ROOT>"
}
```

- The absolute repo root is `Path(__file__).resolve().parents[3]` (`_REPO_ROOT`) —
  **never a hardcoded personal path**. Committed docs must use
  `/ABSOLUTE/PATH/TO/vox-controller`; the real path only ever appears in the live
  API response and the UI.
- If a real `.cursor/mcp.json` exists on disk, its `mcpServers` block is surfaced
  verbatim **with `cwd` patched to the real root** (so committed placeholder paths
  can't leak). Otherwise the canonical vox-speak block above is generated.
- `vox-speak` is idea #34 — an MCP server that speaks finished-work announcements
  through the system TTS. The launch command (`python -m vox.mcp.speak`) is a
  forward reference; the config is informational setup text, so the route works
  whether or not that module exists yet.

### Helpers added (module-level, private)

- `_memory_supports_tier(mod)` — `True` if `mod.add` has a `tier` parameter.
- `_memory_dir()` — abs path to `data/memory/`, preferring the memory module's own
  `path_for("core")` parent / `MEMORY_DIR` / `DATA_DIR`, else `<repo>/data/memory`.
- `_mcp_config()` — builds the `{cursor, claudeAdd, repoRoot}` payload.

New stdlib imports: `json`, `shutil`, `subprocess`.

### Verify

```bash
# All new routes against whatever memory module is present (v1 or v2), via TestClient.
uv run python -c "
from fastapi.testclient import TestClient
from vox.web.server import create_app
c = TestClient(create_app())
print('core ', c.get('/api/memory/core').status_code, type(c.get('/api/memory/core').json()).__name__)
print('daily', c.get('/api/memory/daily').status_code)
print('dates', c.get('/api/memory/dates').status_code)
print('reveal', c.post('/api/memory/reveal').json().get('ok') in (True, False))
cfg = c.get('/api/mcp/config').json()
print('mcp repoRoot endswith vox-controller:', cfg['repoRoot'].endswith('vox-controller'))
print('mcp cursor has vox-speak:', 'vox-speak' in cfg['cursor'] or bool(cfg['cursor']))
"
# expect: core 200 list / daily 200 / dates 200 / reveal True / repoRoot True / cursor True

# Tiered round-trip (v2 module): core POST lands in core, deletes across tiers.
uv run python -c "
from fastapi.testclient import TestClient
from vox.web.server import create_app
c = TestClient(create_app())
r = c.post('/api/memory', json={'text':'verify core','tier':'core','tags':['t']})
mid = r.json().get('id'); print('tier stored:', r.json().get('tier'))
print('in core:', any(e['id']==mid for e in c.get('/api/memory/core').json()))
print('delete:', c.delete('/api/memory/'+mid).json())
"
# expect: tier stored: core (on v2) / in core: True / delete: {'ok': True}
```

> `POST /api/memory/reveal` opens Finder on a dev Mac — harmless, but expect a
> Finder window. Runtime memory data under `data/memory/` is gitignored.

---

## Memory auto-capture + recall wiring (`assistant.py`, `settings_store.py`)

Wires the tiered Markdown memory store (see `MEMORY_DESIGN.md`) into the live voice
brain: the model can **auto-capture** durable/contextual facts and Vox **recalls**
them into later turns. Everything additive and try/except-guarded — if the memory or
settings modules are missing or broken, the daemon behaves exactly as before.

### `settings_store.py` — new toggle

Added `memory_autocapture` to `SCHEMA` (group **Behavior**, type `toggle`). It has no
`Config` attribute, so an unset value reads as `None` and the assistant's `_setting`
helper falls back to **`True`** (auto-capture on by default, as the design requires).
The dashboard writes the override to `data/settings.json`; the toggle takes effect on
the next turn (no restart).

### `assistant.py` — capture + recall

All new helpers are lazy-importing and guarded; a failure is a silent no-op.

- **`_autocapture_on()`** — `bool(_setting("memory_autocapture", True))`; the single
  gate for every capture path. Guarded → `True` when the settings store is absent.
- **`_mem_add(text, tier)`** — saves one memory. Calls `memory.add(text, tier=...)`
  (tiered store) and falls back to `memory.add(text)` on `TypeError` (legacy flat
  store). No-op on empty text or a missing module.
- **`_capture_from_reply(reply)`** — parses `MEMORY[core]: <fact>` / `MEMORY[daily]:
  <note>` directives (regex `_MEMORY_DIRECTIVE`, one per line), stores each at its
  tier (gated on the toggle), and **strips the directive lines from the reply** so they
  are never shown or spoken. A trailing `[OPEN]/[DONE]/[BIG]` turn-tag sharing the
  directive's line is scrubbed from the stored fact. Stripping happens even when
  capture is off, so the syntax never leaks. Fast-paths out when `"MEMORY["` isn't
  present.
- **`_capture_from_user(user_text)`** — handles an explicit **"remember that X" /
  "remember to X"** → stores `X` to **core**; a bare **"remember this/that"** stores the
  whole utterance to core. Gated on the toggle.
- **`_memory_block(user_text)`** (rewritten) — injects **all core memories** under
  *"What you always remember about the user:"* plus the **top relevant daily entries**
  under *"Recent notes that may be relevant…"*. Uses `memory.core()` + `memory.recall(
  user_text, k=5)` when available; a recall hit tagged `tier == "core"` is folded into
  the core section (deduped, never shown twice). Falls back to the legacy single-block
  *"Things you remember about the user"* when the store exposes no `core()`/`tier`
  (back-compat). Empty string on any error.
- **System prompt** — a short "Memory:" paragraph tells the model it can remember
  across conversations and to append `MEMORY[core|daily]: …` **sparingly**, with the
  core-vs-daily rule from `MEMORY_DESIGN.md` (core = rare, durable, high-signal; daily
  = passing/contextual; don't repeat what it already remembers).

**Wiring point:** `respond_turn` calls `_capture_from_user(text)` then
`raw = _capture_from_reply(raw)` *before* `_split_signal`, so directives are stripped
ahead of turn-tag parsing and the cleaned reply is what's shown/spoken. Recall is
layered in the existing `_rules_block()/_memory_block()` loop that builds the system
prompt — unchanged call site, richer block.

### Guarantees

- Missing/broken `vox.memory` → `_memory_block` returns `""`, captures no-op; reply
  unchanged.
- Missing/broken `vox.web.settings_store` → `_autocapture_on()` returns `True`
  (capture works out of the box) and recall still functions.
- A `MEMORY[...]` directive **never** leaks into shown/spoken text, on or off.
- Works against **both** the tiered store (current) and the legacy flat store.

### Verify

```bash
# schema: toggle present, Behavior group, in all()
uv run python -c "from vox.web import settings_store as s; \
m=next(x for x in s.SCHEMA if x['key']=='memory_autocapture'); print(m['group'], m['type']); \
print('memory_autocapture' in {x['key'] for x in s.all()})"
# expect: Behavior toggle  /  True

# default gating is True when unset
uv run python -c "from vox.web import settings_store as s; \
ov=s._load_overrides(); ov.pop('memory_autocapture',None); s._save_overrides(ov); \
import vox.assistant as a; print(a._autocapture_on())"
# expect: True

# directive parse + strip (does NOT leak the syntax or the [DONE] tag)
uv run python -c "import vox.assistant as a; \
print(repr(a._capture_from_reply('Done.\nMEMORY[core]: name is Dan\nMEMORY[daily]: note [DONE]')))"
# expect: 'Done.'   (and two entries added: 1 core, 1 daily — clean up __TEST__ rows if you seed them)

# recall block: core section + daily section, core not duplicated
uv run python -c "import vox.assistant as a; print(a._memory_block('cursor'))"
```

> Capture writes real entries to `data/memory/` (gitignored). When verifying live,
> prefix test facts with `__TEST__` and delete them via `vox.memory.remove(id)`.
