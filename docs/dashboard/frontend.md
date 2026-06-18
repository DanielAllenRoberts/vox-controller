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

---

## Iteration 2 — Token Usage page + Overview polish

### New files
- `src/hooks/useUsageStream.ts` — subscribes to WS `/api/usage/stream`, prepends
  each incoming `UsageEvent` into a bounded newest-first buffer (dedupes by `id`),
  auto-reconnects with a 2s backoff, exposes `{ events, status }` where status is
  `connecting|live|offline`. Accepts a `seed` (the REST `usage/recent` snapshot) to
  prime the feed before the first live push, without clobbering streamed rows.
- `src/hooks/useNow.ts` — ticking `Date.now()` (default 1s) so relative timestamps
  in the feed update from one shared timer instead of per-row intervals.
- `src/components/usage/KindBadge.tsx` — kind glyph (chat/command/vision/rewrite)
  with tint; falls back gracefully on unknown kinds.
- `src/components/usage/LiveFeed.tsx` — shared live recent-calls feed. Newest-first,
  spring slide-in per new row (`AnimatePresence` + `layout`, reduced-motion aware),
  per-row `model · brain · tokens · latency · cost · relative-time`. Subscription
  providers (`claude_sdk`/`claude_cli`) render a subtle **"subscription"** badge in
  place of `$cost`. Great empty state when no calls yet. Used by both pages.

### Changed files
- `src/pages/TokenUsage.tsx` — replaced the ComingSoon stub with the full page:
  - 4 summary cards with **animated counters** (`SlidingNumber`): total calls,
    input tokens, output tokens, and a violet→cyan **hero "Total cost"** card
    (gradient text + radial glow blob).
  - **Cost over time** area chart (recharts) from `summary.byDay`, violet→cyan
    gradient fill, glass tooltip.
  - **Tokens by model** horizontal bar chart from `summary.byModel` (accent palette
    per bar) paired with a legend list showing provider · calls · tokens · cost.
  - **Live recent-calls feed** (`LiveFeed`) seeded from `usage/recent`, then live.
  - Distinct empty states for each chart + the feed when there's no usage yet.
- `src/pages/Overview.tsx` — kept all 6 status cards; addressed the visual critique:
  - Added a fixed **background radial glow** (violet + cyan blurred blobs, `-z-10`).
  - New lower section fills the dead space: a **"Today's cost"** hero card
    (gradient counter + all-time total + a 14-day cost **sparkline**), a compact
    **live activity feed**, and **quick-action chips** linking to key pages.
  - Personality now renders **"Default"** when `status.personality` is empty.
- `src/lib/utils.ts` — added shared display formatters: `formatTokens`,
  `formatCost`, `formatLatency`, `formatTime`, `relativeTime`, `todayKey`.

### Decisions
- The WS pushes raw `UsageEvent` JSON (`server.py` `ws.send_json`, fields already
  camelCase) so the hook `JSON.parse`s straight into the TS type — no mapping.
- "Today" uses local `todayKey()` matched against `byDay[].date`; all-time totals
  come from `summary.totals`.
- Charts are inline `recharts` (already a dependency) with theme-matched HSL
  literals; no new deps added.
- Subscription cost surfaced as a badge (not `$0.00`) per the contract's note.

### TODOs / future
- byDay sparkline needs ≥2 days of data; until then a flat baseline shows.
- Bundle is ~826kB (recharts) — fine for a local tool; could code-split later.

### How to verify
1. `cd dashboard && npm install && npx tsc -b --noEmit` — no errors in the touched
   files (3 pre-existing `React`-unused errors in `animate/{FadeIn,Spring,Stagger}`
   are unrelated to this iteration).
2. `npm run build` → succeeds; `dashboard/dist` rebuilt.
3. With the bridge up on `127.0.0.1:8765`: Overview shows today's cost + sparkline +
   a live feed + quick-action chips, glassy radial-glow background, "Default"
   personality when unset; `/usage` shows animated summary cards, both charts, and
   the live feed prepending rows as you talk to Vox. With the bridge down both pages
   degrade to empty/offline states (daemon unaffected — `vox.web` stays lazy).

---

## Iteration 3 — Settings page + toast system

### New files
- `src/hooks/useToast.tsx` — dependency-free toast system (no `sonner`/radix-toast).
  A `<ToastProvider>` holds a bounded (newest-4) queue; `useToast().toast({title,
  description?, variant?, duration?})` pushes one; `dismiss(id)` and auto-dismiss
  timers (default 3.2s, `0` = sticky) clean up. Variants: `success | error | info`.
- `src/components/ui/toast.tsx` — `<Toaster/>`: mounted once near the app root,
  reads the queue from context and renders a bottom-right stack of glass cards with
  spring slide-in / fade-out (`AnimatePresence` + `layout`, reduced-motion aware),
  tinted icon chip per variant, and a manual dismiss button.

### Changed files
- `src/main.tsx` — wrapped the app in `<ToastProvider>` and mounted `<Toaster/>`
  (inside `TooltipProvider`, alongside `BrowserRouter`). Additive; no behavior change
  to existing providers.
- `src/pages/Settings.tsx` — replaced the `ComingSoon` stub with the full page:
  - **Data:** react-query `["settings"]` against `GET /api/settings` (`Setting[]`,
    contract shape `{key,label,group,type,value,options?,help}`).
  - **Grouping:** settings bucketed by `Setting.group` and rendered as one glass
    card per group in a 2-col grid, ordered **Brains → Behavior → Voice → Debug**
    (unknown groups fall after, ungrouped). Each group card has an icon chip + a
    one-line blurb; within a group the API's schema order is preserved.
  - **Controls per `type`:** `toggle` → shadcn `Switch` (animated, with an On/Off
    label); `select` → shadcn `Select` driven by the API's `options[]` (covers
    `provider` + `escalation_mode`); `text` → shadcn `Input` (mono) that commits on
    **blur / Enter** (Escape reverts) so we don't POST per keystroke.
  - **Optimistic save:** a `useMutation` writes the new value into the cached
    `Setting[]` immediately (`onMutate`), POSTs `{key,value}` to `/api/settings`,
    then on success **reflects the server's returned `value`** over the optimistic
    one and fires a subtle **success toast**; on error it **rolls back** to the
    snapshot and fires an **error toast**. A non-`ok` response (unknown key) surfaces
    a "Rejected" toast. The mutating row dims (`opacity-70`) while in flight.
  - **Hints:** each row shows the setting's `help` text plus a small badge —
    **"needs restart"** (amber, `RotateCcw`) when the help text says so, else
    **"applies on next call"** (`Zap`). The restart/next-call split is derived from
    `help` (the store encodes it there), so no client-side key list to maintain.
  - **Header:** a tasteful explainer banner (gradient-glow glass) stating these are
    **runtime overrides layered over the daemon's `Config`** — no code edit / config
    file — and that the voice assistant keeps running while you tune it.
  - **States:** skeleton group cards while loading; an offline notice (with the
    "falls back to Config" reassurance) when the bridge is unreachable.

### Decisions
- **Own toast system, no new dep.** Reused `motion` (already a dependency) +
  `useReducedMotion` for the animation; a tiny context provider is simpler than
  pulling in `sonner` and matches the hand-authored-components rule.
- **Text fields commit on blur/Enter, not per keystroke** — avoids a POST storm on
  model-name edits and keeps the optimistic cache from thrashing.
- **Restart vs. next-call is read from `help`**, not hard-coded — keeps the schema
  the single source of truth (the Python `settings_store` already encodes "Restart
  to apply." in those help strings).
- **Optimistic + server-authoritative.** We render the change instantly but always
  overwrite with the POST's returned `value`, so the UI can't drift from the store.
- Group icons/blurbs are presentation-only; an unknown group still renders (generic
  icon, no blurb) so adding a setting server-side never 404s the UI.

### TODOs / future
- No "reset to Config default" affordance yet (store has no per-key clear endpoint;
  out of contract scope for iter 3).
- Toasts are bottom-right, single-region; a future iter could add per-page anchoring
  or an undo action on the save toast.

### How to verify
1. `cd dashboard && npm install && npx tsc -b --noEmit` — clean (no errors).
2. `npm run build` → succeeds; `dashboard/dist` rebuilt.
3. With the bridge up on `127.0.0.1:8765`: `/settings` shows four grouped glass
   cards (Brains/Behavior/Voice/Debug) with animated switches, provider +
   escalation-mode selects populated from the API, mono model-name inputs, per-row
   help + restart/next-call badges, and the runtime-override header banner.
   Toggling a switch or changing a select/model **updates instantly**, POSTs to
   `/api/settings`, persists to `data/settings.json`, and pops a success toast;
   reflected value matches the server. With the bridge down the page shows the
   offline notice and a failed save rolls back + shows an error toast (daemon
   unaffected — `vox.web` stays lazy).

   Verified live at 1440px: all four groups render cohesively (dark glass +
   backdrop-blur, violet accent toggles, hairline borders), a Debug toggle POSTed
   and persisted `{"debug": false}` to `data/settings.json`, 0 console errors.

## Iteration 4 — Personalities page (preset gallery + custom editor)

Replaced the `Personalities` ComingSoon stub with a real, data-driven page.
Frontend-only: the `api.personalities*` methods and `Personality` types already
existed in `lib/api.ts` (added by iter 1 to mirror CONTRACT.md), so no client or
type changes were needed.

### New files
- `dashboard/src/components/ui/textarea.tsx` — shadcn-style `<Textarea>` matching
  `<Input>` (same border/ring/glass tokens). Used by the custom-persona editor.

### Changed files
- `dashboard/src/pages/Personalities.tsx` — full rewrite. Drives off
  `GET /api/personalities` (`{active, presets[], custom[]}`) via React Query.
  Two galleries (Presets, Your personas) of rich persona cards: big emoji avatar,
  name, tagline, 3-line clamped persona preview, and a `suggestedVoice` chip
  (audio-lines icon). Responsive grid: 1 col → 2 (sm) → 3 (lg) → 4 (xl), staggered
  fade-in.

### Decisions
- **Whole card is the activate control.** Clicking any card POSTs
  `/api/personalities/active {id}` with an **optimistic** cache update (writes
  `active` immediately) + the existing toast; on error it rolls back and warns.
  No-ops when the card is already active. The active card gets an unmistakable
  state: violet→cyan **glow halo** behind it, an `accent` ring, a corner gradient
  wash, and an **Active** badge. The header also shows the active persona as an
  accent badge.
- **Delete on custom cards only.** A trash affordance (revealed on hover/focus)
  lives inside the card; it `stopPropagation`s so it never activates the card, and
  opens a confirm `<Dialog>` ("Delete persona?") before
  `DELETE /api/personalities/custom/{id}`. Success prunes the cache + info toast.
- **Create flow = `<Dialog>`** (header "Create custom" button + the empty-state
  CTA both open it). Fields: emoji (short text input, centered), name, persona
  (`<Textarea>`), and an optional suggested-voice `<Select>` limited to the macOS
  `say` voices Daniel/Karen/Moira/Rishi/Samantha/Tessa. Submit (name + persona
  required) POSTs `/api/personalities/custom`; success appends the returned
  persona to the cache, toasts, resets, and closes. Radix Select can't hold an
  empty value, so "no voice" uses a `__none__` sentinel mapped back to
  `undefined` on submit.
- **Empty state.** When `custom` is empty, the second section shows a centered
  glass card (gradient blur, user-plus icon, copy, gradient CTA) instead of a
  grid — reuses the iter-1/3 premium look.
- Reused existing primitives only (`Card glass`, `Badge`, `Button` gradient/
  destructive/ghost, `Dialog`, `Select`, `Input`, `Skeleton`, `FadeIn`,
  `Stagger`). Toast variants are the system's `success|error|info`. No new deps,
  no client/contract changes, daemon untouched.

### TODOs / future
- No inline **edit** of an existing custom persona (create + delete only — matches
  the contract's API surface). An edit flow would need a PATCH route not in
  CONTRACT.md.
- Emoji input is a plain text field (no picker) per the "simple emoji input" ask.
- Presets aren't deletable (no delete affordance rendered) — correct per contract.

### How to verify
1. `cd dashboard && npm install && npx tsc -b --noEmit` — clean (no errors).
2. `npm run build` → succeeds; `dashboard/dist` rebuilt.
3. With the bridge up on `127.0.0.1:8765`: `/personalities` shows a Presets
   gallery (Posh Butler, Batman, J.A.R.V.I.S., …) of glass cards with emoji,
   name, tagline, persona preview, and a voice chip. Clicking a card **instantly**
   moves the Active ring + glow + badge to it, POSTs `/api/personalities/active`,
   and pops a success toast; the header badge updates. "Create custom" opens the
   editor — filling name + persona (+ optional emoji/voice) and submitting POSTs
   `/api/personalities/custom`, the new card appears under "Your personas", and it
   persists to `data/personalities.json`. The custom card's hover trash → confirm
   dialog → DELETE removes it. With no custom personas the section shows the empty
   state. With the bridge down: offline notice; a failed activate rolls back +
   error toast (daemon unaffected — `vox.web` stays lazy).

---

## App shell + Command palette (iteration 5 — frontend agent)

Owns the shared frontend chrome: `src/App.tsx` (router), `src/components/layout/*`
(AppShell, SideNav, TopBar, nav.ts), `src/lib/api.ts`, plus the new
`src/components/CommandPalette.tsx`.

### Router + nav (verified, no change needed)
The scaffold (iterations 1–4) already wires all 7 routes in `App.tsx`
(`/`, `/usage`, `/settings`, `/personalities`, `/axtree`, `/rules`, `/memory`,
plus a `*` → Overview fallback) and lists the matching `NAV_ITEMS` in
`layout/nav.ts` (AX Tree, Rules, Memory present, correct icons + paths). The
SideNav renders them with the animated `layoutId` gradient indicator. Left
as-is — adding/duplicating routes would have been redundant.

### lib/api.ts (verified, no change needed)
Already exposes the full typed client + every TS type from CONTRACT.md
(`Status`, `UsageEvent/Summary`, `Setting`, `Personality/Personalities`, `Rule`,
`Memory`, `AxNode/AxTree/AxTreeError`) and helpers for status, usage, settings,
personalities (incl. `setActivePersonality`), rules, memory, and axtree, plus
`usageStreamUrl()` for the WS. Camel-case shapes match the bridge. The command
palette consumes `api.personalities` + `api.setActivePersonality` from here;
page agents rely on the rest (or fall back to direct fetch).

### Command palette — `src/components/CommandPalette.tsx`
A glassy ⌘K modal, mounted **once** in `AppShell`, toggled by a global
`Cmd/Ctrl+K` handler (in AppShell) or the TopBar ⌘K button (now enabled, wired
via the `onOpenPalette` prop). Portals to `document.body` at `z-[100]`.

- **Search:** dependency-free subsequence `fuzzyScore()` (scoped to this file)
  ranks commands across label + keywords; contiguous/early matches win, ties
  break toward shorter targets. Empty query shows everything, grouped.
- **Actions (3 groups):** *Navigate* → any of the 7 pages (from `NAV_ITEMS`,
  single source of truth); *Personalities* → activate any preset/custom persona
  (lazy-fetched via react-query the first time the palette opens; POSTs
  `/api/personalities/active`, then invalidates `["status"]` + `["personalities"]`
  so the TopBar chip + Personalities page update, and toasts); *Links* → open the
  GitHub repo.
- **Keyboard:** ↑/↓ wrap-around through the flat ranked list, Enter runs the
  active row, Esc / scrim-click / ⌘K closes. Active row auto-scrolls into view;
  mouse hover syncs the active index. Input auto-focuses on open; query +
  selection reset each open.
- **Design:** `.glass` card, brand-gradient hairline at the top edge, accent
  (violet) active state with a subtle ring/glow on the leading icon tile,
  section overlines, spring open/close via the existing `motion` dep,
  reduced-motion aware (opacity-only fallback), footer hint bar (↑↓ / ↵). Empty
  state for no matches.
- **Resilience:** personality fetch failure degrades gracefully (palette still
  navigates); a failed activate shows an error toast and never throws. No new
  deps; no daemon touch points.

### Files touched
- `src/components/CommandPalette.tsx` (new)
- `src/components/layout/AppShell.tsx` (mount palette + global ⌘K hotkey)
- `src/components/layout/TopBar.tsx` (enable ⌘K button, `onOpenPalette` prop)
- `App.tsx`, `lib/api.ts`, `layout/nav.ts`, `layout/SideNav.tsx`: verified
  contract-correct, left unchanged.

### Decisions / TODOs
- Palette state lives in AppShell (closest common owner of TopBar + hotkey); no
  global store added for one boolean.
- Personalities fetched lazily on first open (not on shell mount) to avoid an
  extra request for users who never open the palette.
- No "recent actions" / command history (not requested; would need persistence).
- GitHub link is the only quick link; more can be appended to `linkCmds`.

### How to verify
1. `cd dashboard && npx tsc -b --noEmit` — the only errors are in `AxTree.tsx`
   (owned by the AX Tree page agent); the shell/palette/api files are clean.
2. `npm run build` once AxTree typechecks → `dashboard/dist` rebuilt.
3. In the app: press `⌘K` (or `Ctrl+K`, or click the ⌘K chip) → glass palette
   springs in. Type "mem" → Memory ranks first; Enter navigates there and the
   palette closes. Type a persona name (e.g. "batman") → activating it moves the
   TopBar personality badge + toasts. ↑/↓ move selection, Esc closes. With the
   bridge down, navigation still works and persona activation shows an error
   toast without breaking the page.

---

## Cost Budget widget — Token Usage page (iteration 7)

**Owned file:** `dashboard/src/pages/TokenUsage.tsx` (only).

Adds a **Cost Budget** card near the top of the Token Usage page (directly under
the page header / bridge-error banner, above the summary metric cards). It shows
month-to-date spend against a configured monthly cap.

### Data source
- `GET /api/budget` → `{ budgetUsd, spentUsd, remainingUsd, percent, state }`
  where `state ∈ { ok | warn | over | none }`.
- The budget route is served by the Python bridge but is **not** part of the
  typed `api` client in `lib/api.ts` (owned by another agent — not edited). The
  widget therefore does a small **direct `fetch`** that mirrors `lib/api.ts`'s
  `API_BASE` resolution (`import.meta.env.VITE_API_BASE`, same-origin in prod,
  Vite-proxied in dev). Types are declared locally (`Budget`, `BudgetState`).
- Polled every 10s via React Query (`queryKey: ["budget"]`), matching the
  page's other usage queries.

### Behavior / states
- **none / error / unavailable** → clean empty state: a wallet glyph, "No monthly
  budget set", and a hint chip pointing to **Settings → Monthly budget**
  (`monthly_budget_usd`). Any fetch error or "budget module not available"
  response is folded into this unset state so the widget never looks broken
  (the backend `budget_status()` may not be wired up yet in every iteration).
- **ok / warn / over** → an animated SVG progress **ring** (spent of budget) with
  the percent counting up in the center (`SlidingNumber`), plus Spent / Remaining
  / Budget figures. Remaining flips to red and reads "over the cap" (with a
  signed `-$` value) when over.

### Design
- Glass card (`<Card glass>`), rounded-2xl, hairline border, generous padding —
  consistent with the existing summary/chart cards.
- **Color shifts by state:** `ok` = violet→cyan accent gradient, `warn` = amber,
  `over` = red. The gradient drives both the ring stroke and a soft radial glow
  in the card corner; the status `<Badge>` (accent/warning/danger) echoes it.
- **Motion** (existing `motion/react` dep): the ring arc springs from empty to
  its fill on mount/update; the percent + dollar figures use the shared
  `SlidingNumber`. All respect `prefers-reduced-motion` via `useReducedMotion`
  (ring renders instantly, numbers snap).
- The arc is capped at 100% even when over budget (the badge + figures carry the
  overspend), keeping the ring legible.

### Verify
1. `cd dashboard && npx tsc --noEmit` → passes (no new errors).
2. `npm run build` → `dashboard/dist` rebuilt.
3. In the app, open **Token Usage**:
   - Bridge down / no `budget_status()` → the **"No monthly budget set"** empty
     state shows with the Settings hint (no console errors, page intact).
   - With a budget configured: ring fills to `percent`, badge + glow are violet
     (ok), amber (warn), or red (over); Spent/Remaining/Budget read correctly and
     Remaining turns red + signed when over.

## System health card — Overview (Iteration 7)

A compact **"System health"** card on the **Overview** page surfacing live
process/runtime telemetry from `GET /api/diagnostics`: CPU %, memory MB, process
uptime, the Whisper model + compute type, and the active small/big brains.

### Files touched
- `dashboard/src/pages/Overview.tsx` — **only** file edited (this agent owns it).
  Added: a local `Diagnostics` type, a small `fetchDiagnostics()` reader, the
  `SystemHealthCard` component (+ `HealthRow` row + `pressureClass`/`brainLabel`
  helpers), and the layout change that hosts it. The rest of the Overview is
  unchanged.

### Data source — why a local reader, not `lib/api.ts`
`GET /api/diagnostics` is owned by the parallel iteration-7 **backend** agent and
is **not** in `lib/api.ts` (and we must not edit that file). So Overview reads it
with a tiny direct `fetch` that mirrors the api client's conventions:
- same `VITE_API_BASE` resolution (`(import.meta.env.VITE_API_BASE ?? "")`),
  so it works identically in dev (Vite proxy) and prod (same-origin), and
- the same `{detail|error}` error-envelope handling the api client uses.

The `Diagnostics` type mirrors **`docs/dashboard/diagnostics.md`** (the backend
agent's pinned shape) exactly, but every field is optional and rendered
defensively (`—` placeholders, optional badges), so the card degrades gracefully
when the backend returns its `"unknown"`/sentinel envelope (off-mac, missing
`psutil`, etc.):
```ts
{
  process?: { cpuPercent?: number; memMb?: number; uptimeSeconds?: number };
  stt?: { model?: string; computeType?: string; sampleRate?: number };
  smallBrain?: { provider?: string; model?: string };
  bigBrain?: { provider?: string; model?: string };
  error?: string;   // the endpoint returns {error} instead of a 500
}
```
The backend uses the literal string `"unknown"` as its sentinel for unreadable
config (not an omitted field), so `brainLabel()` and the STT/Whisper row treat
`"unknown"` as empty and fall back to `—`. We read `memMb` (not `memoryMb`) and
the nested `process.*` / `stt.*` / top-level `smallBrain`/`bigBrain` keys per
that doc. The endpoint surfaces `tts` and `platform` too — not shown on this
card by design (the card's scope is CPU/mem/uptime/Whisper/brains).
> **TODO (cross-agent):** fold a typed `api.diagnostics()` into `lib/api.ts` in a
> future iteration so this local reader can be removed (we couldn't edit
> `lib/api.ts` here).

### Design
- Glass card (`<Card glass>`), rounded-2xl, hairline border, generous padding,
  with a soft `accent-2` radial glow in a corner — consistent with the sibling
  "Today's cost" card it stacks beneath.
- **Small stat rows** (`HealthRow`): a muted icon+label on the left, the value on
  the right, separated by `divide-y divide-border/60` hairlines — the established
  stat-row idiom.
- **Subtle live feel:** a header `ListeningPulse` (the dashboard's signature
  violet pulse) animates only while the daemon is `running` and diagnostics are
  healthy; the adjacent word reads `live` / `idle` / `offline`. Numbers animate
  via the shared `SlidingNumber` (spring; `motion/react` dep), and CPU/memory/
  uptime tick on the 4s `refetchInterval`.
- **Pressure colour:** CPU value is green < 60%, amber 60–85%, red ≥ 85%
  (`pressureClass`) so load reads at a glance.
- Whisper compute type renders as a mono `outline` `<Badge>`; brains render as
  `small · big` model labels in mono (falling back to provider, then `—`).
- All motion respects `prefers-reduced-motion` via the existing primitives.

### States
- **Loading** — each row shows a `Skeleton`, matching the metric-card skeletons.
- **Error / unavailable** — a thrown fetch error *or* an `{error}` envelope (e.g.
  the diagnostics module not being built yet) shows a centered gauge icon,
  "Diagnostics unavailable", and the underlying message; the indicator reads
  `offline` with a static (non-pulsing) dot. No console noise, page stays intact.
- **Populated** — the five stat rows with live, animated values.

### Layout
The lower Overview section is a 3-col grid. The left column (`lg:col-span-1`) now
**stacks** the existing "Today's cost" card and the new "System health" card; the
"Live activity" feed keeps `lg:col-span-2` on the right. This keeps the grid
balanced and the existing cards byte-for-byte intact (only their wrapper changed).

### Verify
1. `cd dashboard && npm run typecheck` → passes (no new errors).
2. `npm run build` → `dashboard/dist` builds clean.
3. In the app, open **Overview**:
   - Bridge down / `diagnostics` module missing → the **"Diagnostics
     unavailable"** error state shows (offline dot, message), page intact.
   - With the bridge live (or a stubbed `/api/diagnostics`): CPU/Memory/Uptime/
     Whisper/Brains rows populate and animate; the header pulse goes `live`;
     CPU colour reflects load. Verified via Playwright against both a stubbed
     success response and the real bridge-down error path at 1440px.

---

## Iteration 7 — Theme switcher, keyboard shortcuts & help overlay (shell)

Frontend-shell additions. **Owned files only:** `src/App.tsx`,
`src/components/layout/*`, `src/index.css`, `src/lib/api.ts`. All additive; the
voice daemon is untouched (no Python edited by this agent).

### 1. Theme switcher (dark default + premium light)

- **Tokens (`index.css`).** Dark stays the default and lives on `:root` (so the
  hardcoded `class="dark"` in `index.html` and any no-JS render stay correct).
  A new **`.light`** block overrides the same token names with a *premium
  daylight* palette — cool off-white surfaces (misted slate `#f4f5f9`, never pure
  white), cards lifted to `#fff` above the bg, deepened violet→cyan accent and
  `-600` semantic colours for AA contrast on light, plus a soft cool shadow.
- **Theme-aware glass.** `.glass` now reads `--glass-bg`, `--glass-bg-alpha`,
  `--glass-border` (RGB), `--glass-border-alpha`, and `--glass-shadow`, all set
  per theme. On dark: white hairline + black drop shadow. On light: white veil +
  dark slate hairline + soft cool shadow. Every existing glass/accent surface
  (cards, TopBar, palette, overlays) flips automatically — no per-component work.
  The accent gradient (`.bg-brand-gradient`) and token-driven scrollbar already
  worked in both.
- **`ThemeProvider` / `useTheme` (`layout/theme.tsx`).** Toggles `.dark`/`.light`
  + `color-scheme` on `<html>`, persists to `localStorage["vox.theme"]`,
  **defaults to dark**. Storage failures (private mode) degrade to session-only.
  Mounted in `App.tsx` (wraps `<Routes>`) so the context reaches the TopBar.
- **`ThemeToggle` (`layout/ThemeToggle.tsx`).** Small TopBar button; Sun/Moon
  cross-fades + rotates via `motion`, respects reduced-motion.

### 2. Keyboard shortcuts (g-then-key navigation)

- **Registry (`layout/shortcuts.ts`).** Single source of truth shared by the
  handler and the help overlay so they never drift: `GO_SHORTCUTS`
  (`g`→`o` Overview, `u` Usage, `s` Settings, `p` Personalities, `a` AX Tree,
  `r` Rules, `m` Memory — mirrors the SideNav) and `GLOBAL_SHORTCUTS`
  (⌘K, `?`, Esc).
- **Handler (`layout/useKeyboardShortcuts.ts`).** Window `keydown` listener,
  mounted once in `AppShell`. Arms on `g`, navigates on the next key within a
  1.2 s timeout (a stray `g` disarms, never sticks). **Never fires while typing**
  (ignores `INPUT`/`TEXTAREA`/`SELECT`/`contenteditable`) and ignores modified
  chords so ⌘K (handled separately in `AppShell`) is unaffected. `?` opens help.

### 3. Help overlay

- **`layout/HelpOverlay.tsx`.** Glassy modal mirroring the CommandPalette recipe
  (portal + `AnimatePresence` + reduced-motion fallback). Lists the full
  `g`-nav set ("press `g` then…") and the general shortcuts (⌘K / `?` / Esc) as
  `<kbd>` chips, with accent hairline, header icon, and footer hint. Opened by
  `?` or the TopBar **`?`** button; closes on Esc / scrim / `×`. Mounted once in
  `AppShell` alongside the palette.

### 4. API client helpers (`lib/api.ts`)

- `api.budget()` → `BudgetStatus | ApiErrorBody` for `GET /api/budget`
  (`{budgetUsd, spentUsd, remainingUsd, percent, state}`, `state`:
  none/ok/warn/over — mirrors `usage.budget_status()` per backend.md §it.7).
- `api.diagnostics()` → `Diagnostics` for `GET /api/diagnostics` (open record;
  shape owned by the diagnostics agent, `error?` present on failure).
- Both routes return HTTP 200 with `{error}` when their bridge module is absent;
  added `isApiError(value)` type-guard so page agents narrow before reading.

### Verify
1. `cd dashboard && npm run typecheck` → passes (no new errors).
2. `npm run build` → `dashboard/dist` builds clean; the `.light` block and
   `--glass-*` vars are present in `dist/assets/*.css`.
3. In the app (verified via Playwright at 1440px against the built bundle):
   - First load is **dark** (`html.dark`, bg zinc-950), no stored value.
   - The TopBar **theme toggle** flips to `html.light` (bg `#f6f6f9`, ink text),
     persists `vox.theme=light`, and survives reload.
   - **`?`** opens the help overlay showing all 7 g-nav rows + ⌘K/?/Esc; **Esc**
     closes it.
   - **`g` then `u`** (within the timeout) navigates to `/usage`; the same chord
     **typed inside an `<input>`** does **not** navigate (input guard holds).
