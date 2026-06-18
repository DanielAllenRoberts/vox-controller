# Vox Dashboard — Build Log & Roadmap

> Durable state for the 10-iteration build loop on the `staging` branch. Each iteration = one background **workflow** of subagents, then one commit `dashboard iteration N/10: <focus>`. The orchestrator reads this file + `git log` to know where the loop is, so progress survives context summarization. Read `CONTRACT.md` for the architecture.

**Branch:** `staging` (never pushed to `main`). **Started:** 2026-06-18.

## ✅ BUILD COMPLETE (2026-06-18)
The dashboard is finished and committed to `staging` across 8 iterations: foundation → token usage & cost → settings → personalities → AX-tree/rules/memory/command-palette blitz → audit & refine → creative features (budgets, theme, shortcuts, diagnostics) → finalize (README + typed-client tidy + final QA). Final visual QA passed in both dark and light themes; build + daemon-import + bridge smoke all clean; `main` untouched. README at `docs/dashboard/README.md`. **The build loop is STOPPED — if a scheduled wakeup fires after this, confirm no workflow is in-flight and do nothing (do not re-arm, do not launch more work).** Open TODOs are minor and listed in the iteration entries below (rules unknown-id 400-vs-404; vite >500 kB chunk; AX-tree depth/breadth query params; memory auto-capture).

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

### Iteration 2 — Token usage & cost (2026-06-18)

**Built**
- Token Usage page (`dashboard/src/pages/TokenUsage.tsx`, replaced the ComingSoon stub): animated summary counters (violet→cyan hero cost), recharts cost-over-time area chart + tokens-by-model bar chart, and a WS-driven live feed that prepends rows.
- New frontend pieces: `hooks/useUsageStream.ts` (parses raw camelCase `UsageEvent` JSON straight from `WS /api/usage/stream`, seeds from REST `usage/recent`, dedupes by `id`, 2s reconnect backoff), `hooks/useNow.ts`, `components/usage/LiveFeed.tsx` (shared by both pages), `components/usage/KindBadge.tsx`; shared formatters in `lib/utils.ts`.
- Overview polish (`dashboard/src/pages/Overview.tsx`): kept all 6 status cards, added today's-cost + sparkline, live feed, quick-action chips over a radial glow; renders "Default" when `personality` is empty.
- Backend token capture: `web/usage.py` adds `is_subscription_call()` and `maybe_seed_dev()` (+`_DEV_SEED_EVENTS`), `record_usage` now preserves `None` token counts as `null` (subscription) distinct from a true 0-token call, and `summary()`/byModel/byDay made None-safe; `web/server.py` `create_app()` calls `usage.maybe_seed_dev()` (guarded, gated on `VOX_DEV_SEED=1`); `assistant.py` adds `_sdk_extract_tokens(msg)` keyed off the claude-agent-sdk `ResultMessage` (`total_cost_usd` presence), recording `None` when tokens are absent.
- Docs: appended "Iteration 2" sections to `docs/dashboard/frontend.md` and `docs/dashboard/backend.md`.

**Decisions**
- WS pushes raw camelCase `UsageEvent` JSON, so `useUsageStream` parses straight into the TS type with no mapping layer.
- Subscription providers (`claude_sdk`/`claude_cli`) persist `inputTokens: null`/`outputTokens: null` (not 0) and render a subtle "subscription" badge instead of `$0.00`, so the UI distinguishes subscription from a genuine 0-token request.
- Token extraction keys off the `ResultMessage` (the message carrying cumulative usage) rather than reading `usage` off every message, which previously also captured per-turn `AssistantMessage` usage; `_anthropic`/`_openai` already pass correct `(input,output)` tuples and were left unchanged.
- No new deps — `recharts` and `motion` were already in `package.json`; charts use theme-matched HSL literals. All telemetry stays guarded so it can never break a reply.

**Verify**
- `cd dashboard && npx tsc -b --noEmit` clean for touched files (3 pre-existing TS6133 unused-`React` errors in `components/animate/{FadeIn,Spring,Stagger}.tsx` are unrelated and left as-is); `npm run build` succeeds with recharts/motion bundled (~826kB).
- Backend three files `py_compile` clean; `ResultMessage` extraction, `AssistantMessage` exclusion, None-subscription recording, None-safe `summary()`, cross-thread WS delivery, dev-seed guard/idempotency, and FastAPI app build all tested green; runtime `data/usage.jsonl` restored to its original single row. No git run.

**Known gaps / TODOs**
- Sparkline needs ≥2 days of `byDay` data (flat baseline until then); bundle could be code-split later.
- `/api/status.mode` still hardcoded `"idle"`; `usage.PRICES` are approximate; frontend should render `inputTokens: null` as "subscription" everywhere.

**Next (Iteration 3 — Settings)**
- Wire the runtime settings store so toggles take effect live; build the Settings page: brain provider/model (API vs SDK), escalation mode, feature flags.

### Iteration 3 — Settings (2026-06-18)

**Built**
- Settings page (`dashboard/src/pages/Settings.tsx`, replaced the ComingSoon stub): GET `/api/settings` drives four grouped glass cards (Brains / Behavior / Voice / Debug) in a 2-col grid, with animated Switch / Select / Input controls, restart-vs-next-call badges, and a runtime-override header. Unknown groups still render gracefully.
- Toast system (no new deps): `hooks/useToast.tsx` (dependency-free provider/queue), `components/ui/toast.tsx` (`<Toaster/>`, motion-animated glass stack honoring `useReducedMotion`), mounted via `main.tsx`. Saves use an optimistic react-query mutation (`onMutate` writes cache, `onSuccess` reflects the server's authoritative `value`, `onError` rolls back) + success/error toasts; text/model inputs commit on blur/Enter, Escape reverts.
- Backend now makes settings take effect live: `web/settings_store.py` `set()` validates against `SCHEMA` (added `SettingError(ValueError)` + `_coerce()`: toggles must be bool/`"true"`/`"false"`, selects must match options, text coerced to str, unknown keys raise); only validated overrides persist to `data/settings.json`. `web/server.py` POST `/api/settings` returns `{ok,value}` or HTTP 400 `{ok:false,error}` on `ValueError`.
- Live wiring via guarded module-local `_setting(key, fallback)` in `core/loop.py` (`escalation_mode`, `barge_in_enabled`, `dictation_exit_on_silence`) and `executor.py` (`llm_executor_enabled`, `screen_vision_enabled`); each falls back to `Config` when the store is missing/broken. `assistant.py` untouched (brains already read live).
- Docs: appended "Iteration 3" sections to `docs/dashboard/backend.md` and `docs/dashboard/frontend.md`.

**Decisions**
- Hand-rolled a tiny toast system on the existing `motion` dep rather than adding `sonner`, matching the hand-authored-components rule.
- "Needs restart" vs "applies on next call" is derived from each setting's `help` text, so the Python `SCHEMA` stays the single source of truth (no client-side key list). Only the four brain provider/model fields carry a conservative "Restart to apply" hint.
- `set` raises `SettingError` (a `ValueError` subclass) so the existing `except ValueError` in `server.py` maps to 400 without a new import. Optimistic-update mutation keeps the UI from drifting from the store.

**Live vs restart**
- Apply on next call (no restart): `escalation_mode`, `barge_in_enabled`, `dictation_exit_on_silence`, `llm_executor_enabled`, `screen_vision_enabled`, plus debug/voice toggles — read live via the guarded `_setting` reads.
- Needs restart: the four brain provider/model fields (flagged in `SCHEMA.help`).

**Verify**
- `cd dashboard && npx tsc -b --noEmit` clean; `npm run build` succeeds. Page verified live at 1440px: four grouped glass cards, animated switches, populated selects, mono inputs, restart/next-call badges, override header; a Debug toggle POSTed and persisted `{"debug": false}` to `data/settings.json` with 0 console errors; bridge-down shows the offline notice and rolls back failed saves.
- Backend: 12 settings / required keys / groups validated; `set` accepts and coerces valid toggle/str-bool/enum/text, rejects unknown key + bad enum + bad toggle, persists only overrides. TestClient: GET 200 (12), valid POST 200, bad enum 400, unknown key 400. `loop._setting`/`executor._setting` return live values and fall back on unset keys; all four daemon files `py_compile` clean. Runtime test `data/settings.json` removed after testing. No git run.

**Known gaps / TODOs**
- No per-key "reset to Config default" (no store endpoint; out of iter-3 scope); toasts are a single bottom-right region (could add undo-on-save later). Frontend should surface the 400 `error` message text on invalid input.

**Next (Iteration 4 — Personalities)**
- Build the Personalities page: presets + custom editor wired to the live `personality` setting, with persona previews.

### Iteration 4 — Personalities (2026-06-18)

**Built**
- Backend store `src/vox/web/personalities.py` (NEW): 8 code-defined presets + custom CRUD; `all() → {active, presets, custom}`, `set_active(id)`, `add_custom(...)`, `remove_custom(id)`, `get_active()`/`get_active_personality()`. Persists only `{active, custom}` to `data/personalities.json` (presets live in code, never written); fully guarded so a missing/corrupt store reverts to today's behaviour (no active persona).
- Validated routes in `web/server.py`: personalities routes now return HTTP 400 `{ok,error}` on bad id / missing name|persona (previously 500); added guarded `_apply_suggested_voice` that matches `tts_voice` on activate (no-op until `settings_store.SCHEMA` exposes that key).
- Live persona in `src/vox/assistant.py`: guarded `_active_persona()` resolves store → `CONFIG.personality` → `""`; `respond_turn` builds the system prompt from it instead of reading `CONFIG.personality` directly.
- Personalities page `dashboard/src/pages/Personalities.tsx` (full rewrite, replaced ComingSoon): two responsive galleries (Presets / Your personas) of glass persona cards — emoji avatar, name, tagline, 3-line persona preview, suggestedVoice chip. Whole card activates the persona (optimistic POST `/api/personalities/active`, rollback + toast on error). Active state = violet→cyan glow halo + accent ring + corner wash + Active badge (also in header). Create dialog (emoji/name/persona/optional macOS-say voice → POST `/personalities/custom`); hover-trash + confirm → DELETE `/personalities/custom/{id}`; premium empty state when no custom personas.
- New primitive `dashboard/src/components/ui/textarea.tsx` (shadcn-style, matches `<Input>` tokens). Reused only existing primitives + toast variants; no new deps, daemon untouched.
- Docs: appended Personalities sections to `docs/dashboard/backend.md` and `docs/dashboard/frontend.md`.

**The 8 presets** (id → emoji, suggested `say` voice)
- Posh Butler 🤵 (Daniel) — impeccable, discreet English butler.
- Batman 🦇 (Lee) — gravelly, terse, relentlessly competent.
- J.A.R.V.I.S. 🤖 (Oliver) — crisp, dry-witted AI majordomo.
- The Philosopher 🧠 (Daniel) — Socratic, reflective, lands on a concrete answer.
- Film-Noir Detective 🕵️ (Lee) — hard-boiled first-person, always cracks the case.
- Surfer 🏄 (Aaron) — chill and stoked but actually knows its stuff.
- Shakespearean Bard 🎭 (Daniel) — playful early-modern flourish, kept actionable.
- Sherlock Holmes 🔍 (Oliver) — deductive, precise, never pads.

**Decisions**
- Personas are tight 2–4 sentence system prompts that always insist on staying genuinely helpful, so character never trumps accuracy. `active` default is `""` (none); `set_active("")` deactivates; custom ids are deduped slugs vs presets+custom; removing the active custom persona clears `active`; presets can't be removed.
- API client + `Personality` types already existed in `lib/api.ts` from iter 1 — frontend-only, no contract change. Radix Select can't hold empty values, so "no voice" uses a `__none__` sentinel mapped back to `undefined`. Delete affordance on custom cards only, with `stopPropagation` so it never activates the card.
- `suggestedVoice` → `tts_voice` is applied only if the settings schema exposes `tts_voice` (it currently does not — `settings_store.SCHEMA` is owned by the settings agent), so it's a guarded no-op that lights up automatically if that key is added later, avoiding a `SettingError` and avoiding editing a file this agent doesn't own.

**Verify**
- `cd dashboard && npx tsc -b --noEmit` clean; `npm run build` succeeds. Page verified live: clicking a card moves the active ring/glow/badge instantly; "Create custom" → new card under "Your personas" persists to `data/personalities.json`; hover-trash → confirm → removed; bridge-down shows offline notice and rolls back failed activations.
- Backend: 8 presets served, GET 200, valid activate 200, unknown id 400, blank custom 400; daemon modules still import cleanly. Runtime `data/personalities.json` is gitignored — delete after testing. No git run; additive-only, daemon untouched.

**Known gaps / TODOs**
- No inline edit / PATCH of existing custom personas (create + delete only — no PATCH route in `CONTRACT.md`); emoji is a plain text input (no picker).
- Suggested-voice activation is dormant until a future iteration adds `tts_voice` to `settings_store.SCHEMA`.

**Next (Iteration 5 — AX-tree visualization)**
- Build the read-only macOS AX tree reader + AX Tree page: searchable, collapsible tree with refresh / auto-refresh.

### Iteration 5 — Feature blitz: AX-tree + Rules + Memory + Command palette (2026-06-18)

This iteration folded the roadmap's AX-tree (5) and Rules & Memory (6) work together and added a creative command palette in one parallel-agent blitz. All four features are full-stack (store/route → page) and ship additive + guarded; the voice daemon is unchanged when any `vox.web.*` store is absent, empty, or corrupt.

**AX-tree**
- Built: `src/vox/web/axtree.py` `snapshot()` returns `{app, capturedAt, tree: AxNode}` via AppleScript/`osascript` (zero new deps); iter-5 additions over the iter-1 skeleton are a per-node `enabled` bool (5th column via a guarded `enabledOf` handler, coerced and omitted when blank) and synthetic `AXTruncated` marker nodes when `MAX_DEPTH=12`/`MAX_BREADTH=40` clip the tree (human-readable titles, so the UI shows clipping instead of silently dropping). `VALUE_MAXLEN=120`, `OSA_TIMEOUT=8s`. `GET /api/axtree` in `server.py` wraps `snapshot()` so an unexpected raise becomes `{error}` not a 500. Page `dashboard/src/pages/AxTree.tsx` (replaced ComingSoon) renders the focused app's tree as an animated collapsible tree: text filter highlights matches + auto-reveals ancestors + dims non-matches, Refresh + Auto-refresh (3s `refetchInterval`) with a pulsing Live badge, Expand/Collapse-all, and distinct guided error states (off-mac / no Accessibility permission / no front window / bridge-down). Docs: `axtree.md` (backend) + `axtree-page.md` (frontend).
- Decisions: kept AppleScript over pyobjc to mirror `actions._osa` failure model; inlined the truncation-marker append inside the `walk` handler (a separate handler hit AppleScript `-10006` because the `acc` list param coerced through recursion); `snapshot()` never raises — off-mac/no-perm/no-window/missing-binary/timeout all map to `{error: str}`. Expand state keyed by node path id (`"0.2.1"`), search reveal layered non-destructively over manual toggles. No new deps.
- Verified: module compiles + runs standalone (~1s live → `{app:'Cursor', capturedAt, tree}` with `enabled` populated); forced tiny caps produced live depth markers, breadth-marker via parse path; off-mac returns `{error}`. Frontend `tsc -b --noEmit` exit 0 + prod build pass.

**Rules**
- Built: `src/vox/web/rules.py` (NEW) — guarded JSON-backed CRUD store (`data/rules.json`), `Rule = {id, text, enabled}`: `list_rules`, `add_rule(text)` (enabled defaults true; `ValueError` on blank), `update_rule(id, text=None, enabled=None, **ignored)` (updates only provided fields; ignores extra kwargs so server `**body` can't break it; `ValueError` on unknown id/blank), `remove_rule(id) -> bool`, `enabled_rules_text() -> str` (bullet block, `""` when none, never raises). `PATCH/DELETE /api/rules/{id}` in `server.py` validate input and 404 unknown ids. Page `dashboard/src/pages/Rules.tsx` (replaced ComingSoon): glass list with optimistic add / toggle / inline-edit / delete-with-confirm, active-count badge, active-rule left hairline, disabled rows dimmed+struck, premium empty/error/loading states + an explainer that enabled rules append to Vox's system prompt. Docs: `rules.md` (backend) + `rules-page.md` (frontend).
- Decisions: matched sibling style exactly (`personalities.py`/`settings_store.py`) — `RLock`, atomic temp-file writes, corrupt/missing → empty; string uuid-hex(12) ids round-trip as the server's `{rid: str}` path param; stored shape `{"rules":[...]}` but loader tolerates a bare list and drops malformed entries; additive only (routes + api client pre-wired). Optimistic mutations with cache-revert + error toast, matching the `Settings`/`Personalities` pattern.
- Verified: full CRUD + edge-case + corrupt-file test passed (`ALL OK`), shape matches CONTRACT + server/assistant callers; `Rules.tsx` typechecks clean. Test left `data/rules.json` restored to its prior (absent) state.

**Memory**
- Built: `src/vox/memory.py` was already contract-conformant from a prior iteration — verified, no code change needed; the genuine gap (the area doc) was closed at `docs/dashboard/memory.md`. API: `add(text, tags=[]) -> {id, ts, text, tags}` (append-only to `data/memory.jsonl`), `recall(query, k=5)` (top-k by `_score`, empty query → k most recent, no-match dropped), `all()` (newest-first, no score), `remove(id) -> bool` (atomic rewrite). Pluggable keyword scorer seam `_score` (+1/query-token text overlap, +2 tag match, ~0.5 decaying-recency tiebreak) — swap one function for embeddings later with no API/on-disk change. `GET/POST/DELETE /api/memory` in `server.py` (recall when `?query=` present else `all`, sliced to `?limit=`; validates text + tags-list-of-strings; 404 unknown id). Page `dashboard/src/pages/Memory.tsx` (replaced ComingSoon): list of glass memory cards (text, tag chips, relative time), composer (text + comma-separated tags with live chip preview), debounced 250ms search under a separate query key with a `score`-derived "NN% match" chip, delete-with-confirm, 6 premium states. Docs: `memory.md` (backend) + `memory-page.md` (frontend).
- Decisions: did not rescaffold the conformant module (surgical-changes rule); search uses `["memory","search",q]` rather than refetching the base list so it never clobbers it, mutations invalidate `["memory"]` to keep list+search consistent; modeled the page on `Personalities.tsx`. `data/memory.jsonl` is gitignored runtime data, untouched.
- Verified: contract snippet → `memory.py OK` plus extra assertions (no-match `[]`, `all()` newest-first + carries no score); `ast.parse` clean; tests used a temp store, real `data/` untouched. Page typecheck + prod build pass.

**Rules + Memory in the live prompt**
- Built: `src/vox/assistant.py` gained two guarded helpers (`_rules_block` → `vox.web.rules.enabled_rules_text()`, `_memory_block` → top-3 `vox.memory.recall(user_text, k=3)`) and 3 lines in `respond_turn` appending them to the system prompt after persona logic. Order: persona → rules → memories. The same `system` string feeds the small→big `[BIG]` escalation re-call, so rules + memories reach the big brain for free.
- Decisions: both helpers swallow all exceptions → `""`, matching the existing `_setting`/`_active_persona`/`_record_usage` guard style, so a missing/broken store leaves today's behaviour byte-identical. Strictly additive in `assistant.py` only.
- Verified: empty/absent/broken store → `''`; live render produces the rules block + "Things you remember about the user" bullet list; `from vox import assistant` imports cleanly, no stray runtime data left.

**Backend routes (axtree / rules / memory) hardened**
- Built: `src/vox/web/server.py` shared helpers `_bad_request`(400)/`_not_found`(404)/`_service_unavailable`(503)/`async _json_body()` (guards malformed/non-object bodies); read routes never error (empty list / `{error}`), write routes return 400 (bad input) / 404 (unknown id) / 503 (required module missing); successful creates return the stored record directly.
- Decisions: feature-module imports stay lazy + per-request (verified via AST that the only top-level vox imports remain `config`, `settings_store`, `usage`), so the daemon is unaffected; relied on store CONTRACT signatures rather than editing the store files.
- Verified: TestClient over `create_app()` — all routes returned expected 200/400/404; no 500s; test records under `data/` cleaned up.

**Command palette + router/api verify (creative)**
- Built: `dashboard/src/components/CommandPalette.tsx` (NEW) — glassy portaled ⌘K modal with fuzzy subsequence search and 3 action groups (navigate to any page, activate any personality via `POST /api/personalities/active`, GitHub quick link); fully keyboard-driven (↑↓ wrap, Enter, Esc, scrim-click), spring-animated + reduced-motion aware, personalities lazy-fetched on first open with graceful degradation. Mounted once in `AppShell.tsx` (global Cmd/Ctrl+K toggle); `TopBar.tsx` ⌘K button enabled with `onOpenPalette`. Router (`App.tsx` — 7 routes incl. `/axtree`,`/rules`,`/memory` + `*`→Overview), nav (`nav.ts`), and the typed `lib/api.ts` client + all CONTRACT TS types were already contract-correct from the scaffold and left unchanged. Docs: appended to `frontend.md`.
- Decisions: palette open-state lives in AppShell (closest common owner of hotkey + TopBar), no global store for one boolean; activating a personality invalidates `["status"]`/`["personalities"]` so the TopBar chip + Personalities page stay in sync; no new deps.
- Verified: `tsc -b --noEmit` — only errors were in a parallel agent's `AxTree.tsx` (since resolved); CommandPalette bundles via esbuild; in-app ⌘K opens, "mem" ranks Memory first, persona name activates + updates the TopBar badge.

**Next (Iteration 6 — end-to-end tests + review + refinement)**
- Real end-to-end run: bring up the bridge (`uv run python -m vox.web.server`) + dashboard (`npm run dev`) together and exercise AX-tree / Rules / Memory / Command palette against the live daemon (the frontend pages have only been verified against contracts + their own error states so far).
- Visual QA pass (Playwright) over the four new pages at desktop + mobile widths per the Visual QA section; write a design critique and feed it into refinement.
- Review + fix any cross-agent integration seams (e.g. confirm the now-resolved `AxTree.tsx` typecheck, rules/memory live in the prompt end-to-end, route error contracts) and refine rough edges; build the frontend.
- Deferred TODOs to fold in: AX-tree bounds as `?depth=&breadth=` query params + optional `AXSubrole`/pyobjc fast-path; wire memory auto-capture on "remember that…" + pinned/threshold prompt injection; surface `AxNode.enabled` in the AX row; command history in the palette.

### Iteration 6 — Audit & refine (2026-06-18)

This iteration was a full audit pass: a severity-ranked code review of the dashboard backend + frontend, a live end-to-end exercise of the API, and targeted fixes for everything confirmed real. All fixes are backend-only and preserve the guarded-additive daemon invariant (no daemon touch points modified; memory/web calls stay lazy + `except Exception`-guarded; `data/` left as found).

**Code-review findings (by severity)**
- BLOCKER: 0.
- HIGH: 1 — Memory `ts` written as a float epoch (`time.time()`) while the contract, the `Memory.ts: string` type, `usage.py`, and the frontend's `relativeTime`/`new Date(memory.ts)` all expect an ISO-8601 string; `new Date(1718700000.0)` was read as milliseconds → 1970 → garbage relative times ("20601d"). Fixed (A).
- MEDIUM: 2 confirmed-real, both fixed (B) — (1) unguarded `await request.json()` on 3 POST handlers returned 500 instead of 400 on malformed/empty bodies; (2) CORS shipped `allow_credentials=True` alongside wildcard methods/headers (spec-invalid combo).
- LOW: 4 — `setActivePersonality` TS return type understates the body (`api.ts:185`); `int(input_tokens or 0)` asymmetric-None (`usage.py:159`); WS loop-binding micro-race (`server.py`); dev-seed side effect guarded by `VOX_DEV_SEED=1` (`server.py:122`). All deferred as TODOs (no runtime impact).

**E2E results**
- All 14 endpoints PASSed; no 500s. The lone e2e note was the `Memory.ts` float-vs-ISO mismatch, which fix (A) resolves.

**Fixes applied**
- (A) HIGH — Memory timestamps. Fixed in one place, the backend `src/vox/memory.py`, matching `usage.py`'s convention: `add()` now writes `"ts": datetime.now(timezone.utc).isoformat()`; added a `_ts_seconds(ts)` helper that converts ISO (and tolerates legacy float + junk) to epoch seconds, used by `_score()`'s recency math and the three sort sites (`recall`, `recall` empty-query branch, `all`) so recency/sort stay correct and crash-free across mixed legacy+new records; updated the module-docstring example record to ISO. Frontend untouched — `relativeTime`/`formatTime` in `dashboard/src/lib/utils.ts` and their callers (`Memory.tsx` `memory.ts`, `LiveFeed.tsx` `e.ts`) were already ISO-correct and are now consistently ISO-fed.
- (B) MEDIUM ×2 — `src/vox/web/server.py`. Routed `POST /api/settings`, `POST /api/personalities/active`, and `POST /api/personalities/custom` through the existing `_json_body(request)` helper (same pattern the rules/memory handlers use) so bad bodies return `400 {ok:false,error}` not 500. Set CORS `allow_credentials=False` (the client sends no cookies/auth), which makes the `["*"]` methods/headers valid per spec; origins remain restricted to localhost dev ports.
- Deferred (LOW, left as TODOs): the 4 LOW items above — cosmetic/latent/practically-harmless, none with current runtime impact.

**Verification**
- Daemon imports clean (`vox.config`, `core.loop`, `assistant`, `executor`, `wakeword.backends`); `create_app()` builds all 24 routes; memory ISO round-trip parses and recall/sort work; mixed legacy-float + ISO records sort without crashing; no unguarded `request.json()` remains in route handlers; test artifact removed from `data/`. No git run. Touched files: `src/vox/memory.py`, `src/vox/web/server.py`.

**Next (Iteration 7 — more end-to-end coverage + new creative features)**
- Broaden end-to-end coverage beyond the 14 endpoints (write-path round-trips, error contracts, frontend-against-live-daemon for the four new pages); add new creative features on top of the now-audited base.

### Iteration 7 — Creative features: budgets, theme, shortcuts, diagnostics (2026-06-18)

A parallel-agent creative round adding four user-facing features full-stack (store/module → guarded route → typed client → page widget), each additive and guarded so the voice daemon is unchanged. All agents stayed in their owned files; no git run.

**Cost budget**
- Built: `web/settings_store.py` adds one `monthly_budget_usd` schema entry (new `Cost` group, `text` type, "0 = no budget", slotted before Debug); `web/usage.py` adds a pure read-only `budget_status() → {budgetUsd, spentUsd, remainingUsd, percent, state}` (+ `_budget_usd`/`_month_key`/`_month_to_date_cost` helpers) — `spentUsd` is current-UTC-month ledger cost, `percent` 0–100 clamped, `state` = `none`/`ok`/`warn`(≥80%)/`over`(≥100%) from the un-clamped percent. Frontend: a Cost Budget widget at the top of `pages/TokenUsage.tsx` (animated progress ring spent/budget, color-shifting ok=violet→cyan / warn=amber / over=red, Spent/Remaining/Budget figures, "no budget set" empty state pointing to Settings), polled every 10s via React Query.
- Decisions: budget stored as `text` (schema only supports toggle/select/text) with the float parse/guard in `budget_status()`; lazy import of `settings_store` inside `_budget_usd()` keeps `usage.py` standalone-importable and degrades to `0.0`/`none` on any failure; None-safe throughout (bad `ts` → this month, non-numeric `costUsd` skipped). Widget does a direct `fetch` (mirrors `lib/api.ts` `VITE_API_BASE`) since the typed client is owned by another agent, and folds any error/unavailable into the `none` empty state so it never renders broken; ring capped at 100% even over budget (red badge + signed `-$` remaining carry the overspend). No new persistence/state; `record_usage` untouched.
- Next: integration agent folds `api.budget()` into the typed `lib/api.ts` + CONTRACT.md `GET /api/budget` entry so the widget can drop its local fetch/types.

**Diagnostics (system health)**
- Built: `web/diagnostics.py` (NEW) read-only `snapshot() → {capturedAt, platform, process:{cpuPercent,memMb,uptimeSeconds}, stt:{model,computeType,sampleRate}, smallBrain/bigBrain:{provider,model}, tts:{enabled,voice}}` (camelCase, matching other `/api` responses). Frontend: a live "System health" card in `pages/Overview.tsx` (CPU%, memory MB, uptime, Whisper model+compute, active brains) in the glass style, header `ListeningPulse` that animates only when live, CPU-pressure colouring, skeleton + "Diagnostics unavailable" states; placed in the lower-grid left column under "Today's cost".
- Decisions: CPU/mem reuse `vox.stats.process_stats()` → direct `psutil` → zeros; uptime from `psutil.Process().create_time()` → import-time monotonic anchor → `0.0`; config reads go `settings_store.get` → frozen `Config` → sentinel so live overrides win; **never raises** — every section wrapped in a `_safe(fn, fallback)` guard, forced total-failure returns the degraded shape (`0`/`"unknown"`/`false`/`""`); fully lazy/self-contained (`stats`/`psutil`/`settings_store`/`Config` imported inside probes — nothing pulled in at module load, so it can't affect daemon boot). Overview card reconciled to the real nested shape and treats the `"unknown"` sentinel as empty (→ `—`); uses a local `fetchDiagnostics()` mirroring api-client conventions.
- Next: fold a typed `api.diagnostics()` into `lib/api.ts` so the local reader can be removed.

**Backend routes**
- Built: two guarded GETs in `web/server.py` `create_app()` (before `_mount_static`): `GET /api/budget` → `usage.budget_status()`, `GET /api/diagnostics` → `diagnostics.snapshot()`. Both mirror the `/api/axtree` pattern — lazy `_try_import`, return HTTP 200 + safe `{error}` on missing module or any exception, never a 500; payloads pass through when present.
- Decisions: `/api/budget` adds a `hasattr(mod,"budget_status")` guard (usage is eagerly imported but `budget_status` was supplied by the parallel agent) so it degrades to `{"error":...}` until that lands, then lights up automatically; read-only GETs so no body validation; mounted before the SPA catch-all so `/api/*` always wins; response shapes owned by the budget/diagnostics agents (thin pass-through). Verified 4 cases all HTTP 200 (missing modules, working impls, each impl raising).
- Next: CONTRACT.md route entries for `/api/budget` + `/api/diagnostics` and their TS types belong to the integration agent.

**Theme + keyboard shortcuts (frontend shell)**
- Built: premium light theme + dark default with theme-aware glass tokens, g-then-key navigation, and a `?` help overlay. `index.css` moves dark to `:root` (matches `index.html`'s hardcoded `class="dark"`, zero flash) and adds a `.light` palette, refactoring `.glass` to theme-aware `--glass-*` tokens so every glass/accent surface flips automatically. New (all under owned `layout/`): `theme.tsx` (provider + `useTheme`, localStorage `vox.theme`, defaults dark), `ThemeToggle.tsx`, `shortcuts.ts` (single-source registry), `useKeyboardShortcuts.ts`, `HelpOverlay.tsx`; `App.tsx` wraps routes in `<ThemeProvider>`, `AppShell.tsx` mounts the shortcuts hook + overlay, `TopBar.tsx` gains the toggle + `?` button. `lib/api.ts` adds `BudgetStatus`/`Diagnostics`/`ApiErrorBody` types, an `isApiError()` guard, and `api.budget()`/`api.diagnostics()` helpers.
- Decisions: `ThemeProvider` mounted via `App.tsx` (owned) rather than `main.tsx` to avoid cross-agent collisions; shortcut registry single-sourced so handler + help overlay never drift; g-chord has a 1.2s timeout + strict editable-element guard, modified chords ignored so ⌘K is unaffected; budget/diagnostics typed per backend.md (both can return `{error}` at HTTP 200 → narrow with `isApiError()`). Verified via Playwright at 1440px: default dark on first load, toggle → persisted `html.light`, `?` overlay lists all 7 g-nav rows + ⌘K/?/Esc, `g`→`u` navigates to /usage, same chord in an `<input>` does not.
- Next: page agents consume `api.budget()`/`api.diagnostics()` and tighten the open `Diagnostics` record once fields settle; optional no-flash light-on-first-paint via a pre-hydration script in `index.html`.

**Verify**
- Backend: `usage.budget_status()` returns `state:none` with no budget, `50 ok / 85 warn / 120 over` against mocked ledger+budget, degrades to the no-budget shape under a raising settings store / null data; `diagnostics.snapshot()` runs clean (live: `small.en`/`int8`/`16000`, small brain `openai/deepseek-chat`, big brain `claude_sdk/claude-opus-4-8`, tts `Daniel`) and returns the degraded shape under forced total-probe failure without raising; both modules import without pulling guarded deps. `server.py` `create_app()` builds cleanly with both routes registered; all 4 route cases HTTP 200, never 500. `data/settings.json` restored to `{}` (no test pollution).
- Frontend: `npm run typecheck` + `npm run build` clean; light palette + `--glass-*` present in built CSS; budget widget + system-health card verified in-browser at 1440px across populated, empty/no-budget, and bridge-down/error states.

**Known gaps / TODOs**
- `/api/budget` + `/api/diagnostics` are not yet in CONTRACT.md or the typed `api` client consumed by the widgets (both widgets use local direct fetches mirroring `lib/api.ts`); `lib/api.ts` already has the `api.budget()`/`api.diagnostics()` helpers + types, so the page widgets can switch to them next iteration.
- `Diagnostics` TS type is still an open record pending tightening to the nested backend shape; `index.html` still ships `class="dark"` as the default (fine — no-flash light-on-first-paint deferred).

**Next (Iterations 8–10 — more end-to-end coverage, final polish, README)**
- Iteration 8–9: broaden end-to-end coverage (write-path round-trips, error contracts, the new budget/diagnostics routes + widgets against the live daemon), wire the budget/diagnostics CONTRACT.md entries + typed-client consumption, and final UI polish (empty/error states, animations, theme edge cases).
- Iteration 10: full docs + README + run steps, final frontend build + smoke test, changelog/demo script.

### Iteration 8 — Finalize (2026-06-18)

The finalize pass: tied off the iteration-7 "Next" items, wrote the dashboard README, and ran a clean-room QA sweep. Strictly additive/cosmetic — no daemon touch points changed, the guarded-additive invariant holds, and no git run.

**Tidy / cleanup**
- Closed the iter-7 integration debt so the budget + diagnostics widgets stop reaching around the typed client: `GET /api/budget` and `GET /api/diagnostics` are now first-class entries in `docs/dashboard/CONTRACT.md`, and the page widgets consume `api.budget()` / `api.diagnostics()` from `dashboard/src/lib/api.ts` instead of their local direct-`fetch` shims (the `Diagnostics` TS type tightened to the real nested backend shape).
- Touched only the files carrying that debt: `dashboard/src/lib/api.ts`, `dashboard/src/pages/Overview.tsx` (System Health card → typed `api.diagnostics()`), `dashboard/src/pages/TokenUsage.tsx` (Cost Budget widget → typed `api.budget()`), and `docs/dashboard/CONTRACT.md`. No store/route signatures changed; no new deps.

**README**
- Wrote `docs/dashboard/README.md` (NEW, 183 lines) — the dashboard's front-door doc: what the Control Center is, the additive/guarded design promise ("the voice assistant runs unchanged if `vox.web` is absent, half-built, or broken"), the full feature tour (Overview, Token Usage + cost, Cost budget, Settings, Personalities, AX Tree, Rules, Memory, command palette, themes/shortcuts), how to run it (bridge + Vite dev, or the daemon-served prod build at `http://127.0.0.1:8765`), the "open dashboard" wake phrase, and the loopback-only / no-committed-runtime-data safety posture. The repo-root `README.md` (M0-scoped voice daemon) was intentionally left unchanged — the dashboard is documented under `docs/dashboard/` to keep the public root README focused on the daemon.

**Final QA results**
- Build clean: `cd dashboard && npm run build` exits 0 — 2702 modules transformed, `dist/assets/index-*.js` ~979kB (gzip ~289kB), `index-*.css` ~43kB; only the known >500kB chunk-size advisory (non-blocking, code-split deferred).
- Daemon imports clean: `import vox.config, vox.core.loop, vox.assistant, vox.executor, vox.wakeword.backends` all import with the dashboard code present (the guarded-additive invariant verified once more — the daemon still doesn't depend on `vox.web`).
- Endpoints pass: `create_app()` builds with 20 `/api` routes registered; all 10 read endpoints (`/api/status`, `/api/usage/recent`, `/api/usage/summary`, `/api/settings`, `/api/personalities`, `/api/rules`, `/api/memory`, `/api/axtree`, `/api/budget`, `/api/diagnostics`) return HTTP 200 via TestClient with zero failures and no 500s.

**Feature set is complete.** All ten roadmap areas are built and full-stack (store/module → guarded route → typed client → page): Overview/diagnostics, Token Usage + cost + budget, Settings, Personalities, AX Tree, Rules, Memory, plus the creative layer (command palette, themes, keyboard shortcuts). The only remaining step is a final visual QA pass (Playwright over every page at desktop + mobile widths per the Visual QA section) and the wrap-up (commit, changelog/demo script).

**Next (final wrap-up)**
- Run the Playwright visual QA sweep across all pages at 1440px + mobile, write the critique, fix any visual rough edges, then do the closing commit + changelog/demo script.

### Memory v1 — tiered Markdown + auto-capture + MCP Integrations (2026-06-18)

A parallel-agent slice rebuilding memory around the v1 design doc (tiered human-editable Markdown), wiring auto-capture/recall into the voice brain, and shipping the Integrations page (vox-speak MCP setup). All additive + guarded; the voice daemon runs unchanged if `vox.web`/`vox.memory` is absent or broken; no git run.

**Built**
- Tiered Markdown store (`src/vox/memory.py`, full rewrite): `data/memory/core.md` (always injected) + `data/memory/daily/YYYY-MM-DD.md` logs; entries are human-editable bullets `- [ISO-ts] (#tags) text`. Additive API: `add(text, tier="daily", tags=None)`, `recall(query, k=5)` (all core + today/yesterday always, then keyword-matched older days), `core()`, `daily(date=None)`, `dates()`, `remove(id)`, `path_for(...)`; stable `sha1(tier+line)[:12]` id survives hand-edits/reordering. Back-compat: `all()` kept, legacy `add(text, tags_list)` positional shim, ISO-8601 `ts`. Legacy `data/memory.jsonl` folded into `core.md` once (idempotent `.migrated-jsonl` marker). Every read never raises (missing/corrupt → empty).
- Auto-capture + recall in the voice brain (`src/vox/assistant.py`): guarded `_mem_add`/`_capture_from_reply`/`_capture_from_user`, rewritten `_memory_block`, a "Memory:" paragraph in `_SYSTEM`, wired into `respond_turn` before `_split_signal`. Model `MEMORY[core|daily]:` directives and "remember that X" turns now persist (gated, always stripped from shown/spoken output); core+daily recalled into the prompt with core dedup. New `memory_autocapture` toggle (`web/settings_store.py`, group **Behavior**), default-on via `_setting(..., True)`.
- Backend bridge routes (`src/vox/web/server.py`): `GET /api/memory/core|daily?date=|dates`, `POST /api/memory/reveal` (Finder `open -R` of `data/memory/`), `GET /api/mcp/config` (vox-speak block, repo root computed at runtime from the server file — never hardcoded). `POST /api/memory` now accepts optional `tier` (forwarded only when `add` advertises it via `inspect.signature`); `DELETE /api/memory/{id}` deletes across tiers. Defense-in-depth: every route holds HTTP 200 even against a pathological memory module.
- Frontend: app-shell slice (`layout/nav.ts`, `layout/shortcuts.ts`, `App.tsx`, `lib/api.ts`) adds the 8th nav item + `/integrations` route + `g`→`i` shortcut + tiered-memory/MCP client helpers/types (`MemoryTier`, `McpConfig`, `memoryCore/Daily/Dates`, `revealMemory`, extended `addMemory`, `mcpConfig`). `pages/Memory.tsx` redesigned to Core + Daily-logs tabs with an auto-capture toggle card, date picker, add/edit/delete, and "Open file location". `pages/Integrations.tsx` built as the vox-speak MCP setup page (Cursor + Claude Code wiring blocks, copy buttons, local-only note, guarded against the config route being absent). Docs appended across `memory.md`, `backend.md`, `frontend.md`, `integrations-page.md`.

**Capture rules used (v1)**
- Two tiers: **core** = always-injected curated facts; **daily** = dated log, recalled for today/yesterday always + keyword match on older days.
- Capture triggers: explicit model `MEMORY[core|daily]:` directives, and a simple regex on user "remember that / to / this" turns → daily.
- Gated by `memory_autocapture` (default-on); directives always stripped from output even when capture is off, so `MEMORY[...]` syntax never leaks; trailing turn-tags (`[OPEN]/[DONE]/[BIG]`) scrubbed from the stored fact; core recall hits deduped so a fact never shows twice.

**Decisions**
- Plaintext human-editable Markdown over JSONL so memories are hand-editable; line-hash ids keep dashboard edit/delete stable after manual edits. Dual-store compatible: assistant prefers the tiered API and falls back to the legacy single-block shape on `TypeError`. Default-on toggle via the already-guarded `_setting` helper (no store signature change). MCP block synthesized when no `.cursor/mcp.json` exists, with `cwd` always patched to the real runtime repo root so committed placeholder paths can't leak. Routes guard capability checks inside `try/except` so a broken module degrades to `[]`/`{error}`, never 500, never touching the daemon.

**Verify**
- `src/vox/memory.py` + `src/vox/assistant.py` `py_compile` clean; tiered store verified end-to-end (core/daily add, positional-tags shim, recall injecting core, `path_for`, `remove`); JSONL migration verified idempotent (one legacy record, no dup on re-run). Capture/recall validated against the real tiered store and the legacy fallback; `memory_autocapture` present in **Behavior** and defaults True; directives stripped even with capture off. Backend routes verified at HTTP 200 against the real v2 store and a pathological broken module (tiered POST routing, cross-tier DELETE 404-on-missing, reveal, dates, MCP config). Frontend `tsc --noEmit` + `vite build` clean with Integrations as the 8th nav row + ⌘K command; runtime `data/` left clean (test rows removed).

**Known gaps / TODOs**
- "remember that X" parser is intentionally simple (v1) — to be tuned with the user. `vox.mcp.speak` (idea #34) is a forward reference; the MCP config route is informational and works whether or not that module exists. Memory page's local `memoryApi` fetch helper + inline-edit verb (`PATCH /api/memory/{id}`) to be consolidated into `lib/api.ts` / confirmed with backend.

**Next**
- Big-brain "dream"/consolidation pass (#28): periodic pass that distills daily logs into core + `weekly/`/`monthly/`/`dream-log.md` (names reserved, not yet created).
- Tune the capture rules (what gets auto-remembered, core-vs-daily routing, the "remember that" parser) with the user.

### Handbook + Default persona + prompt debug logging (2026-06-18)

A parallel-agent slice adding a searchable in-app reference for everything Vox can say/do, a deselectable "base Vox" persona, and full prompt/raw-response debug logging in the voice brain. All additive + guarded; the voice daemon runs unchanged when `vox.web` is absent or `CONFIG.debug` is off; no git run.

**Handbook (backend)**
- Built: guarded `GET /api/handbook` in `src/vox/web/server.py` → JSON array of `{title, blurb?, items:[{phrase, description}]}` across 7 groups. Live-from-`CONFIG` groups (never drift): Wake & Activation (`control_/assistant_/open_dashboard_phrases`), Dictation (`dictate_phrases` bare + `assistant_name`-prefixed for idle), Sleep/Stop/Quit (`sleep_/abort_/quit_/restart_phrases`), Escalation Keywords (`escalation_keywords`). Curated static groups: Control Commands (open apps/sites, tabs/windows/Spaces, profiles, search, write, vision, …), Modes, Features. Helpers `_phrase_items(phrases, description, prefix="")`, `_handbook_live`, `_handbook_static`, `_handbook`. Docs: "Handbook catalog" in `backend.md`.
- Decisions: `CONFIG` imported lazily **inside** `_handbook_live()` (not at module load) to preserve the daemon-safe boot. Three-tier fallback live+static → static-only (CONFIG read fails) → `[]`; always HTTP 200, read-only, no subprocess. Empty live groups dropped so no hollow headers. Dictation lists `dictate_phrases` twice (bare + "Vox "-prefixed) per spec.

**Handbook (frontend)**
- Built: `dashboard/src/pages/Handbook.tsx` (NEW) renders the catalog as grouped glass cards with a live search box (case-insensitive over phrase+description+title, `/` focuses, `Esc` clears, empty groups hide, match count), click-to-copy on every phrase (clipboard + check flash + toast), per-group `lucide-react` icons with fallback, and full loading/error/empty/no-results states. App-shell wiring (owned shell files): `nav.ts` adds the `BookOpen` Handbook nav item, `shortcuts.ts` adds the `g`→`h` chord, `App.tsx` adds the `/handbook` route, `lib/api.ts` adds `HandbookItem`/`HandbookGroup`/`Handbook` types + `api.handbook()`. Because SideNav/CommandPalette/shortcuts/HelpOverlay are data-driven from `nav.ts`/`shortcuts.ts`, the item appears in sidebar, ⌘K, keyboard handler, and `?` overlay automatically. Docs: `handbook-page.md` + sections in `frontend.md`.
- Decisions: typed client mirrors the real wire shape — `_handbook` returns a **bare** `HandbookGroup[]` (not a `{groups}`/`{error}` envelope; it falls back to static groups even if CONFIG fails), so `Handbook = HandbookGroup[]` with no error-narrowing. Page consumes the shared `api.handbook()` client (no drift) with a defensive normaliser so a malformed payload can't crash render. Icon `BookOpen` + chord `g h` chosen to avoid existing clashes.

**Default persona (backend + page)**
- Built: synthetic **Default** deselect entry so users can turn a persona off and return to exact base behaviour. `src/vox/web/personalities.py` adds a module-level `_DEFAULT` (id `default`, name `Default`, emoji `🎙️`, empty `persona`/`suggestedVoice`, `preset: True`) kept **out** of `PRESETS`/`_PRESETS_BY_ID`. `all()` prepends Default (9 total, Default first) and reports `active: "default"` when nothing is set; `set_active("default")` maps to `""` (clears active). `get_active()`/`get_active_personality()` unchanged (return `""`/`None` → assistant layers nothing). Page `dashboard/src/pages/Personalities.tsx` adds a visually-distinct `DefaultCard` (dashed border, `Mic` glyph, quieter halo, "Base" chip) as the first card in the Presets grid, split from the character count; header shows a "Default — Vox as itself" pill when base is active. Docs: `personalities-page.md` + section in `backend.md`.
- Decisions: Default synthesised at runtime, never written to `data/personalities.json` (selecting it stores `""`), so validation/custom-CRUD/persistence shape are untouched. The bridge's `set_active()` rejects synthetic ids, so the client treats `active === "default" | ""` as base-active, marks Default active optimistically, but sends `""` over the wire (`id === "default" ? "" : id`) — the real deselect path.

**Prompt + raw-response debug logging (voice brain)**
- Built: guarded `_dbg(label, content)` in `src/vox/assistant.py` — when `CONFIG.debug` is True, prints a marked block to stdout **and** appends it to `CONFIG.log_file` with `[debug]<label>` … `[debug]<label>/end` markers; complete no-op when debug is off, wrapped in try/except so it can never break a reply. `_fmt_messages(history, text)` renders the full conversation. Instrumented at the `complete()` choke point (covers chat + executor across all four providers): logs `[debug][prompt->small|big] … system` (exact system prompt), `[debug][prompt->…] messages` (history + user text) before dispatch, and `[debug][raw-response]` after (raw text **before** any `[OPEN]`/`[DONE]`/`[BIG]`/`SAY:`/`MEMORY[...]` stripping). `look()` (vision) instrumented the same way for both `_sdk_look`/`_anthropic_look`. Docs: appended to `backend.md`.
- Decisions: instrumented at the `complete()`/`look()` dispatch seams (one guarded site per brain/provider, no per-provider duplication, no provider-internal changes). Reused the existing `CONFIG.log_file` (`vox.log`) — no new file/config; `[debug]…` markers keep it greppable. Logs the literal assembled system prompt (persona + rules + memory) as sent.

**Verify**
- Backend: `TestClient(create_app()).get('/api/handbook').json()` → 7 groups with live phrases (e.g. 'take control'/'hey vox') and a `Vox `-prefixed dictation entry. Personalities: `all()['presets'][0]` → `default Default True` with 9 presets; `set_active('default')` → `''`, `all()['active']` → `default`, `get_active()` → `''`; the 8 presets + custom CRUD unaffected. `_dbg` smoke test: prints to stdout + appends to `CONFIG.log_file` with `[debug]…` markers when debug on, true no-op when off. Frontend: `npx tsc -b --noEmit` + `vite build` clean; Handbook appears in sidebar/⌘K/`g h`/`?`, payload 7 groups / 99 items matches the rendered shape; the dashed Default card shows Active when no persona is set and clears the active persona on click. No git run; runtime `data/` left clean.

**Known gaps / TODOs**
- Handbook's static Control/Modes/Features groups are curated by hand — they can drift from the actual command surface and should be reconciled as commands are added. The "remember that" parser note from the prior slice still stands. Debug logging writes full prompts to `vox.log` when `CONFIG.debug` is on — fine for local debugging, but the log can grow and may contain conversation content, so it stays off by default.
