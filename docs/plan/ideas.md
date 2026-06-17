# Vox — Idea Parking Lot

> Bigger, further-out ideas captured so we don't lose them. Not scheduled — graduate to `roadmap.md`/`features.md` when ready. (Small near-term items live in `features.md`; bugs/edge cases in `observations.md`.)

## 1. Gaze-directed input — "type/write here"

**Vision:** eye tracking so you can *look* at a pane and direct input there. In Cursor with split panes/terminals (code in one, Claude in another), look at a pane and say **"type here"** / **"write here"** → Vox routes your speech to wherever you're looking.

**How it might work:**
- Gaze source: dedicated hardware (e.g. Tobii) for accuracy, or webcam-based gaze estimation (cheaper, coarser).
- Map gaze → screen point → the window / UI element under it via the macOS **Accessibility API**; focus it.
- Inject dictated text as keystrokes (CGEvent / Accessibility).

**Risks/notes:** webcam gaze is coarse — realistically good for "which pane," not pixel-exact; hardware gaze is precise but an extra dependency. Depends on accessibility + keystroke injection + dictation.

## 2. Coding / handoff mode — literal dictation vs AI tasks

**Vision:** distinguish two kinds of "write" instruction:
- **Literal dictation** — "write here: <words>" → type your speech verbatim where you're looking.
- **Handoff / AI task** — "write an email excusing me from this event", or "create a for-loop that sums numbers" → hand off to an LLM/agent (Claude / OpenCode) to *compose or implement*, then insert the result.

**Why it matters:** this is the intent-classification heart of the system — "do exactly what I said" vs "figure out what I want and do it." A **coding mode** could pull gaze/editor context and delegate complex tasks to a coding agent.

**Connects to:** the tiered cascade (`overview.md`), the assistant/LLM (M4), agentic execution / OpenCode (backlog), and the "escalate when unsure" principle (`observations.md`).

## 3. Voice callback from Claude Code (MCP / hook)

**Vision:** bridge Claude Code (CLI) → Vox so long-running CLI work can **talk back**. Tell Claude "give me a shout when you're done"; when it finishes, it notifies Vox, which **speaks** the result.

**How it might work:**
- Vox runs a small local notify endpoint (socket / HTTP).
- Claude Code side: a **Stop hook** (fires when Claude finishes) or a small **MCP tool** (`notify(message)`) that POSTs to Vox.
- Vox speaks it via TTS.

**Notes:** very achievable once **TTS exists (M2)** + a local notify channel — the hook route is probably simplest; an MCP "notify/speak" tool is the more general version. Genuinely useful for long agent runs.

## 4. In-browser tab & profile control

**Tab navigation:** "go to my GitHub tab", "go to the first tab", "tab above / below", "two tabs up". Select a tab by **title/URL match**, by **index**, or **relative** to the current one. Doable via browser AppleScript (Chrome/Arc expose `tabs` and `active tab`); Arc's vertical sidebar makes "above/below" = previous/next.

**Profile / space switching:** Arc **Spaces** and Chrome **profiles** — "switch to my work profile/space". Browser-specific and more limited via AppleScript (Arc has some Space commands; Chrome profiles are separate windows) — needs per-browser research.

## Sequencing note

Most of these rest on two foundations we haven't built yet: the **assistant / LLM (M4)** and **voice output / TTS (M2)**. Those two unlock most of the magic above — worth weighting toward them when we pick what to build next.
