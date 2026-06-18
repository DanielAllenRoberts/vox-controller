# vox-speak — speak-from-your-editor MCP

A tiny [MCP](https://modelcontextprotocol.io) server that gives your AI assistant (Cursor,
Claude Code/CLI) a voice: it can call a `speak` tool to talk to you through the system
text-to-speech. So while you work *with* the assistant, you can say "give me a shout when
you're done" and it will literally say it out loud. (Idea #34.)

macOS only (uses `say`). On other platforms the tools no-op with a clear message.

## Tools

- `speak(text, voice="", rate=0)` — say `text` aloud. `voice` defaults to Vox's configured
  voice (`config.tts_voice`), else the system default.
- `announce_done(summary="The task is finished.", voice="")` — convenience for the common
  "tell me when you're done" case.

## Install the dependency

```bash
uv add mcp        # or: uv pip install mcp
```

## Wire it into Cursor

Add to `.cursor/mcp.json` (project-level) or your global Cursor MCP settings:

```json
{
  "mcpServers": {
    "vox-speak": {
      "command": "uv",
      "args": ["run", "python", "mcp/vox_speak_server.py"],
      "cwd": "/Users/danielroberts/Repos/Personal/vox-controller"
    }
  }
}
```

Restart Cursor (or reload MCP servers). Then in chat: *"When you finish, use vox-speak to
tell me out loud."*

## Wire it into Claude Code / CLI

From the repo root:

```bash
claude mcp add vox-speak -- uv run python mcp/vox_speak_server.py
```

or add the same `mcpServers` block to a project `.mcp.json`.

## Test it directly

```bash
# the underlying command:
say -v Daniel "Vox speak is online"

# or run the server and let your editor's MCP client call it.
uv run python mcp/vox_speak_server.py   # stdio server; Ctrl-C to stop
```
