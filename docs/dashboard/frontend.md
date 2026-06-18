# Vox Dashboard — Frontend Shell (Iteration 1)

> The Vite + React + TS + Tailwind + shadcn/ui + Animate UI app under `dashboard/`.
> Iteration-1 scope = a runnable **foundation**: full toolchain config, theme tokens,
> typed API client + all data-shape types, the component set the shell needs, the
> app shell (SideNav + TopBar), a **fully working Overview** page, and titled
> "coming soon" placeholders for the other 6 pages so routing works end-to-end.
>
> **Hand-written only** — no `npm`/CLI/network was run. Every component (shadcn +
> Animate UI) is hand-authored source per `CONTRACT.md` + `research/ui.md`.

## Files touched (all new, under `dashboard/`)

**Config / toolchain**
- `package.json` — pinned deps: react/react-dom 18.3.1, @tanstack/react-query 5.62.7,
  recharts 2.15.0, lucide-react 0.468.0, motion 11.15.0, react-router-dom 6.28.0,
  the Radix packages each `ui/*` component needs, cva/clsx/tailwind-merge; dev:
  vite 6, typescript 5.7, tailwindcss 3.4, postcss, autoprefixer, tailwindcss-animate,
  @vitejs/plugin-react, @types/*. Scripts: `dev`, `build` (`tsc -b && vite build`),
  `preview`, `typecheck`.
- `vite.config.ts` — React plugin, `@`→`src` alias, **`/api` proxy to
  `http://127.0.0.1:8765` with `ws: true`** (REST + WebSocket), `outDir: dist`.
- `tsconfig.json` / `tsconfig.app.json` / `tsconfig.node.json` — strict, bundler
  resolution, `@/*` path, project references.
- `tailwind.config.ts` — dark-mode class strategy; maps every CSS-var token to
  Tailwind colors (`hsl(var(--…))`), `2xl` radius, Geist/Inter + Geist Mono stacks,
  `display`/`overline` font sizes, glass/accent-glow shadows, `bg-brand-gradient`,
  and `listening-pulse` + `shimmer` keyframes/animations. Plugin: tailwindcss-animate.
- `postcss.config.js`, `components.json` (shadcn parity; CLI never invoked),
  `index.html` (`<html class="dark">`, color-scheme dark), `.gitignore`
  (covers `dist/`, `node_modules/`, `.env.*.local`), `.env`
  (`VITE_API_BASE=http://127.0.0.1:8765`).

**Theme + libs**
- `src/index.css` — all design tokens as HSL triplets under `:root` (dark-first):
  zinc surfaces, violet→cyan accent, semantic colors. Utilities: `.tnum`,
  `.bg-brand-gradient`, `.text-brand-gradient`, `.glass` (the glass-card recipe),
  custom scrollbar, and a global `prefers-reduced-motion` reset.
- `src/lib/utils.ts` — `cn()` = `twMerge(clsx(...))`.
- `src/lib/api.ts` — **all** TS types mirroring CONTRACT data shapes (`Status`,
  `UsageEvent`, `UsageSummary`, `Setting`, `Personality`, `Personalities`, `Rule`,
  `Memory`, `AxNode`, `AxTree`, …) + a typed `api` client covering **every**
  CONTRACT REST route, an `ApiError`, and `usageStreamUrl()` for the WS.
- `src/vite-env.d.ts` — typed `import.meta.env.VITE_API_BASE`.

**shadcn/ui (`src/components/ui/*`)** — hand-written: `button`, `card` (with a
`glass` prop), `badge`, `separator`, `skeleton` (shimmer), `tooltip`, `scroll-area`,
`switch`, `input`, `tabs`, `select`, `slider`, `dialog`. (Iteration 1 only renders
button/card/badge/skeleton/tooltip; the rest are ready for iterations 2–6.)

**Animate UI (`src/components/animate/*`)** — hand-written, all `prefers-reduced-motion`
gated via `src/hooks/useReducedMotion.ts`:
- `SlidingNumber` — spring number counter, tabular figures, prefix/suffix/decimals.
- `FadeIn`, `Stagger`/`StaggerItem`, `Spring` — entrance wrappers.
- `ListeningPulse` — the signature pulsing violet "listening" indicator.
- `PageTransition` — route-level fade+slide.

**Composite + layout**
- `src/components/StatusDot.tsx`, `MetricCard.tsx`, `PageHeader.tsx`, `ComingSoon.tsx`.
- `src/components/layout/{nav.ts,SideNav.tsx,TopBar.tsx,AppShell.tsx}` — 240px SideNav
  linking all 7 pages with an animated gradient active indicator + bottom status dot;
  56px sticky glass TopBar with listening pulse + brain/personality chips; AppShell
  fetches `/api/status` (5s poll) and shares it with nav/topbar.

**Pages (`src/pages/*`)**
- `Overview.tsx` — **fully working**: react-query against `/api/status` (5s refetch),
  animated glass `MetricCard`s for status/uptime/personality/small-brain/big-brain/
  bridge, staggered entrance, listening pulse, and a graceful error card when the
  bridge is unreachable.
- `TokenUsage`, `Settings`, `Personalities`, `AxTree`, `Rules`, `Memory` — titled
  `ComingSoon` placeholders (each notes which iteration delivers it) so routing is
  end-to-end.

**App entry**
- `src/App.tsx` — routes for all 7 pages under `AppShell`, each wrapped in
  `PageTransition`; unknown paths fall back to Overview.
- `src/main.tsx` — `QueryClientProvider` + `TooltipProvider` + `BrowserRouter`.

## Key decisions

- **No CLI/network.** shadcn and Animate UI are copy-paste distributions, so every
  `ui/*` and `animate/*` file is hand-authored. `components.json` exists for tooling
  parity only.
- **Tokens once, in `index.css`.** HSL triplets so shadcn `hsl(var(--…))` and the
  Tailwind color map share one source of truth (palette per `research/ui.md` §3).
- **Same-origin by default.** The fetch client uses `VITE_API_BASE` if set, else
  same-origin `/api` — which is exactly how the FastAPI bridge serves the built app
  in production. The `.env` value + Vite `/api` proxy cover local dev.
- **Status fetched once** in `AppShell` and reused; Overview also queries `["status"]`
  so react-query dedupes. 5s poll now; swap to the WS in iteration 2.
- **Motion confirms state, gated by reduced-motion** (one hook, used everywhere).
- **Routing is real end-to-end now** — placeholders are titled pages, not 404s, so
  later iterations only swap a page body in.

## TODOs for later iterations

- **Iter 2:** wire `useUsageStream` to `WS /api/usage/stream`; build Token Usage page
  (recharts breakdowns, live feed, `SlidingNumber` counters). `select`/`tabs` ready.
- **Iter 3:** Settings page from `GET /api/settings` using `switch`/`select`/`input`,
  grouped Brains/Behavior/Voice/Debug, "needs restart" notes.
- **Iter 4:** Personalities page (presets + custom editor via `dialog`).
- **Iter 5:** AX Tree page (collapsible `scroll-area` tree, search, refresh).
- **Iter 6:** Rules + Memory CRUD pages.
- **Iter 7–8:** ⌘K command palette (TopBar affordance already scaffolded), activity
  timeline, mic waveform, themes/skins, light theme.
- **Fonts:** self-host Geist/Inter `woff2` (stacks already fall back to system).
- **Polish:** SideNav mobile drawer below `md`; collapse-to-rail at `lg`.

## How to run / verify

> The orchestrator installs deps + builds (iteration 9). This agent ran no commands.

1. `cd dashboard && npm install` (pinned versions).
2. **Type-check:** `npm run typecheck` (or `tsc -b`) — strict, no unused.
3. **Dev:** start the daemon/bridge on `127.0.0.1:8765`, then `npm run dev` →
   Overview shows live brains/mode/personality/uptime in animated glass cards; the
   TopBar listening pulse animates while the daemon is running; with the bridge down
   it degrades to an offline state + error card (daemon stays unaffected).
4. **Build:** `npm run build` → `dashboard/dist` for the bridge to serve at `/`.
5. **Routing:** all 7 SideNav items navigate; 6 show titled "coming soon" pages.

**Static checks already done (no runtime):** every `@/…` import maps to a created
file; every external import is a declared dependency; named imports match exports;
all files using the `React.` namespace import React.
