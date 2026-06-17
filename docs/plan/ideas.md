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

## 16. Timers, alarms & reminders (Echo-style, native macOS)

**Vision:** "set a timer for 10 minutes", "remind me to call Sam at 3pm", "set an alarm for 7am" — like an Amazon Echo, but wired into **native Apple apps** so the reminders/alarms live where you already see them. Reminders should also be **spoken back** once Vox has a voice (TTS).

**How it might work (per type):**
- **Reminders — easy, scriptable now.** Apple's Reminders.app has full AppleScript support: `make new reminder with properties {name:"call Sam", remind me date:date "…"}`. Voice → the brain parses time + text → create the reminder → it fires natively. Spoken readback of due reminders once TTS (M2) lands.
- **Timers / alarms — Clock.app isn't scriptable**, so use one of:
  - **macOS Shortcuts** "Start Timer" / "Set Alarm" actions, invoked via `shortcuts run "<name>"` (or URL scheme) — real native Clock integration.
  - **Vox's own timer** — a background thread that plays a sound (and speaks, once TTS) when it elapses. No native app, but dead simple; only runs while Vox does.
- **Time parsing:** lean on the small brain to turn "in ten minutes" / "quarter past three" into a concrete datetime — pairs naturally with the executor's translate-to-command approach (#12).

**Depends on / connects to:** TTS (M2) for spoken reminders; the brains/executor (#12, #17) for parsing + dispatch; could surface in the on-screen pet (#7) as a visible countdown.

**Notes:** Reminders is the quick win (scriptable today). Timers via Shortcuts is the cleanest native path; the in-Vox timer is the simplest fallback.

## 18. Screen visibility — screenshot vs. accessibility tree

**Vision:** when the brain needs to know what's actually on screen (not just running apps/tabs), give it a way to "see" — so it can answer "what does this say?" or act on what's in front of you.

**Two approaches (the second is the better long-term one):**
- **Screenshot → vision model.** Capture is trivial (`screencapture -x /tmp/vox.png`), then send the image to a vision-capable model. *But*: it's **provider-specific** (Anthropic API takes image blocks cleanly; the Claude SDK/subscription path and local LLMs vary), and images are **token-heavy**. Best as an opt-in *fallback* skill via the API vision path, not the default.
- **Accessibility (AX) tree → text.** The macOS analog of the Windows UI-Automation tree (what worked well on OpenFlow): walk `AXUIElement` from the focused app and dump a structured text tree of windows/controls/values. **Token-cheap, structured, and more useful** than a screenshot for *acting* on UI. More work to build (AX traversal, per-app quirks, Accessibility permission), and some apps expose poor trees.

**Where we already are:** `actions.environment_context()` (running apps + open tab titles) is a lightweight slice of this — the brain already gets *some* sight. The AX tree is the rich extension; the screenshot is the visual fallback.

**Recommendation:** AX-tree is the direction that matches the "see through text/structure" idea and stays cheap. Add the screenshot as a small opt-in skill (Anthropic API + a vision model) for the rare "just look at it" case. Both gated behind a config flag; watch token cost on the screenshot path.

**Connects to:** the executor/brains (#12, #17), `environment_context` (built), and the coding-agents research note on per-turn `environment_details`.

## 19. Barge-in — interrupt mid-task ("stop it NOW")

**Vision:** say the emergency word (or any speech) and have Vox **stop immediately**, even mid-LLM-call — the "cancel before it acts" the abort phrases can't yet do.

**Why it's not free today:** Vox is **synchronous** — while waiting on the brain it isn't processing the mic, so `abort` is only seen *between* utterances, after the current action finishes.

**How it might work:**
- Keep the mic stream draining on a **background listener thread** during any blocking brain call.
- Run the brain/executor call so its result can be **discarded** if an abort/stop phrase is detected before it lands (Python can't kill a thread cleanly, so let the call finish but skip the action).
- Where possible, cancel the underlying subprocess (claude CLI/SDK).
- Generalises to true **interruption/barge-in** (the voice-agent research pattern): a quick word also stops TTS playback once that exists.

**Connects to:** the emergency-stop phrases (built — `abort_phrases`), the executor (#12), and `research/voice-turn-taking.md` (barge-in / interruption).

**Status:** ✅ BUILT for LLM calls — say "go to sleep" / "stop" / "quit" / "restart" *while the brain is thinking* and it cancels immediately (the call runs on a thread; a stop phrase abandons it). Toggle `barge_in_enabled`. Caveat: the abandoned call finishes in the background, so a quick *action* it was about to run may still complete (slow calls are usually chat/compose/vision, where abandoning is clean). Still pending: interrupting Vox's own *spoken* reply (TTS), which needs AEC (#21) so it doesn't hear itself.

## 20. Cross-platform (Windows / Linux)

**Vision:** it's open source — others will want it on Windows (and Linux).

**The split:**
- **Easy parts (already near-portable):** STT (faster-whisper) is cross-platform. **TTS**: Windows has built-in **SAPI** (`System.Speech.Synthesis` via PowerShell), and the cross-platform lib **`pyttsx3`** wraps SAPI (Win) / NSSpeechSynthesizer (Mac) / espeak (Linux). `tts.py` is already the swap point, so a `speak()` per-OS is small.
- **The hard part:** `actions.py` is **entirely macOS** — AppleScript + System Events for every command (apps, tabs, windows, Spaces, keystrokes, clipboard, screenshot). A Windows port needs a parallel automation layer: **UI Automation / pywinauto**, `pyautogui`/`keyboard` for keystrokes, `pygetwindow` for windows, PowerShell to launch apps, browser-specific automation, and `PIL.ImageGrab` for the screenshot.

**Approach:** define a platform-agnostic `actions` interface with `actions_macos.py` (current) + `actions_windows.py`, selected at runtime; TTS/STT abstract cleanly already. The architecture (swappable I/O, deterministic-first) is friendly to it — but it's a real effort, mostly re-implementing `actions.py`.

**Connects to:** `tts.py` (the swap point), the modular-components goal in `overview.md`.

## 22. Personalities (swappable + self-tweaking)

**Vision:** give Vox a **personality** you can choose — concise-professional, warm-friendly, witty, deadpan butler — with a setting to swap presets, and (the fun part) let Vox **tweak or invent its own** on request ("be more sarcastic", "talk like a pirate"), persisting it.

**How it might work:**
- **Now (minimal, built):** a `personality` string in config, injected into the chat system prompt — instant tone control.
- **Presets:** a small named dict; a voice command or setting picks one ("switch to professional mode").
- **Self-tweaking:** "Vox, be more X" → the brain rewrites its own personality string → saved to the local store (ties to the learning layer / #14).
- **Accent pairing:** each personality can carry a `tts_voice` (e.g. a British voice for the dry-butler persona) — macOS `say` already has per-accent voices (Daniel en_GB, Karen en_AU, Moira en_IE, Rishi en_IN, Tessa en_ZA…).

**Connects to:** the chat system prompt (`_SYSTEM`), TTS voices (`tts_voice`), the learning/rules store (#14).

## 23. Escalation policy — when an unparsed command reaches the brain

**Vision:** control mode is **deterministic-first** — a known command runs locally; anything else *escalates* to the LLM. That escalation is great for "do what I mean", but it also means **any speech the parser can't handle reaches the brain** — including a video on the speakers or a side conversation (issues.md O7). Give the user a dial for how eager that escalation is.

**Two modes (config `escalation_mode`):**
- **`"auto"` (default, as it's always been):** escalate whatever the parser misses. Most natural for headphones / a quiet room — you can phrase anything and Vox tries. The 1-word/filler **noise gate** still drops obvious background fragments.
- **`"keywords"`:** escalate **only** when the utterance contains an `escalation_keywords` trigger — "write", "compose", "make this", "rewrite", "vox", "I need help", "learn", "what does this"… (grouped by the executor capability they reach: compose / rewrite / screen-vision / direct-ask). Everything else is ignored. You **opt the brain in by phrasing** ("*Vox,* write me an email", "make this pretty"), so a podcast or a colleague talking no longer trips the LLM. The keyword list is tunable to your habits.

**Important nuance:** a **pending clarification** (the brain just asked *you* a question) always escalates regardless of mode — otherwise a keyword-free answer like "the blue one" would be dropped.

**Why it matters / connects to:** this is the **steerable** sibling of the noise gate and a strong, today-available mitigation for **O7** (ambient audio → false LLM triggers) until AEC (#21) lands. It also sets up the future **tiered cascade** (rules → keywords → fast model → deep model) and pairs with the learning layer (#14): learned triggers could extend `escalation_keywords` automatically.

**Status:** ✅ BUILT (2026-06-17). `escalation_mode` + `escalation_keywords` in config; gated in `_control_mode` so non-keyword utterances are ignored in keyword mode (auto mode unchanged). Default stays `"auto"` so nothing changes unless you opt in.

## Sequencing note

Most of these rest on two foundations we haven't built yet: the **assistant / LLM (M4)** and **voice output / TTS (M2)**. Those two unlock most of the magic above — worth weighting toward them when we pick what to build next.
