# Memory page (frontend)

`dashboard/src/pages/Memory.tsx` — UI for Vox's long-term memory: facts and
preferences it can recall mid-conversation. Consumes the memory backend
(`src/vox/memory.py`, documented in `memory.md`); this doc covers the React page
only. Replaced the `ComingSoon` stub.

## What it does

- Loads the full recall list from `GET /api/memory` (`Memory[]` =
  `{id, ts, text, tags, score?}`) via `@tanstack/react-query` (`api.memory()`
  from `lib/api.ts`). Cache key `["memory"]`.
- **Add** (top composer): a `Textarea` for the memory text + an `Input` for
  optional comma-separated tags → `POST /api/memory` `{text, tags?}`
  (`api.addMemory`). ⌘/Ctrl+↵ saves from either field. Tags are parsed,
  trimmed, and de-duped (case-insensitive) and previewed as chips live. On
  success the list query is invalidated and the composer clears.
- **Search**: a debounced (250ms) search box queries
  `GET /api/memory?query=…` (`api.memory(query)`) under a per-term cache key
  `["memory","search",q]`, so typing never clobbers the recall list. Results
  are shown ranked, each with a relevance chip rendered from the backend's
  `score` (`Math.round(score*100)% match`). Clearing the box (✕ or empty)
  returns to the full list.
- **Delete**: a trash icon on each card opens a confirm `Dialog` (shows a
  truncated preview of the text) → `DELETE /api/memory/{id}`
  (`api.removeMemory`). On success the list (and any open search results) are
  invalidated. Error toasts, same pattern as `Personalities.tsx`.

Relative timestamps ("just now" / "12s" / "4m" / "2h" / "3d") use the shared
`relativeTime` helper from `lib/utils.ts`, ticking via the `useNow` hook (15s
interval). The full ISO time is in each card's `title` tooltip.

## States

- **Loading**: six glass skeleton cards.
- **Empty** (nothing memorised): premium centered card — gradient glow halo,
  brain icon, prompt explaining Vox pulls relevant memories into conversations.
- **No results** (search miss): centered glass card naming the query with a hint
  to clear or reword.
- **Error** (bridge unreachable): glass danger-bordered notice; memories load
  once the daemon returns.

## Design

Native to Overview / Token-Usage / Settings / Personalities:

- Dark glass cards (`<Card glass>`, backdrop-blur + hairline border),
  rounded-2xl, generous padding.
- Violet→cyan accent gradient (`bg-brand-gradient`) for the composer glow,
  empty-state halo, and the gradient "Remember this" button. Accent color for
  tag-icon, relevance chips, and the header count badge.
- Tags render as `Badge` chips (outline on cards, accent in the composer
  preview).
- Motion via the existing `motion` dep: `FadeIn` (composer + empty/no-result
  states) and `Stagger`/`StaggerItem` (the card grid). Cards lift on hover; the
  delete affordance fades in on hover/focus.
- Header `Badge` shows the total memory count; the header description states Vox
  recalls these mid-conversation.

## Boundaries

- Owns **only** `dashboard/src/pages/Memory.tsx`.
- Uses the existing typed client in `lib/api.ts` (NOT edited) — `api.memory /
  addMemory / removeMemory` already existed and match the contract.
- Routing + nav for `/memory` already wired (`App.tsx`, `layout/*`) — untouched.
- Backend (`src/vox/memory.py` + its `/api/memory` routes) is a separate agent's
  file (see `memory.md`); this page is purely the consumer. Until the bridge
  serves `/api/memory`, the page shows its error/empty state gracefully.

## Verify

```bash
cd dashboard
npm run typecheck   # or: npx tsc -b   → no errors
npm run build       # full prod build  → succeeds
npm run dev         # then open /memory
```

With the bridge running: add a memory (type text, optional tags, ⌘↵ or the
button), watch it appear; type in the search box to see scored matches; delete
via the trash icon's confirm dialog. Without the bridge: the error notice
renders and add/delete toast gracefully.
