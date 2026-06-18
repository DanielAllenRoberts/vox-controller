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

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_DEV_ORIGINS,
        allow_credentials=True,
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
    async def post_settings(request: Request) -> dict:
        body = await request.json()
        key = body.get("key")
        value = body.get("value")
        return settings_store.set(key, value)

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
    async def set_personality_active(request: Request) -> dict:
        mod = _try_import("personalities")
        if mod is None:
            return {"ok": False}
        body = await request.json()
        return {"ok": True, "active": mod.set_active(body.get("id"))}

    @app.post("/api/personalities/custom")
    async def add_personality(request: Request) -> dict:
        mod = _try_import("personalities")
        if mod is None:
            return {"ok": False}
        body = await request.json()
        return mod.add_custom(
            name=body.get("name"),
            persona=body.get("persona"),
            emoji=body.get("emoji"),
            suggestedVoice=body.get("suggestedVoice"),
        )

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
        return mod.list_rules() if mod else []

    @app.post("/api/rules")
    async def add_rule(request: Request) -> dict:
        mod = _try_import("rules")
        if mod is None:
            return {"ok": False}
        body = await request.json()
        return mod.add_rule(body.get("text", ""))

    @app.patch("/api/rules/{rid}")
    async def update_rule(rid: str, request: Request) -> dict:
        mod = _try_import("rules")
        if mod is None:
            return {"ok": False}
        body = await request.json()
        return mod.update_rule(rid, **body)

    @app.delete("/api/rules/{rid}")
    def remove_rule(rid: str) -> dict:
        mod = _try_import("rules")
        if mod is None:
            return {"ok": False}
        return {"ok": bool(mod.remove_rule(rid))}

    # --- Memory (guarded; src/vox/memory.py) ---
    @app.get("/api/memory")
    def get_memory(query: str = "", limit: int = 20) -> list:
        mod = _try_import_memory()
        if mod is None:
            return []
        if query and query.strip():
            return mod.recall(query, k=limit)
        return mod.all()[: limit if limit and limit > 0 else None]

    @app.post("/api/memory")
    async def add_memory(request: Request) -> dict:
        mod = _try_import_memory()
        if mod is None:
            return {"ok": False}
        body = await request.json()
        return mod.add(body.get("text", ""), body.get("tags") or [])

    @app.delete("/api/memory/{mid}")
    def remove_memory(mid: str) -> dict:
        mod = _try_import_memory()
        if mod is None:
            return {"ok": False}
        return {"ok": bool(mod.remove(mid))}

    # --- AX tree (guarded) ---
    @app.get("/api/axtree")
    def get_axtree() -> dict:
        mod = _try_import("axtree")
        if mod is None:
            return {"error": "AX tree module not available"}
        return mod.snapshot()

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
