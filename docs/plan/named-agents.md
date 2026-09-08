# Named coding agents — talk to your CLIs by name (design doc)

> Deep-dive for **idea #39** (multiple named agents). Nothing here is built yet — this is a
> captured design so we can sit down, read it, and choose later. **No decisions are forced; every
> option is kept.** Related: #3 (voice callback), #34 (vox-speak MCP), #49 (MCP two-way bridge),
> #38 (coding brain), #25 (scoped prompts), #22 (personalities).
>
> **Status:** 💡 mostly design. Shipped so far: the **pre-speech sound cue** (see "Speak-back"), and
> as of **2026-08-31** the **identity half** of stage 1 plus one stage-5 item —
> `src/vox/agents.py` (the `data/agents.json` registry), the `register_agent` / `whoami` /
> `list_agents` MCP tools, automatic name-prefixing on spoken replies, agent names on notification
> bubbles (#62), and the **central speak-queue** (`src/vox/speech_lock.py`, #63) that this doc listed
> under "honest risks" as fine to skip for an MVP — it turned out to be the first thing that bit.
>
> **Still not built: the routing half.** Getting your voice back *into* David's session
> (`tmux send-keys`, the `agent:<name>:<text>` label in `_oneshot`/`loop.py`) is untouched. Today you
> can tell who is talking; you can't yet talk back to one by name.

---

## TL;DR — the vision in one paragraph

You run several Claude CLIs at once (one per task). You **give each a name** — "David", "Greg" —
and from then on you address them by voice from anywhere: *"David, what's the status on those
changes?"* routes your words into **David's** session; *"Greg, how are you getting along?"* goes to
**Greg's**. They answer **out loud** (the speak-back you already use). Crucially, Vox does **not**
steal your focus or switch your tab — it types into the right session in the background, exactly as
if you'd typed it yourself. The result is a hands-free, full **back-and-forth conversation** with
each named agent, while you keep working in whatever window you're in.

This is a "fun side project" layer on top of things that already exist — it reuses the wake/one-shot
router, the vox-speak MCP, and Vox's Mac automation. The genuinely new surface area is small.

---

## The two halves of the loop (and what already exists)

A named-agent conversation is two directions. **You already built one of them.**

| Direction | What it is | Status |
|---|---|---|
| **Agent → you (speak-back)** | The CLI talks to you out loud | ✅ **Exists** — `vox-speak` MCP (`speak`/`announce_done`). Now with a pre-speech chime. |
| **You → agent (routing)** | Your voice goes into one specific CLI | 🚧 The **new** piece. But the *router hook* already exists (see below). |

The router hook: Vox's idle listener already anchors a name at the **first word** of an utterance
and routes the rest — that's how "Vox, open Safari" works today
(`src/vox/wakeword/backends.py:_oneshot`):

```python
m = re.match(r"(?:vox|vocks|vaux|fox|box)\s+(.+)", t)  # name + the rest
```

Extending this to *also* match registered agent names ("david …", "greg …") and emit a new label
like `agent:David:<the rest>` is a small, natural change. The label→handler plumbing in
`src/vox/core/loop.py` is built for exactly this kind of routing.

So: speak-back exists, the name-router exists. **The only real new work is "type the words into the
right session without stealing focus."**

---

## The key clarification: headless vs. interactive (you do NOT need headless)

You said you imagined these would "all be headless agents." Let's pin down the difference, because
it changes everything — and the conclusion is the opposite of what you expected.

**Interactive session (what you use today):** you run `claude` in a Cursor terminal. It draws a full
text UI. You watch it think and stream output live, and you type follow-ups. It's a **persistent
conversation living in that tab**, and you can touch it with your hands any time.

**Headless agent:** the same Claude brain with **no UI**. You hand it a prompt programmatically
(`claude -p "do X"`), it works, prints a result, and exits. To continue you "resume" it with another
programmatic call. There's **no tab to watch** — Vox would own it and surface it only via the
dashboard/logs.

Here's the crux: **for what you described, interactive tabs are the better fit — they do not need to
be headless.** Why:

- **You want to see them work.** Your words: *"it would be cool to have real interactive tabs."*
  Headless = nothing to watch.
- **You want to steer and reply mid-conversation.** With an interactive tab, Vox injecting your
  spoken words is **literally identical to you typing them** into that tab. So steering and replying
  "just work" — it's one continuous session you can *also* drive by hand. With headless you'd have to
  manage session-resume plumbing for every follow-up.
- **The thing that made you think "headless"** was probably "Vox runs them in the background." But
  *"a visible interactive tab"* and *"Vox can send text to it without me switching to it"* are **not
  mutually exclusive.** tmux / iTerm let Vox type into a **visible, interactive** session without
  stealing your focus. You get **both**: a real tab you watch + voice control of it.

> **Recommendation:** interactive tabs that Vox types into by name — **not** headless. Headless stays
> documented below as an option for "fire-and-forget background workers" later, but it's not the
> primary design.

---

## How Vox gets your words into the right session (mechanisms — all kept)

Ranked by robustness. We keep all of them documented; pick per setup.

### 1. tmux `send-keys` — most robust, no focus change *(recommended)*
Each Claude runs inside a named tmux session (`tmux new -s David`, then `claude`). Routing is then:

```bash
tmux send-keys -t David "what's the status on those changes" Enter
```

- **Pros:** rock-solid, scriptable, **never** touches your focus or front window, targets by name
  directly, and unlocks the "read the agent's output" trick (below) almost for free.
- **Cons:** you run your CLIs inside tmux (a one-time `tmux new -s <name>` per agent — and Vox could
  spawn them for you on command: *"Vox, start an agent called David"*).

### 2. iTerm2 `write text` — no tmux, keeps native tabs
iTerm can write to a session **by id** without bringing it forward:
`tell session id "…" to write text "…"`.
- **Pros:** no tmux; uses your normal iTerm tabs; no focus steal.
- **Cons:** iTerm-specific; you must capture each session's id (the self-registration trick handles
  this). Terminal.app has an equivalent (`do script … in <tab>`) but tends to raise the window.

### 3. System Events keystroke — **rejected**
Bring the terminal forward, type, press Enter. Works, but **steals focus** — defeats the whole
"without switching tabs" goal. Listed only to say: not this.

### 4. Headless (`claude -p --resume`) — the background-worker alternative
Vox owns named headless sessions, captures their text output directly, and speaks it. No terminal
automation at all (least fragile), but no tab to watch and follow-ups need resume plumbing. Good for
"go off and do this, tell me when done" workers; not the primary design.

> **Cursor note (your setup):** your CLIs run in **Cursor's integrated terminals** in your main work
> folder. Cursor's terminal is a normal terminal emulator, so the cleanest path there is **run the
> CLI inside tmux** *within* that Cursor terminal (`tmux new -s David` → `claude`). Vox then routes
> by tmux name and never has to know or care that it's inside Cursor. This is why tmux wins for you:
> it's terminal-emulator-agnostic and **works from anywhere**.

---

## The elegant bit: agents name *themselves* (self-registration)

The hard sub-question is "how does Vox know which terminal is David?" The clean answer you liked:
**the agent registers itself.**

Add **one tool** to the MCP server — `register_agent("David")` — which records *its own* tmux pane
(it inherits `$TMUX_PANE` from the CLI that launched it) into a small registry file
(e.g. `data/agents.json`). Flow:

1. You open a fresh tmux tab and start `claude`.
2. You tell it: *"Your name is David — register yourself."*
3. David calls `register_agent("David")` → the registry now maps **David → that pane**.
4. From anywhere: *"David, …"* → Vox looks up the pane and `send-keys` your words to it.

No central config, no guessing which window you meant. (For the iTerm path, the same tool captures
the iTerm session id instead of the tmux pane.) An agent can re-register / rename freely; a
`whoami` / `list_agents` tool makes the registry inspectable.

---

## The conversation model — your two questions, answered

This is the heart of what you asked. Both work, and both are **symmetric** with the first prompt,
because *Vox addressing an agent = typing into its session.*

### Q1 — "What if I want to steer it: *'also, when you're working on this, make sure you do X'*?"
**Works, trivially.** Steering is just another line typed into David's tab:

> *"David, also make sure you handle the empty-list case."*

→ Vox types that into David's session as the next input. It's **identical to you typing it by hand**,
just hands-free and without switching tabs. If David is mid-generation, the CLI queues your line as
the next turn (exactly like typing while it's responding) — normal CLI behavior, nothing special
needed.

### Q2 — "When it tells me it's done via the MCP (my most-used feature) and I want to reply to that character — does it work the same way?"
**Yes — it's a full round-trip.** Concretely:

1. David finishes and calls `speak("done — tests pass")` → you hear the **chime, then the voice**.
2. You reply: *"David, great — now also update the changelog."*
3. Vox matches "David" → types `great — now also update the changelog` into David's tab.
4. David continues, in the **same conversation**.

So the loop is: **you talk → David's tab → David works → David speaks → you talk → …** — a hands-free
conversation with a specific named agent, never touching the keyboard or switching tabs. That's
precisely the "shortcut" you wanted.

### Nice enhancement: "sticky" last-addressed agent
After David speaks (or after you address David), a **bare follow-up within ~N seconds** — *"great,
now also do Y"* with **no name** — routes to David automatically. This mirrors Vox's existing
assistant `expecting_answer` turn-taking (`loop.py`): when an agent just spoke, Vox briefly "expects"
your reply and sends a nameless follow-up to that same agent. So you don't have to repeat the name in
a quick back-and-forth. Optional; documented so we don't lose it.

---

## Speak-back, voices, and the new sound cue

- **The sound cue (✅ shipped this session).** Every MCP `speak`/`announce_done` now plays a short
  chime **first**, so a spoken heads-up doesn't appear from nowhere. Default `Tink.aiff`; change or
  disable it in **Dashboard → Settings → MCP voice → "MCP speak cue sound"** (blank = off), or via
  `VOX_MCP_CUE`. Implemented in `mcp/vox_speak_server.py` (`_play_cue`), config key
  `mcp_speak_cue`. **Reload the MCP server in your editor to pick up a change.**
- **Per-agent voices.** Each agent's MCP server can launch with a different `VOX_MCP_KOKORO_VOICE`
  (the server already supports per-instance env), so David and Greg **sound different**. We could
  also key the voice off the registered name automatically.
- **Per-agent sound cues.** Same idea — a different chime per agent, so you know who's about to talk
  before you even hear the words.
- **Name prefixing.** Instruct agents (via the project CLAUDE.md) to prefix spoken replies with their
  name — *"David here — tests pass"* — so multiple agents never blur together.

### Bonus: read the output instead of relying on the model to speak
Today the agent only speaks if it *chooses* to call the MCP. With the **tmux path** we get a stronger
option almost free: after Vox sends a prompt, it can **wait for the pane to settle and read the new
output** (`tmux capture-pane`), then speak a short summary itself. This makes **any** CLI answer
audibly — even ones without the MCP wired — and removes the dependency on the model remembering to
call `speak`. Documented as an option; the MCP path stays the default.

---

## Setup & "works from anywhere"

- **The registry + tmux/iTerm targeting are folder-independent** — addressing "David" works no matter
  which directory David was started in, or which app you're focused on. Only the *per-project*
  instructions live in a CLAUDE.md.
- **Your main CLAUDE.md is in your main work folder.** To make agents auto-register and speak back
  nicely, add a short block there (or a shared snippet) telling the agent to: (a) call
  `register_agent(<name>)` when you give it a name; (b) call `vox-speak` when it finishes a task you
  asked to be told about; (c) prefix spoken replies with its name. This is the only project-scoped
  bit; everything else is global.
- **Spawning by voice (optional).** *"Vox, start an agent called David in ~/Repos/your-project"* → Vox
  opens a terminal running `tmux new -s David` + `claude` in that dir, and David self-registers on
  first hello.

---

## Honest risks & open problems (kept so we decide with eyes open)

- **Name mishears / false triggers.** "David"/"Greg" are common words Whisper sometimes mis-hears or
  trips on. First-word anchoring helps; distinctive names help more; a tiny confirm-on-low-confidence
  could help. Same class of problem as the "vox" wake word — manageable, not solved for free.
- **Overlapping speech.** Each agent's MCP server speaks independently, and the Vox daemon speaks too
  — no shared audio lock across processes. Two agents finishing at once could talk over each other. A
  small central **speak-queue** (a file lock, or routing all speech through the running daemon) fixes
  it; fine to skip for an MVP.
- **Long output is bad to speak.** A full diff read aloud is awful. Agents should answer with a short
  spoken status, or Vox summarizes the captured pane. (The `speak` tool already truncates at 1000
  chars.)
- **Knowing the agent is "ready" for your steer.** Injected text lands as the next turn; if the agent
  is mid-run it's queued. Matches normal CLI behavior, but worth confirming it feels right per CLI.
- **tmux is a small workflow nudge.** One `tmux new -s <name>` per agent. If that's unwanted, the
  iTerm path or headless variant avoids it.
- **Mic ownership.** The Vox daemon owns the mic (single-instance guard). Anything where an *agent*
  wants to ask *you* a question and hear the answer must route through the daemon (see #49's
  web-bridge note), not have the MCP grab the mic. Out of scope for the basic feature; relevant if we
  later add agent-initiated questions.

---

## Suggested staging (when we pick it up — not now)

Each stage is independently useful; stop anywhere.

1. **MVP — one named agent, one direction.** Registry file + `register_agent` MCP tool +
   `agent:<name>:<text>` routing in `_oneshot`/`loop.py` + `tmux send-keys`. Address one agent by
   name, watch it run. *(Speak-back already works.)*
2. **Round-trip + multiple agents.** Per-agent voices/cues, name-prefixed replies, two+ agents at
   once. Confirms the David/Greg scenario end-to-end.
3. **Sticky follow-ups.** Last-addressed-agent context so nameless replies route correctly in a
   back-and-forth.
4. **Pane-capture speak-back.** Vox reads + summarizes the agent's output, so any CLI answers audibly
   without relying on the MCP.
5. **Polish.** Voice-spawned agents, `list_agents`/`whoami`, central speak-queue, low-confidence
   confirm, dashboard "Agents" panel.

---

## Decisions to make later (none now)

When you sit down to read this, these are the only real forks:

1. **Interactive tabs (tmux) vs. headless workers** — recommendation: interactive/tmux. *(Your
   instinct was headless; this doc argues interactive is the better fit for what you described.)*
2. **tmux vs. iTerm** for the injection path (if not tmux).
3. **Speak-back source:** model-initiated MCP (today) vs. Vox reading the pane (stage 4) — or both.
4. **Sticky follow-ups on/off**, and the timeout window.
5. **Naming convention** to minimize mishears (distinctive names, optional prefix word).

Everything above is reusable and additive — none of it disturbs how Vox or your CLIs work today.
