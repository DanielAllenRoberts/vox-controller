# Handbook page (`dashboard/src/pages/Handbook.tsx`)

A premium, searchable reference for **everything you can say and do** with Vox —
wake phrases, control commands, modes and features — in one scannable page.

## What it does

- Fetches the catalog from **`GET /api/handbook`** (defined in
  `src/vox/web/server.py` → `_handbook()`), which returns a flat list of groups:
  the **live** phrase groups pulled from `vox.config.CONFIG` (so the documented
  vocabulary never drifts from what the daemon listens for), followed by curated
  **static** groups (Control Commands, Modes, Features).
- Renders each group as a **glass card** with an icon, a title + entry count
  badge, an optional blurb, and a list of phrase rows.
- A **search box** at the top filters live across every entry —
  case-insensitive substring over each item's `phrase` + `description`, plus the
  group `title` (a title match keeps the whole group). Groups with no surviving
  items are hidden; a match count shows in the box.
- **Click-to-copy** on every phrase row: copies the phrase to the clipboard,
  flashes a check, and toasts confirmation.
- Intro line under the title: *"Everything you can say and do — wake phrases,
  control commands, modes and features, in one searchable reference."*

## Response shape (mirrors the Python bridge exactly)

```ts
HandbookItem  = { phrase: string; description: string }
HandbookGroup = { title: string; blurb?: string; items: HandbookItem[] }
// GET /api/handbook -> HandbookGroup[]
```

Verified against the live bridge: 7 groups / 99 items, each item exactly
`{phrase, description}`. The page normalises defensively (drops malformed
groups/items and empty groups) so a partial backend response can't crash the
render.

## States

- **Loading** — a grid of shimmer skeleton cards.
- **Error** (bridge unreachable) — the standard "is the daemon running on
  127.0.0.1:8765?" card, matching the other pages.
- **Empty** (endpoint returns `[]`) — a friendly "handbook is empty" card.
- **No search results** — a centered prompt with a "Clear search" action.

## Design

Matches the established dashboard look: glass cards (`Card glass`,
backdrop-blur + hairline border), a left-edge brand-gradient hairline and a soft
gradient glow per card, violet→cyan accent on icon chips and badges, generous
spacing, `FadeIn` / `Stagger` entrance animations (via the existing `motion`
dep, reduced-motion aware), and works in both dark and light themes through the
shared tokens. Icons are chosen per group title (`lucide-react`) with a sensible
fallback so new backend groups still get an icon.

## Interactions

- Press **`/`** anywhere (when not already typing) to focus the search box;
  **Esc** clears it. The grid re-keys on the query so filtering replays the
  stagger entrance.

## Ownership / boundaries

- This page **only** touches `dashboard/src/pages/Handbook.tsx` (owned by this
  agent) and this doc. It does **not** edit `lib/api.ts`, `nav.ts`, or `App.tsx`
  (owned by the shell/integration agent).
- The shell/integration agent has already added `api.handbook()` plus the
  `HandbookGroup` / `HandbookItem` types to `lib/api.ts`, so this page consumes
  the **shared typed client** (`import { api, type HandbookGroup, ... }`) rather
  than a private fetch helper. It still wraps the call in a defensive normaliser
  (`fetchHandbook`) that drops malformed groups/items so a partial payload can't
  crash the render.

## Wiring (already done by the integration/shell agent)

The route, nav entry and backend endpoint are all in place:

- `dashboard/src/App.tsx` — routes `path="handbook"` → `<Handbook />`.
- `dashboard/src/components/layout/nav.ts` — `NAV_ITEMS` entry
  `{ to: "/handbook", label: "Handbook", icon: BookOpen }`.
- `src/vox/web/server.py` — `GET /api/handbook` → `_handbook()`.

No further wiring is needed; visiting `/handbook` renders the page.

## How to verify

- Typecheck: `cd dashboard && npx tsc -b --noEmit` (passes).
- Build: `cd dashboard && npx vite build` (passes).
- Payload: `uv run python -c "from vox.web import server; print(len(server._handbook()))"`.
- Live: run the daemon (or `python -m vox.web.server`), wire the route per the
  TODO above, open the dashboard, and visit `/handbook` — type in the search box
  to filter, click any phrase to copy it.
