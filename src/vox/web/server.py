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

    # --- Conversation (live, ephemeral RAM feed; idea #43) ---
    @app.get("/api/conversation/recent")
    def get_conversation_recent(limit: int = 100) -> list:
        mod = _try_import("conversation")
        if mod is None:
            return []
        try:
            return mod.recent(limit)
        except Exception:  # never 500 a list read
            return []

    @app.websocket("/api/conversation/stream")
    async def conversation_stream(ws: WebSocket) -> None:
        await ws.accept()
        mod = _try_import("conversation")
        if mod is None:  # feed module absent → accept then close cleanly
            await ws.close()
            return
        queue = mod.subscribe()
        # Bind the queue to this event loop so cross-thread publish() can deliver.
        queue._vox_loop = asyncio.get_running_loop()  # type: ignore[attr-defined]
        try:
            while True:
                turn = await queue.get()
                await ws.send_json(turn)
        except WebSocketDisconnect:
            pass
        except Exception:
            pass
        finally:
            mod.unsubscribe(queue)

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
                kokoroVoice=body.get("kokoroVoice"),
                tagline=body.get("tagline"),
            )
        except ValueError as exc:  # missing name/persona
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)

    @app.patch("/api/personalities/custom/{pid}")
    async def edit_personality(pid: str, request: Request):
        mod = _try_import("personalities")
        if mod is None:
            return {"ok": False, "error": "personalities module not available"}
        body, err = await _json_body(request)
        if err is not None:
            return err
        try:
            return mod.update_custom(
                pid,
                name=body.get("name"),
                persona=body.get("persona"),
                emoji=body.get("emoji"),
                suggestedVoice=body.get("suggestedVoice"),
                kokoroVoice=body.get("kokoroVoice"),
                tagline=body.get("tagline"),
            )
        except ValueError as exc:  # preset / unknown id / blank required field
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

    # --- Commands (app/site-scoped voice command DB; guarded; src/vox/web/commands.py, idea #36) ---
    @app.get("/api/commands")
    def get_commands() -> dict:
        mod = _try_import("commands")
        if mod is None:
            return {"contexts": [], "intents": [], "summary": {}}
        try:
            return mod.list_all()
        except Exception:  # never 500 a read — degrade to an empty DB view
            return {"contexts": [], "intents": [], "summary": {}}

    @app.patch("/api/commands/contexts/{ctx_id}")
    async def patch_command_context(ctx_id: int, request: Request):
        mod = _try_import("commands")
        if mod is None:
            return _not_found("context")
        body, err = await _json_body(request)
        if err is not None:
            return err
        enabled = body.get("enabled")
        if not isinstance(enabled, bool):
            return _bad_request("'enabled' must be a boolean")
        try:
            return mod.set_context_enabled(ctx_id, enabled)
        except ValueError:
            return _not_found("context")
        except Exception as exc:
            return _bad_request(f"could not update context: {exc}")

    @app.patch("/api/commands/{cmd_id}")
    async def patch_command(cmd_id: int, request: Request):
        mod = _try_import("commands")
        if mod is None:
            return _not_found("command")
        body, err = await _json_body(request)
        if err is not None:
            return err
        enabled = body.get("enabled")
        if not isinstance(enabled, bool):
            return _bad_request("'enabled' must be a boolean")
        try:
            return mod.set_command_enabled(cmd_id, enabled)
        except ValueError:
            return _not_found("command")
        except Exception as exc:
            return _bad_request(f"could not update command: {exc}")

    @app.post("/api/commands/{cmd_id}/phrases")
    async def add_command_phrase(cmd_id: int, request: Request):
        mod = _try_import("commands")
        if mod is None:
            return _not_found("command")
        body, err = await _json_body(request)
        if err is not None:
            return err
        text = body.get("text")
        if not isinstance(text, str) or not text.strip():
            return _bad_request("'text' is required and must be a non-empty string")
        match_type = body.get("matchType", "contains")
        if match_type not in ("exact", "contains", "regex"):
            return _bad_request("'matchType' must be exact, contains, or regex")
        try:
            return mod.add_phrase(cmd_id, text, match_type)
        except ValueError as exc:
            return _bad_request(str(exc))
        except Exception as exc:
            return _bad_request(f"could not add phrase: {exc}")

    @app.delete("/api/commands/phrases/{phrase_id}")
    def remove_command_phrase(phrase_id: int):
        mod = _try_import("commands")
        if mod is None:
            return _not_found("phrase")
        try:
            removed = bool(mod.remove_phrase(phrase_id))
        except Exception as exc:
            return _bad_request(f"could not remove phrase: {exc}")
        if not removed:
            return _not_found("phrase")
        return {"ok": True}

    # --- Reminders / timers / alarms (guarded; src/vox/scheduler.py, idea #16) ---
    @app.get("/api/reminders")
    def get_reminders() -> list:
        mod = _try_import_scheduler()
        if mod is None:
            return []
        try:
            return [_job_to_api(j) for j in mod.list_jobs()]
        except Exception:  # never 500 a list read
            return []

    @app.post("/api/reminders")
    async def add_reminder(request: Request):
        mod = _try_import_scheduler()
        if mod is None:
            return _service_unavailable("scheduler")
        body, err = await _json_body(request)
        if err is not None:
            return err
        kind = body.get("kind")
        if kind not in ("timer", "alarm", "reminder"):
            return _bad_request("'kind' must be one of timer|alarm|reminder")
        fire_at = body.get("fireAt")
        if not isinstance(fire_at, str) or not fire_at.strip():
            return _bad_request("'fireAt' (ISO local datetime) is required")
        recurrence = body.get("recurrence")
        # Accept the fixed words, an interval ("every:<seconds>" or "every 30 minutes"), or
        # null/empty. The scheduler's canon is the single source of truth (None ⇒ unrecognised).
        if recurrence not in (None, "") and mod._canon_recurrence(recurrence) is None:
            return _bad_request("'recurrence' must be null|daily|weekdays|weekly "
                                "or an interval like 'every:1800'")
        try:
            job = mod.create_job(
                kind,
                str(body.get("text") or ""),
                fire_at=fire_at.strip(),
                recurrence=recurrence or None,
            )
        except ValueError as exc:
            return _bad_request(str(exc))
        except Exception as exc:
            return _bad_request(f"could not create reminder: {exc}")
        return _job_to_api(job)

    @app.delete("/api/reminders/{the_id}")
    def remove_reminder(the_id: str):
        mod = _try_import_scheduler()
        if mod is None:
            return _not_found("reminder")
        try:
            removed = bool(mod.cancel_job(the_id))
        except Exception as exc:
            return _bad_request(f"could not cancel reminder: {exc}")
        if not removed:
            return _not_found("reminder")
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

    # --- Handbook (catalog of voice commands & features) ---
    @app.get("/api/handbook")
    def get_handbook() -> list:
        """A structured reference catalog for the dashboard Handbook page.

        Wake/spoken phrases are pulled LIVE from ``vox.config.CONFIG`` so the
        documented vocabulary can never drift from what the daemon listens for.
        Read-only and fully guarded: any failure degrades to a curated static
        catalog (the command/mode/feature groups don't depend on CONFIG) so the
        page always renders something useful."""
        try:
            return _handbook()
        except Exception:
            # CONFIG read failed → still return the static groups (no live phrases).
            try:
                return _handbook_static()
            except Exception:
                return []

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


def _try_import_scheduler():
    """Guarded import of the top-level scheduler module (src/vox/scheduler.py)."""
    try:
        from .. import scheduler

        return scheduler
    except Exception:
        return None


def _job_to_api(job: dict) -> dict:
    """Map a scheduler Job (snake_case on disk) to the dashboard's camelCase shape."""
    return {
        "id": job.get("id"),
        "kind": job.get("kind"),
        "text": job.get("text") or "",
        "fireAt": job.get("fire_at"),
        "recurrence": job.get("recurrence"),
        "createdAt": job.get("created_at"),
        "enabled": bool(job.get("enabled", True)),
    }


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
        "args": ["run", "python", "mcp/vox_speak_server.py"],
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
        "-- uv run python mcp/vox_speak_server.py"
    )

    return {
        "cursor": servers,
        "claudeAdd": claude_add,
        "repoRoot": repo_root,
    }


def _phrase_items(phrases, description: str, prefix: str = "") -> list:
    """Turn a CONFIG phrase tuple into ``[{phrase, description}]`` items.

    ``prefix`` is prepended to each phrase (e.g. the ``"Vox"`` wake word that
    dictation needs from idle). Guarded: a missing/empty tuple yields ``[]``."""
    out = []
    try:
        for p in phrases or ():
            if not isinstance(p, str) or not p.strip():
                continue
            text = f"{prefix} {p}".strip() if prefix else p
            out.append({"phrase": text, "description": description})
    except Exception:
        return []
    return out


def _handbook_live() -> list:
    """WAKE & SPOKEN PHRASES groups, pulled LIVE from ``vox.config.CONFIG``.

    Imported lazily inside the call (see ``_handbook``) so a missing/broken
    config can't stop the server booting. The phrase lists are the daemon's
    real vocabulary, so the docs can never drift."""
    from ..config import CONFIG as cfg

    wake = cfg.assistant_name or "Vox"

    def canon(phrases, fallback):
        """The canonical phrase to show — the first real config entry, else the fallback."""
        try:
            for p in (phrases or ()):
                if isinstance(p, str) and p.strip():
                    return p
        except Exception:
            pass
        return fallback

    def item(phrase, description, variants=()):
        """One handbook item. ``variants`` are curated *legitimate* alternative phrasings
        (NOT the misrecognition spellings like 'hey fox'/'quit box'), surfaced when the
        phrase is clicked in the UI."""
        out = {"phrase": phrase, "description": description}
        vs = [v for v in variants if isinstance(v, str) and v.strip() and v != phrase]
        if vs:
            out["variants"] = vs
        return out

    def dedupe(keywords):
        """Collapse spelling duplicates (e.g. summarise/summarize) for the handbook display."""
        seen, deduped = set(), []
        for k in (keywords or ()):
            if not isinstance(k, str) or not k.strip():
                continue
            norm = k.lower().replace("ise", "ize").replace("our", "or")
            if norm not in seen:
                seen.add(norm)
                deduped.append(k)
        return deduped

    groups = [
        {
            "title": "Wake & Activation",
            "blurb": "Say one of these from idle to switch modes. Click a phrase to see the "
            "other ways you can say it.",
            "items": [
                item(canon(cfg.control_phrases, "take control"),
                     "Enter CONTROL mode — drive apps, tabs, windows and spaces by voice.",
                     ["control mode", "start control"]),
                item(canon(cfg.assistant_phrases, "hey vox"),
                     "Enter ASSISTANT mode — a back-and-forth conversation with the brain."),
                item(canon(cfg.open_dashboard_phrases, "open dashboard"),
                     "Open this dashboard (Vox Control Center) in your browser.",
                     ["open the dashboard", "show dashboard", "launch dashboard"]),
                item(canon(getattr(cfg, "close_dashboard_phrases", ()), "close dashboard"),
                     "Close the dashboard window again.",
                     ["close the dashboard", "hide dashboard"]),
            ],
        },
        {
            "title": "Dictation",
            "blurb": f"Speak-to-type at the cursor. From CONTROL mode just say the phrase; "
            f"from idle, prefix it with “{wake}” (e.g. “{wake} start typing”).",
            "items": [
                item(canon(cfg.dictate_phrases, "start typing"),
                     "Start dictation — types what you say at the cursor.",
                     ["start dictation", "begin typing", "dictate"]),
                item("stop typing",
                     "Stop dictation and go back to idle.",
                     ["stand down", "go to sleep"]),
            ],
        },
        {
            "title": "Sleep, Stop & Quit",
            "blurb": "Stand down to idle, force-stop from any mode, or quit/restart "
            "the whole assistant — all hands-free.",
            "items": [
                item(canon(cfg.sleep_phrases, "stand down"),
                     "Stand down to idle (stop the current mode).",
                     ["go to sleep", "go ahead and sleep"]),
                item("emergency stop",
                     "Emergency stop — drop straight to idle from any mode.",
                     ["terminate task", "abort abort", "stop stop stop"]),
                item(canon(cfg.quit_phrases, "quit vox"),
                     "Quit Vox entirely (ends the program).",
                     ["close vox", "exit vox", "shut down vox"]),
                item(canon(cfg.restart_phrases, "restart vox"),
                     "Restart Vox in place (re-launches to pick up code changes).",
                     ["reboot vox", "vox restart", "restart yourself"]),
            ],
        },
        {
            "title": "Escalation Keywords",
            "blurb": "When escalation mode is “keywords”, an utterance only reaches the brain if "
            "it contains a trigger word — protection against ambient speech. Click to see them all.",
            "items": [
                item("write",
                     "In keyword-escalation mode, only utterances containing one of these trigger "
                     "words reach the brain. Click for the full list.",
                     dedupe(cfg.escalation_keywords)),
            ],
        },
    ]
    # Drop any group that ended up with no items (e.g. an emptied config tuple)
    # so the page never shows a hollow header.
    return [g for g in groups if g["items"]]


def _handbook_static() -> list:
    """Curated CONTROL COMMANDS, MODES and FEATURES groups.

    These don't depend on CONFIG — they describe Vox's deterministic command
    parser, the three modes, and the headline features — so they render even if
    the live config read fails."""
    return [
        {
            "title": "Control Commands",
            "blurb": "Example phrasings the CONTROL-mode parser understands. "
            "Natural variations work too; these are the canonical forms.",
            "items": [
                {
                    "phrase": "open Safari / open Cursor / open Spotify",
                    "description": "Launch (or focus) an app by name.",
                },
                {
                    "phrase": "open GitHub / open YouTube / go to gmail.com",
                    "description": "Open a website as a new tab in your browser.",
                },
                {
                    "phrase": "next tab / previous tab",
                    "description": "Move one tab right or left in the focused browser window.",
                },
                {
                    "phrase": "go to my GitHub tab",
                    "description": "Jump to an already-open tab by what it's about.",
                },
                {
                    "phrase": "next window / previous window",
                    "description": "Cycle between windows of the focused app.",
                },
                {
                    "phrase": "swipe left / swipe right",
                    "description": "Move between macOS Spaces (desktops).",
                },
                {
                    "phrase": "profile 2 / switch to profile 1",
                    "description": "Switch browser profile by number.",
                },
                {
                    "phrase": "go back",
                    "description": "Navigate back in the current app/browser.",
                },
                {
                    "phrase": "close tab",
                    "description": "Close the focused browser tab.",
                },
                {
                    "phrase": "show tabs / hide tabs",
                    "description": "Toggle the browser's tab overview.",
                },
                {
                    "phrase": "search for the weather in London",
                    "description": "Run a web search for whatever follows.",
                },
                {
                    "phrase": "write me an email declining the meeting",
                    "description": "Compose fresh text and type it at the cursor (brain).",
                },
                {
                    "phrase": "make this pretty / rewrite this / fix this",
                    "description": "Rewrite the current selection in place (brain).",
                },
                {
                    "phrase": "what does this say? / read this / what's on my screen",
                    "description": "Screen vision — reads what's on screen (accessibility tree first, "
                    "screenshot fallback).",
                },
                {
                    "phrase": "what app is this? / what am I looking at?",
                    "description": "Instantly speaks the name of the app you're focused on — no brain call.",
                },
                {
                    "phrase": "click Submit / click the Log in button",
                    "description": "Press a button, link, tab or control by its label — found in the "
                    "accessibility tree (works best in native apps & standard UI).",
                },
            ],
        },
        {
            "title": "Timers, Alarms & Reminders",
            "blurb": "Vox owns these — they show on the Scheduler page and you can cancel them by "
            "voice. Reminders are spoken (with your name); timers chime; alarms do both. Spoken "
            "numbers work (“in two minutes”), and the task can come before or after the time.",
            "items": [
                {
                    "phrase": "set a timer for 5 minutes",
                    "description": "A countdown that chimes when it's up (seconds / minutes / hours).",
                },
                {
                    "phrase": "remind me to call Sam in 10 minutes",
                    "description": "A spoken reminder after a delay.",
                },
                {
                    "phrase": "remind me at 5pm to leave / remind me every day at 9 to stretch",
                    "description": "Reminders at a clock time, optionally repeating (daily / weekdays / weekly).",
                },
                {
                    "phrase": "set an alarm for 7am",
                    "description": "An alarm at a clock time — repeats its sound and speaks.",
                },
                {
                    "phrase": "what are my reminders? / what timers do I have?",
                    "description": "Speaks a summary of everything scheduled.",
                },
                {
                    "phrase": "cancel my timer / cancel my reminders",
                    "description": "Cancels matching scheduled items.",
                },
            ],
        },
        {
            "title": "Typing & Special Keys",
            "blurb": "In DICTATION mode everything you say is typed at the cursor "
            "(pasted as a block, so fast speech never drops characters). A few spoken "
            "words act as edit keys instead of being typed:",
            "items": [
                {
                    "phrase": "new line  /  next line  /  new paragraph",
                    "description": "Soft line break (Shift+Return) — moves to a new line WITHOUT "
                    "sending, so it's safe in chat apps.",
                },
                {
                    "phrase": "enter  /  return  /  send  /  submit",
                    "description": "A real Return — sends the message or submits the field.",
                },
                {
                    "phrase": "backspace  /  delete  /  delete that",
                    "description": "Delete the character before the cursor.",
                },
                {
                    "phrase": "delete word  /  delete the last five words",
                    "description": "Delete whole words (⌥⌫) — one, or a count you name (up to 50).",
                },
                {
                    "phrase": "delete line  /  delete paragraph",
                    "description": "Delete back to the start of the line, or the whole paragraph.",
                },
                {
                    "phrase": "undo  /  redo",
                    "description": "Undo (⌘Z) or redo (⌘⇧Z) your last edit — e.g. after an accidental delete.",
                },
                {
                    "phrase": "literally <words>",
                    "description": "Type a phrase verbatim even when it's a command — 'literally delete line' "
                    "types those words instead of deleting.",
                },
                {
                    "phrase": "tab key",
                    "description": "Press Tab — indent, or jump to the next field.",
                },
            ],
        },
        {
            "title": "Modes",
            "blurb": "The entry points share the SAME capabilities (commands, scheduler, "
            "compose/rewrite/vision) — they differ only in how long they stay active and their "
            "default bias.",
            "items": [
                {
                    "phrase": "One-shot — “Vox, …”",
                    "description": "From idle, do a single thing then return to idle — any command, "
                    "reminder, “write me…”, or “what can you see?”. Same powers as control.",
                },
                {
                    "phrase": "Control",
                    "description": "Stays on for continuous, command-first control — app/tab/window/"
                    "space, plus compose/rewrite/vision and the scheduler. Uncertain commands defer "
                    "to the brain.",
                },
                {
                    "phrase": "Assistant",
                    "description": "Stays on, chat-first — conversation with spoken answers. Now also "
                    "writes, rewrites, reads the screen and runs commands/timers mid-chat.",
                },
                {
                    "phrase": "Dictation",
                    "description": "Speak-to-type straight at the cursor. Auto-exits after a "
                    "long pause (configurable) so you can't get stuck.",
                },
            ],
        },
        {
            "title": "Features",
            "blurb": "What's under the hood — tune most of these on the Settings, "
            "Personalities, Rules and Memory pages.",
            "items": [
                {
                    "phrase": "Small & big brains",
                    "description": "A fast/cheap brain handles most turns and defers complex "
                    "ones to a more powerful big brain. Each is a configurable provider + model.",
                },
                {
                    "phrase": "Personalities",
                    "description": "Pick a persona (Posh Butler, Batman, J.A.R.V.I.S. and more) "
                    "or write your own; it shapes Vox's tone and can match a speaking voice.",
                },
                {
                    "phrase": "Rules",
                    "description": "Standing instructions injected into every prompt — your "
                    "always-on preferences and guardrails.",
                },
                {
                    "phrase": "Memory",
                    "description": "Tiered, human-readable memory: durable core facts plus dated "
                    "daily notes, auto-captured and recalled so Vox remembers you.",
                },
                {
                    "phrase": "Budgets",
                    "description": "Track month-to-date token spend against a monthly cap with "
                    "warn/over states.",
                },
                {
                    "phrase": "Themes",
                    "description": "A dark-first premium control-center look, with an optional "
                    "light theme.",
                },
                {
                    "phrase": "Command palette",
                    "description": "Jump anywhere in the dashboard and run actions from a "
                    "keyboard-driven palette.",
                },
            ],
        },
    ]


def _handbook() -> list:
    """Full handbook catalog, assembled + ordered for reading: Modes first (the big picture), the
    Typing & Special Keys items merged into Dictation (same topic), then the rest.

    Each group is ``{title, blurb?, items:[{phrase, description}]}``. The live half is best-effort
    — if CONFIG can't be read we still return the static groups so the page is never empty."""
    try:
        live = _handbook_live()
    except Exception:
        live = []
    by_title = {g["title"]: g for g in (live + _handbook_static())}

    # Merge "Typing & Special Keys" into "Dictation" — they're the same topic.
    typing = by_title.pop("Typing & Special Keys", None)
    if typing and "Dictation" in by_title:
        by_title["Dictation"]["items"] = by_title["Dictation"]["items"] + typing["items"]

    # Reading order — Modes first, then how to drive each; any unlisted group keeps its place after.
    order = ["Modes", "Wake & Activation", "Dictation", "Sleep, Stop & Quit",
             "Control Commands", "Escalation Keywords", "Features"]
    out = [by_title.pop(t) for t in order if t in by_title]
    out += list(by_title.values())
    return out


def _mount_static(app: FastAPI) -> None:
    """Serve ``dashboard/dist`` at ``/`` with SPA fallback, if it's been built.

    Mounted last so ``/api/*`` routes always win. If the frontend isn't built
    yet, a friendly placeholder is served at ``/`` instead of a 404 wall.
    """
    if _DIST_DIR.is_dir():
        assets = _DIST_DIR / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        # index.html must NEVER be browser-cached — it references the content-hashed JS bundle, so a
        # stale index.html keeps loading an old bundle after a rebuild (the "I rebuilt but the
        # dashboard didn't change until a hard-refresh" gremlin). The hashed /assets are immutable
        # and cache freely.
        _NO_CACHE = {"Cache-Control": "no-cache, max-age=0"}

        @app.get("/{full_path:path}")
        def spa(full_path: str):
            # Serve a real file if it exists, else fall back to index.html so the
            # client-side router handles the route.
            candidate = _DIST_DIR / full_path
            if full_path and candidate.is_file():
                if candidate.name == "index.html":
                    return FileResponse(candidate, headers=_NO_CACHE)
                return FileResponse(candidate)
            index = _DIST_DIR / "index.html"
            if index.is_file():
                return FileResponse(index, headers=_NO_CACHE)
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
