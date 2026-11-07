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
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from ..config import CONFIG
from ..paths import DATA_DIR
from . import settings_store, usage

# Process start time → uptimeSeconds in /api/status.
_STARTED_AT = time.monotonic()
# True only when the voice daemon started us (start_in_background). Standalone `python -m
# vox.web.server` has no daemon to restart, so /api/restart refuses there.
_IN_DAEMON = False


def _engine_permissions() -> dict:
    """The engine's OWN view of its privacy permissions. It inherits them from Vox.app, but a
    process keeps the answer it started with, so after a grant (or an ad-hoc rebuild, which
    re-identifies the app) the app and the engine can disagree until the engine restarts."""
    out = {}
    try:
        import ctypes
        lib = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
        lib.AXIsProcessTrusted.restype = ctypes.c_bool
        out["accessibility"] = bool(lib.AXIsProcessTrusted())
    except Exception:
        pass
    try:
        import Quartz
        out["screenRecording"] = bool(Quartz.CGPreflightScreenCaptureAccess())
    except Exception:
        pass
    return out


def _version() -> str:
    try:
        from importlib.metadata import version
        return version("vox")
    except Exception:
        return "dev"

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


def _say_voices() -> list:
    """The installed macOS ``say`` voices (English), parsed from ``say -v '?'`` — order preserved,
    deduped. Empty list off-mac or if ``say`` is missing. Each line is
    ``Name…  <locale>  # sample``; the name may contain spaces (e.g. "Bad News")."""
    exe = shutil.which("say")
    if exe is None:
        return []
    proc = subprocess.run([exe, "-v", "?"], capture_output=True, text=True, timeout=5)
    seen: set[str] = set()
    out: list[str] = []
    for line in proc.stdout.splitlines():
        m = re.match(r"^(.+?)\s{2,}([a-z]{2}(?:[_-][A-Z]{2})?)\b", line)
        if not m or not m.group(2).lower().startswith("en"):
            continue
        name = m.group(1).strip()
        if name and name not in seen:
            seen.add(name)
            out.append(name)
    return out


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

    # A plain-text or form POST is a CORS "simple request": a browser sends it to localhost from
    # ANY web page without asking first, so a malicious page could change settings, teach Vox a
    # command or type into it. Requiring a JSON content type on every state-changing request forces
    # a preflight, which the CORS policy above refuses for foreign origins. (PATCH/PUT/DELETE always
    # preflight, but they're held to the same rule for consistency.)
    @app.middleware("http")
    async def _json_only_writes(request: Request, call_next):
        if (request.method in ("POST", "PUT", "PATCH", "DELETE") and request.url.path.startswith("/api/")
                and "application/json" not in request.headers.get("content-type", "")):
            return JSONResponse({"ok": False, "error": "expected application/json"}, status_code=415)
        return await call_next(request)

    # --- Status ---
    @app.get("/api/status")
    def get_status() -> dict:
        from vox import runtime
        mode, since = runtime.mode() if _IN_DAEMON else ("standalone", time.time())
        return {
            "running": True,
            "mode": mode,
            "modeSince": since,
            "paused": runtime.paused,
            "pid": os.getpid(),
            "version": _version(),
            "permissions": _engine_permissions(),
            "smallBrain": _brain("small_brain"),
            "bigBrain": _brain("big_brain"),
            "personality": settings_store.get("personality") or "",
            "uptimeSeconds": round(time.monotonic() - _STARTED_AT, 1),
        }

    @app.post("/api/restart")
    def post_restart(request: Request) -> dict:
        """Restart the voice daemon — the same path as saying "restart vox". Answers first and
        relaunches half a second later, so the browser gets its response before this process exits.

        Requires a JSON content type: a bodyless POST is a CORS "simple request", so without this any
        web page could fire a hidden form at localhost and restart Vox. A JSON fetch from another
        origin needs a preflight, which the CORS policy refuses."""
        if "application/json" not in request.headers.get("content-type", ""):
            raise HTTPException(status_code=415, detail="expected application/json")
        if not _IN_DAEMON:
            raise HTTPException(status_code=409, detail="dashboard is running standalone — no daemon to restart")
        from ..core import loop
        print("↻ Restarting Vox (dashboard)…")
        threading.Timer(0.5, loop.relaunch).start()
        return {"ok": True}

    # --- Typed input + pause (ideas #68) ---
    @app.post("/api/say")
    async def post_say(request: Request):
        """Feed text to Vox as if it had been spoken: it's heard in whatever mode Vox is in (from
        idle it runs as a one-shot). Replies arrive on the conversation feed, as they do for speech."""
        body, err = await _json_body(request)
        if err is not None:
            return err
        if not _IN_DAEMON:
            raise HTTPException(status_code=409, detail="no daemon running to hear it")
        from vox import runtime
        if not runtime.submit(str(body.get("text", ""))):
            raise HTTPException(status_code=400, detail="empty text, or too many queued")
        return {"ok": True}

    @app.post("/api/ptt")
    async def post_ptt(request: Request):
        """Hold-to-talk: {"held": true} while the talk key is down, {"held": false} on release."""
        body, err = await _json_body(request)
        if err is not None:
            return err
        from vox import runtime
        runtime.set_ptt(bool(body.get("held")))
        return {"ok": True}

    # --- Spotify account link (vox.spotify) ---
    @app.get("/api/spotify")
    def spotify_status() -> dict:
        from vox import spotify
        return spotify.status()

    @app.post("/api/spotify/connect")
    async def spotify_connect(request: Request):
        """The Spotify login URL for the app to open in the browser."""
        _body, err = await _json_body(request)
        if err is not None:
            return err
        from vox import spotify
        try:
            return {"url": spotify.auth_url()}
        except ValueError as exc:
            return _bad_request(str(exc))

    @app.get("/api/spotify/callback")
    def spotify_callback(code: str = "", state: str = "", error: str = ""):
        """Where Spotify sends the browser after login. A plain page the user can close."""
        from fastapi.responses import HTMLResponse
        from vox import spotify
        if error or not code:
            msg = f"Spotify didn't link ({error or 'no code'}). Close this tab and press Connect again."
        else:
            try:
                who = spotify.finish_login(code, state)
                msg = f"Spotify is linked{' as ' + who if who else ''}. You can close this tab."
            except Exception as exc:
                msg = f"Spotify didn't link: {exc}. Close this tab and try again."
        import html
        return HTMLResponse(f"<!doctype html><meta charset=utf-8><title>Vox</title>"
                            f"<body style='font:16px -apple-system;padding:48px'><h2>Vox</h2>"
                            f"<p>{html.escape(msg)}</p></body>")

    @app.post("/api/spotify/disconnect")
    async def spotify_disconnect(request: Request):
        _body, err = await _json_body(request)
        if err is not None:
            return err
        from vox import spotify
        spotify.disconnect()
        return {"ok": True}

    @app.post("/api/stop")
    async def post_stop(request: Request):
        """The ⏹ button: stop whatever Vox is doing now (speech, a brain call, an agent run).
        Listening carries on. Returns what was stopped, e.g. {"stopped": ["speech"]}."""
        _body, err = await _json_body(request)
        if err is not None:
            return err
        from vox import runtime
        stopped = runtime.request_stop()
        print(f"⏹ Stop button{': ' + ', '.join(stopped) if stopped else ' (nothing was running)'}", flush=True)
        return {"ok": True, "stopped": stopped}

    @app.post("/api/listening")
    async def post_listening(request: Request):
        """Pause / resume the mic ({"paused": true}). Typed input keeps working while paused."""
        body, err = await _json_body(request)
        if err is not None:
            return err
        from vox import runtime
        runtime.set_paused(bool(body.get("paused")))
        return {"ok": True, "paused": runtime.paused}

    # --- Setup: API keys + a brain test (used by the app's onboarding) ---
    def _secret_names() -> list[str]:
        return sorted({CONFIG.anthropic_key_env, CONFIG.llm_api_key_env, CONFIG.local_ai_key_env,
                       CONFIG.openai_key_env, "COMPOSIO_API_KEY"})

    @app.get("/api/brain/models")
    async def brain_models(provider: str = "chatgpt") -> dict:
        """Models a provider offers, read live (only ChatGPT for now: OpenAI's list for this key)."""
        if provider != "chatgpt":
            return {"provider": provider, "models": []}
        from .. import assistant
        return {"provider": provider, "models": await asyncio.to_thread(assistant.chatgpt_models)}

    @app.get("/api/secrets")
    def get_secrets() -> dict:
        """Which API keys are set. Never returns the values."""
        return {n: bool(os.environ.get(n)) for n in _secret_names()}

    @app.post("/api/secrets")
    async def post_secret(request: Request):
        """Save one API key to the .env file (owner-only) and apply it now, no restart needed."""
        body, err = await _json_body(request)
        if err is not None:
            return err
        name, value = str(body.get("name", "")), str(body.get("value", "")).strip()
        if name not in _secret_names():
            raise HTTPException(status_code=400, detail=f"unknown key name; expected one of {_secret_names()}")
        from dotenv import set_key, unset_key
        from ..paths import ENV_FILE
        ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
        ENV_FILE.touch(mode=0o600, exist_ok=True)
        if value:
            set_key(str(ENV_FILE), name, value)
            os.environ[name] = value
        else:
            unset_key(str(ENV_FILE), name)
            os.environ.pop(name, None)
        os.chmod(ENV_FILE, 0o600)
        return {"ok": True, "set": bool(value)}

    @app.post("/api/brain/test")
    async def post_brain_test(request: Request):
        """One tiny round-trip to a brain, so setup can prove it works and show how fast it is."""
        body, err = await _json_body(request)
        if err is not None:
            return err
        brain = "big" if body.get("brain") == "big" else "small"
        from .. import assistant

        def call():
            t0 = time.monotonic()
            reply = assistant.complete("Are you there?", brain=brain, kind="test",
                                       system="Reply with exactly the word: ready")
            return reply, (time.monotonic() - t0) * 1000

        reply, ms = await asyncio.to_thread(call)
        failed = (not reply) or reply.startswith("(LLM error") or reply.startswith("I need ")
        return {"ok": not failed, "reply": reply[:300], "ms": round(ms)}

    # --- Agent hooks: "David needs you" (research/agent-messaging.md, feature 1) ---
    @app.post("/api/agents/event")
    async def post_agent_event(request: Request):
        """Receives Claude Code hook events (configure a `type: "http"` hook pointing here). A
        Notification means an agent is blocked on you (a permission prompt, or idle waiting for
        input); Vox says which agent, by the name it registered. This works without trusting the
        model to announce itself."""
        body, err = await _json_body(request)
        if err is not None:
            return err
        event = str(body.get("hook_event_name", ""))
        how = settings_store.get("agent_alerts") or getattr(CONFIG, "agent_alerts", "bubble")
        # Empty 204 replies: Claude Code parses a JSON response body as hook *output*.
        if how == "off" or event not in ("Notification", "Stop"):
            return Response(status_code=204)
        if event == "Stop" and not (settings_store.get("agent_done_alerts") or False):
            return Response(status_code=204)
        from .. import agents
        who = agents.name_for(str(body.get("session_id", "")), str(body.get("cwd", ""))) or "An agent"
        folder = os.path.basename(str(body.get("cwd", "")).rstrip("/"))
        if event == "Stop":
            text = f"{who} is done" + (f" in {folder}." if folder and who == "An agent" else ".")
        else:
            msg = str(body.get("message", "")).strip()
            kind = str(body.get("notification_type", ""))
            if "permission" in (kind + msg).lower():
                # "Claude needs your permission to use Bash" → "David needs your OK to use Bash"
                rest = re.sub(r"^claude needs your permission\s*", "", msg, flags=re.I).strip()
                text = f"{who} needs your OK" + (f" {rest}" if rest else ".")
            else:
                text = f"{who} is waiting for you" + (f" in {folder}." if folder else ".")
        def deliver():
            try:
                if how == "speak":
                    from .. import tts
                    tts.speak(text)
                else:
                    from .. import bubble
                    bubble.show(text, source=who if who != "An agent" else "")
            except Exception:
                pass
        threading.Thread(target=deliver, daemon=True).start()
        print(f"🔔 agent alert: {text}")
        return Response(status_code=204)

    # --- Prompts: every prompt Vox sends, editable by the user (vox/prompts.py) ---
    @app.get("/api/prompts")
    def get_prompts() -> list:
        from .. import prompts
        return prompts.all_prompts()

    @app.get("/api/prompts/recent")
    def get_prompts_recent(prompt: str = "", limit: int = 10) -> list:
        from .. import prompts
        return prompts.recent(prompt or None, max(1, min(limit, 50)))

    @app.put("/api/prompts/{name}")
    async def put_prompt(name: str, request: Request):
        body, err = await _json_body(request)
        if err is not None:
            return err
        from .. import prompts
        try:
            return prompts.put(name, str(body.get("text", "")))
        except KeyError:
            raise HTTPException(status_code=404, detail="no such prompt")
        except ValueError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)

    @app.delete("/api/prompts/{name}")
    def reset_prompt(name: str):
        from .. import prompts
        try:
            return prompts.reset(name)
        except KeyError:
            raise HTTPException(status_code=404, detail="no such prompt")

    # --- Onboarding: voice previews + get to know you (vox/onboarding.py) ---
    @app.post("/api/voices/preview")
    async def post_voice_preview(request: Request):
        body, err = await _json_body(request)
        if err is not None:
            return err
        from .. import onboarding
        onboarding.preview(str(body.get("engine", "kokoro")), str(body.get("voice", "")))
        return {"ok": True}

    @app.get("/api/onboarding/questions")
    async def get_onboarding_questions() -> dict:
        from .. import onboarding
        return await asyncio.to_thread(onboarding.questions)

    @app.post("/api/transcribe")
    async def post_transcribe(request: Request):
        """{"audio": <base64 16-bit WAV>} → {"text": ...}. Used to answer setup questions by voice."""
        body, err = await _json_body(request)
        if err is not None:
            return err
        import base64
        from .. import voice_samples
        try:
            audio = voice_samples._decode_wav(base64.b64decode(str(body.get("audio", "")), validate=True))
            text = await asyncio.to_thread(lambda: voice_samples._get_transcriber().transcribe(audio))
            return {"text": (text or "").strip()}
        except Exception as exc:
            return JSONResponse({"ok": False, "error": f"couldn't read that audio ({type(exc).__name__}: {exc})"},
                                status_code=400)

    @app.post("/api/onboarding/answers")
    async def post_onboarding_answers(request: Request):
        body, err = await _json_body(request)
        if err is not None:
            return err
        from .. import onboarding
        return {"ok": True, "saved": onboarding.save_answers(body.get("answers") or [])}

    # --- Issues logged by voice (vox/issues.py) ---
    @app.get("/api/issues")
    def get_issues() -> list:
        from .. import issues
        return issues.all_issues()

    @app.patch("/api/issues/{iid}")
    async def patch_issue(iid: str, request: Request):
        body, err = await _json_body(request)
        if err is not None:
            return err
        from .. import issues
        try:
            return issues.set_status(iid, str(body.get("status", "open")), body.get("note"))
        except KeyError:
            raise HTTPException(status_code=404, detail="no such issue")
        except ValueError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)

    # --- Insights → Testing: every feature, how to test it, and the user's verdict (vox/features.py) ---
    @app.get("/api/features")
    def get_features() -> list:
        from .. import features
        return features.all_features()

    @app.patch("/api/features/{fid}")
    async def patch_feature(fid: str, request: Request):
        body, err = await _json_body(request)
        if err is not None:
            return err
        from .. import features
        try:
            return features.update(fid, status=body.get("status"), comment=body.get("comment"))
        except KeyError:
            raise HTTPException(status_code=404, detail="no such feature")
        except ValueError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)

    # --- Voice Lab: the user's own recordings for testing (vox/voice_samples.py) ---
    @app.get("/api/samples")
    def get_samples() -> dict:
        from .. import voice_samples
        return {"samples": voice_samples.all_samples(), "prompts": voice_samples.PROMPTS}

    @app.post("/api/samples")
    async def post_sample(request: Request):
        """{"audio": <base64 16-bit PCM WAV>, "prompt": str, "category": str}. Transcribes it,
        names it after what was heard, saves it. Returns the stored entry."""
        body, err = await _json_body(request)
        if err is not None:
            return err
        import base64
        from .. import voice_samples
        try:
            wav = base64.b64decode(str(body.get("audio", "")), validate=True)
            return await asyncio.to_thread(voice_samples.add, wav, str(body.get("prompt", "")),
                                           str(body.get("category", "")))
        except Exception as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)

    @app.get("/api/samples/{sid}/audio")
    def get_sample_audio(sid: str):
        from .. import voice_samples
        path = voice_samples.path_of(sid)
        if path is None or not path.exists():
            raise HTTPException(status_code=404, detail="no such recording")
        return FileResponse(path, media_type="audio/wav")

    @app.delete("/api/samples/{sid}")
    def delete_sample(sid: str) -> dict:
        from .. import voice_samples
        if not voice_samples.remove(sid):
            raise HTTPException(status_code=404, detail="no such recording")
        return {"ok": True}

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

    @app.patch("/api/personalities/{pid}/voice")
    async def set_personality_voice(pid: str, request: Request):
        """Change a persona's voice — works for PRESETS too (saved as an override). Body:
        ``{suggestedVoice?, kokoroVoice?}``. Applies live (the TTS reads the active persona's voice)."""
        mod = _try_import("personalities")
        if mod is None:
            return _service_unavailable("personalities")
        body, err = await _json_body(request)
        if err is not None:
            return err
        if "suggestedVoice" not in body and "kokoroVoice" not in body:
            return _bad_request("provide 'suggestedVoice' and/or 'kokoroVoice'")
        try:
            updated = mod.set_voice(pid, suggestedVoice=body.get("suggestedVoice"),
                                    kokoroVoice=body.get("kokoroVoice"))
        except ValueError as exc:
            return _bad_request(str(exc))
        except Exception as exc:
            return _bad_request(f"could not set voice: {exc}")
        # Keep the say-engine tts_voice setting in sync if we just changed the ACTIVE persona.
        _apply_suggested_voice(mod)
        return updated

    @app.get("/api/voices")
    def get_voices() -> dict:
        """Installed macOS `say` voices (English) for the persona voice picker. Guarded — returns
        ``{voices: []}`` off-mac or on any error."""
        try:
            return {"voices": _say_voices()}
        except Exception:
            return {"voices": []}

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
        app_name = body.get("app")
        try:
            return mod.add_rule(text.strip(), app=app_name if isinstance(app_name, str) else None)
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
        if "app" in body:  # null / "" = everywhere
            a = body.get("app")
            patch["app"] = a if isinstance(a, str) else None
        if not patch:
            return _bad_request("provide at least one of 'text', 'enabled' or 'app'")
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

    # --- Dictionary / speech corrections ("learn a word"; guarded; src/vox/vocab.py, idea #54) ---
    @app.get("/api/vocab")
    def get_vocab() -> list:
        try:
            from .. import vocab
            return vocab.list_entries()
        except Exception:  # never 500 a read
            return []

    @app.post("/api/vocab")
    async def add_vocab(request: Request):
        try:
            from .. import vocab
        except Exception:
            return _service_unavailable("vocab")
        body, err = await _json_body(request)
        if err is not None:
            return err
        heard = body.get("heard")
        if not isinstance(heard, str) or not heard.strip():
            return _bad_request("'heard' is required and must be a non-empty string")
        write = body.get("write")
        if write is not None and not isinstance(write, str):
            return _bad_request("'write' must be a string")
        try:
            return vocab.add(heard, write or "")
        except ValueError as exc:
            return _bad_request(str(exc))
        except Exception as exc:
            return _bad_request(f"could not add correction: {exc}")

    @app.patch("/api/vocab/{entry_id}")
    async def patch_vocab(entry_id: str, request: Request):
        try:
            from .. import vocab
        except Exception:
            return _not_found("correction")
        body, err = await _json_body(request)
        if err is not None:
            return err
        patch: dict = {k: body.get(k) for k in ("heard", "write", "enabled") if k in body}
        if not patch:
            return _bad_request("provide at least one of 'heard', 'write', or 'enabled'")
        if "enabled" in patch and not isinstance(patch["enabled"], bool):
            return _bad_request("'enabled' must be a boolean")
        try:
            updated = vocab.update(entry_id, **patch)
        except ValueError as exc:
            return _bad_request(str(exc))
        except Exception as exc:
            return _bad_request(f"could not update correction: {exc}")
        if updated is None:
            return _not_found("correction")
        return updated

    @app.delete("/api/vocab/{entry_id}")
    def delete_vocab(entry_id: str):
        try:
            from .. import vocab
            removed = bool(vocab.remove(entry_id))
        except Exception as exc:
            return _bad_request(f"could not delete correction: {exc}")
        if not removed:
            return _not_found("correction")
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

    @app.get("/api/commands/learning")
    def get_learning() -> dict:
        """What Vox has taught itself, and what it's still considering (idea #24)."""
        mod = _try_import("commands")
        if mod is None:
            return {"mode": "unknown", "learned": [], "candidates": []}
        try:
            return mod.learning()
        except Exception:
            return {"mode": "unknown", "learned": [], "candidates": []}

    @app.post("/api/commands/candidates/{cand_id}/promote")
    def post_promote_candidate(cand_id: int):
        mod = _try_import("commands")
        if mod is None:
            raise HTTPException(status_code=503, detail="command DB unavailable")
        row = mod.promote_candidate(cand_id)
        if row is None:
            raise HTTPException(status_code=404, detail="candidate not found or already promoted")
        return row

    @app.post("/api/commands/candidates/{cand_id}/reject")
    def post_reject_candidate(cand_id: int) -> dict:
        """Say "never learn this" from the dashboard — blocks the candidate so it stops
        accumulating and can't promote itself later."""
        mod = _try_import("commands")
        if mod is None:
            raise HTTPException(status_code=503, detail="command DB unavailable")
        if not mod.reject_candidate(cand_id):
            raise HTTPException(status_code=404, detail="candidate not found")
        return {"ok": True}

    @app.delete("/api/commands/learned/{cmd_id}")
    def delete_learned(cmd_id: int) -> dict:
        mod = _try_import("commands")
        if mod is None:
            raise HTTPException(status_code=503, detail="command DB unavailable")
        if not mod.forget_learned(cmd_id):
            raise HTTPException(status_code=400, detail="not a learned command")
        return {"ok": True}

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

    # --- Workspace board (Trello-like kanban + agent knowledge base; guarded; board_store, idea #51) ---
    @app.get("/api/board")
    def get_board(archived: bool = False) -> dict:
        mod = _try_import("board")
        if mod is None:
            return {"id": None, "name": None, "lists": []}
        try:
            return mod.snapshot(archived=archived)
        except Exception:  # never 500 a read — degrade to an empty board
            return {"id": None, "name": None, "lists": []}

    @app.get("/api/board/search")
    def search_board(query: str = "", limit: int = 50) -> list:
        mod = _try_import("board")
        if mod is None or not query.strip():
            return []
        try:
            return mod.search(query.strip(), limit)
        except Exception:
            return []

    @app.post("/api/board/cards")
    async def create_board_card(request: Request):
        mod = _try_import("board")
        if mod is None:
            return _service_unavailable("board")
        body, err = await _json_body(request)
        if err is not None:
            return err
        title = body.get("title")
        if not isinstance(title, str) or not title.strip():
            return _bad_request("'title' is required and must be a non-empty string")
        list_name = body.get("list")
        if not isinstance(list_name, str) or not list_name.strip():
            return _bad_request("'list' (column name) is required")
        try:
            card = mod.create_card(list_name, title, body.get("body") or "", body.get("tags") or "")
            if body.get("due"):
                card = mod.update_card(card["id"], due=body["due"])
            return card
        except ValueError as exc:
            return _bad_request(str(exc))
        except Exception as exc:
            return _bad_request(f"could not add card: {exc}")

    @app.patch("/api/board/cards/{card_id}")
    async def update_board_card(card_id: int, request: Request):
        mod = _try_import("board")
        if mod is None:
            return _not_found("card")
        body, err = await _json_body(request)
        if err is not None:
            return err
        # Only forward provided fields; at least one must be present.
        patch: dict = {}
        for key in ("title", "body", "tags", "due", "checklist", "archived"):
            if key in body:
                patch[key] = body.get(key)
        if "due" in patch and patch["due"] is None:
            patch["due"] = ""  # null clears the deadline
        if not patch:
            return _bad_request("provide at least one of 'title', 'body', 'tags', 'due', 'checklist' or 'archived'")
        if "checklist" in patch and not isinstance(patch["checklist"], list):
            return _bad_request("'checklist' must be a list")
        if "title" in patch and (not isinstance(patch["title"], str) or not patch["title"].strip()):
            return _bad_request("'title' must be a non-empty string")
        try:
            updated = mod.update_card(card_id, **patch)
        except ValueError as exc:
            return _bad_request(str(exc))
        except Exception as exc:
            return _bad_request(f"could not update card: {exc}")
        if updated is None:
            return _not_found("card")
        return updated

    @app.post("/api/board/cards/{card_id}/move")
    async def move_board_card(card_id: int, request: Request):
        mod = _try_import("board")
        if mod is None:
            return _not_found("card")
        body, err = await _json_body(request)
        if err is not None:
            return err
        to_list = body.get("toList")
        if to_list is None or (isinstance(to_list, str) and not to_list.strip()):
            return _bad_request("'toList' (target column name or id) is required")
        position = body.get("position")
        if position is not None and not isinstance(position, int):
            return _bad_request("'position' must be an integer when provided")
        try:
            moved = mod.move_card(card_id, to_list, position)
        except Exception as exc:
            return _bad_request(f"could not move card: {exc}")
        if moved is None:
            return _not_found("card or target list")
        return moved

    @app.delete("/api/board/cards/{card_id}")
    def delete_board_card(card_id: int):
        mod = _try_import("board")
        if mod is None:
            return _not_found("card")
        try:
            removed = bool(mod.delete_card(card_id))
        except Exception as exc:
            return _bad_request(f"could not delete card: {exc}")
        if not removed:
            return _not_found("card")
        return {"ok": True}

    @app.post("/api/board/bulk")
    async def bulk_board(request: Request):
        """{"ops": [{"op": "add"|"move"|"delete"|"archive"|"update", …}]} → per-op results."""
        mod = _try_import("board")
        if mod is None:
            return _service_unavailable("board")
        body, err = await _json_body(request)
        if err is not None:
            return err
        ops = body.get("ops")
        if not isinstance(ops, list) or not ops:
            return _bad_request("'ops' must be a non-empty list")
        return {"results": mod.bulk(ops[:200])}

    @app.get("/api/board/due")
    def board_due(days: int = 7) -> list:
        mod = _try_import("board")
        if mod is None:
            return []
        try:
            return mod.due(max(0, min(days, 366)))
        except Exception:
            return []

    @app.post("/api/board/lists")
    async def create_board_list(request: Request):
        mod = _try_import("board")
        if mod is None:
            return _service_unavailable("board")
        body, err = await _json_body(request)
        if err is not None:
            return err
        name = body.get("name")
        if not isinstance(name, str) or not name.strip():
            return _bad_request("'name' is required and must be a non-empty string")
        try:
            return mod.create_list(name)
        except ValueError as exc:
            return _bad_request(str(exc))
        except Exception as exc:
            return _bad_request(f"could not add list: {exc}")

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
        if kind not in ("timer", "alarm", "reminder", "routine"):
            return _bad_request("'kind' must be one of timer|alarm|reminder|routine")
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

    @app.post("/api/reminders/{the_id}/run")
    async def run_routine(the_id: str, request: Request):
        """Run a routine now (the Reminders page's Run Now). It speaks as if it had fired."""
        _body, err = await _json_body(request)
        if err is not None:
            return err
        mod = _try_import_scheduler()
        job = next((j for j in (mod.list_jobs() if mod else []) if j.get("id") == the_id), None)
        if job is None:
            return _not_found("routine")
        from vox import routines
        routines.run_in_background(job)
        return {"ok": True}

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
    @app.get("/api/guide")
    def get_guide() -> list:
        """Every feature, what it does and how to use it (Vox.app → Guide)."""
        from vox import guide
        return guide.guide()

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
    return (DATA_DIR / "memory").resolve()


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
                {
                    "phrase": "show clickable  →  “click 14”",
                    "description": "Overlays a number on every clickable element on screen; say the "
                    "number to press it (“click 14”, or just “14”). Also triggers "
                    "on “click link” / “click button”. Say anything else to dismiss. "
                    "Best in control mode, which stays listening for the number.",
                },
            ],
        },
        {
            "title": "Commands Vox Learns",
            "blurb": "When Vox has to work something out with the brain, it remembers the wiring — "
            "after a few uses the same request runs instantly and for free, with no AI call. It "
            "saves these on its own; these phrases let you take over. Everything it has learned is "
            "reviewable, and nothing it learns can override a built-in command.",
            "items": [
                {
                    "phrase": "remember that",
                    "description": "Save what Vox just did as a command right now, without waiting "
                    "for it to happen a few times. The best way to teach it something "
                    "you use often but not in bursts.",
                    "variants": ["save that as a command", "learn that", "keep that"],
                },
                {
                    "phrase": "forget that",
                    "description": "Delete the command behind what just ran, and stop it being "
                    "re-learned for a month. Only ever removes something Vox taught "
                    "itself — built-in commands can't be unlearned.",
                    "variants": ["unlearn that", "delete that command"],
                },
                {
                    "phrase": "no  /  that's wrong",
                    "description": "Said straight after Vox acts, this retires the learned command "
                    "that misfired — one correction is enough. It also stops that "
                    "wrong mapping counting towards anything it's still considering.",
                    "variants": ["not that", "wrong", "undo"],
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
    global _IN_DAEMON
    _IN_DAEMON = True
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
