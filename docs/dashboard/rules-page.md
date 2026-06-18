# Rules page (frontend)

`dashboard/src/pages/Rules.tsx` — UI for the standing instructions injected into
Vox's system prompt on every turn. Consumes the rules backend documented in
`rules.md` (`src/vox/web/rules.py`); this doc covers the React page only.

## What it does

- Loads rules from `GET /api/rules` (`Rule[]` = `{id, text, enabled}`) via
  `@tanstack/react-query` (`api.rules()` from `lib/api.ts`).
- **Add** (top composer): single-line `Input` + gradient button → `POST /api/rules`
  `{text}` (`api.addRule`). Enter submits. Optimistic: the row appears immediately
  with a temp id and is reconciled to the server's rule on success.
- **Toggle**: animated shadcn `Switch` per row → `PATCH /api/rules/{id}` `{enabled}`
  (`api.updateRule`). Optimistic with revert-on-error.
- **Inline edit**: click the rule text (or the pencil) to edit in a `Textarea`.
  ⌘/Ctrl+↵ saves, Esc cancels → `PATCH /api/rules/{id}` `{text}`. Empty text won't
  save; a whitespace-only / no-op change is ignored.
- **Delete**: trash icon opens a confirm `Dialog` → `DELETE /api/rules/{id}`
  (`api.removeRule`). Optimistic removal, revert-on-error.

All mutations are optimistic (cache-patched) and toast on error while reverting the
cache — same pattern as `Settings.tsx` / `Personalities.tsx`.

## States

- **Loading**: three glass skeleton rows.
- **Empty**: premium centered card (gradient glow halo, scroll icon, prompt to add).
- **Error** (bridge unreachable): glass danger-bordered notice; rules load when the
  daemon returns.

## Design

Native to Overview / Token-Usage / Settings / Personalities:

- Dark glass cards (`<Card glass>`, backdrop-blur + hairline border), rounded-2xl.
- Violet→cyan accent gradient (`bg-brand-gradient`) for the active-rule left hairline,
  the add icon glow, and the gradient buttons.
- Disabled rules dim + strike-through the text (kept, just paused).
- Motion via the existing `motion` dep: `FadeIn` (explainer + composer + empty state)
  and `Stagger`/`StaggerItem` (the list). The Switch animates via its shadcn primitive.
- Header `Badge` shows the active-rule count; a short explainer card states enabled
  rules are appended to Vox's system prompt before every reply.

## Boundaries

- Owns **only** `dashboard/src/pages/Rules.tsx` (replaced the `ComingSoon` stub).
- Uses the existing typed client in `lib/api.ts` (not edited) — `api.rules / addRule /
  updateRule / removeRule` already existed.
- Routing + nav for `/rules` already wired (`App.tsx`, `layout/nav.ts`) — untouched.
- Backend (`src/vox/web/rules.py`) is a separate agent's file (see `rules.md`); this
  page is purely the consumer. Until the bridge serves `/api/rules`, the page shows its
  error/empty state gracefully.

## Verify

```bash
cd dashboard
npx tsc --noEmit -p tsconfig.app.json   # Rules.tsx: no errors
npm run dev                             # then open /rules
```

With the bridge running: add a rule (Enter or button), toggle it on/off, click the
text to edit (⌘↵ to save), delete via the trash icon's confirm dialog. Without the
bridge: the error notice renders and mutations toast + revert.
