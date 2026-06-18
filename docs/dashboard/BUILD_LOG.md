# Vox Dashboard — Build Log & Roadmap

> Durable state for the 10-iteration build loop on the `staging` branch. Each iteration = one background **workflow** of subagents, then one commit `dashboard iteration N/10: <focus>`. The orchestrator reads this file + `git log` to know where the loop is, so progress survives context summarization. Read `CONTRACT.md` for the architecture.

**Branch:** `staging` (never pushed to `main`). **Started:** 2026-06-18.

## How the loop runs
1. Run the iteration's workflow (agents write files per `CONTRACT.md`, never commit).
2. When it finishes: quick verify, append an entry under "Progress" below, then commit `dashboard iteration N/10: <focus>`.
3. If N < 10 → launch the next iteration. After iteration 10 → finalize.
- Idempotency: on each wake, count `dashboard iteration N/10` commits in `git log` and check for an in-flight workflow before launching another.

## Roadmap (adapt as you learn — creativity encouraged)
1. **Foundation** — research (memory / AX-tree / UI) + FastAPI bridge skeleton (`/api/status`, server, usage+settings stubs with real signatures) + Vite/React/shadcn/Animate UI shell with SideNav + working **Overview** page (live daemon status) + `open dashboard` wake phrase. Runnable skeleton.
2. **Token usage & cost** — instrument all LLM calls, usage store + WS stream, **Token Usage** page (animated counters, charts, per-model/day breakdown, live feed).
3. **Settings** — runtime settings store wired so toggles take effect; **Settings** page (brain provider/model API-vs-SDK, escalation mode, feature flags).
4. **Personalities** — presets + custom editor, wired to live `personality`; **Personalities** page with persona previews.
5. **AX-tree visualization** — read-only macOS AX tree reader + **AX Tree** page (searchable, collapsible tree, refresh/auto-refresh).
6. **Rules & Memory** — rules CRUD + scaffolded memory system (OpenClaw/Hermes-inspired) with add/recall; **Rules** + **Memory** pages.
7. **Creative round 1** — invent useful features (e.g. live activity/conversation timeline, command palette, quick brain-switcher, cost-budget alerts, voice/persona live preview, listening waveform).
8. **Creative round 2 + polish** — themes/skins, keyboard shortcuts, onboarding, personality playground, animations, empty/error states.
9. **Hardening & integration** — real end-to-end run (daemon + dashboard together), error handling, cross-platform graceful degradation, fix prior-iteration bugs, build the frontend.
10. **Finalize** — full docs + README + run steps, final build + smoke test, changelog/demo script.

## Visual QA (Playwright) — the orchestrator can SEE the UI; use it
After any iteration that changes the frontend (from iteration 2 on, once real pages exist), the orchestrator runs a visual pass itself (more reliable than a headless subagent):
1. One-time: `cd dashboard && npm install` (disk ~13GB free — fine). Bring this forward from the old "iteration 9" plan.
2. Background: `uv run python -m vox.web.server` (bridge) **and** `cd dashboard && npm run dev` (Vite on http://localhost:5173, proxies /api → 8765).
3. Load Playwright MCP via ToolSearch: `select:mcp__plugin_playwright_playwright__browser_navigate,mcp__plugin_playwright_playwright__browser_take_screenshot,mcp__plugin_playwright_playwright__browser_snapshot,mcp__plugin_playwright_playwright__browser_resize`. Navigate to each page, screenshot, and actually LOOK (resize for desktop + mobile widths).
4. Write a short visual critique (what's good / off / broken) into that iteration's Progress entry, and pass it into the NEXT iteration's workflow as concrete design feedback.
5. Stop the dev server afterward.
Goal: make it genuinely look professional and cool — confirmed by eye, then improved.

## Progress

### Iteration 1 — Foundation (2026-06-18)

**Built**
- FastAPI bridge `src/vox/web/` — `server.py` (`create_app`/`run`/`start_in_background`, 18 `/api/*` routes, WS `/api/usage/stream`, static `dashboard/dist` + SPA fallback, `python -m vox.web.server`), `usage.py` (UsageEvent ledger → `data/usage.jsonl`, PRICES, cross-thread WS fan-out), `settings_store.py` (12-key SCHEMA, override layer over Config → `data/settings.json`).
- Daemon integration (additive, guarded): `config.py` `dashboard_*` fields + `open_dashboard_phrases`; `wakeword/backends.py` `("dashboard", …)` wake label; `core/loop.py` starts the bridge on a daemon thread and routes "open dashboard" → `webbrowser.open`; `assistant.py` records usage after each provider call and reads brain provider/model via `settings_store.get` with Config fallback.
- Frontend shell `dashboard/` — hand-written Vite + React 18 + TS + Tailwind + shadcn/ui + Animate UI (51 files): theme tokens, typed API client + all data-shape types, AppShell/SideNav/TopBar, fully-working live `/api/status` Overview, titled placeholders for the other 6 pages.
- Docs: `01-foundation.md`, `backend.md`, `integration.md`, `frontend.md`.

**Decisions**
- Zero top-level `vox.web` imports in daemon files — every touch point is a lazy import inside try/except, so the voice daemon runs unchanged when `vox.web.*` is missing or half-built (verified with only `axtree.py` present).
- Backend always boots: `create_app` imports only `usage` + `settings_store`; personalities/rules/memory/axtree are lazily imported per-request and return safe empty/placeholder data instead of 500.
- WS fan-out binds each subscriber's queue to its event loop and publishes via `call_soon_threadsafe`, so `record_usage` from the voice thread reaches WS clients losslessly.
- Settings are an override layer (changed keys only) over the frozen Config; only brain provider/model are read back by the daemon in iter 1, taking effect on the next LLM call without a restart.
- Subscription providers (`claude_sdk`/`claude_cli`) record tokens at cost 0; pricing resolves by exact id then prefix; same-origin `/api` by default with a Vite proxy for dev.

**Next (Iteration 2 — Token usage & cost)**
- Build the Token Usage page: `useUsageStream` on `WS /api/usage/stream`, animated `SlidingNumber` counters, recharts per-model/per-day breakdowns, live feed.
- Refine SDK/subscription token extraction to the live SDK shape; verify `record_usage` against real provider calls end-to-end.
- Confirm cost rendering for subscription (0) vs metered calls and the `data/usage.jsonl` read path.
