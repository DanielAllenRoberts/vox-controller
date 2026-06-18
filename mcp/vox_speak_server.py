"""vox-speak — a tiny MCP server that lets an MCP client (Cursor, Claude Code/CLI) speak
aloud through the system text-to-speech.

The point: while you work *with* an assistant in the IDE, it can give you an audible
heads-up — "give me a shout when you're done" → it says "the workflow is finished" out loud
— instead of you having to watch the screen. (Idea #34.)

Run as a stdio MCP server:
    uv run python mcp/vox_speak_server.py

Wire it into your editor — see mcp/README.md. macOS only (uses `say`); on other platforms
the tools degrade to a no-op with a clear message rather than erroring.
"""

import platform
import shutil
import subprocess

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("vox-speak")

_MAX_CHARS = 1000  # keep spoken text sane


def _default_voice() -> str:
    """Reuse Vox's configured TTS voice if the package is importable; else system default."""
    try:
        from vox.config import CONFIG
        return CONFIG.tts_voice or ""
    except Exception:
        return ""


def _say(text: str, voice: str, rate: int) -> str:
    if platform.system() != "Darwin" or not shutil.which("say"):
        return "(text-to-speech unavailable: macOS `say` not found on this system)"
    text = (text or "").strip()
    if not text:
        return "(nothing to speak)"
    cmd = ["say"]
    if voice:
        cmd += ["-v", voice]
    if rate and rate > 0:
        cmd += ["-r", str(rate)]
    cmd.append(text[:_MAX_CHARS])
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
        voice: Optional macOS voice name (e.g. "Daniel", "Samantha"). Defaults to Vox's
               configured voice, else the system default.
        rate: Optional words-per-minute. 0 = the voice's natural rate.
    """
    return _say(text, voice or _default_voice(), rate)


@mcp.tool()
def announce_done(summary: str = "The task is finished.", voice: str = "") -> str:
    """Announce out loud that the current task/workflow has completed.

    A convenience wrapper around `speak` for the common "let me know when you're done" case.

    Args:
        summary: A one-line spoken summary of what finished.
        voice: Optional macOS voice name (defaults to Vox's configured voice).
    """
    return _say(summary, voice or _default_voice(), 0)


if __name__ == "__main__":
    mcp.run()
