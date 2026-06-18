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

## Progress
- _(none yet — iteration 1 launching)_
