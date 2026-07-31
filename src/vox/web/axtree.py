"""Read-only macOS Accessibility (AX) tree snapshot of the focused app.

Foundation skeleton (dashboard iteration 1). Walks the frontmost app's front
window via AppleScript / System Events UI-element traversal — NO interaction,
read-only — and returns it as a nested ``AxNode`` per ``docs/dashboard/CONTRACT.md``.

Design (see ``docs/dashboard/research/axtree.md`` for the full rationale):
- AppleScript over pyobjc: zero new deps (the package already shells ``osascript``;
  pyobjc is not installed), one subprocess round-trip, same failure model as
  ``actions.py``.
- A recursive AppleScript handler emits ONE tab-delimited line per node
  ``depth<TAB>role<TAB>title<TAB>value`` with bounded depth/breadth so we never
  walk a pathological tree. Python rebuilds the nesting from the depth column.
- Off-mac / no-permission / no-window / timeout all degrade to ``{"error": ...}``;
  the voice daemon must keep working even when this fails.

Public API (CONTRACT): ``snapshot() -> dict`` →
``{"app", "capturedAt", "tree": AxNode}`` or ``{"error": str}``.
``AxNode`` = ``{"role", "title?", "value?", "enabled?", "children": [AxNode]}``.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone

# Bounds to keep snapshots small and fast. Deep Electron apps chain single-child
# AXGroups; native apps fan out — so we cap both dimensions. When a cap clips the
# tree we emit a synthetic "… (truncated)" marker node so the UI can show it,
# rather than silently dropping content. Tunable later.
MAX_DEPTH = 12
MAX_BREADTH = 40
VALUE_MAXLEN = 120  # truncate long text values inside AppleScript before transfer
OSA_TIMEOUT = 8  # seconds; a wedged System Events call must never freeze the loop

# Sentinel role used for truncation markers (depth/breadth caps hit). Parsed into
# a child AxNode with this role and a human-readable title.
TRUNC_ROLE = "AXTruncated"

# Recursive bounded traversal. Each property read is wrapped in its own
# ``tell application "System Events"`` so the handlers parse outside the tell
# block (UI-element terms are only defined inside it). Emits one line per node:
# ``depth<TAB>role<TAB>title<TAB>value<TAB>enabled`` (enabled = "1"/"0"/"").
# When a node is clipped by MAX_DEPTH or MAX_BREADTH it emits a TRUNC_ROLE marker
# line one level deeper so the truncation is visible in the rebuilt tree.
_SCRIPT = """
on roleOf(e)
\ttry
\t\ttell application "System Events" to return role of e
\ton error
\t\treturn "?"
\tend try
end roleOf
on titleOf(e)
\ttry
\t\ttell application "System Events" to set t to title of e
\t\tif t is missing value then return ""
\t\treturn t as text
\ton error
\t\treturn ""
\tend try
end titleOf
on valueOf(e)
\ttry
\t\ttell application "System Events" to set v to value of e
\t\tif v is missing value then return ""
\t\tset vs to v as text
\t\tif (length of vs) > %(vmax)d then set vs to (text 1 thru %(vmax)d of vs)
\t\treturn vs
\ton error
\t\treturn ""
\tend try
end valueOf
on enabledOf(e)
\ttry
\t\ttell application "System Events" to set en to enabled of e
\t\tif en is missing value then return ""
\t\tif en then return "1"
\t\treturn "0"
\ton error
\t\treturn ""
\tend try
end enabledOf
on walk(e, depth, acc)
\tset end of acc to (depth as text) & tab & my roleOf(e) & tab & my titleOf(e) & tab & my valueOf(e) & tab & my enabledOf(e)
\tif depth >= %(maxd)d then
\t\tset end of acc to ((depth + 1) as text) & tab & "%(trunc)s" & tab & "… (max depth reached)" & tab & "" & tab & ""
\t\treturn acc
\tend if
\ttry
\t\ttell application "System Events" to set kids to UI elements of e
\ton error
\t\treturn acc
\tend try
\tset total to count of kids
\tset n to total
\tif n > %(maxb)d then set n to %(maxb)d
\trepeat with i from 1 to n
\t\tmy walk(item i of kids, depth + 1, acc)
\tend repeat
\tif total > n then
\t\tset end of acc to ((depth + 1) as text) & tab & "%(trunc)s" & tab & ("… (" & (total - n) & " more children truncated)") & tab & "" & tab & ""
\tend if
\treturn acc
end walk
tell application "System Events"
\tset p to first process whose frontmost is true
\tset appName to name of p
\ttry
\t\tset w to front window of p
\ton error errMsg
\t\treturn "ERROR" & tab & "no front window: " & errMsg
\tend try
end tell
my walk(w, 0, {})
set theLines to result
set AppleScript's text item delimiters to linefeed
return appName & linefeed & (theLines as text)
"""


def _is_mac() -> bool:
    return sys.platform == "darwin"


def _enable_manual_ax() -> None:
    """Best-effort: tell the focused app to expose its full accessibility tree. Electron/Chromium
    apps (Slack, Discord, VS Code/Cursor, Teams…) only build their web-content AX tree once an
    assistive client sets ``AXManualAccessibility`` — without this their windows read as nearly empty.
    Idempotent + guarded; a short settle lets a cold app build the tree before we read it."""
    try:
        subprocess.run(
            ["osascript", "-e",
             'tell application "System Events" to tell (first process whose frontmost is true) '
             'to set value of attribute "AXManualAccessibility" to true'],
            capture_output=True, timeout=4)
        import time
        time.sleep(0.3)
    except Exception:
        pass


def _run_osa(script: str) -> tuple[bool, str]:
    """Shell osascript once. Mirrors ``actions._osa`` failure handling."""
    try:
        r = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=OSA_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return False, "timed out"
    except FileNotFoundError:
        return False, "osascript not found"
    return r.returncode == 0, (r.stdout or r.stderr).strip()


def _parse(lines: list[str]) -> dict:
    """Rebuild nested AxNodes from ``depth<TAB>role<TAB>title<TAB>value<TAB>enabled``.

    A stack indexed by depth: each node attaches to the last-seen node one level
    up. Robust to AppleScript's pre-order emission order. ``enabled`` is "1"/"0"
    (coerced to bool) or "" (omitted — frequently missing on container roles).
    Truncation markers (``TRUNC_ROLE``) become plain title-only leaf nodes.
    """
    root: dict | None = None
    stack: list[dict] = []  # stack[d] is the most recent node at depth d
    for line in lines:
        if not line:
            continue
        parts = line.split("\t")
        depth = int(parts[0])
        role = parts[1] if len(parts) > 1 else "?"
        title = parts[2] if len(parts) > 2 else ""
        value = parts[3] if len(parts) > 3 else ""
        enabled = parts[4] if len(parts) > 4 else ""
        node: dict = {"role": role, "children": []}
        if title:
            node["title"] = title
        if value:
            node["value"] = value
        if enabled in ("0", "1"):
            node["enabled"] = enabled == "1"
        if depth == 0:
            root = node
            stack = [node]
        else:
            if depth <= len(stack):
                stack[depth - 1]["children"].append(node)
            if depth < len(stack):
                stack[depth] = node
            else:
                stack.append(node)
    return root or {"role": "?", "children": []}


def snapshot() -> dict:
    """Read-only snapshot of the focused app's AX tree.

    Returns ``{"app", "capturedAt", "tree": AxNode}`` on success, or
    ``{"error": str}`` off-mac / on any failure. Never raises.
    """
    if not _is_mac():
        return {"error": "AX tree is only available on macOS"}
    _enable_manual_ax()  # so Electron/Chromium apps expose their web content (else the tree is blank)
    script = _SCRIPT % {
        "vmax": VALUE_MAXLEN,
        "maxd": MAX_DEPTH,
        "maxb": MAX_BREADTH,
        "trunc": TRUNC_ROLE,
    }
    ok, out = _run_osa(script)
    if not ok:
        return {"error": f"accessibility read failed: {out or 'unknown error'}"}
    lines = out.split("\n")
    if not lines or lines[0].startswith("ERROR"):
        detail = lines[0].split("\t", 1)[-1] if lines else "empty result"
        return {"error": detail}
    app = lines[0].strip()
    tree = _parse(lines[1:])
    return {
        "app": app,
        "capturedAt": datetime.now(timezone.utc).isoformat(),
        "tree": tree,
    }


# Max characters of flattened tree text handed to the brain. Keeps the vision
# prompt token-light vs an image; a clipped tree ends with a "… (clipped)" marker.
TEXT_MAXLEN = 6000


def _flatten(node: dict, depth: int, out: list[str]) -> None:
    """Append one compact ``  role: title = value`` line per node, indented by depth."""
    role = node.get("role", "?")
    title = node.get("title", "")
    value = node.get("value", "")
    line = "  " * depth + role
    if title:
        line += f": {title}"
    if value:
        line += f" = {value}"
    out.append(line)
    for child in node.get("children", []):
        _flatten(child, depth + 1, out)


def snapshot_text() -> dict:
    """Compact indented-text view of the focused app's AX tree for the brain's vision path.

    Returns ``{"app", "text"}`` on success or ``{"error": str}`` (off-mac / failure /
    empty tree) so the caller can fall back to a screenshot. Never raises. ``text`` is
    capped at ``TEXT_MAXLEN`` chars to stay token-light vs sending an image.
    """
    snap = snapshot()
    if "error" in snap:
        return {"error": snap["error"]}
    tree = snap.get("tree") or {}
    lines: list[str] = []
    _flatten(tree, 0, lines)
    text = "\n".join(lines).strip()
    # A genuinely empty read can rebuild to a lone placeholder root ("?") with no
    # content — treat that as empty too so "auto" mode falls back to a screenshot.
    if not text or text == "?":
        return {"error": "empty AX tree"}
    if len(text) > TEXT_MAXLEN:
        text = text[:TEXT_MAXLEN].rstrip() + "\n… (clipped)"
    return {"app": snap.get("app", ""), "text": text}


if __name__ == "__main__":  # python -m vox.web.axtree — quick manual check
    import json

    print(json.dumps(snapshot(), indent=2)[:4000])
