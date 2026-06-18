# Vox Dashboard — Build Contract

> Single source of truth for the dashboard build. **Every agent (in every iteration) reads this first and follows it EXACTLY** — file paths, names, API routes, and data shapes — so parallel work stays coherent. Additive only: never break the existing voice daemon.

## Product

A local, cross-platform web dashboard ("Vox Control Center") for the existing macOS voice assistant. Opened hands-free by a wake phrase ("open dashboard"). Premium, dark-first, animated. Shows live token usage/cost, lets you toggle brains/providers and feature flags, manage personalities + rules + memory, and visualise the focused app's accessibility (AX) tree (read-only — no UI interaction yet).

## Stack (fixed)

- **Frontend:** Vite + React 18 + TypeScript + TailwindCSS + **shadcn/ui** (hand-write component source under `src/components/ui/` — do NOT run the CLI/network) + **Animate UI** (hand-write under `src/components/animate/`). Charts: `recharts`. Icons: `lucide-react`. Data: `@tanstack/react-query` + a thin typed fetch client. Live updates via WebSocket.
- **Backend bridge:** **FastAPI + uvicorn**, added to the existing Python package. Serves REST under `/api`, a WS at `/api/usage/stream`, and the built frontend (`dashboard/dist`) as static files at `/` with SPA fallback. Add deps with `uv add fastapi "uvicorn[standard]"`.
- **Runtime data:** JSON / JSONL under `data/` (already gitignored). Never commit runtime data or secrets.

## File layout

```
dashboard/                         # Vite React app (new)
  package.json vite.config.ts tsconfig*.json index.html
  tailwind.config.ts postcss.config.js components.json .gitignore
  .env                             # VITE_API_BASE=http://127.0.0.1:8765
  src/main.tsx src/App.tsx src/index.css   # index.css holds theme tokens
  src/lib/api.ts                   # typed client + ALL TS types (mirror shapes below)
  src/lib/utils.ts                 # cn()
  src/components/ui/*              # shadcn source (button card switch tabs input select slider dialog badge ... )
  src/components/animate/*        # Animate UI (animated counter, fade/spring wrappers, ...)
  src/components/layout/*         # AppShell SideNav TopBar
  src/pages/{Overview,TokenUsage,Settings,Personalities,AxTree,Rules,Memory}.tsx
  src/hooks/*                     # useUsageStream, useApi, ...
src/vox/web/                       # Python bridge (new)
  __init__.py
  server.py        # create_app()->FastAPI ; run(host,port) ; start_in_background(cfg)->daemon Thread ; python -m vox.web.server runnable
  usage.py         # record_usage(...) ; recent(limit) ; summary() ; PRICES ; WS subscribers ; persists data/usage.jsonl
  settings_store.py# SCHEMA ; get(key) ; set(key,value) ; all() ; persists data/settings.json (overrides over Config)
  axtree.py        # snapshot()->dict ; macOS System Events, READ-ONLY ; graceful {error:...} off-mac/on-failure
  personalities.py # PRESETS ; all()->{active,presets,custom} ; set_active(id) ; add_custom(...) ; remove_custom(id) ; persists data/personalities.json
  rules.py         # list_rules() ; add_rule(text) ; update_rule(id,**) ; remove_rule(id) ; persists data/rules.json
src/vox/memory.py  # add(text,tags=[]) ; recall(query,k=5) ; all() ; remove(id) ; keyword scoring now (pluggable for embeddings) ; persists data/memory.jsonl
docs/dashboard/*   # one doc per area; CONTRACT.md (this) ; BUILD_LOG.md (roadmap/status)
```

### Existing files — edited ONLY by the single "integration" agent in any given iteration (additive)
- `config.py`: add `dashboard_enabled: bool=True`, `dashboard_host:str="127.0.0.1"`, `dashboard_port:int=8765`, `open_dashboard_phrases: tuple=(...)` ("open dashboard", "open the dashboard", "show dashboard", "launch dashboard", "open vox dashboard"). Remove nothing.
- `wakeword/backends.py` (`make_backend`): add label `("dashboard", cfg.open_dashboard_phrases)`.
- `core/loop.py`: on startup, `vox.web.server.start_in_background(cfg)` (guarded, non-fatal). Handle the `"dashboard"` wake label → open browser to `http://{host}:{port}` (webbrowser.open). 
- `assistant.py`: after each provider call (`_anthropic`,`_openai`,`_claude_sdk`,`_anthropic_look`,`_sdk_look`) record usage via `vox.web.usage.record_usage(...)`; read brain provider/model via `settings_store.get(...)` falling back to Config.
- `executor.py`, `actions.py`: read relevant feature flags via `settings_store.get(...)` where it makes toggles take effect on the next call.

## API (REST under `/api`, JSON; camelCase fields)

- `GET /api/status` → `{running, mode, smallBrain:{provider,model}, bigBrain:{provider,model}, personality, uptimeSeconds}`
- `GET /api/usage/recent?limit=100` → `UsageEvent[]`
- `GET /api/usage/summary` → `{totals:{calls,inputTokens,outputTokens,costUsd}, byModel:[{model,provider,calls,inputTokens,outputTokens,costUsd}], byDay:[{date,costUsd,inputTokens,outputTokens}]}`
- `WS  /api/usage/stream` → pushes a `UsageEvent` per call as it happens
- `GET /api/settings` → `Setting[]` ; `POST /api/settings` `{key,value}` → `{ok,value}`
- `GET /api/personalities` → `{active, presets:Personality[], custom:Personality[]}` ; `POST /api/personalities/active` `{id}` ; `POST /api/personalities/custom` `{name,persona,emoji?,suggestedVoice?}` ; `DELETE /api/personalities/custom/{id}`
- `GET /api/rules` → `Rule[]` ; `POST /api/rules` `{text}` ; `PATCH /api/rules/{id}` `{enabled?,text?}` ; `DELETE /api/rules/{id}`
- `GET /api/memory?query=&limit=` → `Memory[]` ; `POST /api/memory` `{text,tags?}` ; `DELETE /api/memory/{id}`
- `GET /api/axtree` → `{app, capturedAt, tree:AxNode}` or `{error}`

## Data shapes (TS types in `lib/api.ts` MUST match Python responses)

- `UsageEvent` = `{id, ts, provider, model, brain:"small"|"big", kind:"chat"|"command"|"vision"|"rewrite", inputTokens, outputTokens, costUsd, latencyMs}`
- `Setting` = `{key, label, group, type:"toggle"|"select"|"text", value, options?:{value,label}[], help}`
- `Personality` = `{id, name, emoji, tagline, persona, suggestedVoice?, preset:boolean}`
- `Rule` = `{id, text, enabled}`
- `Memory` = `{id, ts, text, tags:string[], score?}`
- `AxNode` = `{role, title?, value?, enabled?, children:AxNode[]}`

## Settings exposed (keys map to Config / settings_store)

`small_brain_provider` (select: claude_sdk|anthropic|openai|claude_cli) · `small_brain_model` (text) · `big_brain_provider` (select) · `big_brain_model` (text) · `escalate_to_big_brain` (toggle) · `escalation_mode` (select: auto|keywords) · `llm_executor_enabled` (toggle) · `screen_vision_enabled` (toggle) · `tts_enabled` (toggle) · `barge_in_enabled` (toggle) · `dictation_exit_on_silence` (toggle) · `debug` (toggle). Group them sensibly (Brains / Behavior / Voice / Debug). Note in the UI which need a restart.

## Token pricing (`usage.PRICES`, $ per 1M tokens — approximate, editable)

`claude-haiku-4-5-*`: (1.00, 5.00) · `claude-opus-4-8`: (5.00, 25.00) · `deepseek-chat`: (0.27, 1.10). SDK/subscription calls: record tokens if the SDK exposes them, cost shown as subscription (0) with a note. Unknown model → (0,0) + flag.

## Personalities (presets — flesh out persona text)

Posh Butler 🤵 · Batman 🦇 · J.A.R.V.I.S. 🤖 · The Philosopher 🧠 · Film-Noir Detective 🕵️ · Surfer (chill) 🏄 · Shakespearean Bard 🎭 · Sherlock Holmes 🔍. Each: a tight system-prompt persona that stays helpful, plus a suggested macOS `say` voice. Custom personalities editable in the UI, persisted, and applied to the live `personality` config.

## Theme / craft

Dark-first premium "AI control center" (think Linear × Vercel × Arc). zinc-950 base, glassy cards (backdrop-blur + hairline border), a tasteful accent gradient (violet→cyan; you may choose), Inter/Geist, rounded-2xl, soft shadows. Animate UI micro-interactions: animated number counters for tokens/cost, spring tab/page transitions, staggered fade-in lists, a live "listening" pulse. Optional light-theme toggle if cheap. Be creative but cohesive and professional.

## Rules for every agent

Additive only; never break the daemon. Match existing code style (see `CLAUDE.md`: simplicity, surgical changes, no speculative abstractions). Follow this contract's paths/signatures exactly. Runtime data under `data/`. **Never run git** (the orchestrator commits). Document your part under `docs/dashboard/`. Return a concise markdown summary (files touched, decisions, TODOs, how to run/verify) — your return text is data, not chat.
