# Apple Voice Control vs Vox — what to borrow, and where we already win

> **Date:** 2026-11-11 · **Branch:** `voice-control-ideas` · **Status:** iterations 1–2 built (ambiguous clicks, show names)
> **Sources:** Apple's Voice Control guide for macOS 26 ([commands][cmds], [overlays][ovl],
> [customise][cust], [settings][set]), the [2019 Tech Brief][brief], [MacMost][macmost],
> [TidBITS][tidbits], Apple Community threads on Tahoe overlay bugs ([1][bug1], [2][bug2]).

## How Voice Control works, in one screen

| Area | Voice Control | Vox today |
|---|---|---|
| **Item numbers** | "Show numbers" → badges in reading order; say the number (bare, or "click 12", "double-click 12", "control-click 12"). **One-shot by default**: gone after the command. "Show numbers continuously" keeps them up. Menu items are *always* numbered. | ✅ "show clickable" / "show numbers" → badges, "click 14" / "14". One-shot. No continuous mode, no double/right-click by number, menus not numbered. |
| **Item names** | "Show names" → each control's label drawn beside it, so you know what to say. | ✅ **NEW** — "show names" / "show labels": "14 Export" badges. |
| **Ambiguous names** | "Click Options" with three Options buttons → **numbers only the matches** and waits. Same for "replace X" when X appears twice. | ✅ **NEW (this branch)** — was: clicked whichever the tree walk reached first, then "no, the other one" re-offered. |
| **Grid** | "Show grid" / "Show window grid": 7×4 numbered cells; saying a number drills into that cell (with a magnifier when small); "click 17" acts and closes. "Start drag 10" … "Drop 9". | Vision agent instead (computer-use tool, 1.1 px error) — no user-driven grid. Drag exists as an intent but not by number. |
| **Modes** | Dictation (default; non-commands become text) · Command mode · Spelling mode (NATO) · Swift mode. | Control / assistant / dictation / auto-dictation (Dragon-style, off by default). No spelling mode. |
| **Command vs text** | Exact template match + ~0.5 s pause bracketing; "Type <phrase>" forces text. | Exact-only lookup + risk tiers in auto-dictation; LLM fallback for everything else. |
| **Text editing** | "select <phrase>", "replace X with Y", "insert X before Y", "delete <phrase>", "capitalize that", "move to end of line", "select next 3 words", "correct that" → numbered alternatives. **Only works on text Voice Control itself dictated** — the #1 complaint. | "scratch that", "undo that", EDIT: (LLM rewrite of the selection). No phrase-addressed editing. |
| **Feedback** | Menu-bar mic; a pill showing what it recognised; **"Show hints"** — near-miss speech shows suggested commands; a sound on recognition. | Bubble + cue; "Did you mean X?" for phonetic click picks. No near-miss *command* hints. |
| **Custom commands** | "When I say" + scope (any app / one app) + action (open item, URL, paste text, keyboard shortcut, **menu item**, Shortcut, Automator). **"Make this speakable"** pre-fills a command from the current selection/menu. Import/export. No parameters. Can't rename built-ins. | Command DB + TEACH by voice + automatic learning (trial). Built-ins *can* gain phrases. No "make this speakable" capture; no Shortcuts action. |
| **Vocabulary** | Static list, + "add to vocabulary" on a selection; record a pronunciation (Sequoia+). No learning. | ✅ replacement dictionary + background mis-hear learning (ahead). |
| **Help** | "Show commands" (context-sensitive window), iOS "what can I say". | "Try saying" tips in the app; no in-context "what can I say here". |

## Where Vox already beats it

- **Edits any text, not just its own dictation** (EDIT: reads the real selection). Voice Control's
  "‹text› not found!" in typed documents is its most-reported failure.
- **Natural language.** Voice Control's grammar is rigid ("look up the variants"); Vox's LLM tier
  catches anything the templates don't.
- **Learns.** Vocabulary and commands adapt; Voice Control never does.
- **Web/Electron.** Vox reads the DOM directly and re-asserts collapsed Electron trees; Voice
  Control's numbers are flaky in Gmail/Outlook/Firefox and its only fallback is the grid.

## What to borrow — ranked, and what each iteration of the loop picks up

1. ✅ **Number the matches when a name is ambiguous** (iteration 1, below).
2. ✅ **"Show names"** (iteration 2) — draw labels instead of numbers. Cheap: same overlay, same targets list; shows
   the user *what to say*, and doubles as an AX debugging view.
3. **Verbs by number** — "double-click 12", "right-click 12" while numbers are up (we already have
   `double_click` / `right_click` intents; they just don't take a badge number).
4. **Phrase-addressed text editing on real text** — "select ‹phrase›", "replace X with Y",
   "delete ‹phrase›", "capitalize ‹phrase›", "insert X after Y" — via the focused field's AX value +
   `AXSelectedTextRange`, so it works on text Vox didn't type (beats Voice Control). Ambiguous
   phrase → number the occurrences, same as #1.
5. **Near-miss command hints** — when a command misses, show the 1–3 closest real commands in the
   bubble (we already have the fuzzy matcher for Vosk snapping).
6. **"What can I say here"** — the app's commands from the command DB + numbered visible targets.
7. **"Make this speakable"** — capture the current menu item / selection into a TEACH command.
8. **Continuous numbers** ("show numbers continuously") with fade-on-idle, refreshed on focus change.
9. **Start drag N … drop M.**

Not borrowing: the grid (the vision agent does it better), spelling mode (rare for this user),
Attention Aware (iOS camera feature).

## Iteration 1 — ambiguous clicks number the matches (2026-11-11)

**Before:** "click Send" with two Send buttons clicked whichever the depth-first walk reached first;
you found out it was the wrong one afterwards and had to say "no, the other one".

**Now:** voice clicks (`run_intent("click")`, the executor's `CLICK:`) pass
`ask_if_ambiguous=True`. The AX walk (`ax.click`) and the in-page DOM matcher
(`targets.click_label`) keep going past the first **exact** match; a second, *separate* exact match
returns `("ambiguous", label)` without pressing anything. `targets.offer_choices` then numbers just
those controls with the existing overlay, and the existing overlay flow handles the spoken number.
The bubble says "Which one? There are 2 called 'Send' — say a number." Silent, like "show
clickable" (avoids the TTS → mic stall).

**What counts as "separate":** exact label (case-insensitive) only — substring matches never ask;
frames that overlap are one control (a button and the text inside it); slivers under 4 px are
ignored (Slack keeps clipped sticky headers in the tree at 1 px tall — counting them turned one
"Jump to date" into two); off-screen frames are ignored. If the chooser can't confirm two visible
ones, it clicks as before. The screen agent and the MCP `click` tool are unchanged (they can't
answer a spoken number).

**Side fix:** a plain click now skips a leading 1-px sliver in favour of a real control with the same
label — measured on a live Slack, a person's name appeared both as a 1-px clipped header button and
as the real sidebar entry, and the sliver came first in the walk.

**Measured on live apps (read-only survey):** of ~170 Slack targets, the only remaining exact
duplicate is a pair of "active" status icons. Finder, Cursor, Notion, Obsidian, Spotify: none.

**Tests:** `tests/test_click_choices.py` (11, fake AX tree). **Not yet voice-tested** — see to-test.md.

## Iteration 2 — "show names" (2026-11-11)

"show names" / "show labels" / "show item names" draw the same overlay as "show numbers", but each
badge reads **"14 Export"** on a dark plate (blue = numbers only, so the two modes are told apart at a
glance). Numbers still work while names are up ("14", "click 14"); saying a name dismisses the
overlay and clicks by name as usual; "hide names" / "hide labels" dismiss it. The phrases are on the
Vosk fast lane alongside "show clickable".

Labels are one line, capped at 28 characters. Name badges are wider than their controls, so
neighbours in a menu bar or toolbar covered each other's names — the helper now nudges an
overlapping name badge down a row (up to three) before drawing it (`overlay._nudge`). Number badges
are unchanged.

**Checked:** rendered off-screen against Finder's and Slack's real AX targets (menu bar: "1 Apple",
"2 Slack" on the row below, …). Background Electron apps only expose their menu bar, so a dense
in-window test needs the app in front — on the to-test list. **Tests:** `tests/test_show_names.py` (6).

[cmds]: https://support.apple.com/guide/mac-help/use-voice-control-commands-mh40719/26/mac
[ovl]: https://support.apple.com/en-asia/guide/mac-help/mchl26854b08/12.0/mac
[cust]: https://support.apple.com/guide/mac-help/mchl9899c8a5
[set]: https://support.apple.com/en-is/guide/mac-help/change-voice-control-settings-spc002/26/mac/26
[brief]: https://apple.com/accessibility/pdf/Voice_Control_Tech_Brief_Sept_2019.pdf
[macmost]: https://macmost.com/20-voice-control-dictation-tips.html
[tidbits]: https://tidbits.com/2020/08/31/how-ios-and-macos-dictation-can-learn-from-voice-controls-dictation/
[bug1]: https://discussions.apple.com/thread/256317435
[bug2]: https://discussions.apple.com/thread/254840973
