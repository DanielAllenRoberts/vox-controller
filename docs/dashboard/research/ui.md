# Vox Control Center — UI / Design System Research

> Iteration 1 (Foundation) research. Defines the design system the frontend agent builds against. Grounded in the `CONTRACT.md` "Theme / craft" section: dark-first premium "AI control center" (Linear × Vercel × Arc), zinc-950 base, glassy cards, violet→cyan accent, Inter/Geist, rounded-2xl, tasteful Animate UI motion. **This is a spec, not code.** The frontend agent owns implementation under `dashboard/`.

---

## 1. Setup confirmation — hand-written, no CLI, no network

The contract's stack is confirmed feasible **without ever running a component CLI or hitting the network at build time**:

- **Vite + React 18 + TypeScript** — standard `npm create vite@latest -- --template react-ts`. No design constraints.
- **TailwindCSS** — config + `@tailwind` directives in `src/index.css`. Theme tokens live as CSS variables in `index.css` (`:root` / `.dark`) and are referenced from `tailwind.config.ts` (`theme.extend.colors` mapped to `hsl(var(--…))` / `var(--…)`), exactly the shadcn convention.
- **shadcn/ui** — shadcn is **copy-paste source**, not an npm runtime package. Each component (`button.tsx`, `card.tsx`, …) is a small self-contained file using Radix primitives + `cva` + `cn()`. We **hand-write** these under `src/components/ui/`. The only runtime deps are the Radix packages (`@radix-ui/react-*`), `class-variance-authority`, `clsx`, `tailwind-merge`, `tailwindcss-animate`. A `components.json` is included for editor/tooling parity but **the CLI is never invoked**.
- **Animate UI** — same model: Animate UI is a copy-paste "component distribution" (Primitives = unstyled-but-animated, Components = styled, Icons = animated Lucide). Its registry command (`shadcn add @animate-ui/…`) just copies source files. We **hand-write** the handful we need (`SlidingNumber`, `CountingNumber`, fade/spring wrappers, `ListeningPulse`) under `src/components/animate/`. The only runtime dep is **`motion`** (the successor package to `framer-motion`; `import { motion } from "motion/react"`).
- **No network at runtime** — fonts are **self-hosted/bundled** (Geist + Inter via `npm` font packages or local `woff2`), never Google Fonts CDN. The dashboard is served locally by the FastAPI bridge.

**Runtime dependency list (frontend):** `react`, `react-dom`, `react-router-dom`, `@tanstack/react-query`, `motion`, `recharts`, `lucide-react`, `class-variance-authority`, `clsx`, `tailwind-merge`, `@radix-ui/react-*` (per component), plus dev: `vite`, `typescript`, `tailwindcss`, `postcss`, `autoprefixer`, `tailwindcss-animate`, `@types/*`.

> **Why this matters:** the orchestrator builds offline-friendly and the daemon must keep working even if the dashboard build fails. Hand-written source means no surprise CLI prompts, no registry drift, and every file is reviewable/diffable.

---

## 2. Design direction — synthesis of the references

| Reference | What we take |
|---|---|
| **Linear** | The violet/indigo→cyan accent, restrained chrome, hairline borders, dense-but-calm information layout, fast spring transitions, command-palette ergonomics. |
| **Vercel / Geist** | Monochrome zinc foundation with a *single* accent, flat surfaces (no skeuomorphism), Geist typeface, tabular numerals for metrics, ruthless restraint. |
| **Arc** | Personality and playful motion *in moderation* — a "living" feel via the listening pulse, gentle gradients, and delightful micro-interactions, without becoming toy-like. |
| **Paperclip-style local daemon dashboards** | "Control center / task-manager" mental model: a persistent left **SideNav**, a status-forward **TopBar**, page = a focused board. Local-first, cost/audit-forward (token + cost always visible), governance/toggles surfaced as first-class panels. |

**One-line aesthetic:** *Quiet, premium, dark control room with one electric accent and motion that confirms rather than decorates.*

---

## 3. Palette (exact hex)

Dark-first. Light theme is a stretch goal (see §9). Surfaces are **zinc** (Tailwind zinc scale — cool neutral, signals precision). Accent is **violet→cyan**.

### 3.1 Neutrals / surfaces (Tailwind `zinc`)

| Token | Role | Hex |
|---|---|---|
| `--bg` | App background (base) | `#09090b` (zinc-950) |
| `--bg-elevated` | Raised background / sidebar | `#0c0c0e` (between 950/900) |
| `--surface` | Card / panel fill | `#18181b` (zinc-900) |
| `--surface-2` | Inset / nested fill | `#27272a` (zinc-800) |
| `--border` | Hairline border | `#27272a` (zinc-800) @ ~70% → use `#ffffff14` overlay for glass edges |
| `--border-strong` | Emphasised border / focus base | `#3f3f46` (zinc-700) |
| `--muted` | Muted fill / hover | `#27272a` (zinc-800) |
| `--fg` | Primary text | `#fafafa` (zinc-50) |
| `--fg-secondary` | Secondary text | `#a1a1aa` (zinc-400) |
| `--fg-muted` | Tertiary / placeholder | `#71717a` (zinc-500) |
| `--fg-disabled` | Disabled | `#52525b` (zinc-600) |

Full zinc reference (for shade picking): `50 #fafafa · 100 #f4f4f5 · 200 #e4e4e7 · 300 #d4d4d8 · 400 #a1a1aa · 500 #71717a · 600 #52525b · 700 #3f3f46 · 800 #27272a · 900 #18181b · 950 #09090b`.

### 3.2 Accent (violet → cyan)

| Token | Role | Hex |
|---|---|---|
| `--accent` | Primary accent (violet) | `#8b5cf6` (violet-500) |
| `--accent-hover` | Hover/active | `#a78bfa` (violet-400) |
| `--accent-press` | Pressed | `#7c3aed` (violet-600) |
| `--accent-2` | Gradient end (cyan) | `#22d3ee` (cyan-400) |
| `--accent-ring` | Focus ring | `#8b5cf6` @ 60% (`#8b5cf699`) |
| **Signature gradient** | Brand / hero / active-nav | `linear-gradient(135deg, #8b5cf6 0%, #22d3ee 100%)` |

Accent is used **sparingly**: active nav item, primary buttons, focus rings, the live "listening" pulse, key metric highlights, and chart primary series. Everything else is monochrome zinc.

### 3.3 Semantic / status

| Token | Role | Hex (dark-tuned) | Subtle bg (12% alpha) |
|---|---|---|---|
| `--success` | Online / under budget | `#34d399` (emerald-400) | `#34d3991f` |
| `--warning` | Approaching budget / restart-needed | `#fbbf24` (amber-400) | `#fbbf241f` |
| `--danger` | Error / over budget / offline | `#f87171` (red-400) | `#f871711f` |
| `--info` | Neutral info / subscription cost note | `#60a5fa` (blue-400) | `#60a5fa1f` |

Status colors use the `-400` step (lifted lightness) for adequate contrast on dark surfaces, per dark-mode semantic-color guidance.

### 3.4 Charts (recharts series)

Ordered palette for per-model / per-brain series, harmonised with the accent:

`#8b5cf6` (violet) · `#22d3ee` (cyan) · `#34d399` (emerald) · `#fbbf24` (amber) · `#f472b6` (pink-400) · `#60a5fa` (blue). Grid lines `#27272a`; axis text `#71717a`.

### 3.5 Glass card recipe

```
background: rgba(24,24,27,0.55);   /* zinc-900 @ 55% */
backdrop-filter: blur(12px) saturate(120%);
border: 1px solid rgba(255,255,255,0.08);  /* hairline */
border-radius: 1rem;                /* rounded-2xl = 16px */
box-shadow: 0 1px 0 rgba(255,255,255,0.04) inset,
            0 8px 24px rgba(0,0,0,0.40);
```

---

## 4. Typography

**Primary UI face:** **Geist Sans** (Vercel). Built for dashboards/dense tables, clean tabular figures, sharp at small sizes. **Fallback / equally acceptable:** **Inter**. Stack: `"Geist", "Inter", ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif`.

**Mono:** **Geist Mono** for token counts, model ids, cost figures, the AX-tree, and code. Stack: `"Geist Mono", ui-monospace, "SF Mono", "JetBrains Mono", monospace`.

**Self-hosted** (npm `geist` package or local `woff2`) — no CDN.

**Numerals:** enable `font-feature-settings: "tnum" 1, "cv01" 1;` on metrics so counters don't jitter as digits change. Animated counters (§6) must use tabular figures.

### Type scale (rem / px @ 16px base)

| Token | Size | Line height | Weight | Tracking | Use |
|---|---|---|---|---|---|
| `display` | 2.25rem / 36px | 1.1 | 600 | -0.02em | Big metric numbers (cost/tokens) |
| `h1` | 1.5rem / 24px | 1.2 | 600 | -0.015em | Page title |
| `h2` | 1.25rem / 20px | 1.3 | 600 | -0.01em | Card / section title |
| `h3` | 1rem / 16px | 1.4 | 500 | 0 | Sub-section |
| `body` | 0.875rem / 14px | 1.5 | 400 | 0 | Default UI text |
| `body-sm` | 0.8125rem / 13px | 1.5 | 400 | 0 | Secondary text |
| `label` | 0.75rem / 12px | 1.3 | 500 | 0.02em | Form labels, nav |
| `overline` | 0.6875rem / 11px | 1.2 | 600 | 0.08em UPPERCASE | Group headers, eyebrows |
| `mono` | 0.8125rem / 13px | 1.5 | 400 | 0 | Tokens, ids, AX tree, code |

Default body is **14px** (dashboard density). Color: primary text `--fg`, secondary `--fg-secondary`, never pure white on pure black (zinc-50 on zinc-950).

---

## 5. Layout

**App shell** = persistent left **SideNav** + sticky **TopBar** + scrollable content. Implemented as `components/layout/{AppShell,SideNav,TopBar}.tsx`.

```
┌──────────────────────────────────────────────────────────┐
│ TopBar:  Vox ●Listening    [⌘K]      brain · personality  │  56px, sticky, glass
├───────────┬──────────────────────────────────────────────┤
│ SideNav   │  Page content (max-w-[1200px], px-6/8, py-6)  │
│ 240px     │                                               │
│           │  ┌──── grid of glass cards (gap-4/6) ────┐    │
│ Overview  │  │  metric   │  metric   │  metric        │    │
│ Token Use │  │  ─────────┴───────────┴──────────────  │    │
│ Settings  │  │  chart / live feed                     │    │
│ Personas  │  └────────────────────────────────────────┘    │
│ AX Tree   │                                               │
│ Rules     │                                               │
│ Memory    │                                               │
│ ───────── │                                               │
│ ●online   │                                               │
└───────────┴──────────────────────────────────────────────┘
```

- **SideNav** — 240px (collapsible to a 64px icon rail at `lg` breakpoint as a later nice-to-have). Sections: **Overview, Token Usage, Settings, Personalities, AX Tree, Rules, Memory** (mirrors `src/pages/*`). Active item: violet text + left 2px gradient indicator + subtle `--surface` fill; inactive: `--fg-secondary`. Daemon status dot pinned at the bottom (green online / red offline / amber connecting).
- **TopBar** — 56px sticky glass. Left: product mark + live status ("●Listening" pulse when daemon active). Center/right: `⌘K` command-palette affordance (scaffold only in iter 1), current brain + personality chips.
- **Content** — centered column `max-w-[1200px]`, generous padding (`px-6 lg:px-8 py-6`), responsive card grid (`grid gap-6 md:grid-cols-2 xl:grid-cols-3`), `rounded-2xl` cards. **Mobile:** SideNav collapses to a sheet/drawer below `md`.
- **Spacing scale:** Tailwind defaults; card padding `p-5`/`p-6`, section gap `gap-6`, inner stack `gap-3`. **Radii:** cards/dialogs `rounded-2xl` (16px), buttons/inputs/badges `rounded-lg`/`rounded-xl`, pills `rounded-full`.
- **Breakpoints:** `sm 640 · md 768 · lg 1024 · xl 1280`. Single-column < `md`, 2-col `md`, 3-col `xl`.

---

## 6. Key components

### shadcn/ui (`src/components/ui/*`) — hand-written
Iteration-1 foundation needs: `button`, `card`, `badge`, `separator`, `skeleton`, `tooltip`, `scroll-area`. Later iterations add: `switch`, `tabs`, `input`, `select`, `slider`, `dialog`, `dropdown-menu`, `sheet`, `command` (⌘K), `table`, `sonner`/toast, `tabs`. All use the zinc/violet tokens above via `cn()` + `cva` variants.

### Animate UI (`src/components/animate/*`) — hand-written
- **`SlidingNumber` / `CountingNumber`** — odometer/spring number transitions for token & cost counters (the headline metric animation). Tabular figures, `motion`-driven.
- **`FadeIn` / `Stagger`** — page + list entrance wrappers (`motion` variants; respects `prefers-reduced-motion`).
- **`SpringTabs`** — animated tab indicator that springs between tabs (settings groups, usage breakdown views).
- **`ListeningPulse`** — the live "listening" indicator: a soft pulsing violet ring/dot driven by daemon status (the dashboard's signature "alive" element).
- **`PageTransition`** — route-level fade/slide between pages.

### Composite (app-specific, built on the above)
- **`MetricCard`** — glass card: overline label + big `SlidingNumber` value + delta/sparkline + status dot. The Overview & Token Usage workhorse.
- **`StatusDot` / `StatusBadge`** — semantic dot+label (online/offline/connecting/over-budget).
- **`BrainChip` / `PersonalityChip`** — compact pills in the TopBar showing live brain (provider·model) + personality emoji.
- **`LiveFeedRow`** — a single streamed `UsageEvent` row (provider, model, brain, tokens, cost, latency) for the live usage feed (iteration 2+).
- **`EmptyState`** — illustrated empty/error/offline panel (graceful degradation, e.g. AX-tree off-mac).

### Iteration-1 (Foundation) component scope
Only what the **Overview** page + shell need: `AppShell`, `SideNav`, `TopBar`, `MetricCard`, `StatusDot`/`StatusBadge`, `ListeningPulse`, `SlidingNumber`, `FadeIn`/`Stagger`, plus `button`/`card`/`badge`/`skeleton`/`tooltip`. Everything else is stubbed/scaffolded for later iterations.

---

## 7. Motion patterns

Principle: **motion confirms state, it doesn't decorate.** Fast, spring-based, interruptible, and always gated by `prefers-reduced-motion` (fall back to instant or simple opacity).

| Pattern | Where | Spec |
|---|---|---|
| **Number transition** | Token/cost counters | Per-digit spring, `~600ms`, tabular figures. Update on poll/WS tick. |
| **Page transition** | Route change | Fade + 8px upward slide, `spring { stiffness: 260, damping: 30 }`, ~250ms. |
| **Staggered list entrance** | Cards, feed rows, settings | `staggerChildren: 0.04`, each child fade + 6px rise. |
| **Spring tab indicator** | Tabs/segmented controls | `layoutId` shared element, `spring { stiffness: 400, damping: 32 }`. |
| **Listening pulse** | TopBar / SideNav status | Infinite scale `1→1.25` + opacity `0.6→0` ring, ~1.6s ease-in-out. Violet. Only when daemon listening. |
| **Hover lift** | Interactive cards/buttons | `translateY(-1px)` + border brighten + faint accent glow, ~120ms ease-out. |
| **Focus ring** | Inputs/buttons | 2px `--accent-ring`, no layout shift (use ring, not border). |
| **Live data flash** | New feed row / fresh metric | Brief accent left-border / bg flash (`accent @ 12%` → transparent, ~700ms). |
| **Skeleton shimmer** | Loading | Subtle zinc-800→zinc-700 sweep while React Query is `pending`. |

**Durations:** micro 120ms · standard 200–250ms · entrance 300ms. **Easing:** UI springs for movement, `ease-out` for hovers/fades. Never block interaction on animation; all transitions interruptible.

---

## 8. Theming implementation notes (for the frontend agent)

- Define every token in `src/index.css` under `:root` (defaults to dark — set `<html class="dark">` and `color-scheme: dark`). Use HSL triplets for shadcn compatibility where the component expects `hsl(var(--…))`; raw hex/`oklch` is fine for app-specific tokens.
- Map tokens in `tailwind.config.ts → theme.extend.colors` (`background`, `foreground`, `card`, `muted`, `border`, `accent`, `success`, `warning`, `danger`, `info`) and `borderRadius` (`2xl` etc.).
- `cn()` in `src/lib/utils.ts` = `twMerge(clsx(...))` (standard shadcn).
- Keep the signature gradient as a single reusable utility class (e.g. `.bg-brand-gradient`) so nav indicator, hero, and primary CTA stay consistent.
- `prefers-reduced-motion`: wrap motion in a hook/util that swaps to instant variants.

---

## 9. Six+ "cool feature" ideas (later iterations)

Creative directions for iterations 7–8 ("creative rounds"), beyond the contracted pages. Not for iteration 1.

1. **Command palette (⌘K)** — fuzzy actions: switch brain, jump page, toggle a feature flag, set personality, add a rule/memory. Mirrors the voice command surface in a keyboard surface. (TopBar already scaffolds the affordance.)
2. **Live conversation / activity timeline** — a vertical, real-time stream of wake → transcript → brain → action → cost, with the `UsageEvent` WS feeding it. The "audit trail" Paperclip-style control center expects.
3. **Listening waveform / live mic visualizer** — animated waveform reacting to the daemon's audio level (via WS), reinforcing the "alive control room" feel; doubles as a mic-health indicator.
4. **Cost-budget alerts & burn-down** — set a daily/monthly USD budget; animated ring + projected burn-down; banner flips warning/danger as you approach/exceed; ties to the `--warning`/`--danger` tokens.
5. **Quick brain-switcher / A-B "brain duel"** — a TopBar toggle to flip small↔big brain live, plus an optional side-by-side latency/cost comparison card for the same prompt class.
6. **Personality playground & live voice preview** — pick/edit a personality, hear a `say`-voice sample, and preview a sample response in-tone before applying it live.
7. **Theme/skin switcher** — dark (default), an optional light theme, and a couple of accent skins (violet→cyan default, plus e.g. emerald or amber) swappable via CSS-variable sets.
8. **Onboarding spotlight tour** — first-run guided tour of the panels, with a "what needs a restart" legend for settings that require a daemon restart.
9. **AX-tree "x-ray" hover** — when iteration 5's AX-tree lands, hover a node to highlight role/value and offer copy-as-selector, building toward future UI automation.

---

## 10. How to verify this part

This is a **research/spec doc** — no code, nothing to run. Verification:

1. `docs/dashboard/research/ui.md` exists and is readable.
2. The palette (§3) and typography (§4) are concrete (exact hex / fonts / sizes) and consistent with `CONTRACT.md` "Theme / craft".
3. The frontend agent can implement `tailwind.config.ts` + `src/index.css` tokens and the iteration-1 component scope (§6) directly from this doc with no further design decisions.

When the frontend lands, the design is "correct" if: dark zinc-950 base, glassy hairline cards, one violet→cyan accent used sparingly, Geist/Inter type with tabular metric numerals, rounded-2xl, and the listening pulse animates only while the daemon is live.

---

### Sources
- [Animate UI](https://animate-ui.com/) · [animate-ui GitHub (imskyleen)](https://github.com/imskyleen/animate-ui) · [Sliding Number](https://animate-ui.com/docs/text/sliding-number) · [Components](https://animate-ui.com/docs/components)
- [Vercel Geist — Colors](https://vercel.com/geist/colors) · [Geist — Typography](https://vercel.com/geist/typography) · [Geist Font](https://vercel.com/font)
- [Tailwind zinc scale (uicolors)](https://uicolors.app/tailwind-colors/zinc) · [Tailwind Colors docs](https://tailwindcss.com/docs/colors) · [shadcn/ui colors](https://ui.shadcn.com/colors)
- [Paperclip (open-source AI agent control plane)](https://github.com/paperclipai/paperclip) · [Paperclip deep dive](https://dev.to/truongpx396/paperclip-deep-dive-a-build-guide-for-an-ai-company-control-plane-dda)
- [Modern UI color trends 2026 (Recursion)](https://www.recursion.agency/blog/ui-color-trends-2026) · [SaaS dashboard color palette (sixtythirtyten)](https://www.sixtythirtyten.co/blog/saas-dashboard-color-palette-css-tailwind)
