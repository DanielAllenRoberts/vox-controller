# AX Tree page (`dashboard/src/pages/AxTree.tsx`)

Frontend visualiser for the read-only accessibility tree of the focused macOS
app. Pairs with the backend reader documented in [`axtree.md`](./axtree.md) and
the `GET /api/axtree` route. **Read-only** — it only renders; it never interacts
with the target UI.

## Data flow

- Fetches via `api.axtree()` (`lib/api.ts`, owned by the shell agent — not edited
  here) using `@tanstack/react-query` under the key `["axtree"]`.
- The endpoint returns either `AxTree = {app, capturedAt, tree: AxNode}` or a
  graceful `{error}` (off-mac / missing Accessibility permission / no front
  window / timeout). The page narrows the union with an `isErrorPayload` guard
  and renders the matching state — a non-2xx HTTP response (bridge down) is a
  separate `isError` branch.
- `AxNode = {role, title?, value?, enabled?, children: AxNode[]}`.

## Features

- **Collapsible tree** — recursive `TreeNode`. Each node shows `role` (mono),
  `title` (when present), and `value` (mono, when present), plus a child-count
  chip. Parents get a rotating chevron; leaves get a dot. Expand/collapse is
  animated (motion height/opacity, disabled under reduced-motion).
- **Indentation guides** — one absolutely-positioned hairline per ancestor level
  (`bg-border/50`), so deep trees stay readable.
- **Filter / search** — debounce-free text filter matches role/title/value.
  Matches are highlighted (`<mark>` accent tint), ancestors of a match are
  auto-revealed, and non-matching branches dim. A live match count shows in the
  toolbar; a no-matches empty state appears when nothing hits.
- **Expand all / Collapse all** — bulk toggles that pre-compute every parent id.
- **Refresh** — manual refetch with a spinning icon while fetching.
- **Auto-refresh toggle** — a `Switch` that drives react-query `refetchInterval`
  (every 3s); a pulsing "Live" badge appears while active.
- **Empty / error states** — `classifyError` shapes copy for off-mac, missing
  Accessibility permission (links to System Settings → Privacy & Security →
  Accessibility), no front window, and generic/bridge-down failures, always
  showing the raw error string for debugging.

## State model

- Expand state is a `Set<string>` of node ids, where the id is the node's path
  (`"0.2.1"`) — stable across re-renders for a given tree. Root (`"0"`) starts
  open.
- While searching, the computed `reveal` set is layered on top of the manual
  open set so matches show without mutating user toggles; clearing the query
  restores the manual state.

## Design

Matches the established premium look: dark glass cards (`Card glass`), hairline
borders, violet→cyan accent (`bg-brand-gradient`, `text-accent`) for active /
primary states, `FadeIn` entrance, motion micro-interactions, and the shared
shadcn primitives (`Button`, `Badge`, `Input`, `Switch`, `ScrollArea`,
`Skeleton`). Feels native to Overview / Token Usage / Settings / Personalities.

## Verify

1. `cd dashboard && npm run build` — type-checks and builds clean.
2. With the daemon running on a Mac, open the dashboard, go to **AX Tree**:
   focus an app, hit **Refresh** → the tree renders; type in the filter →
   matches highlight and reveal; toggle **Auto-refresh** → it re-polls with a
   Live badge.
3. Off-mac or without Accessibility permission → the corresponding guided error
   state renders (no crash, daemon unaffected).

## TODOs / future

- `enabled` is part of `AxNode` but not yet surfaced in the row (kept minimal —
  add a dimmed/"disabled" chip if it proves useful).
- No virtualisation; the backend already bounds depth/breadth, so trees stay
  small. Revisit if larger snapshots land.
