"""FastAPI bridge for the Vox dashboard.

Foundation skeleton (dashboard iteration 1). Serves the REST API under ``/api``,
a WebSocket at ``/api/usage/stream``, and the built frontend (``dashboard/dist``)
as static files at ``/`` with SPA fallback. See ``docs/dashboard/CONTRACT.md``.

Design guarantees:
- **The voice daemon must never break because of the dashboard.** ``create_app``
  is pure; ``start_in_background`` swallows every error and returns a daemon
  Thread so a missing dep / bad port can't take down ``core/loop.py``.
- **The server ALWAYS boots.** Optional modules (personalities, rules, memory,
  axtree) are imported lazily and guarded — if they don't exist yet, their routes
  return safe empty/placeholder data instead of 500ing.

Public API (CONTRACT): ``create_app() -> FastAPI`` ; ``run(host, port)`` ;
``start_in_background(cfg) -> threading.Thread`` ; ``python -m vox.web.server``.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import threading
import time
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ..config import CONFIG
from . import settings_store, usage

# Process start time → uptimeSeconds in /api/status.
_STARTED_AT = time.monotonic()

# Built frontend lives at <repo>/dashboard/dist. This file is
# src/vox/web/server.py → parents[3] is the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_DIST_DIR = _REPO_ROOT / "dashboard" / "dist"

# Vite dev server origin (CONTRACT) — allowed for CORS so the dashboard can talk
# to this bridge while developed with `npm run dev`.
_DEV_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]


def _brain(prefix: str) -> dict:
    """Resolve a brain's {provider, model} via settings_store (Config fallback)."""
    return {
        "provider": settings_store.get(f"{prefix}_provider"),
        "model": settings_store.get(f"{prefix}_model"),
    }


# --- Guarded optional-module accessors -------------------------------------
# Each returns the module or None. Imported lazily so a missing module never
# stops the server booting; routes degrade to safe placeholders.

def _try_import(name: str):
    try:
        module = __import__(f"vox.web.{name}", fromlist=[name])
        return module
    except Exception:
        return None


# --- Small response helpers --------------------------------------------------
# Keep error shapes consistent across the write routes and never let bad input
# (or a half-built feature module) turn into a 500.

def _bad_request(message: str) -> JSONResponse:
    return JSONResponse({"ok": False, "error": message}, status_code=400)


def _not_found(what: str) -> JSONResponse:
    return JSONResponse({"ok": False, "error": f"{what} not found"}, status_code=404)


def _service_unavailable(what: str) -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error": f"{what} module not available"}, status_code=503
    )


async def _json_body(request: Request):
    """Parse a JSON object body. Returns ``(body, None)`` on success, or
    ``({}, JSONResponse)`` with a 400 when the body is missing/not a JSON object."""
    try:
        body = await request.json()
    except Exception:
        return {}, _bad_request("request body must be valid JSON")
    if not isinstance(body, dict):
        return {}, _bad_request("request body must be a JSON object")
    return body, None


def _apply_suggested_voice(mod) -> None:
    """If the now-active persona declares a ``suggestedVoice``, persist it as the TTS
    voice via settings_store so spoken output matches the character. Fully guarded and
    additive: any failure (no active persona, no voice, store error) is a silent no-op."""
    try:
        active = mod.get_active_personality()
        voice = (active or {}).get("suggestedVoice")
        if not voice:
            return
        # Only set tts_voice if the settings schema exposes it (avoids a SettingError
        # for an unknown key). If a future iteration adds the key, this lights up
        # automatically; until then it's a silent no-op.
        if any(s.get("key") == "tts_voice" for s in settings_store.SCHEMA):
            settings_store.set("tts_voice", voice)
    except Exception:
        pass


def create_app() -> FastAPI:
    """Build and return the FastAPI app with all routes mounted."""
    app = FastAPI(title="Vox Control Center", version="0.1.0")

    # Dev-only: seed sample usage data for visual QA (no-op unless VOX_DEV_SEED=1
    # and the ledger is empty). Guarded inside usage; never affects normal runs.
    try:
        seeded = usage.maybe_seed_dev()
        if seeded:
            print(f"[vox.web] VOX_DEV_SEED: seeded {seeded} sample usage events")
    except Exception:
        pass

    # No cookies/auth are used, so credentials stay off — which also keeps the
    # wildcard methods/headers valid per the CORS spec (browsers reject "*" when
    # credentials are allowed). Origins are still restricted to localhost dev ports.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_DEV_ORIGINS,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # --- Status ---
    @app.get("/api/status")
    def get_status() -> dict:
        return {
            "running": True,
            "mode": "idle",
            "smallBrain": _brain("small_brain"),
            "bigBrain": _brain("big_brain"),
            "personality": settings_store.get("personality") or "",
            "uptimeSeconds": round(time.monotonic() - _STARTED_AT, 1),
        }

    # --- Settings ---
    @app.get("/api/settings")
    def get_settings() -> list:
        return settings_store.all()

    @app.post("/api/settings")
    async def post_settings(request: Request):
        body, err = await _json_body(request)
        if err is not None:
            return err
        key = body.get("key")
        value = body.get("value")
        try:
            return settings_store.set(key, value)
        except ValueError as exc:  # SettingError: unknown key / bad enum / wrong type
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)

    # --- Usage ---
    @app.get("/api/usage/recent")
    def get_usage_recent(limit: int = 100) -> list:
        return usage.recent(limit)

    @app.get("/api/usage/summary")
    def get_usage_summary() -> dict:
        return usage.summary()

    @app.websocket("/api/usage/stream")
    async def usage_stream(ws: WebSocket) -> None:
        await ws.accept()
        queue = usage.subscribe()
        # Bind the queue to this event loop so cross-thread publish() can deliver.
        queue._vox_loop = asyncio.get_running_loop()  # type: ignore[attr-defined]
        try:
            while True:
                event = await queue.get()
                await ws.send_json(event)
        except WebSocketDisconnect:
            pass
        except Exception:
            pass
        finally:
            usage.unsubscribe(queue)

    # --- Personalities (guarded) ---
    @app.get("/api/personalities")
    def get_personalities() -> dict:
        mod = _try_import("personalities")
        if mod is None:
            return {"active": None, "presets": [], "custom": []}
        return mod.all()

    @app.post("/api/personalities/active")
    async def set_personality_active(request: Request):
        mod = _try_import("personalities")
        if mod is None:
            return {"ok": False, "error": "personalities module not available"}
        body, err = await _json_body(request)
        if err is not None:
            return err
        try:
            active = mod.set_active(body.get("id"))
        except ValueError as exc:  # unknown id
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
        # Optional, additive: when the active persona suggests a voice, match the TTS
        # voice so the spoken output fits the character. Fully guarded — best effort.
        _apply_suggested_voice(mod)
        return {"ok": True, "active": active}

    @app.post("/api/personalities/custom")
    async def add_personality(request: Request):
        mod = _try_import("personalities")
        if mod is None:
            return {"ok": False, "error": "personalities module not available"}
        body, err = await _json_body(request)
        if err is not None:
            return err
        try:
            return mod.add_custom(
                name=body.get("name"),
                persona=body.get("persona"),
                emoji=body.get("emoji"),
                suggestedVoice=body.get("suggestedVoice"),
            )
        except ValueError as exc:  # missing name/persona
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)

    @app.delete("/api/personalities/custom/{pid}")
    def remove_personality(pid: str) -> dict:
        mod = _try_import("personalities")
        if mod is None:
            return {"ok": False}
        return {"ok": bool(mod.remove_custom(pid))}

    # --- Rules (guarded) ---
    @app.get("/api/rules")
    def get_rules() -> list:
        mod = _try_import("rules")
        if mod is None:
            return []
        try:
            return mod.list_rules()
        except Exception:  # never 500 a list read
            return []

    @app.post("/api/rules")
    async def add_rule(request: Request):
        mod = _try_import("rules")
        if mod is None:
            return []  # rules module not present yet → list stays empty
        body, err = await _json_body(request)
        if err is not None:
            return err
        text = body.get("text")
        if not isinstance(text, str) or not text.strip():
            return _bad_request("'text' is required and must be a non-empty string")
        try:
            return mod.add_rule(text.strip())
        except ValueError as exc:
            return _bad_request(str(exc))
        except Exception as exc:
            return _bad_request(f"could not add rule: {exc}")

    @app.patch("/api/rules/{the_id}")
    async def update_rule(the_id: str, request: Request):
        mod = _try_import("rules")
        if mod is None:
            return _not_found("rule")
        body, err = await _json_body(request)
        if err is not None:
            return err
        # Only forward known, well-typed fields so a bad payload can't crash the
        # store. At least one of text/enabled must be present.
        patch: dict = {}
        if "text" in body:
            text = body.get("text")
            if not isinstance(text, str) or not text.strip():
                return _bad_request("'text' must be a non-empty string")
            patch["text"] = text.strip()
        if "enabled" in body:
            enabled = body.get("enabled")
            if not isinstance(enabled, bool):
                return _bad_request("'enabled' must be a boolean")
            patch["enabled"] = enabled
        if not patch:
            return _bad_request("provide at least one of 'text' or 'enabled'")
        try:
            updated = mod.update_rule(the_id, **patch)
        except ValueError as exc:
            return _bad_request(str(exc))
        except Exception as exc:
            return _bad_request(f"could not update rule: {exc}")
        if not updated:
            return _not_found("rule")
        return updated

    @app.delete("/api/rules/{the_id}")
    def remove_rule(the_id: str):
        mod = _try_import("rules")
        if mod is None:
            return _not_found("rule")
        try:
            removed = bool(mod.remove_rule(the_id))
        except Exception as exc:
            return _bad_request(f"could not remove rule: {exc}")
        if not removed:
            return _not_found("rule")
        return {"ok": True}

    # --- Memory (guarded; src/vox/memory.py) ---
    @app.get("/api/memory")
    def get_memory(query: str = "", limit: int = 20):
        mod = _try_import_memory()
        if mod is None:
            return []
        # Clamp limit to a sane positive bound; a non-positive limit means "all".
        k = limit if isinstance(limit, int) and limit > 0 else None
        try:
            if query and query.strip():
                # recall needs a concrete k; fall back to a generous default.
                return mod.recall(query.strip(), k=k or 50)
            records = mod.all()
            return records[:k] if k else records
        except Exception:  # never 500 a list read
            return []

    @app.post("/api/memory")
    async def add_memory(request: Request):
        mod = _try_import_memory()
        if mod is None:
            return _service_unavailable("memory")
        body, err = await _json_body(request)
        if err is not None:
            return err
        text = body.get("text")
        if not isinstance(text, str) or not text.strip():
            return _bad_request("'text' is required and must be a non-empty string")
        tags = body.get("tags")
        if tags is None:
            tags = []
        if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
            return _bad_request("'tags' must be a list of strings")
        # Optional v2 tier ("core"/"daily"). Only forwarded when the underlying
        # memory module advertises tiered support; otherwise we call the v1 shape
        # so the older JSONL store keeps working unchanged.
        tier = body.get("tier")
        if tier is not None and (not isinstance(tier, str) or not tier.strip()):
            return _bad_request("'tier' must be a string when provided")
        try:
            if _memory_supports_tier(mod):
                # v2 signature is add(text, tier=..., tags=...). Pass tags by
                # keyword so it can't bind to the `tier` positional slot, and
                # only set tier when the caller asked for one (else the module's
                # default applies).
                if tier:
                    return mod.add(text.strip(), tier=tier.strip(), tags=tags)
                return mod.add(text.strip(), tags=tags)
            return mod.add(text.strip(), tags)
        except TypeError:
            # add() doesn't accept the kwargs we passed (older signature) → retry v1.
            try:
                return mod.add(text.strip(), tags)
            except Exception as exc:
                return _bad_request(f"could not add memory: {exc}")
        except Exception as exc:
            return _bad_request(f"could not add memory: {exc}")

    @app.delete("/api/memory/{the_id}")
    def remove_memory(the_id: str):
        # DELETE by id across tiers. v2 memory.remove(id) already searches every
        # tier; the v1 store searches its single ledger. Same call either way.
        mod = _try_import_memory()
        if mod is None:
            return _not_found("memory")
        try:
            removed = bool(mod.remove(the_id))
        except Exception as exc:
            return _bad_request(f"could not remove memory: {exc}")
        if not removed:
            return _not_found("memory")
        return {"ok": True}

    @app.patch("/api/memory/{the_id}")
    async def update_memory(the_id: str, request: Request):
        # Edit an entry's text/tags in place (dashboard inline edit). Guarded:
        # degrades to 404/400 rather than 500. Only available on the v2 store
        # (memory.update); the legacy flat store has no editor.
        mod = _try_import_memory()
        if mod is None or not hasattr(mod, "update"):
            return _not_found("memory")
        body, err = await _json_body(request)
        if err is not None:
            return err
        text = body.get("text")
        if text is not None and not isinstance(text, str):
            return _bad_request("'text' must be a string when provided")
        tags = body.get("tags")
        if tags is not None and (
            not isinstance(tags, list) or not all(isinstance(t, str) for t in tags)
        ):
            return _bad_request("'tags' must be a list of strings when provided")
        try:
            updated = mod.update(the_id, text=text, tags=tags)
        except Exception as exc:
            return _bad_request(f"could not update memory: {exc}")
        if not updated:
            return _not_found("memory")
        return updated

    # --- Memory v2: tiered read + reveal (guarded) -------------------------
    # All routes degrade to safe empty/{error} bodies (HTTP 200) when the
    # tiered memory functions aren't present yet, so a half-migrated store can
    # never 500 the dashboard or block the voice daemon.

    @app.get("/api/memory/core")
    def get_memory_core() -> list:
        # hasattr() is inside the try so even a pathological module whose
        # attribute access raises can never 500 — degrade to [].
        try:
            mod = _try_import_memory()
            if mod is None or not hasattr(mod, "core"):
                return []
            return mod.core() or []
        except Exception:  # never 500 a list read
            return []

    @app.get("/api/memory/daily")
    def get_memory_daily(date: str = "") -> list:
        try:
            mod = _try_import_memory()
            if mod is None or not hasattr(mod, "daily"):
                return []
            # Empty/omitted date → module default (latest/today).
            return mod.daily(date.strip() or None) or []
        except Exception:  # never 500 a list read
            return []

    @app.get("/api/memory/dates")
    def get_memory_dates() -> list:
        try:
            mod = _try_import_memory()
            if mod is None or not hasattr(mod, "dates"):
                return []
            return mod.dates() or []
        except Exception:  # never 500 a list read
            return []

    @app.post("/api/memory/reveal")
    def reveal_memory() -> dict:
        """Reveal data/memory/ in the macOS Finder (open -R <abs path>).

        Best-effort: returns {ok: False, error} rather than 500ing if the path is
        missing or `open` is unavailable (e.g. off-mac). The directory is created
        if absent so there's always something to reveal."""
        target = _memory_dir()
        try:
            target.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            return {"ok": False, "error": f"could not prepare memory dir: {exc}"}
        opener = shutil.which("open")
        if opener is None:
            return {"ok": False, "error": "Finder reveal is only supported on macOS"}
        try:
            subprocess.run(
                [opener, "-R", str(target)],
                check=False,
                timeout=5,
            )
        except Exception as exc:
            return {"ok": False, "error": f"could not reveal location: {exc}"}
        return {"ok": True, "path": str(target)}

    # --- MCP integration config (guarded) ----------------------------------
    @app.get("/api/mcp/config")
    def get_mcp_config() -> dict:
        """vox-speak MCP setup for THIS machine (idea #34).

        Returns the editor config block with the real absolute repo root computed
        from this file's location — never a hardcoded personal path. Shape:
        ``{cursor, claudeAdd, repoRoot}``. Fully guarded: any failure degrades to
        ``{error}`` (HTTP 200)."""
        try:
            return _mcp_config()
        except Exception as exc:
            return {"error": f"could not build MCP config: {exc}"}

    # --- AX tree (guarded) ---
    @app.get("/api/axtree")
    def get_axtree() -> dict:
        mod = _try_import("axtree")
        if mod is None:
            return {"error": "AX tree module not available"}
        try:
            return mod.snapshot()
        except Exception as exc:  # snapshot() shouldn't raise, but never 500
            return {"error": f"accessibility read failed: {exc}"}

    # --- Budget (guarded) ---
    @app.get("/api/budget")
    def get_budget() -> dict:
        mod = _try_import("usage")
        if mod is None or not hasattr(mod, "budget_status"):
            return {"error": "budget module not available"}
        try:
            return mod.budget_status()
        except Exception as exc:  # budget_status() shouldn't raise, but never 500
            return {"error": f"budget read failed: {exc}"}

    # --- Diagnostics (guarded) ---
    @app.get("/api/diagnostics")
    def get_diagnostics() -> dict:
        mod = _try_import("diagnostics")
        if mod is None:
            return {"error": "diagnostics module not available"}
        try:
            return mod.snapshot()
        except Exception as exc:  # snapshot() shouldn't raise, but never 500
            return {"error": f"diagnostics read failed: {exc}"}

    # --- Static dashboard + SPA fallback ---
    _mount_static(app)

    return app


def _try_import_memory():
    """Guarded import of the top-level memory module (src/vox/memory.py)."""
    try:
        from .. import memory

        return memory
    except Exception:
        return None


def _memory_supports_tier(mod) -> bool:
    """True if the memory module's ``add`` accepts a ``tier`` keyword (v2)."""
    try:
        import inspect

        return "tier" in inspect.signature(mod.add).parameters
    except Exception:
        return False


def _memory_dir() -> Path:
    """Absolute path to ``data/memory/`` under the repo root.

    Prefer the memory module's own ``path_for``/``DATA_DIR`` (so a future move
    stays in sync), else fall back to ``<repo>/data/memory``."""
    mod = _try_import_memory()
    if mod is not None:
        try:
            if hasattr(mod, "path_for"):
                # path_for returns a file inside the tier dir; its parent for a
                # dated daily file is the daily/ subdir, so walk to data/memory.
                p = Path(mod.path_for("core")).resolve()
                # core.md lives directly in data/memory/
                return p.parent
        except Exception:
            pass
        for attr in ("MEMORY_DIR", "DATA_DIR"):
            try:
                val = getattr(mod, attr, None)
                if val:
                    return Path(val).resolve()
            except Exception:
                pass
    return (_REPO_ROOT / "data" / "memory").resolve()


def _mcp_config() -> dict:
    """Build the vox-speak MCP config for this machine.

    The real absolute repo root is computed from this file's location
    (``_REPO_ROOT``) — never hardcoded. If a real ``.cursor/mcp.json`` exists on
    disk we surface its ``mcpServers`` block verbatim (with cwd patched to the
    real root); otherwise we generate the canonical vox-speak block (idea #34:
    an MCP server that speaks finished-work announcements through system TTS)."""
    repo_root = str(_REPO_ROOT)

    # Canonical vox-speak server entry. Launched via the project's uv env so it
    # picks up the same deps as the daemon. cwd is the real repo root so the
    # server resolves the package regardless of where the editor invokes it.
    server_entry = {
        "command": "uv",
        "args": ["run", "python", "-m", "vox.mcp.speak"],
        "cwd": repo_root,
    }

    # Prefer a real on-disk .cursor/mcp.json if present, patching cwd to the real
    # path so committed placeholder paths never leak through.
    cursor_path = _REPO_ROOT / ".cursor" / "mcp.json"
    servers = {"vox-speak": server_entry}
    if cursor_path.is_file():
        try:
            data = json.loads(cursor_path.read_text())
            on_disk = data.get("mcpServers")
            if isinstance(on_disk, dict) and on_disk:
                for entry in on_disk.values():
                    if isinstance(entry, dict):
                        entry["cwd"] = repo_root
                servers = on_disk
        except Exception:
            # Malformed file → fall back to the canonical block.
            servers = {"vox-speak": server_entry}

    # `claude mcp add` one-liner for the same server, machine-local path filled in.
    claude_add = (
        "claude mcp add vox-speak "
        f"--cwd {repo_root} "
        "-- uv run python -m vox.mcp.speak"
    )

    return {
        "cursor": servers,
        "claudeAdd": claude_add,
        "repoRoot": repo_root,
    }


def _mount_static(app: FastAPI) -> None:
    """Serve ``dashboard/dist`` at ``/`` with SPA fallback, if it's been built.

    Mounted last so ``/api/*`` routes always win. If the frontend isn't built
    yet, a friendly placeholder is served at ``/`` instead of a 404 wall.
    """
    if _DIST_DIR.is_dir():
        assets = _DIST_DIR / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{full_path:path}")
        def spa(full_path: str):
            # Serve a real file if it exists, else fall back to index.html so the
            # client-side router handles the route.
            candidate = _DIST_DIR / full_path
            if full_path and candidate.is_file():
                return FileResponse(candidate)
            index = _DIST_DIR / "index.html"
            if index.is_file():
                return FileResponse(index)
            return JSONResponse({"error": "dashboard not built"}, status_code=404)
    else:
        @app.get("/")
        def placeholder():
            return JSONResponse(
                {
                    "status": "ok",
                    "message": "Vox bridge running. Build the dashboard "
                    "(dashboard/ → npm run build) to serve the UI here.",
                    "api": "/api/status",
                }
            )


def run(host: str = "127.0.0.1", port: int = 8765) -> None:
    """Run the server in the foreground (blocking). Used by ``__main__``."""
    import uvicorn

    uvicorn.run(create_app(), host=host, port=port, log_level="info")


def start_in_background(cfg=CONFIG) -> threading.Thread | None:
    """Start the server on a daemon thread. Returns the Thread (or None).

    Fully guarded: any failure (import error, bad config, port in use) is
    swallowed so the voice daemon keeps running. Reads host/port from ``cfg`` if
    present, else the documented defaults.
    """
    host = getattr(cfg, "dashboard_host", "127.0.0.1")
    port = getattr(cfg, "dashboard_port", 8765)

    def _serve() -> None:
        try:
            import uvicorn

            uvicorn.run(create_app(), host=host, port=port, log_level="warning")
        except Exception as exc:  # never propagate to the voice loop
            print(f"[vox.web] dashboard server failed to start: {exc}")

    try:
        thread = threading.Thread(target=_serve, name="vox-dashboard", daemon=True)
        thread.start()
        return thread
    except Exception as exc:
        print(f"[vox.web] could not launch dashboard thread: {exc}")
        return None


if __name__ == "__main__":
    host = getattr(CONFIG, "dashboard_host", "127.0.0.1")
    port = getattr(CONFIG, "dashboard_port", 8765)
    print(f"[vox.web] serving on http://{host}:{port}  (API at /api/status)")
    run(host, port)
