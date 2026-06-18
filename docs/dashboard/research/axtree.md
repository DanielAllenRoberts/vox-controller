# Research: Read-only macOS Accessibility (AX) Tree Extractor

> Dashboard iteration 1 (foundation). Scope: design a **read-only** snapshot of
> the focused app's UI as a tree. **No interaction** — we only *read* roles /
> titles / values. Owner module: `src/vox/web/axtree.py`. CONTRACT route:
> `GET /api/axtree` → `{app, capturedAt, tree:AxNode}` or `{error}`.

## Goal & contract

Implement `snapshot() -> dict` returning, per `docs/dashboard/CONTRACT.md`:

```py
{ "app": str, "capturedAt": isoZ, "tree": AxNode }   # success
{ "error": str }                                     # off-mac / failure
```

`AxNode = {role, title?, value?, enabled?, children: [AxNode]}` (camelCase JSON,
optional fields omitted when empty). Must degrade gracefully off-mac, without
Accessibility permission, when there is no front window, or on timeout — the
voice daemon must keep working even if this fails.

## Approaches compared

### A. AppleScript via `osascript` / System Events UI-element traversal — CHOSEN

System Events exposes every app's UI as scriptable `UI element`s with `role`,
`title`, `value`, `enabled`, and nested `UI elements`. We already shell
`osascript` throughout `actions.py` (`_osa`, `running_apps`, `_tab_titles`), so
this fits the codebase with **zero new dependencies**.

A single recursive AppleScript handler walks the frontmost process's front
window and emits **one tab-delimited line per node** — `depth⇥role⇥title⇥value`
— in pre-order. Python rebuilds the nesting from the `depth` column with a
depth-indexed stack. This keeps the AppleScript trivial (no JSON building in
AppleScript, which is painful and slow) and the transfer compact.

Pros:
- **No deps.** Pure `osascript`, matching the existing shell-out pattern and its
  failure model (`subprocess.run(..., timeout=...)`, returncode check).
- One subprocess round-trip per snapshot.
- Same Accessibility permission as the rest of the app's UI scripting — nothing
  new for the user to grant beyond what `actions.py` already needs.
- Works identically whether or not the user has Python pyobjc wheels installed.

Cons / gotchas (all handled in the implementation):
- **Property reads must sit inside `tell application "System Events"`.** A
  top-level handler referencing `UI elements of e` fails to *parse* (`-2741
  Expected end of line but found identifier`) because the UI-element terminology
  is only defined inside the tell block. Fix: each `roleOf/titleOf/valueOf/walk`
  wraps its property access in its own `tell application "System Events"`.
- `value` / `title` are reserved-ish and can be `missing value`; guard every
  read with `try` and coerce to `""`.
- **`entire contents` is a trap** — it manually walks in a repeat loop and is
  notoriously slow on rich trees ([studyraid][sr], [Apple Discussions][ad]). We
  avoid it and instead recurse with explicit **depth + breadth caps**.
- Manual recursion has no built-in depth cap, so an unbounded tree could blow the
  AppleScript stack — hence our `MAX_DEPTH` guard returns early.

### B. pyobjc `AXUIElement` (ApplicationServices / HIServices) — rejected for now

The C Accessibility API (`AXUIElementCreateApplication`,
`AXUIElementCopyAttributeValue` with `kAXChildrenAttribute`, etc.) is the
"proper" interface and is exposed to Python through
`pyobjc-framework-ApplicationServices` ([PyObjC API notes][pyobjc],
[Apple docs][axcopy]).

Pros: richer attribute set (frame, AXRole + AXSubrole, AXEnabled,
AXDescription), no AppleScript-parsing quirks, finer error codes, and it can
read **any** app by PID rather than only the frontmost.

Cons (decisive for iteration 1):
- **Heavy dependency.** `pyobjc-framework-*` wheels are large; the dev Mac mini
  is ~97% full (see project memory) and the CONTRACT favours "no heavy deps —
  the project already shells osascript".
- **Confirmed not installed** here: `import ApplicationServices` →
  `ModuleNotFoundError`. Adding it means a non-trivial `uv add` + space cost for
  a read-only nice-to-have.
- More C-bridge boilerplate (CFType unwrapping, error-tuple returns) for the same
  read-only result we already get from AppleScript.

**Decision:** ship AppleScript now. Keep pyobjc as a documented upgrade path
(below) if/when we need off-frontmost capture, frames, or sub-roles.

## Design of `snapshot()`

```
snapshot()
  └─ if sys.platform != "darwin": return {"error": "...only available on macOS"}
  └─ render _SCRIPT with VALUE_MAXLEN / MAX_DEPTH / MAX_BREADTH
  └─ _run_osa(script)  # subprocess.run(["osascript","-e",...], timeout=OSA_TIMEOUT)
  │     ├─ TimeoutExpired      → (False, "timed out")
  │     ├─ FileNotFoundError   → (False, "osascript not found")
  │     └─ else (returncode==0, stdout/stderr)
  └─ not ok                    → {"error": "accessibility read failed: ..."}
  └─ first line == "ERROR\t.." → {"error": <detail>}   # e.g. no front window
  └─ else: app = line[0]; tree = _parse(line[1:])
            return {"app", "capturedAt": utc isoformat, "tree"}
```

### Bounds (tunable constants in the module)

| Constant       | Value | Why |
|----------------|-------|-----|
| `MAX_DEPTH`    | 12    | Electron apps (Cursor/VS Code) chain single-child `AXGroup`s deeply; 12 reaches real content without runaway recursion. |
| `MAX_BREADTH`  | 20    | Caps siblings per node (lists/toolbars can have hundreds) to keep the payload small. |
| `VALUE_MAXLEN` | 120   | Truncates long text-field values **inside AppleScript** before transfer. |
| `OSA_TIMEOUT`  | 8 s   | A wedged System Events call must never freeze the daemon (mirrors `actions._osa`'s 20 s, tighter for a UI request). |

### Wire format → nesting

AppleScript emits pre-order lines `depth⇥role⇥title⇥value`. `_parse` keeps a
stack where `stack[d]` is the most recent node at depth `d`; each node attaches to
`stack[depth-1]`. Verified with siblings and depth jump-backs (e.g. two buttons
at depth 2, then a sibling back at depth 1 reconstruct correctly).

## Empirical validation (on this Mac, iteration 1)

- Frontmost Electron app (Cursor): bounded walk returns in **~0.5–0.7 s**;
  produces valid nested `AxNode` JSON with titles/values on the right nodes.
- No-front-window case (Finder with no window) → `ERROR\tno front window: …` →
  cleanly mapped to `{"error": ...}`.
- `import ApplicationServices` fails → confirms pyobjc is absent (AppleScript is
  the right call).
- Off-mac path (`sys.platform` patched) → `{"error": "...only available on macOS"}`.

## Permissions

System Events UI scripting requires **Accessibility** permission for the host
process (System Settings → Privacy & Security → Accessibility). This is the same
grant the existing tab/window automation in `actions.py` already needs, so no new
user-facing setup beyond what Vox requires today. If permission is missing,
`osascript` returns a non-zero error which surfaces as `{"error": ...}` — the UI
should show that string and a hint to grant Accessibility.

## TODOs for later iterations

- **Iteration 5 (AX Tree page):** wire `GET /api/axtree` in `server.py` to call
  `axtree.snapshot()`; build the searchable/collapsible tree UI + refresh /
  auto-refresh. Add a node count / "truncated" indicator when bounds clip the tree.
- Add `enabled` to the wire format (currently parsed-ready but the AppleScript
  emits 4 columns; extend to 5 with a guarded `enabled` read — note `enabled` is
  frequently `missing value` on container roles).
- Consider an **`AXSubrole`** column for nicer labels (e.g. AXCloseButton).
- Optional **pyobjc fast-path**: if `ApplicationServices` is importable, use
  `AXUIElement` for richer attributes / off-frontmost capture; fall back to
  AppleScript otherwise. Only worth it if a feature needs it.
- Make bounds query-params on the route (`?depth=&breadth=`) once the page exists.
- Cache the last snapshot briefly to avoid hammering System Events on rapid
  refresh.

## How to verify this part

```bash
# Runs the skeleton against whatever app is frontmost; prints AxNode JSON.
PYTHONPATH=src python3 -m vox.web.axtree

# Off-mac / error paths (no real GUI needed):
PYTHONPATH=src python3 -c "import vox.web.axtree as a; a.sys.platform='linux'; print(a.snapshot())"
```

Expect `{app, capturedAt, tree:{role:'AXWindow', children:[...]}}` on macOS with
an app focused, or `{error:...}` off-mac / without a front window / without
Accessibility permission.

[sr]: https://app.studyraid.com/en/read/12377/399674/system-events-and-ui-scripting
[ad]: https://discussions.apple.com/thread/3975018
[pyobjc]: https://pyobjc.readthedocs.io/en/latest/apinotes/Accessibility.html
[axcopy]: https://developer.apple.com/documentation/applicationservices/1462085-axuielementcopyattributevalue
