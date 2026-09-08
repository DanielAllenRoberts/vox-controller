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

> **Status: ✅ slice 1 BUILT (2026-08-03) — the simplified DOM, as the source of truth for page
> elements.** `src/vox/webdom.py` (enumerate + click via the browser's AppleScript
> `execute javascript`) and `src/vox/targets.py` (routes: DOM for pages, AX for native apps). No CDP,
> no extension, no new dependency — this entry assumed browser automation was needed and it wasn't.
>
> **Why it was needed — measured, not assumed.** Correlating every `show clickable` in `vox.log`
> with the focused app showed Slack 121/132/100, Cursor 107, Logic Pro 200 — and **Arc 8, 8, 8, 8,
> 13, 13, never once healthy**. An 85-sample watcher over live browsing found the cause: Chromium
> builds its web-content AX tree on demand and **tears it back down**, so `AXWebArea` was absent in
> **47% of samples**, in runs of 25-35s. On one heavy page (a data table) it was down **37 of 46
> samples — 80%**. Collapsed, the whole page reads as ~12 elements of browser chrome, which is
> exactly the 8/13 in the logs. The DOM returned correct targets on **43 of 43** samples, including
> every one taken while AX was down. Re-asserting `AXManualAccessibility` and re-walking (the
> existing rescue in `ax.targets_with_frames`) does **not** bring it back, so it is not a settle-time
> problem — and that rescue could never fire for a browser anyway, since it compares against the
> per-pid best and Arc's best was itself a collapsed 13.
>
> **Verified live by voice (2026-08-03).** On the same Wikipedia page that returned **15** targets
> minutes earlier on the old build: `'show clickable'` → **96 targets**, `'click 37'` →
> `clicked #37 (Talk)`, then `'show clickable'` → **71** on the page it had just navigated to. So
> enumeration, badge placement, the spoken-number click and re-enumeration after navigation all work
> end to end. Badge positions were also checked visually against a rendered screenshot — which,
> unlike AX hit-testing, doesn't depend on the very tree that's flaky.
>
> **Two things worth knowing.** (a) Arc's own shell UI is web-based, so it exposes a full-window
> `AXWebArea` *before* the tab's; taking the first one put every badge off by the sidebar width. The
> page's web area is now identified by **matching its size to the DOM viewport**, which is
> self-validating — no match means we don't trust it. (b) Merging browser chrome into the list was
> tried and dropped: in a fullscreen window the web view covers the whole window, so no geometric
> rule separates native chrome from page content. Chrome doesn't need badges — `go back`, `next tab`,
> `close tab`, `show tabs`, `profile N` are already deterministic commands.
>
> **Setup caveat:** the browser must allow JavaScript from Apple Events. Arc allows it out of the
> box; **Chrome and Safari need it enabled once** (View/Develop → Allow JavaScript from Apple
> Events) or the call fails and Vox falls back to AX. Also: `querySelectorAll` doesn't cross iframe
> boundaries, so embedded frames aren't enumerated yet.
>
> **Still to build from this entry:** the expand-on-demand tool (2) and the screenshot grid (3, =
> idea #57).

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

> **Voice/AI control BUILT 2026-08-04.** The board was previously invisible to the brain — a grep of
> `executor`/`actions`/`dispatch`/`assistant` found not one reference, so Vox could not see or change
> it at all. Two halves now:
>
> **Seeing** — `actions.board_block()` puts a compact snapshot (lists, card ids + titles, other board
> names, capped at 40 cards) into the action-layer prompt, so "what's on my board?" is answered
> directly with no round-trip, and a card the user names can be resolved precisely.
>
> **Changing** — a `BOARD: <verb> | <arg> | <arg>` directive, same shape as `SCHEDULE:`:
> `add_card` · `move_card` · `update_card` · `note` (append to a card's body) · `delete_card` ·
> `add_list` · `add_board`. Cards are addressed by **title, not id** — voice never produces an id —
> through `board_store.find_card()`, which matches exact → substring → fuzzy, and strips the words
> people wrap names in ("the AC Direct **card**", which otherwise failed both the substring test and
> the fuzzy threshold).
>
> **Store gaps filled to make it possible:** `create_board` did not exist *at all* — the only
> `INSERT INTO board` in the codebase was inside `seed()`, so exactly one board could ever exist even
> though the schema was multi-board throughout. Added with `rename_list` / `delete_list` too (lists
> were add-only). New boards get To Do / Doing / Done seeded, since an empty board can't hold a card.
>
> **Not done:** the new store functions aren't exposed over HTTP yet, so the dashboard still can't
> create a board or rename a list — the Board page needs that plus the drag-and-drop still on the
> original NEXT. And the MCP route (idea #49) is untouched: this gives **Vox's own brain** the board,
> not external agents like Claude Code. That's the natural follow-on and shares all of the store work.

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

> **Status:** ✅ BUILT 2026-08-13 as `vox/agent.py` — but **not** as the grid overlay below. Anthropic's
> computer-use tool (`computer_20251124`) does coordinate clicking natively, and it's *trained* for
> it rather than being a general vision model asked to guess pixels — which was this idea's main
> risk. Its `zoom` action is the zoom-refine pass described here. Measured against real AX frames as
> ground truth on this Mac: **1.1px error**, so the grid-as-classification workaround wasn't needed.
> The build also went further than this idea: because the tool runs in a loop (screenshot → act →
> screenshot), it added the *multi-step* tier Vox never had, not just a third way to click.
> Gated behind `agent_enabled` (off by default), capped, Esc/"stop"-abortable, with an app denylist.
> The design notes below still stand — especially "never learn a coordinate" and "announce it".

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

## 58. Let the brain QUERY its own commands (and everything else) instead of being force-fed

> **Status:** 📋 IDEA — noted 2026-08-07, not scheduled.

**The gap:** the LLM only knows the static command list hardcoded in `executor._SYSTEM`. The actual
**command DB — 50 commands / 152 phrases, including everything learned or taught — is invisible to
it.** `command_cache.active_phrases()` reads the DB but feeds only the Vosk grammar
(`loop.py:257`), never a prompt. So the day after teaching "refresh page", the brain still has no
idea that command exists.

Mostly harmless, because the DB resolves *before* the brain is called — by then the DB has already
missed, so knowing the phrases wouldn't change the action. It hurts in three places:

1. **"What commands do I have?"** — it can only recite the static list, omitting everything you
   taught, and confidently, since nothing tells it the list is partial.
2. **`TEACH:` collisions** — the model can't see that a phrase is already taught. `_teach` catches
   it at execution ("Changed X from Y to Z"), so nothing breaks, but the model is guessing.
3. **Editing by reference** — "change the refresh command" needs to know a refresh command exists.

**Don't solve it by injecting the list.** 152 phrases is ~400–600 tokens on *every* action-layer
call to serve perhaps one utterance in fifty — the worst always-on block we could add, and the same
context-bloat problem already flagged for the board (~1340 tokens at its cap) and the open-tabs list
(~317 whenever the browser is focused). See [`prompts.md`](../prompts.md) for the measured budget.

**Do it as a query instead.** A read tool the brain calls only when it needs the answer — e.g.
`ASK: commands` / `ASK: commands matching <x>` — returning the list at that moment. Costs nothing
until used, scales to a DB of any size, and generalises: the same mechanism could serve the board,
the tab list, the calendar (#2 in [`todo.md`](todo.md)) and the AX tree, replacing several
always-attached blocks with one on-demand lookup.

**The catch worth thinking about:** Vox is *translate-to-command*, not native function-calling — one
utterance, one line, one action. A query tool needs a **second round-trip** (ask → answer → act),
which is a real change to the executor's shape and adds latency to the turn. Two ways out: allow a
bounded second call only when the first output is an `ASK:`, or keep a relevance test that attaches
the right block up front. The first is more general; the second is cheaper and closer to what
exists today.

**Connects to:** #49 (MCP two-way bridge — the same "let the agent look things up" shape), #36
(context-aware profiles), the need-based-context item in `todo.md`, and the v2 prompt work in
[`prompt-v2-draft.md`](../prompt-v2-draft.md).

## 59. Give the MCP control of the board (extends #49/#51)

**Vision:** expose the workspace board (#51) as **MCP tools**, so the IDE assistant (Claude Code /
Cursor) can read and write the same board you drive by voice and see in the dashboard. Claude
finishes a task → it moves the card to Done itself. You say "what am I working on?" → Vox reads back
a board Claude has been keeping current. One board, three ways in: voice, dashboard, coding agent.

**Why it's nearly free:** `board_store.py` is already a plain SQLite module with the whole surface
this needs — `board_snapshot`, `search`, `add_card`, `move_card`, `update_card`, `delete_card`,
`add_list`, `list_boards`, `summary`, plus `find_card` for fuzzy "the proxy card" lookups. The MCP
server (`mcp/vox_speak_server.py`) already imports from `vox.*`, and #49 established the pattern:
each tool is a thin wrapper over a module that exists. No daemon, no mic, no new storage — unlike
the two-way-voice tools in #49, **nothing here contends for the microphone**, so it's one of the
cheapest items on that list.

**Sketch:** `board_read(board?)` → snapshot; `board_search(query)`; `board_add(list, title, body?)`;
`board_move(card, to_list)`; `board_update(card, …)`. Card references should accept a fuzzy title,
not just an id, since the caller is an LLM — `find_card` already does that.

**Worth deciding up front:**
- **Write scope.** Read + add + move is the safe core. `delete_card` / `delete_list` from an agent is
  the one that can silently lose work — consider leaving deletes out of the MCP surface entirely, or
  gating them behind a confirm.
- **Attribution.** If Claude and Vox and you are all moving cards, the board should record *who*
  moved it, or "why is this in Done?" becomes unanswerable. There's no actor column today.
- **Board bloat vs. the prompt budget.** #58 measured the board at ~1340 tokens at its cap in Vox's
  own prompt. On the MCP side that's not an always-on cost — it's a tool the agent calls when it
  cares — which is exactly the on-demand shape #58 argues for. Good precedent to reuse.

**Connects to:** #49 (the MCP bridge this slots into), #51 (the board itself), #58 (query-don't-inject),
#34 (the existing vox-speak MCP).

## 60. Presence-aware reminders — hold them until you're actually there (extends #16)

**Vision:** Vox knows whether you're **at the machine**. A reminder that fires while you're away is
spoken to an empty room and then gone — the one moment it mattered is missed. Instead: if you're
idle when it fires, **hold it**, and deliver the moment you come back (first mouse move, keypress,
or spoken command). "Remind me at 3" becomes "remind me at 3, or the next time I'm here."

**Why it's nearly free:** macOS already tracks this, and Vox already imports Quartz —

```python
Quartz.CGEventSourceSecondsSinceLastEventType(
    Quartz.kCGEventSourceStateHIDSystemState, Quartz.kCGAnyInputEventType)   # → seconds idle
```

Verified working here: zero dependencies, no permission prompt, no polling cost worth measuring.
The scheduler (`vox/scheduler.py`) already owns firing and already has an output policy, so this is
a gate in front of `_fire()` plus a small "deferred" queue, not new machinery.

**Worth deciding:**
- **What's the idle threshold?** A few minutes of no HID input is "away"; 30 seconds isn't. Probably
  a setting, defaulting to something like 3–5 minutes.
- **What's the catch-up rule?** On return, speak them all, or collapse to "you missed three
  reminders while you were away"? Batching is kinder for a long absence.
- **Does a stale reminder still matter?** A "stand up and stretch" from four hours ago is noise;
  "call Sam" isn't. Possibly an expiry per reminder, or just drop timers and keep reminders.
- **Idle ≠ absent.** Watching a video or reading counts as idle to the HID clock. That argues for a
  generous threshold and for delivering on return rather than suppressing outright.

**Also useful beyond reminders:** the same signal tells the daemon when nobody's listening — a cheap
input to "should I speak this now?", and a natural guard for the agent tier (#57), which should
probably not be driving the screen while the user is away from it.

**Connects to:** #16 (the scheduler this gates), #48 (meetings — presence is a signal there too),
#57 (agent tier safety).

## 61. Desktop input primitives — scroll · keys · right-click · drag · set (from Hermes)

**Where this came from:** recon on Nous Research's Hermes Agent (see `hermes-comparison.md`). Its
`computer_use` tool exposes capture · click · double_click · right_click · middle_click · drag ·
scroll · type · key · set_value · wait · list_apps · list_windows · focus_app. Lining that up against
Vox surfaced something we'd missed about our own code.

**The gap wasn't the primitives — it was where they lived.** Vox could already scroll, press key
combos and right-click. But only inside `agent.py`, the tier-4 agent loop: gated off by default,
needs an Anthropic API key, and burns a multi-second model round-trip deciding to do it. To scroll a
page you needed `agent_enabled=true`, a key, and ~$0.035 of tokens. There was no way to just say
"scroll down" and have it happen.

These are CGEvent calls. They cost milliseconds. They belong on the deterministic fast path.

**Built:**

| Primitive | Was | Now |
|---|---|---|
| `scroll` | agent tier only | "scroll down", "scroll up 3", "scroll to the top", "page down" |
| `press` (key combo) | agent tier only, via AppleScript (~200ms) | "press command S", "press escape" — CGEvent, <10ms |
| `right_click` / `double_click` | agent tier only — **and broken**, see below | "right click Submit", "double click 14" |
| `drag` | nowhere | "drag 3 to 7", "drag Inbox onto Archive" |
| `set_value` | nowhere | "set volume to 30", "set theme to dark" |
| background delivery | nowhere | `input_background_delivery` — drive a window without raising it |

**Bug found on the way:** the agent tier's `right_click` and `middle_click` were posting **left**
button events. They called `ax._click_at`, which only ever synthesizes a left click. Nobody noticed
because the tier is off by default. Fixed by routing both through `vox.input`.

**Architecture:** a new `src/vox/input.py` owns the event synthesis; `actions.py` holds the spoken
argument parsing and the human-readable results; `agent.py` now delegates to the same helpers rather
than carrying its own copies. One implementation per gesture, two callers.

**Background delivery** is the interesting one, and the only piece taken wholesale from Hermes'
design. By default Vox posts to the global HID tap (`CGEventPost`) — reliable, but it acts on
whatever is frontmost and moves your real cursor. With `input_background_delivery` on, events go to
a specific process (`CGEventPostToPid`) instead. **This is app-dependent and experimental:** AppKit
apps generally honour posted events; Chromium and Electron frequently ignore posted *mouse* events
while still accepting keys. Off by default, so the default path is byte-for-byte what Vox did before.

**Worth deciding after testing:**
- Does background delivery actually work in the apps you use daily, or only in native ones? If it's
  AppKit-only it might still be worth defaulting on for those and falling back per-app.
- `set_value` on popup buttons has to press the button and walk the menu (the menu doesn't exist as
  AX children until pressed). That costs ~150ms of settle time. Acceptable, or should popups stay a
  click-through?
- Should `scroll` target the element under the pointer, or the focused window? Right now it's the
  pointer, which is how the OS behaves — but voice users aren't moving the pointer.

**Learning interaction (#24):** scroll and press have stable identities and are safe to learn.
`right click 14` is coordinate-shaped — badge indices are no more stable than pixels, and `agent.py`
already warns that pixels must never enter the command DB. Same reasoning applies.

**Not taken from `computer_use`:** `list_apps`/`list_windows` (we have `running_apps()` /
`frontmost_app()`; a cross-app window inventory is a smaller want), and the eight `cua_browser_*`
actions — dialog handling, file upload and download are real gaps but belong with the web-navigation
work, not here.

**Connects to:** #52 (the overlay whose badge numbers these reuse), #57 (the agent tier they were
trapped in), #12 (the executor can now reach them), #24 (what's safe to learn).

## 62. Silent notification bubble — the quiet sibling of the speak MCP

**Where this came from:** the vox-speak MCP (#34) is the most-used piece of the whole project — an
agent in the IDE says "the workflow is finished" out loud so you don't have to watch the screen. The
gap is obvious once you've lived with it: **speaking is the only channel.** In a meeting, on a call,
or when three agents finish inside a minute, an audible heads-up is the wrong tool and the answer is
to turn it off entirely — which loses the notification too.

**Built (2026-08-31):** `src/vox/bubble.py` + a `notify` tool on the vox-speak MCP. A small rounded
HUD card fades into a screen corner, holds for a few seconds, and fades out. Silent.

**It reuses the hard-won part of `overlay.py` (#52):** the helper-process pattern. The daemon is a
single blocking audio loop with no `NSApplication` run loop, and a visible `NSWindow` whose main
thread never services its run loop beachballs the entire app. So the card is drawn by a short-lived
child (`python -m vox.bubble --helper <json>`) that owns its own run loop. The MCP server has the
same problem with its stdio loop, and the same fix works for it.

Non-negotiables, all inherited from the overlay: `NSApplicationActivationPolicyProhibited` (no Dock
icon, can never become active), `setIgnoresMouseEvents_` (click-through — it can never eat a click),
`NSWindowSharingNone` (stays out of screen recordings, **and** out of Vox's own `LOOK:` screenshots,
so a notification about one task can't become input to the next), and joins all Spaces.

Shows on `NSScreen.mainScreen()` — the display holding the active window, i.e. the one you're
actually looking at, which on a laptop-plus-monitor setup is the whole difference between a useful
notification and one you never see.

**Stays until you close it.** `bubble_duration` defaults to **0** — a notification that faded while
you were looking at another window did nothing. The card carries a ✕.

**That ✕ forced the interesting design decision.** A dismissible card can't be mouse-transparent, and
a normal `NSWindow` would have to *activate the app* to handle the click — stealing focus, the one
thing this must never do. The fix is an `NSPanel` with `NSWindowStyleMaskNonactivatingPanel`, which
takes the click without activating. Cost: while a card is up, that corner isn't click-through.

**It says who sent it.** The card is labelled with the sender's registered name (#39 —
`vox.agents` + `register_agent`), because with several CLIs running an unattributed notification
tells you something finished but not what.

**Settings:** `bubble_corner`, `bubble_duration`, `bubble_max_width`, live from the dashboard
(Settings -> Notifications), no restart.

**Known limit, deliberate:** a second bubble replaces the first rather than stacking. Two cards cover
more screen than one notification is worth, and the MCP caller still gets a return value either way.
Revisit if async agents actually make simultaneous finishes common.

**Connects to:** #34 (the speak MCP this is the silent half of), #52 (the overlay whose helper-process
pattern it reuses), #39 (whose registered names label the card), and the async-agent escalation idea —
the bubble is the return channel that makes handing a task off to a background agent bearable.

## 63. One voice at a time — the cross-process speech queue

> **Status:** ✅ BUILT 2026-08-31 (`src/vox/speech_lock.py`). Closes the "overlapping speech" risk
> that `named-agents.md` flagged and deferred.

Vox's daemon and every agent's vox-speak MCP server are **separate processes**, each free to start
talking whenever it likes. Two agents finishing inside a minute, or Vox answering you while an agent
announces a build, produces audio you can't parse — and you lose *both* messages, not one.

An `fcntl.flock` on `data/speaking.lock`, taken by `tts.speak()` and `tts.speak_with()`. It's the one
coordination primitive every process already shares without inventing IPC, and the OS releases it
when a holder crashes. The lock file records who holds it, so `speech_lock.holder()` — and
`cat data/speaking.lock` — answer "who is talking?".

**The timeout is a deadlock guard, not a queue policy.** If the process ahead never releases, we
speak anyway. A voice assistant that has gone silent is a worse failure than one overlap, and this
codebase has already been bitten by exactly that shape of bug (the Kokoro streaming player
deadlocking the voice loop). `speech_queue_timeout`, default 15s.

**Open:** the wait is symmetric, and arguably shouldn't be. An agent's announcement waiting on Vox is
free — it's async. Vox waiting on an agent is not: you asked Vox something and it goes quiet. If that
asymmetry is felt in use, the daemon should get a shorter wait than the MCP servers.

**Connects to:** #39 (named agents, which is what makes several speakers likely), #34, #62.

## 64. The warm brain — stop paying Claude SDK cold-start on every utterance

> **Where this came from:** recon on [backtalk](https://github.com/jaredrhod/backtalk), see
> [`backtalk-comparison.md`](backtalk-comparison.md). He gets first audio in 1-2s from the full
> Claude Code harness. We take many seconds for the same thing, and the reason is four lines.

**The bug is in `assistant._claude_sdk` (`src/vox/assistant.py:508`).** It calls the Agent SDK's
`query()` — which **spawns a fresh Claude Code session per utterance**: process start, tool
discovery, system prompt, project context, every single time. Then it does
`return "".join(parts).strip()`, so nothing reaches TTS until the entire reply has generated. Then
it re-serialises the whole conversation into the next prompt, because a cold session remembers
nothing.

This is the **big brain** (`big_brain_provider = "claude_sdk"`, `claude-opus-4-8`) — vision,
`_click_fuzzy`, every chat escalation. The slow path is the one that runs when Vox is doing
something hard.

**The fix, both halves from Anthropic's own Agent SDK docs:**

1. **`ClaudeSDKClient` held open** instead of `query()` per turn. Anthropic's guidance verbatim:
   *"For low-latency interactive apps: use ClaudeSDKClient with a persistent connection."* The
   session also holds the history, so we stop resending a growing transcript into a cold cache.
2. **`include_partial_messages=True`** → buffer `StreamEvent` text deltas, split on
   `(?<=[.!?])\s`, and yield each complete sentence. TTS starts on sentence one while sentence four
   is still forming. **Cheap for us specifically:** `tts._speak_kokoro_streaming` + `_split_chunks`
   already speak incrementally and `_StreamingPlayer` is already killable for barge-in. The missing
   link is upstream — `assistant.respond()` / `complete()` return `str`, so add a generator variant
   beside them rather than changing either.

**Ship the desync guard FIRST, not after.** The SDK has one shared message stream and
`receive_response()` stops at the first `ResultMessage` with no query/response pairing. Interrupt a
turn without draining it and the leftovers pair with the *next* query — from then on every answer
is one question late, for the rest of the session. Anthropic's docs confirm the requirement;
backtalk's `reset_turn()` documents having lived it. **Vox has barge-in**, so we hit this condition
by design, not by accident. Guard shape: a `_dirty` flag set on query and cleared only on
`ResultMessage`, a bounded drain, and a session rebuild if the drain fails.

**Also free:** `system_prompt={"type": "preset", "preset": "claude_code", "append": …}` instead of
replacing the preset outright (we currently pass `system_prompt=system`, discarding the harness
prompt), and `exclude_dynamic_sections: True`, which moves cwd/git details out of the cached prefix
so it stops varying per machine and directory.

**Not a reason to leave the Agent SDK.** We pass `allowed_tools=[]` — full harness, no harness
benefit — which looks like the wrong surface until you remember the Agent SDK is the only way to
bill against a **Claude subscription**; the Messages API needs an API key. The harness cost is the
price of no-per-token-cost. Pay it once per session instead of once per utterance.

> **⚠️ SCOPE: this is a BIG-BRAIN fix only. Do not try it on the small brain.** Established
> 2026-09-01, so nobody re-reads this in a month and reaches for it on the command path:
>
> 1. **Streaming buys the command path nothing.** The executor needs a COMPLETE directive
>    (`CLICK: x`) before it can act. Sentence-by-sentence yielding is worth everything to a speaker
>    and nothing to a parser — and "first audio in 1-2s" is the number streaming flatters.
> 2. **Warm still carries the `claude_code` system preset** on every turn. Fine amortised across a
>    spoken conversation; not fine on a sub-second command hop.
> 3. **The constraint is structural.** Subscription billing → Agent SDK → harness overhead →
>    seconds. Sub-second → a plain API call → per-token cost. You cannot have both on the hot path,
>    which is why the small-DeepSeek / big-subscription split is the RIGHT architecture.

**⚠️ Licence:** backtalk is AGPL-3.0. Read it for the traps, write ours from Anthropic's docs —
same call we made declining `kan` for the board.

**Connects to:** #57 (the agent tier), #19 (barge-in, which makes the desync guard mandatory),
and the async-agent escalation thread — a warm client is also what makes handing work to a
background agent cheap.

## 65. Give the big brain a harness — files and tools, without the Claude Code tax

**The want:** the big brain should be able to *do* things — read and edit files, run a command —
not just answer. Today `_claude_sdk` passes `allowed_tools=[]`, so we boot the entire Claude Code
harness and then forbid it from using any of it. The agent tier (#57) can act on the *screen*, but
nothing in Vox can act on the *filesystem*.

**Candidate: [Pi](https://pi.dev) (Mario Zechner).** Worth a real look, for three reasons that map
onto constraints we've already hit:

- **MIT licensed.** This is the one that matters. We turned down `kan` (AGPL) for the board and
  we're keeping backtalk (AGPL) at arm's length for #64. MIT means we can actually read and use it.
- **~200-token system prompt, four tools** (read · write · edit · bash), with a lazy-loading skill
  system that injects instructions only when needed. Compare Claude Code's preset, which is the
  overhead #64 is working around. Databricks' internal benchmark reportedly had Pi at the highest
  pass rate on Opus 4.8/xhigh **at lower cost**, because it sent ~3x less context per turn.
- **Model-agnostic** — 37+ models across 20+ providers, so the harness doesn't dictate the brain.

**The two honest problems:**

1. **It's TypeScript; we're Python.** Integration is a subprocess/CLI boundary or a bridge, not an
   import. That's the real cost of this idea and it should be priced before anyone commits.
2. **It probably can't reach the Claude subscription.** Provider-agnostic means API keys. The
   subscription is only reachable through Claude Code / the Agent SDK. So this is a genuine fork,
   not a free upgrade:
   - **Agent SDK (#64):** subscription billing, no per-token cost, heavy harness.
   - **Pi:** light harness, tool use, MIT — but back to paying per token.

   Those are different bets and we should make the choice deliberately rather than drift into one.

**Sequencing:** this sits *behind* #64. Warm the brain we already have first — that's a measured
win on the path we already use. Only then decide whether a second harness earns its integration
cost. Nothing here blocks anything.

**Also worth watching:** OpenCode, named alongside Pi as the other serious open harness (bigger
community, less minimal). Not evaluated.

**Connects to:** #64 (the warm brain, which this would sit beside or replace), #57 (the on-screen
agent tier — a filesystem harness is the missing half), #38 (coding brain), and the async-agent
escalation thread, where "go do this in the background" needs exactly a tool-capable harness.

## 66. Vox's control surface as MCP tools — give the agent hands, not a loop

**The inversion:** everyone else is building an agent *into* their assistant. This does the
opposite — it hands Vox's existing primitives to an agent that already exists. Cheaper, and better
at the one thing Vox is genuinely best at.

**Why this beats what the big labs shipped.** ChatGPT's Computer Use (see
[`chatgpt-desktop-comparison.md`](chatgpt-desktop-comparison.md)) is an agentic loop: screenshot →
reason → click → re-screenshot. Press coverage clocked eight chess moves in three minutes. Vox's
`ax.click` is a **~77ms deterministic AX lookup with no model in the loop**. Exposed over MCP, an
agent gets sub-second GUI control instead of a reasoning loop — and picks targets by real accessibility
label rather than guessing at pixels.

We already have the hard parts. This is mostly plumbing.

### Stage 1 — read tools (do these first)

| MCP tool | Backed by |
|---|---|
| `frontmost_app` | `actions.frontmost_app()` |
| `running_apps` | `actions.running_apps()` |
| `clickable_targets` | `actions.clickable_targets(limit=300)` — frame-filtered, on-screen only |
| `visible_targets` | `targets.visible_targets()` — DOM on a page, AX natively |
| `environment_context` | `actions.environment_context()` — focused app + open tabs |
| `read_window` | the AX tree of the frontmost window as text |

Low risk of *damage*, immediately useful, and they make stage 2 better when it arrives: an agent
that can read structure asks to click `"Submit"`, not `(1877, 68)`.

This is essentially ChatGPT's **Appshots**, except the agent can request it instead of the human
hitting a hotkey — and it returns structured text rather than an image, which is cheaper and exact.

> **"Low risk" means damage, NOT privacy.** Reading the AX tree exposes whatever is on screen —
> messages, a password manager, a private document — to whichever model the agent is running on.
> `capture_screen()` is worse again because it is indiscriminate. Whatever we ship needs an app
> deny-list on the READ side too, not only the write side. Don't let the staging imply reads are safe.

### Stage 2 — write tools (behind a gate)

`click_element` · `click_index` · `type_text` · `press` · `scroll` · `drag` · `set_value`
(from `actions.py`, `ax.py`, `input.py` — all built, see #61).

**The threat model is different from Vox's own control path, and that is the whole problem.** When
Vox clicks something, a human said so out loud. When an MCP tool fires, *a model decided to*. Same
primitives, no person in the loop.

`press` is the sharp edge: keyboard control over Terminal is arbitrary code execution wearing a
different hat. `agent_denied_apps` (Terminal, iTerm, Cursor, Warp, System Settings) already exists
for exactly this and must apply here; the Hermes doc's reasoning for deferring a shell
([`hermes-comparison.md`](hermes-comparison.md)) applies unchanged. Add a per-call confirm on the
destructive verbs — backtalk solved its version with a spoken permission gate, which is a good model.

**Depends on #61's background delivery** (`input_background_delivery`), so an agent can drive a
window without raising it or taking the pointer out of your hands. That is still **untested** —
item B on the standing list — so it is a real dependency, not a given.

### Open questions

- **Which server?** Bolting this onto `vox-speak` makes one server that both talks and acts — simple,
  but then anything wired for notifications also gets hands. A separate `vox-control` server that you
  add deliberately is probably the right call.
- **Does the daemon need to be running?** The read tools go through `vox.ax` directly and don't, which
  is a nice property: an agent could use them with Vox switched off.
- **Overlap with the agent tier (#57).** That tier drives the screen from *inside* Vox with its own
  model loop. If an external agent can do it better, #57 may be the thing that gets retired rather
  than extended.

**Connects to:** #61 (the primitives, and the background-delivery dependency), #52 (badge numbers an
agent could address), #57 (the tier this may replace), #65 (a harness is the other way to get here),
#34/#62 (the MCP this would sit beside), and the async-agent escalation thread — "go do this in the
background" is much more useful when the background agent has hands.

## 67. anarlog — and the STT lane we're not using (Apple SpeechAnalyzer)

> **To look at:** [fastrepl/anarlog](https://github.com/fastrepl/anarlog) — "Open source Granola AI
> alternative", **MIT**, TypeScript + Rust, **9.2k stars**, actively developed. A meeting-notes app,
> so it overlaps [`meetings.md`](meetings.md) / the Meetily recon directly. Licence is MIT, which
> means we can read AND borrow — unlike backtalk (AGPL, #64).

**Why it's worth the look, beyond meetings:** its transcription is noticeably fast, and the reason
is architectural. It doesn't have one STT — it has a *lane per backend*, each its own crate:

| Crate | What it is |
|---|---|
| `transcribe-speechanalyzer` | **macOS-only, binds to a Swift lib via `swift-rs`** — Apple's native on-device speech framework |
| `transcribe-whisper-local` | local Whisper, the familiar path |
| `local-stt-core` / `onnx` | shared local-model plumbing |
| `transcribe-soniqo`, `transcribe-proxy` | cloud / proxied options |

**The interesting one is `transcribe-speechanalyzer`.** Apple's on-device recognition runs on the
Neural Engine rather than the CPU — which is precisely the axis Vox is losing on. Measured on this
machine (issues.md **O17**): faster-whisper's median `rtf` is 0.17, but under Logic Pro + a VM +
a remote-desktop session it hit **3.53** — transcribing slower than real time, so Vox falls further
behind every sentence, and that starvation was also *causing* the dictation cut-outs (O15). An STT
lane that doesn't contend for CPU would make that whole failure class go away, and it costs no disk
either — nothing to download, unlike `small.en` at ~590 MB (O6, disk is tight).

**What I verified vs. what I assumed:** verified from the repo — the crate exists, is macOS-gated,
and binds Swift through `swift-rs` alongside a separate local-Whisper crate. NOT verified — the
exact framework/API it calls, minimum macOS version, accuracy against `small.en` on this accent, or
whether it exposes word timings and confidence (Vox's turn detection and the Vosk fast-lane
comparison both lean on those). Those are the questions to answer before committing to anything.

**Shape of the idea for Vox:** a swappable STT backend behind the existing `stt/` interface (we
already have `whisper_transcriber.py` and `vosk_recognizer.py` behind `stt/base.py`, so the seam
exists), with Apple's engine as a macOS fast lane and Whisper as the portable fallback. Same
pattern anarlog uses, and the same pattern we already use for TTS (`say` vs Kokoro).

**Also worth stealing a look at:** the repo ships `.claude/skills/` and `.agents/skills/` in-tree
(QA, release, changelog, SQLite schema design) — a working example of agent skills committed
alongside the code, which is a distribution question we have open too.

**Connects to:** O17 (the CPU starvation this would sidestep), O15 (which it was causing), #48 /
`meetings.md` + `research/meetily-recon.md` (the meetings work this repo overlaps), #6 (disk).

## Sequencing note

> **Update:** the two foundations this rested on — the **assistant / LLM (M4)** and **voice output / TTS (M2)** — are both now **BUILT** (tiered small/big brains; macOS `say` + neural Kokoro with per-persona voices). Most of the magic above is unblocked. Near-term queue: #41 (persona editing, in progress) → #42 (LLM self-edits its persona) → #43 (live conversation viewer) → #28's "dream" consolidation.

Most of these rest on two foundations we haven't built yet: the **assistant / LLM (M4)** and **voice output / TTS (M2)**. Those two unlock most of the magic above — worth weighting toward them when we pick what to build next.
