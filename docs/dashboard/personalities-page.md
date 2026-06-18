# Personalities page — Default / base-Vox card

Owned file: `dashboard/src/pages/Personalities.tsx` (frontend only).

## What changed

The personalities bridge now prepends a synthetic **Default** entry to `presets`
(`id: "default"`, `emoji: "🎙️"`, empty `persona`) representing *no* special
character — base Vox. The page renders it as a distinct first card so the user
can always return to plain Vox.

- **`DefaultCard`** — a calm "base" card, deliberately *not* a character:
  - Dashed hairline border (`border-dashed border-border-strong/70`) signalling
    "no persona / base slot" rather than a styled character card.
  - A `Mic` glyph instead of a persona emoji; quieter active halo
    (`bg-accent/40`) than the persona cards' `bg-brand-gradient`.
  - Label **"Default"** / "Vox as itself", a short explainer, and a `Base` chip.
  - Shows the standard accent ring + "Active" badge when base is selected.
- **Gallery order** — the Default card always leads the Presets grid, followed by
  the character presets. The "Presets" count now reflects character presets only
  (the synthetic entry is split out via `defaultEntry` / `characterPresets`).
- **Header badge** — shows the active character persona as before; when no persona
  is active it shows an `outline` badge "Default — Vox as itself".
- **Activate / create / delete** — unchanged for presets and custom personas.

## Key decision — how "default" deselects

The contract says "POST `/api/personalities/active` with id `default`", but the
running bridge's `set_active(pid)` only accepts `""` or a **real** preset/custom
id and raises `ValueError` (→ HTTP 400) on anything else. The synthetic
`"default"` id exists only in the `all()` response, not in `_PRESETS_BY_ID`.

So the client:

- Treats `activeId === "default"` **or** `""` as "base Vox is active"
  (`onDefault`). The bridge reports `active: "default"` when nothing is set.
- On click, optimistically marks Default active under id `"default"`, but the
  network call sends `""` — `api.setActivePersonality(id === "default" ? "" : id)`
  — which is the real deselect path. This keeps base-Vox selectable against the
  actual backend without a 400.

This lives entirely in `useSetActive` (mutationFn translation + a tolerant
success toast that says "Back to base Vox" for the deselect case).

## Constraints honoured

- Only `Personalities.tsx` touched (no `lib/api.ts`, no shared components).
- Uses the existing `api` client, shadcn primitives (`Card`, `Badge`, `Button`),
  motion via `Stagger`/`StaggerItem`, and the established theme tokens
  (accent/violet→cyan, glass, hairline borders).
- Additive + guarded: nothing here affects the voice daemon.

## How to verify

1. `cd dashboard && npx tsc -b --noEmit` — no errors in `Personalities.tsx`.
   (A separate in-flight `@/pages/Handbook` import error in `App.tsx` is another
   agent's file, unrelated.)
2. Run the bridge + dashboard, open the Personalities page:
   - The first card is the dashed **Default** card. With no persona set it shows
     **Active** and the header shows "Default — Vox as itself".
   - Activate any character preset → Default loses Active, header shows the
     persona. Click the Default card → toast "Back to base Vox", persona cleared,
     `data/personalities.json` `active` becomes `""`.
   - Create/delete custom personas still work; the custom gallery and empty state
     are unchanged.
