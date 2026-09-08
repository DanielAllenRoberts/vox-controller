"""vox-speak — a tiny MCP server that lets an MCP client (Cursor, Claude Code/CLI) speak
aloud through the system text-to-speech.

The point: while you work *with* an assistant in the IDE, it can give you an audible
heads-up — "give me a shout when you're done" → it says "the workflow is finished" out loud
— instead of you having to watch the screen. (Idea #34.)

Run as a stdio MCP server:
    uv run python mcp/vox_speak_server.py

Wire it into your editor — see mcp/README.md. macOS only. It speaks through Vox's own TTS
(`vox.tts`), so it supports both the macOS `say` engine and the new neural Kokoro engine, in a
voice that's INDEPENDENT of the Vox system voice (so you can tell the assistant apart from Vox).
Configure via env: VOX_MCP_VOICE, VOX_MCP_TTS_ENGINE ("say"|"kokoro"|""), VOX_MCP_KOKORO_VOICE.
Falls back to a bare `say` if the vox package isn't importable; off macOS the tools no-op.
"""

import os
import platform
import shutil
import subprocess

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("vox-speak")

_MAX_CHARS = 1000  # keep spoken text sane

# The MCP voice is INDEPENDENT of the system (Vox daemon) voice, so the assistant's heads-up
# sounds different from Vox itself, and can use the new neural Kokoro engine too. It's controlled
# from the dashboard (Settings → MCP voice: mcp_tts_engine / mcp_tts_voice / mcp_kokoro_voice),
# read live from the settings store at speak-time. If the vox package isn't importable here (a
# bare/standalone run), it falls back to these env vars, then these defaults:
#   VOX_MCP_TTS_ENGINE   "say" | "kokoro" | "" (follow the system engine)   default ""
#   VOX_MCP_VOICE        macOS `say` voice name                              default "Samantha"
#   VOX_MCP_KOKORO_VOICE Kokoro voice id (af_heart, af_bella, am_michael, …) default "af_bella"
# Defaults DIFFER from Vox's default voice ("Daniel" / "af_heart") so the two are audibly distinct.
# The `voice` tool arg still overrides the `say` voice per call.
_DEFAULT_SAY_VOICE = "Samantha"     # US English, present on essentially all macOS — ≠ Vox's "Daniel"
_DEFAULT_KOKORO_VOICE = "af_bella"  # ≠ Vox's default Kokoro "af_heart"
# A short chime played BEFORE the MCP speaks, so a spoken heads-up doesn't appear out of nowhere.
# Resolved dashboard setting (mcp_speak_cue) → env (VOX_MCP_CUE) → this default; "" disables it.
_DEFAULT_CUE = "/System/Library/Sounds/Tink.aiff"

# This process's agent name (idea #39, docs/plan/named-agents.md). One MCP server is spawned per
# client, so one process == one agent. Seeded from the env for a CLI that's configured with a name
# up front; otherwise the agent names ITSELF at runtime by calling `register_agent`, which is the
# self-registration model that design settled on — no central config guessing which terminal is who.
_AGENT_NAME = os.environ.get("VOX_AGENT_NAME", "").strip()


def _cue_path():
    """Path to the pre-speech cue sound: dashboard setting → env → default. '' disables it.
    Mirrors _mcp_voice()'s resolution so it's controllable from the same Settings page."""
    try:
        from vox.web import settings_store
        val = settings_store.get("mcp_speak_cue")
        return _DEFAULT_CUE if val is None else val
    except Exception:
        return os.environ.get("VOX_MCP_CUE", _DEFAULT_CUE)


def _play_cue() -> None:
    """Play the short cue chime and wait for it to finish, so it precedes the voice rather than
    overlapping it. Fully guarded — a missing file / non-macOS / no `afplay` just skips silently,
    never blocking the actual speech."""
    path = _cue_path()
    if not path or platform.system() != "Darwin" or not shutil.which("afplay"):
        return
    try:
        subprocess.run(["afplay", path], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=5)
    except Exception:
        pass


def _mcp_voice():
    """Resolve (engine, say_voice, kokoro_voice) for the MCP. Primary source is the dashboard
    settings store (override → Config default), so the Settings page controls the MCP voice; if the
    vox package isn't importable (bare run), fall back to env vars, then the built-in defaults.
    `engine` "" means follow the system tts_engine (the "system" setting maps to "")."""
    try:
        from vox.web import settings_store
        eng = settings_store.get("mcp_tts_engine")
        return (
            "" if eng in (None, "system") else eng,
            settings_store.get("mcp_tts_voice") or _DEFAULT_SAY_VOICE,
            settings_store.get("mcp_kokoro_voice") or _DEFAULT_KOKORO_VOICE,
        )
    except Exception:
        return (
            os.environ.get("VOX_MCP_TTS_ENGINE", ""),
            os.environ.get("VOX_MCP_VOICE", _DEFAULT_SAY_VOICE),
            os.environ.get("VOX_MCP_KOKORO_VOICE", _DEFAULT_KOKORO_VOICE),
        )


def _say(text: str, voice: str, rate: int) -> str:
    text = (text or "").strip()
    if not text:
        return "(nothing to speak)"
    # With several CLIs running, an unattributed voice is worse than no voice — you hear that
    # something finished but not what. A registered name goes in front of the words. Prefix first,
    # THEN truncate, so the cap covers what actually gets spoken.
    if _AGENT_NAME:
        text = f"{_AGENT_NAME} here — {text}"
    text = text[:_MAX_CHARS]
    _play_cue()  # short chime first, so the spoken heads-up doesn't come out of nowhere
    engine, say_voice, kokoro_voice = _mcp_voice()
    # Prefer Vox's own TTS engine (supports the neural Kokoro engine + the independent MCP voice);
    # fall back to a bare `say` if the vox package isn't importable from this process.
    try:
        from vox import tts
        tts.speak_with(
            text,
            engine=engine,
            say_voice=voice or say_voice,
            kokoro_voice=kokoro_voice,
            rate=(rate or None),
            label=_AGENT_NAME or "mcp",   # names this speaker in the shared speech queue
        )
        return f"spoke aloud: {text[:80]!r}"
    except Exception:
        pass  # vox package not importable here → bare `say` fallback below
    if platform.system() != "Darwin" or not shutil.which("say"):
        return "(text-to-speech unavailable: Vox TTS and macOS `say` both unavailable)"
    cmd = ["say"]
    v = voice or say_voice
    if v:
        cmd += ["-v", v]
    if rate and rate > 0:
        cmd += ["-r", str(rate)]
    cmd.append(text)
    try:
        subprocess.run(cmd, check=True, timeout=60)
        return f"spoke aloud: {text[:80]!r}"
    except Exception as exc:  # never crash the MCP client over a failed announcement
        return f"(speak failed: {exc})"


@mcp.tool()
def speak(text: str, voice: str = "", rate: int = 0) -> str:
    """Speak `text` aloud through the system text-to-speech.

    Use this to give the user an audible message — e.g. a heads-up that a long-running
    task or workflow has finished, or a short status update they asked to be told out loud.

    Args:
        text: What to say (kept short; long text is truncated).
        voice: Optional macOS `say` voice name (e.g. "Samantha", "Daniel") to override the MCP's
               own voice for this call. Defaults to the MCP voice (VOX_MCP_VOICE), which is kept
               distinct from Vox's system voice.
        rate: Optional words-per-minute. 0 = the voice's natural rate.
    """
    return _say(text, voice, rate)


@mcp.tool()
def announce_done(summary: str = "The task is finished.", voice: str = "") -> str:
    """Announce out loud that the current task/workflow has completed.

    A convenience wrapper around `speak` for the common "let me know when you're done" case.

    Args:
        summary: A one-line spoken summary of what finished.
        voice: Optional macOS `say` voice name to override the MCP voice for this call
               (defaults to VOX_MCP_VOICE, kept distinct from Vox's system voice).
    """
    return _say(summary, voice, 0)


@mcp.tool()
def notify(text: str, source: str = "", corner: str = "", duration: float = -1) -> str:
    """Show a SILENT pop-up bubble in a corner of the user's screen — a heads-up with no sound.

    The quiet alternative to `speak`. Use this instead of speaking when the user has asked to be
    notified silently, is in a meeting or on a call, or when several things are finishing at once
    and speaking each one would be noise. The bubble is click-through and never steals focus, so it
    can't interrupt what the user is doing; it fades out on its own.

    Args:
        text: The message to show (kept short — it's a glance, not a document; long text is
              truncated).
        source: Who the message is from. Defaults to this agent's registered name, so with several
                CLIs running the card says which one is talking. Rarely worth setting by hand.
        corner: Optional "top-right" | "top-left" | "bottom-right" | "bottom-left" to override the
                configured corner for this one message.
        duration: Seconds on screen. 0 stays until the user clicks the card's ✕; a negative value
                  (the default) uses the user's configured preference.
    """
    try:
        from vox import bubble
    except Exception as exc:  # bare run outside the repo venv — nothing to draw with
        return f"(notify unavailable: {exc})"
    try:
        shown = bubble.show(text, source=source or _AGENT_NAME,
                            corner=corner, duration=duration)
    except Exception as exc:  # never crash the MCP client over a failed notification
        return f"(notify failed: {exc})"
    return f"(shown silently: {shown})"


@mcp.tool()
def register_agent(name: str) -> str:
    """Give THIS agent a name, so the user can tell which one is talking.

    Call this when the user names you ("your name is David"). From then on your spoken heads-up is
    prefixed with the name and your notification bubbles are labelled with it — which is what makes
    several CLIs running at once distinguishable rather than a chorus of anonymous voices.

    Args:
        name: The name to answer to (e.g. "David").
    """
    global _AGENT_NAME
    try:
        from vox import agents
        entry = agents.register(name)
    except Exception as exc:
        return f"(couldn't register: {exc})"
    _AGENT_NAME = entry["name"]
    return f"registered as {entry['name']!r} (pid {entry['pid']})"


@mcp.tool()
def whoami() -> str:
    """The name this agent is registered under, if any. Useful to check before announcing."""
    return _AGENT_NAME or "(this agent has no name yet — call register_agent to take one)"


@mcp.tool()
def list_agents() -> str:
    """List every named agent currently registered, so you can see who else is running."""
    try:
        from vox import agents
        rows = agents.all_agents()
    except Exception as exc:
        return f"(couldn't read the registry: {exc})"
    if not rows:
        return "(no agents registered)"
    return "\n".join(
        f"- {r.get('name')} — pid {r.get('pid')}, registered {r.get('registered_at')}"
        f"{', pane ' + r['tmux_pane'] if r.get('tmux_pane') else ''}"
        for r in rows)


if __name__ == "__main__":
    mcp.run()
