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
