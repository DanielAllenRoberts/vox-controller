# AX Tree reader (`src/vox/web/axtree.py`)

Read-only snapshot of the **frontmost macOS app's** accessibility (AX) tree, for
the dashboard's AX Tree page. Iteration 5 builds on the iteration-1 skeleton (see
[`research/axtree.md`](./research/axtree.md) for the full design rationale and the
AppleScript-vs-pyobjc tradeoff). **Never interacts** — only reads
role / title / value / enabled. The voice daemon must keep working even if this
fails, so every failure degrades to `{"error": str}` rather than raising.

## Public API (CONTRACT)

```py
snapshot() -> dict
# success:  {"app": str, "capturedAt": isoZ, "tree": AxNode}
# failure:  {"error": str}
```

`AxNode = {"role", "title"?, "value"?, "enabled"?, "children": [AxNode]}` —
camelCase JSON; optional fields omitted when empty. `server.py`'s
`GET /api/axtree` returns `snapshot()` verbatim.

## How it works

1. `sys.platform != "darwin"` → immediate `{"error": "...only available on macOS"}`.
2. A single recursive AppleScript handler (`_SCRIPT`) walks the frontmost
   process's **front window** via System Events UI-element traversal and emits
   **one tab-delimited line per node** in pre-order:
   `depth<TAB>role<TAB>title<TAB>value<TAB>enabled`.
   - Each property read (`roleOf`/`titleOf`/`valueOf`/`enabledOf`) wraps its
     access in its own `tell application "System Events"` so the handlers parse
     outside the tell block (UI-element terminology is only defined inside it).
   - All reads are `try`-guarded; `missing value` coerces to `""`.
3. `_run_osa` shells `osascript -e` once (`subprocess.run`, `timeout=OSA_TIMEOUT`),
   mirroring `actions._osa`. Timeout / missing binary / non-zero return all map to
   `{"error": ...}`.
4. The first output line that starts with `ERROR\t` (e.g. no front window) maps to
   `{"error": <detail>}`.
5. `_parse` rebuilds the nesting from the `depth` column using a depth-indexed
   stack; `capturedAt` is `datetime.now(timezone.utc).isoformat()`.

## Bounds & truncation markers (iteration 5)

The traversal is hard-bounded so a pathological tree can never explode the
payload or the AppleScript stack. **When a cap clips the tree we emit a synthetic
marker node** (`role: "AXTruncated"`, with a human-readable `title`) so the UI can
show that content was hidden instead of silently dropping it.

| Constant       | Value | Why |
|----------------|-------|-----|
| `MAX_DEPTH`    | 12    | Reaches real content in deep single-child Electron `AXGroup` chains without runaway recursion. A node at the cap gets a `"… (max depth reached)"` marker child. |
| `MAX_BREADTH`  | 40    | Caps siblings per node (toolbars/lists can have hundreds). Extra siblings are replaced by a `"… (N more children truncated)"` marker. |
| `VALUE_MAXLEN` | 120   | Truncates long text-field values **inside AppleScript** before transfer. |
| `OSA_TIMEOUT`  | 8 s   | A wedged System Events call must never freeze the daemon (tighter than `actions._osa`'s 20 s). |
| `TRUNC_ROLE`   | `"AXTruncated"` | Sentinel role for the marker leaf nodes above. |

`enabled` is emitted as `"1"`/`"0"`/`""` and parsed to a real `bool`, omitted when
blank (it is frequently `missing value` on container roles).

## Wire format → nesting

`_parse` keeps `stack[d]` = the most recent node at depth `d`; each node attaches
to `stack[depth-1]`. Robust to sibling runs and depth jump-backs. Marker lines are
ordinary lines with role `AXTruncated` and a title, so they nest like any node.

## Permissions

System Events UI scripting needs **Accessibility** permission for the host process
(System Settings → Privacy & Security → Accessibility) — the *same* grant the
existing `actions.py` automation already requires, so nothing new for the user.
If it's missing, `osascript` returns non-zero and the UI shows the `{"error": ...}`
string (hint: grant Accessibility).

## Verify

```bash
# Live snapshot of whatever app is frontmost; prints AxNode JSON.
PYTHONPATH=src python3 -m vox.web.axtree

# Off-mac / error path (no GUI needed):
PYTHONPATH=src python3 -c "import vox.web.axtree as a; a.sys.platform='linux'; print(a.snapshot())"
```

On this Mac with Cursor frontmost: returns in ~1 s with `app`, `capturedAt`, and a
nested `tree` whose nodes carry `enabled`. Electron apps render most content inside
a web view, so the native AX tree above it is sparse — expected. Off-mac yields
`{"error": "AX tree is only available on macOS"}`.

## TODOs (later iterations)

- Make bounds query-params on the route (`?depth=&breadth=`) once the page needs it.
- Optional `AXSubrole` column for nicer labels (e.g. `AXCloseButton`).
- Optional pyobjc fast-path for off-frontmost capture / frames if a feature needs it.
- Brief last-snapshot cache to avoid hammering System Events on rapid refresh.
