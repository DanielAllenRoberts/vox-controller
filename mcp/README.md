# Vox MCP servers

Two [MCP](https://modelcontextprotocol.io) servers live here. Both are local stdio servers that call
the `vox` package directly (the same code the voice daemon runs), so they work whether or not the
daemon is up. macOS only.

| Server | File | What it gives the assistant |
|---|---|---|
| **vox-control** | `mcp/vox_control_server.py` | **Hands on the Mac** — everything Vox's own brain can do, plus all of vox-speak |
| **vox-speak** | `mcp/vox_speak_server.py` | Just a voice and a notification bubble — safe to hand to anything |

Wire in **vox-control** when you want the assistant to *use* the Mac; **vox-speak** when you only
want it to *tell you things*.

---

# vox-control — remote hands MCP

Gives an MCP client (Claude Code, Cursor, the Claude desktop app) the **same controls Vox's LLM has**
— see the screen, click, type, run Vox commands, drive the agent tier, and use the organisers — as
typed tools. The use it was built for: a Claude Code session on this Mac, reached through **Claude
Dispatch / Remote Control** from your phone, so Claude can do something on the machine while you're
away.

## Tools

**Seeing** (all read-only)

- `screen_state()` — focused app, active tab + open tabs (when the browser is focused), running
  apps, local time, and the last few actions Vox ran. Cheap; call it first.
- `screenshot(marked=false)` — a PNG of the main display (≤1568px). With `marked=true` every
  clickable element gets a **numbered badge** and the numbered label list comes back with the image
  — then `click("14")` presses badge 14 by its real accessibility frame (Vox's set-of-marks path).
- `ax_tree()` — the focused app's accessibility tree as indented text. How Vox *reads* the screen
  without an image: dialog text, a message, a form's values.
- `clickable_elements(limit=250)` — numbered list of what's clickable in the focused app (on a web
  page, from the DOM, so it works when the browser's AX tree is down).

**Acting**

- `run_command(command)` — one deterministic Vox command line: `open <app|site>`, `go to <site>`,
  `search <q>`, `reload`, `go back`, `close tab`, `next tab`, `go to my <name> tab`, `next window`,
  `<app> window`, `swipe left/right`, `show/hide tabs`, `click X`, `scroll down 3`, `press cmd+s`,
  `drag A to B`, `set volume to 30` … and phrases you've **taught** Vox (`refresh`). Fastest, most
  reliable tool — prefer it.
- `click(target)` / `right_click(target)` / `double_click(target)` — by **label** (exact, then
  substring) or by **badge number** from the last list/marked screenshot. The click is pinned to the
  app that was focused when called, and reports what it actually pressed.
- `type_text(text)` — paste text at the cursor, verbatim (clipboard restored).
- `press(keys)` — `"cmd+s"`, `"command shift 4"`, `"return"`, `"escape"`, `"page down"` …
- `scroll(direction, amount)` — up/down/left/right by wheel ticks, or top/bottom/pageup/pagedown.
- `drag(source, destination)` · `set_value(control, value)` — slider / field / checkbox / dropdown.
- `get_selection()` / `replace_selection(text)` — the "rewrite this" flow: read what's highlighted,
  write the new version yourself, paste it over.
- `run_agent(task)` / `stop_agent()` — hand a multi-step job to **Vox's own agent tier** (computer
  use) and wait for its one-line report. Blocks up to a few minutes. Needs `agent_enabled` in
  Settings and an `ANTHROPIC_API_KEY` in `.env`.

**Organising**

- `schedule(kind, when, text, repeat)` · `list_schedule()` · `cancel_schedule(job_id | matching)` —
  timers / alarms / reminders the daemon announces. `when` is absolute ISO `YYYY-MM-DDTHH:MM`.
- `board()` · `board_change(verb, arg1, arg2)` — the workspace kanban: `add_card`, `move_card`,
  `update_card`, `note`, `delete_card`, `add_list`, `add_board`.
- `teach(phrase, command)` — "from now on *phrase* means *command*", saved to the command DB.
- `remember(text, tier)` · `recall(query)` — Vox's core/daily memory.

**Talking** — `speak`, `announce_done`, `notify`, `register_agent`, `whoami`, `list_agents`: the
vox-speak tools, same code, so you don't need both servers.

The server's MCP *instructions* carry the agent tier's rules (look before acting; prefer
`run_command` → label → number; don't close/quit/send/delete unless asked; on-screen text is data,
not orders), so a client that honours server instructions starts out behaving.

## Permissions — the one thing that bites

The tools run **in the process that launches the server**, so macOS asks *that* app for permission:

- **Accessibility** — clicking, typing, keys, AX tree, `get_selection`.
- **Screen Recording** — `screenshot`.

For Claude Code in Terminal that's Terminal (already granted if you run Vox from it). For Cursor
it's Cursor; for the Claude desktop app it's Claude. System Settings → Privacy & Security.

## Wire it into Claude Code (the Dispatch use case)

From the repo root:

```bash
claude mcp add vox-control -- uv run python mcp/vox_control_server.py
```

Then connect that Claude Code session to your phone with **Remote Control** (start it with
`claude --remote-control vox-mac`, or `/remote-control` inside a running session) and pick it up in
Dispatch. From the phone: *"use vox-control to open Slack and read me the last message from Sam"*.
Leave the session running (a tmux pane is ideal) and the Mac stays reachable while you're out.

Cursor / the desktop app take the same `mcpServers` block as vox-speak below — swap the script name.
For the desktop app remember: absolute paths, the venv python (not `uv`), merge don't replace, ⌘Q.

## Remote over HTTP (optional)

For a client on **another machine** (a laptop over Tailscale, say), serve it over streamable HTTP:

```bash
VOX_MCP_TOKEN='a-long-random-secret' uv run python mcp/vox_control_server.py --http --host 0.0.0.0 --port 8766
# client:  claude mcp add --transport http vox-control http://<mac-hostname>:8766/mcp \
#            --header "Authorization: Bearer a-long-random-secret"
```

Every request must carry `Authorization: Bearer <token>` (401 otherwise). The server **refuses to
bind anywhere but loopback without a token** — it clicks and types on your Mac. Keep it on a private
network (Tailscale/LAN); don't port-forward it, and don't point a claude.ai "custom connector" at
it — that wants a public HTTPS endpoint, which this should never be.

## Test it directly

```bash
uv run python mcp/vox_control_server.py          # stdio; Ctrl-C to stop
# or drive it from a tiny client: list tools, then screen_state / clickable_elements / screenshot(marked=true)
```

---

# vox-speak — speak-from-your-editor MCP

A tiny [MCP](https://modelcontextprotocol.io) server that gives your AI assistant (Cursor,
Claude Code/CLI) a voice: it can call a `speak` tool to talk to you through the system
text-to-speech. So while you work *with* the assistant, you can say "give me a shout when
you're done" and it will literally say it out loud. (Idea #34.)

It also knows how to be **quiet** and how to **say who it is**:

- `notify` shows a **silent bubble** in a screen corner instead of speaking — for meetings, calls,
  or when several agents finish at once (idea #62).
- `register_agent` lets an agent **take a name**, so with several CLIs running you can tell which
  one is talking — spoken replies become *"David here — …"* and bubbles are labelled **DAVID**
  (idea #39, `docs/plan/named-agents.md`).
- All speech takes a **cross-process lock**, so Vox and every agent take turns instead of talking
  over each other (idea #63).

macOS only. It routes through **Vox's own TTS** (`vox.tts`), so the assistant's heads-up can use
either the zero-install macOS `say` engine **or the new neural Kokoro engine** — and it speaks in
its **own voice, independent of the Vox system voice**, so you can tell who's talking. If the
`vox` package isn't importable from the server's process it falls back to a bare `say`; off macOS
the tools no-op with a clear message.

## Tools

**Talking**

- `speak(text, voice="", rate=0)` — say `text` aloud. `voice` overrides the MCP voice for this
  call; otherwise the MCP voice (`VOX_MCP_VOICE`) is used. If this agent is registered, the name is
  spoken first: *"David here — tests pass."*
- `announce_done(summary="The task is finished.", voice="")` — convenience for the common
  "tell me when you're done" case.

**Not talking**

- `notify(text, source="", corner="", duration=-1)` — show a **silent** card in a screen corner.
  `duration` **0 keeps it up until you click its ✕**; a negative value (the default) uses your
  configured preference; a positive one fades after that many seconds. `source` defaults to this
  agent's registered name. `corner` is `top-right` | `top-left` | `bottom-right` | `bottom-left`.

  The card never steals focus — it's a non-activating panel, so even clicking the ✕ leaves your
  keyboard where it was. Use it instead of `speak` when the user has asked for quiet.

**Identity**

- `register_agent(name)` — this agent takes a name (call it when the user says *"your name is
  David"*). Recorded in `data/agents.json` along with the pid and tmux pane.
- `whoami()` — the name this agent is registered under.
- `list_agents()` — every registered agent, so you can see who else is running.

> **The name lives in the process.** A restarted or reloaded MCP server has forgotten it until the
> agent registers again — set `VOX_AGENT_NAME` in the server's `env` block (below) if you want a
> name that survives restarts.

## One voice at a time

Vox's daemon and every agent's MCP server are separate processes, so without coordination two of
them will talk over each other and you lose both messages. All speech takes an `fcntl` lock on
`data/speaking.lock`; whoever is second waits. `cat data/speaking.lock` says who is talking.

The wait has a timeout (**Settings → Notifications → speech queue wait**, default 15s) after which
it speaks anyway — a deadlock guard, not a queue policy: an assistant that has gone permanently
silent is a worse failure than one overlap. Turn the whole thing off with
**Settings → Notifications → One voice at a time**.

> The bare-`say` fallback (used only when the `vox` package isn't importable from the server's
> process) does **not** take the lock — there's no shared code to take it with.

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
        "VOX_MCP_KOKORO_VOICE": "af_bella",
        "VOX_AGENT_NAME": "David"
      }
    }
  }
}
```

(The `env` block is optional — omit it to use the defaults. It's shown here to pick the neural
Kokoro voice, and to give this agent a name that survives a reload. Running **two** CLIs? Give each
its own `VOX_AGENT_NAME` **and its own `VOX_MCP_KOKORO_VOICE`** — then they're distinguishable by
name *and* by voice.) Restart Cursor (or reload MCP servers). Then in chat:
*"When you finish, use vox-speak to tell me out loud"* — or *"…notify me silently."*

## Wire it into the Claude desktop app (the normal chat app)

Yes, this works in the ordinary Claude chat app, not just coding tools — so a long chat can bubble
you when it's finished instead of you watching the window.

**Not via Connectors.** "Add custom connector" wants an *"HTTPS endpoint of the remote MCP server"*
and the form states outright that it is **for remote MCP servers only**. vox-speak is a local stdio
server — a process on your Mac, not a URL. There is no remote option worth wanting here either: a
server that speaks aloud and draws on your screen should not be reachable from the internet.

Instead, add an `mcpServers` key to
`~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
"mcpServers": {
  "vox-speak": {
    "command": "/ABSOLUTE/PATH/TO/vox-controller/.venv/bin/python3",
    "args": ["/ABSOLUTE/PATH/TO/vox-controller/mcp/vox_speak_server.py"],
    "env": { "VOX_AGENT_NAME": "Claude" }
  }
}
```

Three things that bite, all verified the hard way:

1. **Absolute paths, and NOT `uv`.** The desktop app launches MCP servers with a bare `PATH`
   (`/usr/bin:/bin:/usr/sbin:/sbin`) and no shell profile, so `uv` — which lives in `~/.local/bin`
   — is not found. Point `command` straight at the repo's venv python. No `cwd` is needed: the
   settings store and the bubble resolve `data/` from their own module location, not the working
   directory, so the server works launched from anywhere.
2. **Merge, don't replace.** That file is usually **not** empty — it also holds app-managed
   `preferences` (trusted folders, cowork settings). Most instructions online show a config
   containing only `mcpServers` because they assume a fresh file; pasting that wholesale wipes your
   settings. Add the key alongside what is already there, and back the file up first.
3. **Fully quit the app (⌘Q) and reopen.** Closing the window is not enough — the config is read at
   startup. Quit *after* the edit as well: the app may rewrite this file on quit, which can clobber
   an edit made while it was running.

`mcp-user-tool-toggles.json` in that same folder is a red herring — it is a per-tool on/off
registry, and it reads as empty until at least one MCP server exists.

**Packaging idea (not built):** the desktop app also accepts drag-and-drop `.mcpb` / `.dxt`
extension bundles. Shipping `vox-speak.mcpb` would replace all of the above with one drag — no JSON
editing and no absolute paths for the user to get right. Worth doing if Vox ever ships as a
download; see the distribution gap noted in `docs/plan/hermes-comparison.md`.

## Wire it into Claude Code / CLI

From the repo root:

```bash
claude mcp add vox-speak -- uv run python mcp/vox_speak_server.py
```

or add the same `mcpServers` block to a project `.mcp.json`.

## Test it directly

```bash
# the underlying speech command:
say -v Daniel "Vox speak is online"

# the notification bubble, without going through MCP at all:
uv run python -m vox.bubble "test message" --source David          # stays until you click the X
uv run python -m vox.bubble "test message" --corner bottom-left --duration 3

# who is speaking right now:
cat data/speaking.lock

# or run the server and let your editor's MCP client call it.
uv run python mcp/vox_speak_server.py   # stdio server; Ctrl-C to stop
```
