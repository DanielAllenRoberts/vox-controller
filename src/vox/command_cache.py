"""In-memory cache + logging facade over the command DB (``command_store``).

Phase 2 of the command database (``docs/plan/command-db.md`` §6a): the DB is the source of truth,
but it's read into memory and matched there so the idle hot path NEVER queries SQLite. Three load
points and that's all:

  - **boot** — load the global + mode/system ("Tier-0") commands once.
  - **focus change** — load the focused app's commands once, cached by app name (re-focus reuses
    the cache → no DB hit).
  - **edit** (dashboard / learned, later) — ``invalidate()`` the affected slice.

Every DB read is logged to ``vox.log`` ("which query it runs") via ``command_store``'s query logger,
plus a high-level line per boot / focus load — so you can watch the DB come alive as you switch apps.

This module does **not** change voice behavior on its own. ``resolve()`` is provided for the dispatch
wiring + smoke tests, but ``vox.dispatch`` only consults it when ``CONFIG.command_db_enabled`` is on
(default off). Loading + logging are always safe and additive.
"""

from __future__ import annotations

from vox import command_store

_OUT = None                              # ConsoleOutput-like (.emit); None → no logging
_CFG = None
_BASE: list[dict] = []                   # global + mode/system commands (loaded once at boot)
_APP_CACHE: dict[str, list[dict]] = {}   # app name → its commands (loaded lazily on focus change)
_ACTION_INTENTS: set[str] = set()        # intent names with category='action' (the ones dispatch may run)
_CURRENT_APP: str | None = None          # last-focused app, tracked from on_focus (for resolve's context)


def _emit(msg: str) -> None:
    """High-level log line, gated by ``command_db_log`` (the per-query lines are gated in the store)."""
    if _OUT is not None and getattr(_CFG, "command_db_log", True):
        try:
            _OUT.emit(msg)
        except Exception:
            pass


def log(msg: str) -> None:
    """Public log hook so ``vox.dispatch`` can record resolution hits/misses through the same sink."""
    _emit(msg)


def current_app() -> str | None:
    """The app Vox last saw focused (from the focus watcher) — the context resolve() runs against."""
    return _CURRENT_APP


def boot(out, cfg) -> None:
    """Open the store, install query logging, and load the always-on commands into memory. Called
    once at daemon startup. Idempotent + guarded by the caller — a broken store can't stop the daemon."""
    global _OUT, _CFG, _BASE, _APP_CACHE, _ACTION_INTENTS
    _OUT, _CFG = out, cfg
    _APP_CACHE = {}
    command_store.set_query_logger(out.emit if getattr(cfg, "command_db_log", True) else None)
    conn = command_store.build()  # ensure schema + seed (idempotent); returns an open conn
    try:
        _BASE = _commands_for(conn, "global", None)
        _ACTION_INTENTS = {i["name"] for i in command_store.list_intents(conn)
                           if i["category"] == "action"}  # only these may be dispatched (safety floor)
        s = command_store.summary(conn)
    finally:
        conn.close()
    _emit(f"  [cmddb] boot: {command_store.DEFAULT_DB.name} — {s['command']} commands / "
          f"{s['phrase']} phrases / {s['context']} contexts; {len(_BASE)} global+system loaded "
          f"into memory (resolution {'ON' if getattr(cfg, 'command_db_enabled', False) else 'off'})")


def on_focus(app: str) -> None:
    """Focus changed to ``app`` → load its commands into the cache (once per app). Called from the
    focus-watch thread, so it opens its own short-lived connection (no cross-thread sharing)."""
    global _CURRENT_APP
    if app:
        _CURRENT_APP = app  # track focus even on a cache hit, so resolve() always has the right context
    if not app or app in _APP_CACHE:
        return  # already cached → no DB hit (the §6a "reuse the cache" path)
    try:
        conn = command_store.connect()
        try:
            cmds = _commands_for(conn, "app", app)
        finally:
            conn.close()
    except Exception as exc:  # a bad load must never wedge the focus thread
        _emit(f"  [cmddb] focus→{app}: load failed ({exc})")
        return
    _APP_CACHE[app] = cmds
    if cmds:
        _emit(f"  [cmddb] focus→{app}: loaded {len(cmds)} app command(s) into memory "
              f"(+{len(_BASE)} global always apply)")
    else:
        _emit(f"  [cmddb] focus→{app}: no app-specific commands yet (global set still applies)")


def invalidate(app: str | None = None) -> None:
    """Drop cached slices so the next load re-reads the DB (for dashboard / learned-command edits).
    ``None`` clears every app slice (and forces a base reload on next boot)."""
    if app is None:
        _APP_CACHE.clear()
    else:
        _APP_CACHE.pop(app, None)


def refresh() -> None:
    """Reload the always-on base set (global + mode/system) and drop every per-app slice, so a
    dashboard or learned-command edit takes effect WITHOUT a daemon restart (§6a load-point 3).
    Guarded; the next focus change re-loads the touched app's slice on demand. Safe to call even if
    the cache was never booted (the daemon isn't running) — it just reads the DB and returns."""
    global _BASE, _ACTION_INTENTS, _APP_CACHE
    try:
        conn = command_store.connect()
        try:
            _BASE = _commands_for(conn, "global", None)
            _ACTION_INTENTS = {i["name"] for i in command_store.list_intents(conn)
                               if i["category"] == "action"}
        finally:
            conn.close()
        _APP_CACHE = {}
        _emit("  [cmddb] cache refreshed after edit (base reloaded, app slices cleared)")
    except Exception:
        pass  # a failed refresh must never break the edit that triggered it


def resolve(text: str, *, app: str | None = None, domain: str | None = None,
            actions_only: bool = False) -> dict | None:
    """In-memory resolution (no DB): the focused app's commands (higher priority) first, then the
    global + mode/system set. Mirrors ``command_store.resolve``'s exact→contains→regex order. Returns
    a result dict (intent / arg / param / label / context / phrase / match_type) or ``None``.

    ``actions_only`` skips non-``action`` intents (mode/system) — dispatch passes it so the DB can
    only run app/site actions, leaving the control plane to the loop's hardcoded floor (§8a).
    ``domain`` (site context) is accepted for interface parity but not matched yet — site contexts
    aren't seeded and the focus watcher tracks the app, not the tab. That's the next extension.
    """
    t = command_store.normalize(text)
    if not t:
        return None
    pools: list[list[dict]] = []
    if app and app in _APP_CACHE:
        pools.append(_APP_CACHE[app])  # app context outranks global (priority 10 > 0)
    pools.append(_BASE)
    for pool in pools:
        for mt in ("exact", "contains", "regex"):
            for c in pool:
                if actions_only and c["intent"] not in _ACTION_INTENTS:
                    continue  # mode/system stay in the loop's hardcoded handling (safety floor)
                for p in c["phrases"]:
                    if p["match_type"] == mt and command_store._phrase_hit(p["text"], mt, t):
                        hit = {k: c.get(k) for k in ("intent", "arg", "param", "label")}
                        hit.update(command_id=c["id"],
                                   context=f'{c.get("_ctx_kind")}:{c.get("_ctx_value") or "*"}',
                                   phrase=p["text"], match_type=mt)
                        return hit
    return None


def active_phrases(app: str | None = None) -> list[str]:
    """The enabled command phrases for the current focus (focused-app + global), flattened — this is
    the grammar for the Vosk fast lane (idea #53). Regex phrases are skipped (a grammar wants literal
    phrases). App phrases first, then global; deduped case-insensitively."""
    if app is None:
        app = _CURRENT_APP
    out: list[str] = []
    seen: set[str] = set()
    pools: list[list[dict]] = []
    if app and app in _APP_CACHE:
        pools.append(_APP_CACHE[app])
    pools.append(_BASE)
    for pool in pools:
        for c in pool:
            for p in c.get("phrases", []):
                t = (p.get("text") or "").strip()
                if t and p.get("match_type") != "regex" and t.lower() not in seen:
                    seen.add(t.lower())
                    out.append(t)
    return out


# --- internals -----------------------------------------------------------------------------------

def _commands_for(conn, kind: str, match_value: str | None) -> list[dict]:
    """Find the enabled context of this kind/value and return its commands+phrases (or []). Tags
    each command with its context so ``resolve`` can report where the match came from."""
    for c in command_store.list_contexts(conn):
        if not c["enabled"] or c["kind"] != kind:
            continue
        same = (match_value is None and c["match_value"] is None) or (
            match_value is not None and c["match_value"] is not None
            and c["match_value"].lower() == match_value.lower())
        if not same:
            continue
        cmds = command_store.commands_with_phrases(conn, c["id"])
        for cmd in cmds:
            cmd["_ctx_kind"], cmd["_ctx_value"], cmd["_ctx_priority"] = (
                c["kind"], c["match_value"], c["priority"])
        return cmds
    return []
