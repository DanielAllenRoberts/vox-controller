# Dashboard — Integrations page (vox-speak MCP setup)

> Surfaces the **vox-speak** MCP (idea #34) so the user can wire it into their
> editor in a couple of copy-pastes. Realises MEMORY_DESIGN.md §"Integrations
> panel (MCP setup)". Owned file: `dashboard/src/pages/Integrations.tsx` (only).

## What the page does

vox-speak is a tiny MCP server (`mcp/vox_speak_server.py`) that gives the user's
**editor** assistant (Cursor / Claude Code) a voice via macOS `say` — it can
call a `speak` / `announce_done` tool to talk out loud while the user works. The
page:

> **⚠️ This page's copy is out of date (2026-08-31).** The server now also exposes `notify` (a
> silent on-screen bubble, ideas #62), and `register_agent` / `whoami` / `list_agents` (named
> agents, ideas #39). The hero still describes it as speech-only, and the setup block's `env`
> doesn't mention `VOX_AGENT_NAME`. See `mcp/README.md` for the current tool list. Updating
> `Integrations.tsx` needs a `dashboard/dist` rebuild, so it's a separate change.

- **Hero** — explains what vox-speak does in plain language, plus an "install
  the dependency" hint (`uv add mcp`) with a copy button.
- **Local-only note** — a guarded `ShieldCheck` card stating the config is
  generated locally for *this machine* and never committed, plus an
  "Open config location" affordance (POST `/api/mcp/reveal`, best-effort).
- **Cursor card** — short numbered steps + the `.cursor/mcp.json` `mcpServers`
  block in a copyable code box.
- **Claude Code card** — short numbered steps + the `claude mcp add …` command
  in a copyable code box.

## Data source — `GET /api/mcp/config` (consumed, not owned)

The page does a **direct same-origin `fetch`** (it must NOT edit `lib/api.ts`),
mirroring that file's `API_BASE` convention (`VITE_API_BASE` → same-origin
`/api`). The only machine-specific value is the **absolute repo path**; the
bridge fills it in at runtime.

Accepted (tolerant) response shape — only `repoPath` is required:

```ts
{ repoPath: string;        // this machine's absolute path to vox-controller
  serverScript?: string;   // defaults to "mcp/vox_speak_server.py"
  configPath?: string;     // optional, for the "open location" hint
  installHint?: string;    // defaults to "uv add mcp"
  error?: string }         // bridge returns 200 + {error} when module absent
```

Both the `.cursor/mcp.json` block and the `claude mcp add` command are **derived
locally** from `repoPath` (single source of truth), so a minimal backend that
returns only `{ repoPath }` renders correctly.

### Guarded degradation (additive, never breaks anything)

The endpoint does **not exist yet** (it's the backend/integration agent's to
build per MEMORY_DESIGN §"New bridge endpoints"). The page never assumes it:

- `404`, non-JSON, `!ok`, `{error}`, or a missing `repoPath` → falls back to the
  committed placeholder `/ABSOLUTE/PATH/TO/vox-controller` and shows a
  "Using placeholder" badge + a clear note to substitute the real path.
- A network failure (bridge down) → React Query `isError` → an `ErrorState` with
  a "Try again" retry that still lets the user copy the placeholder snippets.
- "Open config location" (`POST /api/mcp/reveal`) is best-effort; on any failure
  it just toasts where the config lives. No hard dependency on the endpoint.

The page has **no effect on the voice daemon** — it's a leaf React route.

## Privacy

Committed artifacts (this doc, `mcp/README.md`) only ever use the
`/ABSOLUTE/PATH/TO/vox-controller` placeholder. The real path is computed
locally by the bridge and shown only in the running UI — never written to a
committed file by this page.

## Design / craft

Matches the established premium look: glass cards (`Card glass`), brand-gradient
accent (violet→cyan) hero icon + ambient blur orbs, hairline borders, `FadeIn` /
`Stagger` motion (existing `motion/react` wrappers), `lucide-react` icons,
generous spacing. Copy boxes are dark `pre/code` panels with a per-box header,
language dot (accent = JSON, cyan = bash), and an animated copy→check toggle
wired to the shared toast system. Full loading skeleton + empty/error states.

## How to verify

```bash
cd dashboard
npm run typecheck   # tsc -b --noEmit — clean
npm run build       # tsc -b && vite build — succeeds
npm run dev         # open the dashboard → Integrations in the side nav
```

In the running app (`/integrations`):

- With the bridge **up** and `/api/mcp/config` present → real repo path appears
  in both snippets; "Path resolved" badge.
- With the endpoint **absent** (current state) → placeholder snippets render,
  "Using placeholder" badge, copy buttons all work.
- With the bridge **down** → error card with a working retry.

## TODOs (other agents / later)

- **Backend:** implement `GET /api/mcp/config` (return `{ repoPath, serverScript,
  configPath?, installHint? }` with the real local path) and the optional
  `POST /api/mcp/reveal` (`open -R <repo>/.cursor/`). Both guarded, HTTP 200 +
  `{error}` when the module/file is absent. The page already consumes these.
- Optional: a "test speak" button that hits a bridge endpoint to fire a sample
  `say` so the user can confirm audio before leaving the editor.
