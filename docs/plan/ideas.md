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

> **Status:** tab navigation (by name, **index**, relative) **built** for Arc & Chrome. Profile/space switching deferred — Arc spaces aren't exposed to AppleScript (`Can't get every space`); folder-scoped tab nav is likely the same (to confirm).

**Tab navigation:** "go to my GitHub tab", "go to the first tab", "tab above / below", "two tabs up". Select a tab by **title/URL match**, by **index**, or **relative** to the current one. Doable via browser AppleScript (Chrome/Arc expose `tabs` and `active tab`); Arc's vertical sidebar makes "above/below" = previous/next.

**Profile / space switching:** Arc **Spaces** and Chrome **profiles** — "switch to my work profile/space". Browser-specific and more limited via AppleScript (Arc has some Space commands; Chrome profiles are separate windows) — needs per-browser research.

## 5. Window switching (within the same app)

> **Status:** **built** — switches windows of the *frontmost* app by title (needs Accessibility permission). Future: target a named app, smarter title matching.

**Vision:** switch between multiple windows of one app — e.g. two Cursor windows (this project vs a work project). "switch to my work window", "switch to the <project> window", "next window".

**How it might work:** macOS **Accessibility / System Events** can enumerate an app's windows and their titles and raise one (`AXRaise`). Match by title substring (project name, "work"), or cycle next/previous. Same family as tab navigation (#4) but at the window level — works for any app. **Buildable now.**

**Notes:** needs Accessibility permission for the terminal; some apps use generic window titles, which makes matching harder.

## 6. "open UI" — jump to the web UI by voice

**Vision:** once the terminal-first **web UI** exists (see `overview.md`), a quick command — "open UI" / "show dashboard" — opens it instantly.

**Notes:** trivial once the UI is up — just open its local URL / focus its window. Natural pairing with the web-UI work.

## 7. On-screen character (Tamagotchi-style status pet)

**Vision:** a little always-visible character showing Vox is alive and what state it's in — idle, listening, control, assistant. Expression changes with mode; a glance tells you it's running (the sounds already give audio feedback).

**How it might work:** a small always-on-top overlay (a floating widget in the web UI, or a lightweight menu-bar pet) driven by the same mode state that triggers the sounds. Could start as a menu-bar icon that changes with state, then grow into the character. Pure fun + ambient status; rides with the web UI.

## 8. Recognition that personalises over time (accents & phrasing)

**Vision:** Vox gradually learns *your* voice and phrasing, so "Cursor" stops becoming "Casa".

**Feasibility for a small open-source project:**
- **Heavy / long-term — fine-tune Whisper:** possible (e.g. LoRA on Whisper) but needs labelled audio of your voice + GPU training. The big hammer; parked as a long-term goal (also in `overview.md`'s learning layer).
- **Cheap & effective now — ~80% of the benefit:**
  - **Learned corrections table:** when a mis-hear is corrected (you re-say it / it resolves), store "casa → cursor" and post-process future transcripts. Grows with use.
  - **Dynamic hotwords from usage:** auto-add your installed apps + most-used targets to the recognizer bias (we already bias statically).
  - **Fuzzy-match unknowns to known targets:** "casa" → nearest known app/site by edit/phonetic distance → "did you mean Cursor?" (ties into the assistant handoff).
  - **Interaction log → rules:** the learning layer in `overview.md` — log every utterance + correction, compile into personal rules.

**Takeaway:** full fine-tuning is overkill for now; the **corrections-table + dynamic-hotwords + fuzzy-match** combo is very doable at this scale and would noticeably improve accent/phrasing handling over time.

## 9. Conversation vs command detection

**Vision:** Vox should tell whether you're *commanding it* vs *talking to a person*, and stay quiet during conversation — so real commands don't fire from chatter (see the ambient-audio note in `observations.md`).

**Approaches (lightest → heaviest):**
- **Grammar/shape heuristic:** only act on short, command-shaped utterances (verb-first, in the known grammar); ignore long conversational sentences. Cheap.
- **Wake-per-command toggle:** optionally require the wake word before each command — unambiguous, less Dragon-like.
- **Intent classifier:** a small model (or the LLM, M4) that labels "command vs conversation" per utterance. Robust.
- **Personal tuning:** learns your command patterns over time (ties into #8 + the learning layer).

**Note:** the no-guess handoff already makes stray chatter harmless; this is about *also* not firing real commands buried in conversation.

## 10. LLM text commands ("write this" / "make this pretty")

In dictation or on selected text: **"write an email excusing me from X"** → the LLM composes it and types it; **"make this pretty"** → the LLM fixes spelling/punctuation of what you just typed *without changing the words*. Builds directly on M4 (LLM now wired) + dictation (typing) — the natural next step once chat is solid.

## 11. Cycle same-site tabs ("next YouTube tab")

Cycle between multiple open tabs of the *same* site (e.g. several YouTube tabs). "tab up/down" already works since they're adjacent in the sidebar; a dedicated cycler that jumps between matches would be a touch nicer. Low priority — not a current pain point.

## 12. LLM-as-executor — escalation that *does* the task (gated tool-calling)

**Vision:** when a command isn't recognised or is mis-worded ("close the tabs"; "switch cursor" → "search cursor"), the assistant LLM shouldn't *explain* how to do it — it should **just do it**. Give the LLM gated access to Vox's existing actions (open app, switch tab, close tab, profile…) as callable tools, so escalation bridges the wording gap. Phrasing stops mattering as long as the intent is clear.

**Why it matters:** this is the payoff of the escalation hook we already wired. Today an unknown command gets a spoken "I can't do that"; the goal is it gets *done*. The deterministic parser keeps the fast common path; the LLM catches the long tail and executes — so we stop having to word things exactly right.

**How it might work:**
- Wrap each Vox action as a **typed, in-process tool** (Claude Agent SDK `@tool` / `create_sdk_mcp_server`, or a function-calling schema for the API providers) — **not** a raw shell/Bash tool.
- **Gate it:** explicit allow-list of safe actions; `setting_sources=[]` so it can't inherit this repo's Claude Code file/shell tools; headless permission mode (no prompts) in the voice loop.
- **Fast tier:** run this on a quick model (Haiku via the Messages API) so execution is near-instant; reserve the deep model / subscription for genuine reasoning.

**Connects to:** the escalation hook (built), the tiered cascade (`overview.md`), #2 (intent classification), and the `claude-agents.md` / `coding-agents.md` research (dedicated gated tools, permission models).

## 13. Action-first / silent success — don't always talk back

**Vision:** when an utterance resolves to an **action**, Vox should just **do it** (with the existing sound cue) and stay quiet — no spoken reply. It should only speak when it's **genuinely ambiguous / confused** or the user **asked a question**. Most control scenarios ("close the tabs") need no verbal response; a spoken "Done!" every time breaks the seamless feel.

**Why it matters:** speed + seamlessness. The most natural assistant quietly does what you said and only interrupts when it must. Pairs with #12 — the LLM executes silently on success and speaks only to disambiguate.

**How it might work:**
- Classify the resolved intent: **action** → execute + sound cue, no TTS; **question / ambiguous / failure** → speak (clarify or report).
- Tie into turn-taking: a silent action keeps the floor with the user; only a spoken question opens a turn (`[OPEN]`).

**Connects to:** #9 (command vs conversation), the turn-taking work (`voice-turn-taking.md`), and the "ask only when unsure" principle (`observations.md`).

## 14. Self-wiring command learning — fallbacks become permanent rules

**Vision:** the first time you say something Vox doesn't know ("close the tabs") and the LLM works out what you meant, **capture that mapping** — phrase → action — and persist it as a **learned rule**. Next time, the deterministic parser hits it instantly with no LLM call. Over time Vox adapts to *your* phrasing; mistakes are **AI-correctable** later ("no, 'close tabs' should mean X").

**Why it matters:** the learning layer made concrete and cheap. Every LLM fallback is a one-time cost that *teaches* the system; the long tail of phrasings collapses into fast deterministic rules. It's how Vox gets faster and more personal with use.

**How it might work:**
- On a successful LLM-resolved action, log `(spoken_phrase, resolved_intent, args)` to a local store (SQLite — the planned rules/learning store).
- Compile high-confidence mappings into the parser's lookup so they short-circuit future utterances.
- Correction path: a voice/AI command to relabel or delete a rule ("forget that"; "that should open Gmail").

**Connects to:** the learning layer + teachable rules engine (`overview.md`/`roadmap.md`), #8 (corrections table / personalisation), #12 (the executor produces the training signal), and #15 (when the wiring happens).

## 15. Background wiring — learn without making the user wait

**Vision:** decouple **doing** from **learning**. Perform the task immediately and let the user move on, then **wire up** the learned rule (#14) **asynchronously in the background** — so adaptation never adds latency to the live interaction.

**How it might work:**
- After executing, hand the `(phrase → action)` capture to a background worker/queue; persist + compile the rule off the hot path.
- Keep it idempotent and crash-safe (the store is the source of truth); the next utterance picks up new rules whenever they're ready.

**Connects to:** #14 (what gets wired), #12 (executes first), and the learning layer.

## Sequencing note

Most of these rest on two foundations we haven't built yet: the **assistant / LLM (M4)** and **voice output / TTS (M2)**. Those two unlock most of the magic above — worth weighting toward them when we pick what to build next.
