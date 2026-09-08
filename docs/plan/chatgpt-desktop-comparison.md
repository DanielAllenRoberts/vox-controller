# ChatGPT desktop (Work / Codex) vs Vox — recon & what we should take

> **Date:** 2026-08-31 · **Subject:** OpenAI's unified ChatGPT desktop app (macOS), its Computer Use
> plugin, ChatGPT Voice / GPT-Live, Appshots, and Computer History.
> **Question asked:** what does it actually do, how does the "visual agent mouse" work, and what
> should Vox take?
> **Short answer:** it is the closest thing to Vox that exists, it independently arrived at three of
> our designs (background input delivery, window-scoped screen reading, learn-from-what-you-do), and
> the one it does better than us is the one we shipped untested last week.

## What it is now

On **9 July 2026** OpenAI collapsed its separate apps into one desktop application with three
surfaces in a single window: **Chat**, **Work**, and **Codex**. Everything below is a plugin or
setting on that app, not a separate product.

| Feature | Date | What it is |
|---|---|---|
| **Computer Use** | May 2026 (Windows apps), matured through Aug | Sees and operates GUIs. Screenshots, clicks, types, navigates, menus, keyboard, clipboard, across multiple apps in sequence. |
| **Background computer use** | macOS only | Its **own cursor** — the agent works in background windows while your mouse and focus stay yours. Multiple agents in parallel. |
| **Appshots** | macOS only | Double-tap ⌘ (or a custom hotkey) → the **frontmost window** goes to ChatGPT as an image *plus the text macOS accessibility can read from it*. |
| **ChatGPT Voice (GPT-Live)** | 23 Jul 2026 | Full-duplex voice in the desktop app — speaks and listens simultaneously. Drives Computer Use and orchestrates running Work/Codex agents. |
| **Computer History** | 13 Aug 2026 (US), 20 Aug (EEA/UK/CH) | Optional. Records clicks, keystrokes, shortcuts and app switches **via the accessibility API, not screenshots** → memories + a searchable timeline. **Suggests a skill or automation when it spots a repeatable workflow.** |
| **Built-in browser** | through Aug 2026 | In-app browser that inspects and annotates pages, opens background tabs, and **connects to your existing Chrome tabs** (Edge/Brave/Opera/Vivaldi added 25 Aug). WebMCP "site tools" let a website expose actions to it. |
| **Companion window** | ongoing | ⌥Space (⌥/Alt+Space, rebindable) floating always-on-top window over whatever you're doing. |
| **Permission modes** | ongoing | Ask for approval (default) · Approve for me · Full access. Plus per-app and per-website allow/deny with "Always allow". |

Requires macOS **Screen Recording + Accessibility**. Plans: Computer Use needs Work/Codex; Voice is
Plus and up; Computer History is Pro/Business/Enterprise.

## The visual agent mouse — what it actually is

This is the feature worth understanding, because **we have already built our half of it and haven't
tested it.**

On macOS the agent gets a cursor of its own. It drives background windows — click, scroll, type,
drag, resize, key combos — *without raising the window, without moving your pointer, and without
stealing keyboard focus*. Several agents can work on different apps in parallel while you keep
typing in a third. Windows cannot do this: there, Computer Use "runs on the active desktop", the app
must stay visible, and it takes over foreground input for the duration.

The macOS-only split is the tell. That is not a product decision, it is the platform: macOS lets you
address synthesized events at a **process** rather than at the global event stream. Which is exactly
what `input_background_delivery` does in `src/vox/input.py` — `CGEventPostToPid` instead of
`CGEventPost(kCGHIDEventTap)`, added last week under [ideas.md #61](ideas.md), off by default,
**never once run**.

> ⚠ One widely-repeated claim — that the implementation is Swift behind a localhost HTTP server
> accepting click/scroll/type/drag/resize/key commands — comes from a secondary blog we could not
> fetch directly (403). Treat the *architecture* as unverified. The *capability* is confirmed by
> OpenAI's own docs and by hands-on press coverage.

**What this changes for us:** the open question in #61 was "does background delivery actually work in
real apps, or only native AppKit ones?" Someone with a large team has now shipped it as a headline
feature on macOS. It works. If ours only works in AppKit apps and dies in Electron, that is our bug
to find, not evidence the approach is wrong.

## Where they landed on our designs independently

Three of these are uncomfortable in a good way.

**1. Appshots ≈ our `LOOK:` — but scoped to one window.** We capture the whole screen, or walk the
whole AX tree. They capture the **focused window only**, as image *plus* AX text, on one keystroke.
That is a cheaper, sharper primitive than either of ours, and it is the same insight as our
`screen_vision_mode = axtree` (read text before you spend a screenshot) with a tighter boundary.

**2. Computer History ≈ command learning (#24), generalized.** They watch clicks, keystrokes,
shortcuts and app switches through the accessibility API, summarize them, and **offer to turn a
repeatable workflow into a skill**. That is our learning trial, aimed at the whole desktop rather
than at voice commands. It is direct validation that "notice what the user keeps doing, then offer to
automate it" is the right shape.

It also validates the change we were mid-discussion on: theirs is a **model judging** whether a
pattern is worth automating, not a hit counter. Our current bar is mechanical (`is_learnable` +
N hits), and it is why `'no that didn t really work click on the team folder'` became command #53.

**3. Their guardrails are the ones we reasoned our way to.** Computer Use cannot automate terminal
applications, cannot automate ChatGPT itself, and cannot authenticate as admin or approve system
permission prompts. Compare `agent_denied_apps` (Terminal, iTerm, Cursor, Warp, System Settings) and
the Hermes-doc decision to defer giving Vox a shell. Same conclusions, arrived at separately.

## Where Vox still wins

**Latency, and it is not close.** Everything above is an agentic loop: screenshot → reason → act →
re-screenshot. Press coverage of the chess test — eight moves in under three minutes — is impressive
*for an agent* and unusable *as a control surface*. `ax.click` is ~77ms with no model in the loop.
Saying "scroll down" and having the page scroll is a category their architecture cannot enter.

**Voice that controls the machine, not the chat.** Their own framing is orchestration: "status on
agent 2", "redirect to the auth branch". Even sympathetic coverage lands on the limitation — *"this
all lives inside ChatGPT… most of your day happens in Gmail, Slack, Notion, your browser, and your
editor, not in one chat window."* Vox's modes (control / dictation / assistant), dictation at the
cursor, "click 14", the correction dictionary (#54), hotword biasing — none of that has an analogue.
GPT-Live's full-duplex stack is genuinely ahead of our barge-in, but it is talking to a chat app.

**Local, private, unmetered.** Voice-driven agent work burns Work/Codex quota from the same bucket as
typed requests. Computer History ships your activity to OpenAI's servers to be summarized (raw files
deleted after 48h, not used for training) — and is unavailable in the EU/UK/CH for most of its life.
Vox runs on your Mac. For the open-source direction that is the whole pitch.

## Where they are ahead

- **Background input that is shipped and works.** Ours is a flag nobody has flipped.
- **Activity → automation suggestion.** Computer History spots repeatable workflows across every app.
  Our learner only sees utterances the brain resolved.
- **Permission model maturity.** Three modes, per-app *and* per-website allow/deny, "Always allow",
  a menu-bar pause, per-app exclusions, "delete the last 10 minutes". We have `agent_denied_apps`.
- **Browser reach.** Connects to existing Chrome/Edge/Brave/Opera/Vivaldi tabs; WebMCP lets sites
  expose actions directly. Our web story is AX-clicking Arc.
- **Distribution.** Signed app, one download.

## Decisions

**Take now — small, and mostly already half-built:**

1. **Test `input_background_delivery` properly and fix what breaks (#61).** This just went from
   "experimental idea from Hermes" to "the thing the market considers the headline feature".
   Specifically: does it survive Electron (Slack, Cursor, Obsidian)? If posted mouse events are
   ignored there but keys land, ship it enabled for AX-native apps with a per-app fallback rather
   than leaving one global off switch.
2. **A window-scoped appshot primitive.** `LOOK:` currently means "the screen". Add "the focused
   window, as AX text, and a picture only if the text is not enough". Cheaper, sharper, and it makes
   "what does this say?" answerable without a full-screen capture.

**Take, pending the design we're already mid-conversation on:**

3. **Model-judged learning.** Computer History's "suggest an automation when you spot a repeatable
   workflow" is the same call we were about to add to the learner — let the model say whether a
   worked-out command is worth keeping, then keep the hit count as a second, independent filter.
   External validation for the change, not a new idea.

**Queued:**

4. **Permission modes.** If Vox ever gets a shell (deferred in `hermes-comparison.md`), copy the
   three-tier shape and the per-app/per-site allow list rather than inventing one.
5. **Connect to existing browser tabs** instead of only driving the frontmost window.

**Declined:**

- **Cloud-summarized activity capture.** Computer History is the most interesting feature here and
  we should not copy its data path. Always-on keystroke and click capture leaving the machine is the
  opposite of the local-first direction. If we build the equivalent, summarization happens locally or
  it does not happen.
- **The agentic loop as a control surface.** Same call as the Hermes doc. It is the right tool for
  "file my expenses" and the wrong one for "scroll down".
- **Chasing the surface area** — Sites, WebMCP, three-experiences-in-one-window. Not what Vox is.

## Sources

- <https://learn.chatgpt.com/docs/computer-use>
- <https://learn.chatgpt.com/docs/appshots>
- <https://learn.chatgpt.com/docs/permission-modes>
- <https://learn.chatgpt.com/docs/whats-new>
- <https://www.pcworld.com/article/3190769/chatgpt-can-now-control-your-whole-desktop-i-tested-it-with-chess.html>
- <https://www.cultofmac.com/news/chatgpt-computer-history-mac-feature>
- <https://www.voiceos.com/blog/chatgpt-voice-desktop-control-your-computer>
- <https://explainx.ai/blog/chatgpt-voice-desktop-gpt-live-codex-work-july-2026>
- <https://kenashe.ai/blog/2026-07-18-chatgpts-computer-control-turns-the-browser-into-the-new-agent-runtime/>
- <https://techcrunch.com/2026/07/24/openais-new-voice-mode-makes-it-to-the-chatgpt-desktop-app/>
