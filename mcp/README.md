# vox-speak — speak-from-your-editor MCP

A tiny [MCP](https://modelcontextprotocol.io) server that gives your AI assistant (Cursor,
Claude Code/CLI) a voice: it can call a `speak` tool to talk to you through the system
text-to-speech. So while you work *with* the assistant, you can say "give me a shout when
you're done" and it will literally say it out loud. (Idea #34.)

macOS only. It routes through **Vox's own TTS** (`vox.tts`), so the assistant's heads-up can use
either the zero-install macOS `say` engine **or the new neural Kokoro engine** — and it speaks in
its **own voice, independent of the Vox system voice**, so you can tell who's talking. If the
`vox` package isn't importable from the server's process it falls back to a bare `say`; off macOS
the tools no-op with a clear message.

## Tools

- `speak(text, voice="", rate=0)` — say `text` aloud. `voice` overrides the MCP voice for this
  call; otherwise the MCP voice (`VOX_MCP_VOICE`) is used.
- `announce_done(summary="The task is finished.", voice="")` — convenience for the common
  "tell me when you're done" case.

## Choosing the MCP voice & engine (independent of the system voice)

The MCP voice is deliberately **separate** from Vox's system voice so the two sound different.

**Easiest: the dashboard.** Open the Vox dashboard → **Settings → MCP voice** and set the engine,
the `say` voice, and the Kokoro voice. These are read live from the settings store each time the
MCP speaks — **reload the vox-speak server in your editor** to be sure it picks up a change.

| Setting (dashboard key) | What it does | Default |
|---|---|---|
| MCP say voice (`mcp_tts_voice`) | macOS `say` voice for the MCP | `Samantha` (≠ Vox's `Daniel`) |
| MCP TTS engine (`mcp_tts_engine`) | `Follow system` \| `say` \| `kokoro` | `Follow system` |
| MCP Kokoro voice (`mcp_kokoro_voice`) | Kokoro voice id when the engine is `kokoro` | `af_bella` (≠ Vox's `af_heart`) |

To give the MCP the **new neural voice**, set the engine to **Kokoro** (first use downloads the
model to `~/.cache/vox/kokoro/`, then it's offline).

**Fallback: env vars.** If the `vox` package isn't importable from the MCP server's process (a bare
run), it falls back to `VOX_MCP_VOICE`, `VOX_MCP_TTS_ENGINE` (`say`/`kokoro`/`""`=follow system),
and `VOX_MCP_KOKORO_VOICE` — settable as `env` in the MCP server config below.

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
      "cwd": "/ABSOLUTE/PATH/TO/vox-controller",
      "env": {
        "VOX_MCP_VOICE": "Samantha",
        "VOX_MCP_TTS_ENGINE": "kokoro",
        "VOX_MCP_KOKORO_VOICE": "af_bella"
      }
    }
  }
}
```

(The `env` block is optional — omit it to use the defaults. It's shown here to pick the
neural Kokoro voice for the MCP.) Restart Cursor (or reload MCP servers). Then in chat:
*"When you finish, use vox-speak to tell me out loud."*

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
