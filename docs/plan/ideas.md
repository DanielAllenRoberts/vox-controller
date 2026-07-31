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

> **Status:** ✅ BUILT — "open dashboard" / "close dashboard" work from idle, control *and* assistant modes; opens in its own window (Arc Little-Arc), non-disruptive close, with open/close sound cues.

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

> **Status:** ✅ BUILT — voice compose ("write me…") and rewrite ("make this pretty") via the executor; types the result.

In dictation or on selected text: **"write an email excusing me from X"** → the LLM composes it and types it; **"make this pretty"** → the LLM fixes spelling/punctuation of what you just typed *without changing the words*. Builds directly on M4 (LLM now wired) + dictation (typing) — the natural next step once chat is solid.

## 11. Cycle same-site tabs ("next YouTube tab")

Cycle between multiple open tabs of the *same* site (e.g. several YouTube tabs). "tab up/down" already works since they're adjacent in the sidebar; a dedicated cycler that jumps between matches would be a touch nicer. Low priority — not a current pain point.

## 12. LLM-as-executor — escalation that *does* the task (gated tool-calling)

> **Status:** ✅ BUILT — `executor.execute` translates an unrecognised/mis-worded command into a real action via the small brain (tiered small/big), instead of explaining. The deterministic parser still owns the fast path.

**Vision:** when a command isn't recognised or is mis-worded ("close the tabs"; "switch cursor" → "search cursor"), the assistant LLM shouldn't *explain* how to do it — it should **just do it**. Give the LLM gated access to Vox's existing actions (open app, switch tab, close tab, profile…) as callable tools, so escalation bridges the wording gap. Phrasing stops mattering as long as the intent is clear.

**Why it matters:** this is the payoff of the escalation hook we already wired. Today an unknown command gets a spoken "I can't do that"; the goal is it gets *done*. The deterministic parser keeps the fast common path; the LLM catches the long tail and executes — so we stop having to word things exactly right.

**How it might work:**
- Wrap each Vox action as a **typed, in-process tool** (Claude Agent SDK `@tool` / `create_sdk_mcp_server`, or a function-calling schema for the API providers) — **not** a raw shell/Bash tool.
- **Gate it:** explicit allow-list of safe actions; `setting_sources=[]` so it can't inherit this repo's Claude Code file/shell tools; headless permission mode (no prompts) in the voice loop.
- **Fast tier:** run this on a quick model (Haiku via the Messages API) so execution is near-instant; reserve the deep model / subscription for genuine reasoning.

**Connects to:** the escalation hook (built), the tiered cascade (`overview.md`), #2 (intent classification), and the `claude-agents.md` / `coding-agents.md` research (dedicated gated tools, permission models).

## 13. Action-first / silent success — don't always talk back

> **Status:** ✅ BUILT (largely) — control commands execute with just a sound cue, no spoken reply; the assistant-mode command-watcher runs a genuine command silently mid-chat too. Full intent-classified speak/stay-quiet split keeps maturing.

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

> **Status:** 🚧 QUEUED for this session — see `session-2026-06-19.md`. Decision shift:
> build a **Vox-owned unified scheduler** (one job model for timers/alarms/reminders, with
> recurrence + cancel, fired by a background thread, surfaced/cancellable on a dashboard
> page) rather than leaning on Apple Reminders — that's the only shape where "see all the
> crons in the dashboard" works. Native Apple integration stays a later add-on.

**Vision:** "set a timer for 10 minutes", "remind me to call Sam at 3pm", "set an alarm for 7am" — like an Amazon Echo, but wired into **native Apple apps** so the reminders/alarms live where you already see them. Reminders should also be **spoken back** once Vox has a voice (TTS).

**How it might work (per type):**
- **Reminders — easy, scriptable now.** Apple's Reminders.app has full AppleScript support: `make new reminder with properties {name:"call Sam", remind me date:date "…"}`. Voice → the brain parses time + text → create the reminder → it fires natively. Spoken readback of due reminders once TTS (M2) lands.
- **Timers / alarms — Clock.app isn't scriptable**, so use one of:
  - **macOS Shortcuts** "Start Timer" / "Set Alarm" actions, invoked via `shortcuts run "<name>"` (or URL scheme) — real native Clock integration.
  - **Vox's own timer** — a background thread that plays a sound (and speaks, once TTS) when it elapses. No native app, but dead simple; only runs while Vox does.
- **Time parsing:** lean on the small brain to turn "in ten minutes" / "quarter past three" into a concrete datetime — pairs naturally with the executor's translate-to-command approach (#12).

**Depends on / connects to:** TTS (M2) for spoken reminders; the brains/executor (#12, #17) for parsing + dispatch; could surface in the on-screen pet (#7) as a visible countdown.

**Notes:** Reminders is the quick win (scriptable today). Timers via Shortcuts is the cleanest native path; the in-Vox timer is the simplest fallback.

**Cross-device reality (researched 2026-06-19):** for "it also goes off on **my phone**",
macOS **Clock alarms/timers do NOT sync** to iPhone (device-local) and Clock isn't
scriptable — so the phone path is **Apple Reminders** (scriptable *and* iCloud-synced) or
Calendar, NOT Clock. Hence the session-plan decision: build the **Vox-owned scheduler core**
(dashboard-visible, cancellable, fires sound/voice per kind), with an **optional Apple
*Reminders* mirror** for cross-device. **Output policy:** reminders speak (personalised with
your name), timers chime, alarms do both.

## 18. Screen visibility — screenshot vs. accessibility tree

> **Status:** ✅ partial — the **screenshot → vision-model** path is BUILT ("what does this say?" / "what's on my screen" → captures the screen, asks a vision model, speaks the answer). The cheaper **AX-tree → text** path (the better long-term one — was #35) is not yet wired as a brain vision source, though the AX-tree reader exists for the dashboard.

**Vision:** when the brain needs to know what's actually on screen (not just running apps/tabs), give it a way to "see" — so it can answer "what does this say?" or act on what's in front of you.

**Two approaches (the second is the better long-term one):**
- **Screenshot → vision model.** Capture is trivial (`screencapture -x /tmp/vox.png`), then send the image to a vision-capable model. *But*: it's **provider-specific** (Anthropic API takes image blocks cleanly; the Claude SDK/subscription path and local LLMs vary), and images are **token-heavy**. Best as an opt-in *fallback* skill via the API vision path, not the default.
- **Accessibility (AX) tree → text.** The macOS analog of the Windows UI-Automation tree (what worked well on OpenFlow): walk `AXUIElement` from the focused app and dump a structured text tree of windows/controls/values. **Token-cheap, structured, and more useful** than a screenshot for *acting* on UI. More work to build (AX traversal, per-app quirks, Accessibility permission), and some apps expose poor trees.

**Where we already are:** `actions.environment_context()` (running apps + open tab titles) is a lightweight slice of this — the brain already gets *some* sight. The AX tree is the rich extension; the screenshot is the visual fallback.

**Recommendation:** AX-tree is the direction that matches the "see through text/structure" idea and stays cheap. Add the screenshot as a small opt-in skill (Anthropic API + a vision model) for the rare "just look at it" case. Both gated behind a config flag; watch token cost on the screenshot path.

**Connects to:** the executor/brains (#12, #17), `environment_context` (built), and the coding-agents research note on per-turn `environment_details`.

> **Update (2026-06-19):** 🚧 QUEUED this session — wire `axtree.snapshot()` (already built
> for the dashboard) as the brain's vision source behind a `screen_vision_mode`
> (`axtree`|`screenshot`|`auto`) flag; test the tree by disabling the screenshot path. See
> `session-2026-06-19.md`.

## 19. Barge-in — interrupt mid-task ("stop it NOW")

**Vision:** say the emergency word (or any speech) and have Vox **stop immediately**, even mid-LLM-call — the "cancel before it acts" the abort phrases can't yet do.

**Why it's not free today:** Vox is **synchronous** — while waiting on the brain it isn't processing the mic, so `abort` is only seen *between* utterances, after the current action finishes.

**How it might work:**
- Keep the mic stream draining on a **background listener thread** during any blocking brain call.
- Run the brain/executor call so its result can be **discarded** if an abort/stop phrase is detected before it lands (Python can't kill a thread cleanly, so let the call finish but skip the action).
- Where possible, cancel the underlying subprocess (claude CLI/SDK).
- Generalises to true **interruption/barge-in** (the voice-agent research pattern): a quick word also stops TTS playback once that exists.

**Connects to:** the emergency-stop phrases (built — `abort_phrases`), the executor (#12), and `research/voice-turn-taking.md` (barge-in / interruption).

**Status:** ✅ BUILT for LLM calls — say "go to sleep" / "stop" / "quit" / "restart" *while the brain is thinking* and it cancels immediately (the call runs on a thread; a stop phrase abandons it). Toggle `barge_in_enabled`. Caveat: the abandoned call finishes in the background, so a quick *action* it was about to run may still complete (slow calls are usually chat/compose/vision, where abandoning is clean). **Spoken-reply interruption (talking over Vox) is now BUILT too** — killable streaming Kokoro TTS (`tts_interruptible`) stops mid-sentence when you speak over it (clean on headphones); native macOS AEC (`audio_aec`, #21) is wired but flagged-off for speaker use.

## 20. Cross-platform (Windows / Linux)

**Vision:** it's open source — others will want it on Windows (and Linux).

**The split:**
- **Easy parts (already near-portable):** STT (faster-whisper) is cross-platform. **TTS**: Windows has built-in **SAPI** (`System.Speech.Synthesis` via PowerShell), and the cross-platform lib **`pyttsx3`** wraps SAPI (Win) / NSSpeechSynthesizer (Mac) / espeak (Linux). `tts.py` is already the swap point, so a `speak()` per-OS is small.
- **The hard part:** `actions.py` is **entirely macOS** — AppleScript + System Events for every command (apps, tabs, windows, Spaces, keystrokes, clipboard, screenshot). A Windows port needs a parallel automation layer: **UI Automation / pywinauto**, `pyautogui`/`keyboard` for keystrokes, `pygetwindow` for windows, PowerShell to launch apps, browser-specific automation, and `PIL.ImageGrab` for the screenshot.

**Approach:** define a platform-agnostic `actions` interface with `actions_macos.py` (current) + `actions_windows.py`, selected at runtime; TTS/STT abstract cleanly already. The architecture (swappable I/O, deterministic-first) is friendly to it — but it's a real effort, mostly re-implementing `actions.py`.

**Connects to:** `tts.py` (the swap point), the modular-components goal in `overview.md`.

## 22. Personalities (swappable + self-tweaking)

> **Status:** ✅ BUILT — choosable presets (Posh Butler, Batman, J.A.R.V.I.S., Surfer, …) + a Default (no-persona) option, picked from the dashboard or by config. Each persona now carries a **fitting voice** (macOS `say` *and* a Kokoro voice). In-dashboard editing is #41 (in progress); LLM self-tweaking is #42 (queued).

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

## 24. Self-heal on error → a learned fix (extends #14–15)

> **Status:** 🚧 **Phases 0–1 BUILT** (2026-07-31) — full framework in
> [`command-learning/`](command-learning/README.md) (8 docs: what earns a command, variant collapse,
> budgets/decay, resolution safety, schema+API, rollout, multi-step actions).
> **Phase 0:** resolution is now deterministic — every match is collected and ranked
> (context → source → match type → phrase specificity → id), and a true ambiguity falls through to
> the LLM instead of guessing. Previously the *first* row scanned won, which with learned rows would
> have been a silent coin-flip. **Phase 1 (shadow mode):** `command_learn.py` observes every
> LLM-resolved action, applies the never-learn gate and promotion bar, and accumulates candidates +
> evidence — **writing no commands**, so behaviour is unchanged. Gates:
> `scripts/command_learning_gate{0,1}.py`. Next: dashboard Candidates view, then a week of shadow
> data before Phase 2 (promotion) is switched on.

When a control command fails the deterministic parser, instead of escalating to *answer* you, a **background** LLM resolves what you meant, **runs it** (so it works that time too), and **saves a learned phrase→action mapping** so the same phrasing fires **instantly and free** afterwards — the "patch". A **"worth patching?"** judgment decides whether the phrase is a durable command (save it) or a one-off (don't pollute the rules). Later — **task 3** — the LLM can edit actual code/config for cases an action-mapping can't fix (guarded + reviewed). The concrete shape of #14–15. **Confirmation:** when it's unsure whether a fix is worth keeping, it can *ask* — "Would you like me to save this as a skill?" — before writing the rule, so the skill set stays clean and you stay in control.

## 25. Scoped task-prompts — a different prompt per command/agent (separation of concerns)

Don't give every task the full system prompt. Each task type gets a **minimal, scoped** prompt with only the rules and powers it needs: "make this pretty" → only the rewrite rules + permission to rewrite; "write me X" → the compose prompt; the self-heal agent → "you are this agent, your job is X, here are your commands, save output here." Cuts context/cost, sharpens behaviour, and **limits each sub-agent's blast radius** to its one job. The top-level agent still does everything; sub-tasks are narrowed. Connects to #10, #12, #17, #24.

## 26. Full control access for the executor + intent recovery (extends #12)

Let the executor also issue the **control verbs** — sleep, restart, quit, stop, switch mode — so the LLM can recover garbled commands and fix its own mistakes (e.g. "gotta go to sleep" mis-heard → it infers *sleep*). Acts when confident; when **uncertain**, asks a spoken yes/no ("Would you like to put Vox to sleep?") and acts on the answer. Pairs with #24 (learning) and #25 (scoped prompts).

## 27. Storage backends — SQLite + human-readable Markdown (transparency)

> **Status:** ✅ partial — **memory is now human-readable Markdown** (tiered: core + dated daily files, readable/navigable in the dashboard). SQLite for the structured stores (rules/usage) is still pending.

Stores are JSON/JSONL under `data/` today. For an open-source **download** (users get the program, not the repo), consider **SQLite** (single file, ships with Python's `sqlite3`, robust + queryable) for structured stores, and **Markdown** for memory so the user can *read and navigate everything the AI saves* — transparency is a first-class goal. Add a configurable data location + optional encryption for sensitive memory; the Memory dashboard tab becomes a browser/editor over it. (OpenClaw leans on SQLite + Markdown — worth studying.)

## 28. Tiered memory + a "dream" consolidation job + a navigable second brain

> **Status:** ✅ partial — **tiered memory is BUILT** (quick-recall core facts always injected + dated daily logs, recalled by relevance). The scheduled big-brain **"dream" consolidation** job (dedupe/roll-up into weekly/monthly) and the navigable second-brain RAG are still to build.

Stop putting all memory into the prompt. Layer it: **quick-recall** (a few always-injected, high-importance facts) · **daily logs** (the agent documents what it did) · a scheduled **"dream"** job (big-brain) that consolidates the logs, dedupes, resolves inconsistencies, and rolls them up into weekly/monthly/total memories · and a **second brain** — index everything into folders the agent *navigates on demand* ("the user is at work — let me check the work folder for their progress") instead of stuffing it all in context. Agentic RAG over a structured, human-readable tree. Builds on #14/#24/#27; the dream job rides the scheduler (#16) on the big brain.

**Fuller design (discussed 2026-06-21) — give memory an explicit framework the big brain owns:**
- **Two cheap raw inputs.** A short **per-chat / session memory** (what happened in *this* conversation) plus the **daily log** — both append-only, human-readable Markdown, written as you go. This is the unstructured intake.
- **The "dream" job *structures*, not just dedupes.** A scheduled big-brain pass (a **cron on the scheduler #16**) reads the raw session/daily memory and **files each fact into a topic folder** — `coding/`, `uni/`, `personal/`, `finances/`, … — rolling related notes together and resolving contradictions. Memory stops being one flat pile and becomes a **navigable tree the user can read folder-by-folder**. (The folder taxonomy can itself be learned/extended by the dream job rather than hard-coded.)
- **Retrieve by *opening the right folder*, not by stuffing context.** On a new request, an **agentic retrieval step decides which folder(s) are relevant and opens only those** ("finances question → read `finances/`"), so the brain is never barraged with everything at once — the key to keeping context tight as memory grows. This is the **LangGraph** fit (see `research/langchain-langgraph.md`): a small graph routing *query → folder-selector → read → answer*, each node with its own scoped prompt (#25). Builds directly on the topic tree the dream job produces.

Connects to #25 (each dream/retrieval step is its own scoped prompt), #16 (the dream cron), #29 (auto-capture feeds the raw intake), #38/#39 (a `coding/` folder feeding the coding brain/agent), #47 (time-aware "today's" daily file).

## 29. Memory auto-capture — remember on its own

> **Status:** ✅ BUILT — the assistant decides to save salient facts itself via a gated `MEMORY[...]` directive (and on "remember that…"), feeding the tiered store; toggle in Settings.

Today memories are added only via the dashboard; the assistant *recalls* (keyword-matched, injected) but never *stores*. Let it **decide to save** salient facts itself (or on "remember that…"), feeding the tiered store (#28). Ties to #14/#24.

## 30. Voice → dashboard control (close the loop)

> **Status:** ✅ partial — the **"close dashboard"** phrase is BUILT (matches "open dashboard"). The broader voice→settings control ("switch to Batman", "set my budget to ten dollars", "turn on debug") is still to wire.

Today it's one-way: dashboard → voice (UI changes affect the daemon on the next call). Add the reverse — change settings/personality/rules/budget **by voice**: "switch to Batman", "add a rule: keep replies short", "set my budget to ten dollars", "turn on debug". Voice commands write to the bridge/stores. Plus a **"close dashboard"** phrase to match "open dashboard" (#6).

## 31. Pluggable voice-model / TTS API

> **Status:** ✅ BUILT — `tts_engine` flag swaps macOS `say` ↔ local **Kokoro** (neural, 54 voices), lazy-loaded with fallback to `say`. `tts.py` is the clean swap point; more engines (Piper, a cloud voice) drop in here.

Abstract TTS behind a small provider API so the voice can be swapped — macOS `say` now, a neural local model (Piper) or a cloud voice API later — without touching the rest (`tts.py` is already the swap point). Pairs with **M2**.

## 32. Barge-in from phone-call agents — borrow the open-source playbook

Open-source phone-call / sales voice agents have already solved real-time interruption + talk-over (they go silent the instant you speak over them). Mine those repos for their VAD / turn-taking / barge-in handling and fold the approach into Vox's barge-in (#19) + AEC (#21). See `research/voice-turn-taking.md`.

## 33. Dashboard "Phrasebook / Help" tab

> **Status:** ✅ BUILT — the **Handbook** tab, generated from the live phrase config so it never drifts (document layout, accordions, variant popovers).

A reference tab in the dashboard listing every wake phrase, command, mode, and feature — a living help book generated from the actual phrase config so it never drifts.

## 34. "Speak when done" MCP for the coding agent (the concrete #3)

An MCP server that lets the coding agent (Claude Code) speak through the system TTS, so while you work it can announce "workflow finished" / "tests passed" out loud — "give me a shout when you're done." The concrete form of #3.

## 35. Vision as structure-as-text — the AX/DOM-tree path (of #18)

> **⚠️ Duplicate → merged into #18.** Same idea: prefer the **accessibility/DOM tree as text** (cheap, structured, token-light) over screenshots, reusing the **AX-tree reader already built for the dashboard** as the brain's vision source — screenshot stays the fallback. Tracked under #18; this entry is kept only so existing "#35" references resolve.

## 36. Context-aware command profiles — commands that change with the active app/site

> **Status:** 🚧 QUEUED this session (`session-2026-06-19.md`). Two slices: (a) the cheap
> unlock — add the **focused app + active tab (title *and* URL/domain)** to
> `environment_context()` (today it lists running apps only, never the focused one), which
> also fixes Arc tab matching; (b) the deeper **per-app command profiles** (scoped through
> the rules store), likely a later session.

The same phrase should mean different things depending on what's focused. "Search for X" → searches **YouTube** when it's open, the web otherwise; with **Cursor** focused, unlock Cursor-specific verbs ("new terminal", "type in the terminal", "open file"). Per-app / per-site command sets let you **reuse phrases for different purposes** and cut ambiguity — the router picks the profile from the focused app/tab (already surfaced by `actions.environment_context()`). Near-term win on the same theme: tab-switching by name is unreliable when a tab's *title* is generic (a Google Doc shows as "Untitled" / "unknown doc"), so neither the fuzzy matcher nor the brain can tie "open Google Docs" to it — enrich the context with each tab's **URL/domain** (`docs.google.com`) and the match (deterministic, or learned via #24) becomes solid. Pairs with scoped prompts (#25), the learning layer (#24), and AX-tree handles (#35).

**→ Storage design (SQLite):** [`command-db.md`](command-db.md) — the `context`/`command`/`phrase`/`intent` schema (FKs, sample Arc data, runtime resolution flow) that holds per-app command sets. On the SQLite direction from #27; sets up learning (#14). *Schema is in review — no code yet.*

> **Set-of-marks BUILT for native apps (2026-07-31)** — the click path now escalates to vision when
> labels fail. Diagnosed from a real failure ("click Alex's second last message"): the brain was
> handed 60 labels that were **entirely Slack's chrome** — sidebar, channels, toolbar, not one
> message — so it picked the closest thing it could see (the DM sidebar row) and asked "Did you mean
> Alex Fairbairn?". Two causes, both fixed: (a) `clickable_targets()` read `ax.targets()`, which
> lists elements with **no on-screen frame** — on Slack **177 of its 190 labels were invisible menu
> entries** from closed menus — and capped at 60, spent depth-first, never reaching the message list;
> it now reads the frame-filtered `targets_with_frames` at 300, so the brain only ever sees what is
> actually on screen, and sees the same set the overlay badges. (b) New `overlay.annotate()` draws
> #52's numbered badges **onto a screenshot** in-memory (no on-screen flash, and it sidesteps the
> overlay window being `NSWindowSharingNone` — screenshots can't see it), and `executor._click_by_vision`
> asks the big brain for a badge number, then clicks that element via its real AX frame. The model
> only picks a number, never estimates pixels, so the target stays an exact element. This is what
> makes "the second last message" / "the one at 7:52pm" expressible at all — order and position
> aren't in a text list. Gated by `click_vision_fallback` (default on), only on the give-up path.

## 37. Real website control — simplified DOM + expand-on-demand + screenshot grid

Interacting with web pages needs more than the macOS a11y tree. The mature web-agent stack: (1) **simplify the DOM** to a compact list of interactive/labelled elements (or HTML→Markdown for reading) — raw HTML is far too much context; (2) a **progressive-disclosure tool** so the model can *expand* a specific region only when it needs the detail; (3) **screenshot + numbered marks** ("set-of-marks": overlay numbered boxes on clickable elements, the model picks a number) as visual grounding / fallback. Combine: simplified-DOM/a11y as the cheap primary, the expand-tool for depth, the screenshot-grid for visual cases. Needs browser automation (CDP / the browser's own a11y / an extension) beyond System Events. Builds on #35; connects to in-browser tab/profile control (#4) and the learned-click macros of #24/#35.

## 38. A third "coding" brain — hand coding tasks off to a code model

Beyond **small** (fast/cheap) and **big** (deep) brains, add a **coding** brain: when a request is a coding task, hand it to a code-specialised model/agent (e.g. Claude Code or a local code model) instead of the general brain. Extends the brains layer (#17); pairs with the coding/handoff mode (#2).

## 39. Multiple named agents (late-stage)

Call different agents by **name** — "Hey Atlas" for a coding work-session agent, "Hey Vox" for the general one — each with its **own voice, persona, brain, and command set**, so the *name itself routes* to a different agent. Builds on the wake phrases, personalities (#22), scoped prompts (#25), and the coding brain (#38). A fun, late-stage feature.

**→ Full design:** [`named-agents.md`](named-agents.md) — talk to your Claude CLIs by name (David/Greg), no-focus-steal injection (tmux/iTerm), self-registering agents, the steer/reply conversation model, headless-vs-interactive explained, and staging. Related: #3, #34, #49.

## 40. Learn your name (setup / personalization)

Give Vox your name — via a first-run **setup/onboarding** flow, or on the fly ("my name is Dan") — so it addresses you naturally and stores it as a core memory. Small but high-warmth; connects to memory auto-capture (#29), the second brain (#28), and personalising recognition (#8).

## 41. Expand & edit personalities (in the dashboard)

> **Status:** ✅ BUILT — `update_custom` + `PATCH /api/personalities/custom/{id}` (presets read-only) + a dashboard **edit** dialog (all fields incl. both voices) and a read-only **full-text view** (eye icon) for any persona. LLM self-editing is still #42.

View a persona's full text and edit it in place — expand each card to read the whole prompt, then tweak name/emoji/voice/persona and save. Needs an `update_custom` in `personalities.py` + a `PATCH /api/personalities/{id}` route + an expand/edit UI on the Personalities page. Pairs with the new Default (no-persona) option and #42. **Queued to build right after the in-flight Handbook/Default-persona workflow** (shares those files).

## 42. Let the LLM edit its own persona on request

When you tell Vox "I don't like that you do X in this character — do Y instead," it updates the **active** persona going forward (not just this turn). Mirrors the memory auto-capture pattern: a gated `PERSONA[update]: <change>` directive the model appends, which is parsed, applied to the active personality (append/merge the instruction), and stripped from the reply. Gated by a toggle; only edits **custom** personas (presets stay pristine — fork-on-edit). Builds on #22/#41 + the `MEMORY[...]` directive (#29). **Queued next.**

## 43. Live conversation viewer (dashboard tab)

> **Status:** 🚧 QUEUED this session (`session-2026-06-19.md`) — mirror the `usage.py`
> WS pub/sub: an in-RAM ring buffer + `/api/conversation/stream`, rendered on a new
> Conversation page. Ephemeral, nothing to disk.

A dashboard tab that shows the running conversation like a chat — what you said, what each brain replied, and which commands ran — so you can watch what's happening. **Ephemeral by design:** the daemon publishes each turn to the bridge (the same way it already streams usage events over the WS), the page renders them live, and **nothing is written to disk** — it's just the in-RAM session buffer mirrored to the UI. Pairs with the prompt/response debug logging (#just-built); the persistent layer stays the tiered memory (#28/#29).

## 44. Mishear-frequency counter → context-inferred self-heal (extends #24)

A lightweight **failure counter** that watches for phrases which keep *failing to match*. When the same unrecognised / misheard utterance trips the parser **more than N times** (say 3), it fires the self-heal — but instead of guessing from the bad transcript alone, it looks at the **commands and phrases said around those failures** to infer what was actually meant. Example: "go to sleep" keeps coming through as "going to go to sleep" and never matches; the surrounding context (what you tried next, what finally worked) makes it clear you were trying to sleep, so it **patches the mapping** (mishear → intended command) and the phrase fires correctly from then on.

**Why it's nice:**
- **No permanent storage required** — an **ephemeral, in-RAM tally** is enough to *detect* a recurring mishear; only the resolved patch (if judged worth keeping, per #24's "worth patching?" check) needs to persist.
- **Threshold-gated** (> N occurrences) so a one-off slip never pollutes the rules.
- **Context-window inference** — examining the *neighbouring* utterances (the retries, the eventual success) is cheaper and more reliable than recovering intent from a single garbled transcript.

**Connects to:** #24 (self-heal → learned fix — this is the *trigger* that decides when to invoke it), #8 (learned-corrections table, "casa → cursor"), #14–15 (self-wiring learning / background wiring), and #9 (command-vs-conversation). Best built **after** the self-heal system (#24) lands.

## 45. Learn the user's writing style → compose "in your voice" (extends #10)

While dictation/typing is active (between **"start typing"** and **"stop typing"**), **capture what's typed** as a rolling corpus of the user's own writing. Once it crosses a size threshold, hand it to the **big brain** to analyse — extract the user's **style patterns** (tone, sentence length, vocabulary, punctuation/formatting habits, greetings & sign-offs, formality) and distil them into a compact **style profile** (a few injectable rules). Then whenever the user says **"write this"** (#10 compose), inject that profile so the generated email / message / summary reads like *they* wrote it.

**Key points:**
- **Prose only, not code.** Code is right-or-wrong and its style is largely objective; this is for *natural-language* writing. Gate by task type (compose-prose vs code) so it never skews generated code.
- **Grounded, not guessed** — the corpus is the user's *actual* writing, so the learned voice is real, and it sharpens as more accumulates (periodic re-analysis).
- Keep the **distilled profile** (small, injected into the compose prompt) separate from the **raw corpus** (bulkier, just the training material) — and it needn't be heavyweight: even an ephemeral rolling buffer that's analysed and discarded works.

**Self-improving prompts over time (discussed 2026-06-21):** treat the compose prompt as **living**, not fixed. The style profile is **re-tuned** as more of the user's writing accumulates (periodic re-analysis) and, optionally, from explicit feedback ("no — shorter / more casual"). The scoped **"write this"** prompt (#25) carries the current profile, so it gets *better at sounding like you the more you use it*. The mechanism **generalises beyond writing style**: any scoped prompt (#25) can keep a small, evolving "what works for this user" addendum that a background pass refines — the assistant slowly tunes its own prompts to the user rather than shipping one static prompt forever.

**Connects to:** #10 (compose — the consumer of the style profile), #8 (personalisation over time), #2 (literal-dictation vs AI-compose handoff), #25 (scoped prompts — the compose prompt carries the style rules *and* is the thing that self-tunes), and #27/#28 (where the corpus/profile would live).

## 46. Teaching / demonstration mode — show Vox the exact steps (high-stakes tasks)

**Vision:** for software where a wrong click is **costly** (a financial accountant's
ledger, a trading tool, a deploy console), don't let the AX-tree + LLM *infer* the steps and
risk a mistake. Instead, let the user **demonstrate** the task once and have Vox replay it
**deterministically**. *"Start the training"* → Vox **watches and records what you click**
(and type) → *"this is what you do whenever I ask you to do `<task>`"* → it saves the captured
sequence as a **named, replayable macro** bound to that trigger phrase. Next time you ask, it
runs the **recorded steps**, not a guess.

**The in-between (human-in-the-loop) variant:** for steps that are risky but not fully
scripted, say *"be careful when you do this"* → before each action Vox shows a **confirmation
overlay** — a glowing circle/highlight over the element it's about to click: *"click here?"* —
and only acts on your **yes**. Demonstration removes the guesswork; the overlay keeps a human
in the loop where it matters.

**How it might work:**
- **Record:** capture each interaction as a **stable element handle** (AX role + title +
  identifier + app/window, with bounds as a fallback) rather than raw screen coordinates, so
  replay survives window moves/resizes. The AX-tree reader (#18/#35) already produces these
  handles for the dashboard — reuse it as the recorder's source of truth.
- **Store:** the macro = an ordered list of `(action, element-handle, value?)` steps under a
  trigger phrase, persisted as a learned skill (ties to the rules/learning store #14/#24).
- **Replay:** resolve each handle in the *current* AX tree and act (AX press / set value /
  keystroke); if a handle can't be resolved, **stop and ask** rather than clicking blind.
- **Overlay:** a small always-on-top highlight window over the target element's bounds (the
  same overlay surface as the status pet #7) with a yes/no (voice or click) gate.

**Why it matters:** it's **deterministic, demonstrated automation** — the trustworthy path
for tasks where "the AI figured it out" isn't good enough. The recorded macro is also a
perfect training signal for the learning layer.

**Connects to:** #18/#35/#37 (AX/DOM element handles — the recorder & replayer), #14/#24/#25
(learned skills, scoped prompts, "worth keeping?"), #36 (per-app — macros are naturally
app-scoped), #7 (the overlay/glowing-circle surface), #19 (barge-in to abort a replay).

## 47. Give the AI time awareness — current date, time, day & timezone

**Vision:** inject the **current date, time, day-of-week, and timezone** into the brain's
context so it can reason about *now* — answer "what's today?", handle "remind me **tomorrow**
at 9", and time-aware phrasing ("good evening") — instead of being time-blind.

**How it might work:** a tiny addition to the system prompt / `environment_context()` —
`Now: Thu 2026-06-19 14:32 (Europe/London, BST)` — refreshed per turn. Trivial and cheap.

**Why it's more than cosmetic:** the **scheduler (#16)** needs a concrete "now" to turn "in
20 minutes" / "tomorrow at 9" / "every weekday" into real fire-times — so this is a
near-term **prerequisite** for natural reminder/alarm parsing, not just a nicety. Small enough
to fold in alongside the active-app context work (session-2026-06-19 slice 2a).

**Connects to:** #16 (scheduler time-parsing — the main consumer), `environment_context`
(where it rides), #40 (greet you by name + time).

## 48. Meeting recording & notes

**Vision:** "start recording the meeting" / "take notes" → Vox records the conversation, then
produces a **transcript + summary + action items** you can read back, search, and act on. The
hands-free, local-first take on Otter/Granola.

**How it might work (mostly built blocks already):**
- **Capture:** record mic (+ ideally system/other-party audio) to a wav while a session runs.
  The **AEC/VoiceProcessingIO** path (now working) gives a cleaner mic; capturing the *other*
  side (Zoom/Meet output) needs system-audio capture (an aggregate device / ScreenCaptureKit
  audio) — the one new piece.
- **Transcribe:** local **Whisper** (already in-house, no API) over the recording, chunked.
- **Notes:** hand the transcript to the **big brain** → structured summary, decisions, and
  **action items** — action items can auto-create **reminders** (#16) ("follow up with Sam
  Friday").
- **Store & view:** save transcript + notes as **Markdown** in the tiered memory (#27/#28),
  browsable in a dashboard **Meetings** tab; nothing leaves the machine unless asked.

**Why it fits Vox:** local STT + brains + TTS + memory + scheduler already exist — this mostly
*composes* them. Voice-triggered start/stop, spoken summary on request ("what were the action
items?").

**Connects to:** Whisper STT, the brains (#17), memory (#27/#28/#29), scheduler (#16, action
items → reminders), AEC (#21, clean capture), and the conversation viewer (#43, same "show a
session" surface). The genuinely new work is **system-audio capture** of the far end.

## 49. MCP as a two-way bridge to Vox's powers (extends #3/#34)

The vox-speak MCP (#34) only does **output** (TTS). But the MCP server can `import vox.*`, so it can expose **everything Vox already does** to the IDE assistant (Claude Code / Cursor) as tools — turning a one-way "speak when done" into a real bridge between the keyboard-assistant and the voice-assistant. Each tool is a thin wrapper over an existing module:

- **Shared memory** — `remember(fact, tier)` / `recall(query)` over `vox.memory.add`/`.recall`, so a fact Claude learns while coding is something **Vox knows by voice later** (and vice versa): one brain across both assistants. **(user-flagged priority; pure reuse, no mic.)** Ties to #27/#28/#29.
- **Scheduled spoken reminders** — `remind(text, when)` / `set_timer(mins)` over `vox.scheduler.parse_and_create`/`create_job`; the running daemon's scheduler **speaks it out loud** later, even after the IDE is closed. **(user-flagged priority; pure reuse.)** Ties to #16.
- **Two-way voice** — `ask(question) -> spoken answer`: Vox speaks the question and captures the reply via Whisper, so Claude can ask "force-push?" hands-free. Catch: the daemon **owns the mic** (single-instance guard), so the clean design routes the question through a small **web-bridge endpoint** to the running daemon (which already has speak+listen) rather than the MCP grabbing the mic itself. The flagship; biggest build.
- **Voice approval gate** — `confirm(prompt) -> bool`: a spoken yes/no before destructive steps. A subset of two-way voice (same mic-routing).
- **Mac control passthrough** — `do(command)` over `vox.actions.handle` ("open dashboard", "switch to Arc", "go to GitHub"); GUI things Bash can't easily do (Arc tab reuse, Space/window switching). Overlaps Bash → medium value.
- **Screen vision** — `look_at_screen(question)` over `actions.capture_screen` / the AX tree (#18/#35), so Claude can "see" another window ("what's the error in the browser?").
- **Desktop notification** — `notify(title, msg)` (osascript banner) to complement speak when muted/away.

**Start with memory + reminders** (both ~20 lines, no mic constraint); scope the web-bridge endpoint *before* committing to the two-way-voice tools. Connects to #3, #34, #16, #28, #18.

## 50. Clarifying follow-up questions — ask instead of failing (Alexa-style)

**Vision:** when a command is *almost* actionable but missing or ambiguous on one detail, **ask one short spoken follow-up** and use the answer to complete it — instead of giving up with a flat error. Like Alexa: "set an alarm for 3 o'clock" → *"Morning or afternoon?"* → "afternoon" → done.

**Why it matters:** a near-miss should degrade to a quick question, not a dead end. Real example (`issues.md` O10): "remind me at 3:30 PM **that** I have a meeting" failed entirely — but even genuine gaps (a bare "3 o'clock" with no AM/PM, "remind me in a bit" with no duration) should prompt a one-line clarification rather than "I couldn't work out a time."

**How it might work:**
- The plumbing **already exists** — the executor carries a `pending` clarification history and can emit `CHAT: <question>`; control mode already loops the next answer back in with context (`loop._control_mode`'s `pending`). The deterministic scheduler path just doesn't use it: on a `None` from `parse_and_create` it returns a fixed failure string instead of asking.
- Cheapest slice: **hard-code** the common ambiguities (AM/PM, missing duration/time) → ask a templated question, then re-parse with the answer merged in. No LLM needed.
- General slice: when the deterministic parse misses, hand the brain the utterance + "what single detail is missing?" and let it ask via `CHAT:`, then resolve on the reply. Ties to the LLM-executor (#12) and intent recovery (#26).

**Connects to:** the scheduler (#16), the executor + intent recovery (#12/#26), and the command DB (a "needs clarification" outcome could be a first-class command result).

## 51. In-dashboard workspace board (Trello-like, agent-readable/writable)

> **Status:** ✅ BUILT v1 (2026-07-15/16). SQLite `board_store` (board → list → card, CRUD + search, seeds a "Workspace" board with To Do / Doing / Done) + FastAPI routes (`/api/board*`) + a **Board** dashboard page (columns, add cards per column, move via ◄►, delete, add lists, live 4s refresh). Decided **build-our-own over integrating `kanbn/kan`** (AGPL + Postgres + heavy). NEXT: agent-facing tools (`board_add_card`/`board_search`) so the brain reads/writes it mid-conversation (the knowledge-base half), plus real drag-and-drop.

**Vision:** a home-grown, Trello-like kanban board built into the dashboard — lists and cards — that doubles as an **agent-accessible knowledge base**. It's a shared surface: the agent can reference it in conversation and **add, move, read, and search** cards directly via tools, not just a human-facing UI. Use it both to plan Vox itself and as a durable place the agent stashes/retrieves structured notes.

**Why it matters:** a persistent, agent-referenceable place for planning *and* knowledge, without depending on an external SaaS — fits the self-contained storage direction (#27, SQLite/Markdown) over third-party services.

**Build vs integrate — evaluated 2026-07-15 → BUILD OUR OWN.** We looked at [`kanbn/kan`](https://github.com/kanbn/kan) (an open-source Trello alternative). It's a full **Next.js + PostgreSQL + tRPC + Better-Auth + S3/Redis** self-hosted web app under **AGPLv3**. Three reasons to build our own rather than integrate it:
1. **License:** AGPLv3 is viral copyleft — bundling it into our downloadable open-source distro drags licensing obligations across the whole project. Our own board stays clean under our license.
2. **Weight:** kan needs Node 18 + Postgres + Docker + SMTP + S3 — a huge dependency footprint for a single-user local app on a disk-constrained machine, vs our zero-dep SQLite.
3. **Agent-native fit:** the whole point is fast, direct agent read/write. Our Python daemon touches SQLite in-process; kan forces an HTTP/tRPC hop to a separate service. (kan *does* ship an MCP server, but that's still an external process to run + maintain.)
→ We *reference* kan's data model (boards → lists → cards → labels/checklist/comments) but implement lean.

**Shape:**
- **Storage:** a `board`/`list`/`card` schema in SQLite (same pattern as `command-db.md`); optional Markdown mirror for transparency (#27).
- **API:** FastAPI endpoints under the web bridge (list / create / move / update / search cards).
- **Agent tools:** `board_add_card`, `board_move_card`, `board_search`, `board_read` so the brain uses it mid-conversation.
- **UI:** one React page in the dashboard (drag between columns).

**Connects to:** #27 (SQLite/Markdown storage direction), `command-db.md` (SQLite schema precedent), #43 (live conversation viewer), #49 (MCP two-way bridge — could expose the board over MCP later).

## 52. "Click link / click button" — numbered overlay on every clickable element (Dragon-style)

> **Status:** ✅ BUILT (2026-07-16). "show clickable" / "click link" / "click button" draws a numbered blue badge on every clickable element (incl. **text boxes** — Slack compose, search fields); say the number ("click 14" / "14") to click it; any other phrase / "hide clickable" dismisses. Clicks are **coordinate-based** (`ax._click_at` via CGEvent) — reliable on web/Electron where `AXPress` silently no-ops; this also fixed the by-label path (direct + AI-escalated "click X"). The overlay runs in a **separate helper process** (`overlay.py`) so AppKit can't freeze the daemon, is `NSWindowSharingNone` (won't trip screen-capture/DRM), and **spans all displays** (Sidecar / second screens — one window per display). **Fixed 2026-07-28 — "the badges all pile up in the top-left":** not a coordinate bug (window placement, AX→Cocoa flip and AX frames all verified correct against pixels). `targets_with_frames` capped at **80** elements and the walk is depth-first, so on a big app the cap drained into whichever subtree came first — the left sidebar. On Cursor that was 69 of 80 badges on the left half with the entire editor unbadged; Slack's channel list did the same. The full walk is cheap (~70 ms for ~140 elements), so the cap is now **200** and badges cover the whole UI. Knock-on: past 99 the number no longer fit the badge ("100" drew as "10"), so `_make_badge` drops to 9pt at 3 digits (shrink the text, not the box — 3-digit numbers only appear on dense screens, where a wider badge would cover its neighbours). **Second cause, fixed 2026-07-31 — the badges came BACK to the top-left intermittently:** log analysis showed the same app returning wildly different counts (Slack **8 / 13 /** 80 / 132 / 227; Cursor **13 /** 107). The low numbers are the native window chrome alone — which lives in the top-left — because Chromium/Electron builds its web-content AX tree on demand and **tears it back down**, while `ax._enabled_pids` asserted `AXManualAccessibility` only *once per pid, forever*. That's also why killing and restarting the daemon "fixed" it: a fresh process re-asserts. `targets_with_frames` now keeps the best count seen per pid and, when a walk comes back below both 20 elements and half that baseline, re-asserts the flag and re-walks once (~0.4 s settle, only on the degraded path; a healthy walk never retries). Cap also raised 200 → 400 after measuring a busy Slack at 227. NEXT (the learning loop, below): when "click X" can't find it → auto-show the overlay → pick a number → **save the phrase→element to the command DB** so next time it resolves directly (ties #14/#24/#36).

**Vision:** say **"click link"** / **"click button"** / **"show clickable"** and Vox overlays a **numbered badge on every clickable element on screen**; say **"click 14"** (or just "14") and it presses element 14 — exactly the Dragon NaturallySpeaking flow. Doubles as a **debugging/visibility tool**: you see precisely what Vox's accessibility tree exposes and where.

**Why it matters:** (1) clicking by number is faster and far more reliable than clicking by label when labels are ambiguous, missing, or mis-heard; (2) it makes the AX tree *visible* so we can debug why a control isn't clickable. Dragon does this with vision/OCR; **we can do it better with the native AX tree** — exact element identity + frame, no image analysis.

**How it might work:**
- We already enumerate clickable elements natively (`vox/ax.py` `targets()` + `click()`). Extend the AX reader to also return each element's **screen frame** (`AXPosition` + `AXSize` via `AXValueGetValue`) — a small addition.
- Draw a **transparent, click-through, always-on-top overlay** (PyObjC borderless `NSWindow`) with a numbered badge at each element's rect. On "click N", AXPress the stored element; "hide" / "cancel" / "escape" dismisses.
- Voice: add `show_clickable` + `click_number` intents; a lightweight overlay mode in the loop.

**Relation to existing ideas:** #35 (AX-as-structure), #37 (set-of-marks / numbered marks — that entry is the *web/DOM* version; this is the *native macOS* version), #18 (screenshot vs AX). For elements AX doesn't expose (some web content), fall back to the #37 DOM/screenshot-grid path. Because it's AX-based (stable identity), the same overlay could later feed *recorded* actions (#46) with reproducible targets — unlike vision-labeled coordinates.

## 53. Pluggable + streaming STT recognizers (Vosk grammar commands · streaming partials · typed-arg grammar)

> **Status:** ✅ **grammar-command fast lane BUILT** (2026-07-16, gated off). `vosk` dep + `src/vox/stt/vosk_recognizer.py` (grammar from the command DB's `command_cache.active_phrases`, `[unk]`-stripping, recognizer cached per grammar, C++ stderr suppressed) + `core/loop._recognize` two-lane wiring in CONTROL mode + `[vosk]` logging. Verified: ~4–7 ms after warmup, mis-hears snap to the nearest command ("necks tab"→"next tab"), out-of-vocab words (chatgpt/figma) skip gracefully → Whisper. Gated by `vosk_commands_enabled` (default OFF). **Model:** alphacephei.com's TLS cert is expired, so auto-download is broken — user downloaded the official small model to `~/.cache/vox/vosk/` (auto-found). **Streaming partials** + **typed-arg grammar** (the other two levers) still to build. Full research: [`research/dictation-stt-tools.md`](research/dictation-stt-tools.md).

**Vision:** formalize STT behind a recognizer interface and add a **Vosk** backend alongside faster-whisper to unlock three levers documented in [`research/dictation-stt-tools.md`](research/dictation-stt-tools.md):
1. **Grammar-constrained command recognition** — compile the command-DB's active phrases into a Vosk JSON grammar so spoken commands snap to an exact command (or `[unk]`) with no Whisper+LLM round-trip. Highest ROI; reuses the command-DB we already built (#36).
2. **Streaming partial transcripts** — Vosk emits live partials per audio chunk → live captions + a self-correcting loop (show Vosk instantly, replace with Whisper-final). Feeds the live conversation viewer (#43).
3. **Typed-argument command grammar** — adopt Utterly Voice's arg model (no-arg / trailing-arg / optional-with-default / rest-of-utterance) to let users define *parameterised* commands as data (the half the command-DB deliberately left in the code parser).

**Why it matters:** faster, more reliable command recognition; real-time dictation UX; and user-defined parameterised commands — all local, all additive, all gated.

**Foundation:** extend `stt/base.py` (today batch-only `transcribe()`) to a streaming interface + a backend registry. Keep faster-whisper the default. Caveats: Vosk grammar mode needs the small "lookahead" models; some Vosk models are AGPL/CC (license-audit before bundling).

**Connects to:** #31 (pluggable voice-model/API), #36 (command-db), #43 (live viewer), #54 (custom vocabulary — same recognizer foundation). Full mapping + sequencing in [`research/dictation-stt-tools.md`](research/dictation-stt-tools.md).

## 54. Custom vocabulary / "learn a word" — fix homophones like clawed → Claude (Dragon vocabulary)

> **Status:** ✅ BUILT (2026-07-16) — the **replacement-dictionary** slice. `src/vox/vocab.py` applies a user map ("when you hear X, write Y") to Whisper's output right after STT (`whisper_transcriber`) — whole-word, case-insensitive, longest-match-wins, guarded. Managed on a new **Dictionary** dashboard page (add / toggle / delete; re-adding a word updates it); stored in `data/vocab.json` (gitignored), applied live (no restart after the first). Hotword biasing already exists; the optional **cloud-STT keyword-boost** backend (Deepgram/AssemblyAI) is the remaining, ties into #53.

**Problem:** Whisper mis-transcribes specific words / proper nouns — e.g. "Claude" ↔ "clawed" ↔ "cloud" — and there's no way today to *teach* it the right spelling. Dragon lets you add a word to a personal vocabulary; we don't have that.

**What's possible with our current faster-whisper:**
- We already pass **`hotwords`** (soft bias toward expected vocabulary); `initial_prompt` is a similar lever. **But these only bias — they won't reliably win a homophone**, and no acoustic model consistently disambiguates clawed/Claude/cloud from sound alone.
- **You can't "train" Whisper on a new word** without fine-tuning (heavy). Hotwords/initial_prompt is the only in-model knob, and it's weak.

**The reliable local fix — a user-editable replacement dictionary (recommended cheap win):**
- A deterministic **post-ASR substitution map**: "when the transcript contains X, write Y" (e.g. `clawed`→`Claude`, `claude code`→`Claude Code`, plus user-defined rules). Instant, local, 100% reliable — exactly what Dragon vocabulary / WhisperTyping "text replacements" do for spelling. Applies to both dictation and command text.
- Editable in the dashboard; stored in SQLite/Markdown (#27). This is the pragmatic "learn a word" and is worth building regardless of engine.

**The stronger option — a cloud-STT API behind the recognizer interface (#53):**
- Cloud engines with real **keyword boosting** (Deepgram `keyterm`/`keywords`, AssemblyAI `word_boost`, Soniox, …) handle custom vocabulary far better than Whisper hotwords. Offer them as an **optional** backend (privacy/cost tradeoff) via the pluggable recognizer interface (#53) — max accuracy on names/jargon for those who opt in, while local Whisper stays the default. This answers "should we have an API option too?" → yes, as an option, not a replacement.

**Connects to:** #53 (recognizer interface = the foundation for the API option), #31 (pluggable voice/API), #8 (personalises over time — the replacement map is the explicit, deterministic complement to #8's implicit learning), #10 (compose — same cleanup surface).

## 55. MemPalace — local-first semantic memory backend (evaluate adopting)

**What:** [`MemPalace/mempalace`](https://github.com/MemPalace/mempalace) — an **MIT-licensed**, local-first Python memory library for AI apps. Stores verbatim conversation history for semantic search; **ChromaDB** vector store (default; pluggable SQLite/Qdrant/pgvector/Milvus) + a **temporal entity-relationship knowledge graph** on local SQLite. "Palace" hierarchy: people/projects = *wings*, topics = *rooms*, content = *drawers*. Ships a Python API, a CLI (`mine` / `search` / `wake-up`), an **MCP server (36 tools)**, and auto-save hooks for Claude Code / Cursor. Local embeddings (`all-MiniLM-L6-v2` ~30 MB English, or `embedding-gemma-300m` ~300 MB multilingual). No external services required.

**Why it matters for Vox:** a ready-made, permissively-licensed answer to much of our memory roadmap — the **navigable second-brain RAG + tiered/consolidated memory (#28)**, semantic recall over past conversations, and the local/human-readable storage direction (#27). **MIT** means we can embed it directly (contrast kan's AGPL, #51). It could back or augment today's Markdown tiered memory (`memory.py`) with real semantic search instead of relevance heuristics.

**How it might work:** embed as a Python dependency, or run its MCP server and reach it via the #49 MCP bridge. Vox writes each turn/memory into a palace wing; recall does a semantic `search` at turn start alongside/instead of today's injection. Evaluate: (1) does semantic recall beat our current tiered-Markdown recall in practice; (2) the ChromaDB + embedding-model **disk/RAM cost** (~30–300 MB) against the disk-constrained target machine; (3) embed the library vs the MCP-server route.

**Connects to:** #27 (local storage), #28 (tiered memory + dream consolidation + second-brain RAG), #29 (auto-capture), #49 (MCP two-way bridge). Also a candidate backend behind the board's knowledge-base role (#51).

## 56. "No, that's wrong" — self-correcting clicks + a memory of what just ran

> **Status:** 📋 QUEUED — the actionable task **after** the command system (#24 / `command-learning/`).
> Much of the plumbing landed with command-learning Phase 1, so this is mostly wiring, not new
> machinery.

**Vision:** Vox clicks the wrong thing. You say **"no, that's wrong"** — and instead of shrugging, it
(a) knows *exactly what it just clicked*, (b) undoes/re-picks on the spot, and (c) **remembers the
miss**, so next time that phrase comes up it either avoids the thing it got wrong or asks "did you
mean this one or that one?" rather than confidently repeating the mistake.

**Three parts:**

1. **The correction turn.** A negative signal right after a click is already detected —
   `command_learn.check_negative()` (Phase 1) catches "no" / "wrong" / "undo" / a re-said phrase and
   walks the candidate back. What's missing is the *recovery*: on a correction, re-open the click with
   the failed target **excluded**, and go straight to the next-best candidate (or the numbered
   overlay / vision tier) instead of starting from scratch.
2. **A negative memory.** Today a correction only decrements a candidate. It should record the
   **anti-mapping** — "phrase X in app Y is NOT element Z" — so the resolver actively demotes that
   element for that phrase, and the pick prompt can tell the brain "you chose Z before and the user
   said no". Cheap to store: `command_log` already keeps `heard_phrase` + `command_id` + `negated`.
3. **"What did you just do?" / recent-command recall.** A voice command (and an agent-readable tool)
   that reads back the last N resolutions: what was heard, what ran, whether it worked, whether it was
   corrected. Feeds the brain's own context so it's more careful before repeating an action, and gives
   you a way to ask "why did you do that?" — the audit surface the learning system needs anyway.

**Plausibility: high, and cheaper than it looks.** `command_log` (built 2026-07-31) already records
every resolution with `heard_phrase`, `resolved_by`, `success` and `negated` — so part 3 is a query
plus a phrase, and part 2 is a column's worth of reading. Part 1 is the only real logic. The pieces
that would have been expensive — detecting the correction, having a stable element identity to point
at — are done.

**Connects to:** #24 (this *is* the self-heal loop's negative half), #44 (mishear-frequency counter),
#50 (clarifying questions — "which one did you mean?"), #14/#36, and `command-learning/01-promotion.md`
(negative signals already gate promotion).

## 57. Third-tier click escalation — grid overlay + coordinate clicking

> **Status:** 📋 QUEUED — pairs with #56. Completes the escalation ladder started in #52/#37.

**Vision:** a **third tier** for clicking, after the two that now exist:

| Tier | How it picks | Built |
|---|---|---|
| 1 | AX tree, by label | ✅ `actions.click_element` → `_click_fuzzy` |
| 2 | AX tree, by **numbered marks on a screenshot** (big brain picks a badge) | ✅ 2026-07-31 (#37 note) |
| 3 | **Screenshot + coordinate grid** — no AX element required | 📋 this idea |

Overlay a labelled grid (A1…N12, or numbered cells) on the screenshot, let the vision brain name the
cell — optionally refining with a second, zoomed pass on that cell — and click the resulting point
with `ax._click_at()`, which already synthesizes a real CGEvent click at any screen coordinate.

**Why it's genuinely needed:** tiers 1 and 2 can only ever reach things the accessibility tree
exposes. Canvas/WebGL content, custom-drawn controls, images without labels, video scrubbers, apps
with poor AX support — none of them have an element to badge, so no amount of improving the AX path
reaches them. Tier 3 is the only one that can click something Vox cannot *name*.

**One correction to the original hunch:** the motivating theory was that AX hides elements until the
mouse hovers them. That doesn't hold for Slack at least — our enumeration returned its hover-only
message actions (`React with white_check_mark`, `Reply in thread`, `Forward message…`, `Save for
later`) with no pointer anywhere near them. So hover-reveal isn't the gap; **AX-invisible content
is**. Same conclusion, better reason — and worth knowing, because if hover *were* the problem the fix
would be to move the mouse first, which is much cheaper than a grid.

**Design notes:**
- **Accuracy is the whole risk.** Vision models are poor at precise pixel coordinates; a grid turns a
  regression problem into a classification one ("which cell"), and a zoom-refine pass turns a coarse
  cell into a precise point. Worth measuring cell-hit accuracy before trusting it.
- **Coordinate clicks can't be verified.** Tiers 1–2 click a known element and can report what it was;
  tier 3 clicks a *point* and has no idea what it hit. So it should be last-resort, announced ("I'll
  click here — say no if that's wrong"), and paired with #56's correction loop.
- **Never learn a coordinate.** Pixels aren't a stable identity — the window moves and the command is
  wrong forever. Excluded from the command DB by the same rule that excludes free-text args
  (`command-learning/01-promotion.md`).

**Connects to:** #37 (this is its screenshot-grid half, for native apps), #52 (the overlay this
escalates from), #18 (screenshot vs AX), #56 (correction loop covers tier 3's unverifiability).

## Sequencing note

> **Update:** the two foundations this rested on — the **assistant / LLM (M4)** and **voice output / TTS (M2)** — are both now **BUILT** (tiered small/big brains; macOS `say` + neural Kokoro with per-persona voices). Most of the magic above is unblocked. Near-term queue: #41 (persona editing, in progress) → #42 (LLM self-edits its persona) → #43 (live conversation viewer) → #28's "dream" consolidation.

Most of these rest on two foundations we haven't built yet: the **assistant / LLM (M4)** and **voice output / TTS (M2)**. Those two unlock most of the magic above — worth weighting toward them when we pick what to build next.
