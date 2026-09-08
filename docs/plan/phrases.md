# Vox — Known Phrases (cheat sheet)

> Everything Vox currently understands: the hard-coded phrases and command patterns. Keep in sync with `src/vox/config.py` and `src/vox/actions.py`. Matching is lowercased and punctuation-insensitive.

## Activation (from idle)

| Intent | Say | Notes |
|---|---|---|
| Enter **control** mode | "take control", "control mode", "start control" | |
| Enter **assistant** mode (LLM chat) | "Hey Vox" | multi-turn chat with Claude; + variants: hey vaux, hey vocks, a vox, hey fox, hey box |
| One-shot command | "Vox, <command>" — e.g. "Vox, open Safari" | runs one command from idle ("vox" + a command, no "hey") |
| **Dictation** from idle | "Vox start typing" | speak-to-type at the cursor; "stop typing" ends it (auto-exits on a long pause) |
| **Quit** Vox | "quit Vox", "close Vox", "exit Vox", "shut down Vox", "terminate Vox" | + quit/quick/close/exit/terminate × vox/fox/box variants (keyed to "vox" so idle chatter can't trigger it) |
| **Restart** Vox | "restart Vox", "reboot Vox" | re-runs the process (picks up code changes) |

## While in a mode

| Intent | Say |
|---|---|
| Back to idle (**sleep**) | "stand down", "go to sleep" |
| **Emergency stop** (any mode) | "terminate task", "emergency stop", "abort abort", "stop stop stop" → straight to idle |
| **Switch** control → assistant | "Hey Vox" |
| **Switch** assistant → control | "take control" |
| **Quit** | any quit phrase above (incl. "terminate Vox") |

## Control-mode commands

| Command | Say | Result |
|---|---|---|
| Open / go to | "open <app>", "go to <site>", "open a new <site>" | app if installed; known site **reuses an open tab** ("open new" forces a fresh one) |
| Search | "search <query>", "search for <query>" | web search in your browser |
| Switch browser tab | "go to my <name> tab" (**fuzzy**), "next/previous tab", "move up/down <n> tabs" | by name, or ⌘⌥↑↓ relative (stays in your profile) |
| Go back | "go back" | browser/app back (⌘[) |
| Switch app window | "next window", "switch to my <name> window" | cycles front app's windows (⌘`); can't cross macOS Spaces (needs Accessibility) |
| Switch desktop/Space | "**swipe right/left**", "next space/screen/desktop", "go to desktop <n>" | Ctrl+→/← (index needs the macOS shortcut enabled) |
| Cycle an app's windows | "cursor window", "next cursor window", "switch cursor" | crosses Spaces (Dock-click) |
| Switch Arc profile | "profile <n>", "next/previous profile" | Ctrl+<n> (absolute) or ⌘⌥←→ (relative) |
| Chain commands | "<cmd> and <cmd>" — e.g. "open Arc and search this" | runs both (only when both parse) |
| Close tab | "close tab", "close this tab" | ⌘W |
| Show/hide tabs | "show tabs", "hide tabs", "toggle sidebar" | toggles Arc's sidebar |
| **Scroll** | "scroll down", "scroll up", "scroll down 3", "scroll down five" | wheel scroll at the pointer (default 5 lines) |
| **Scroll to an end** | "scroll to the top", "scroll to the bottom" | ⌘↑ / ⌘↓ — a jump, not a pile of ticks |
| **Page** | "page up", "page down" | Page Up / Page Down |
| **Press a key** | "press command S", "press escape", "hit enter", "press command shift four" | spoken digits and modifier names work; an unknown key falls through to the LLM so "press submit" still means click |
| **Right click** | "right click Submit", "right click 14" | by control label, or a badge number from "show clickable" |
| **Double click** | "double click Inbox", "double click 7" | same targets as right click |
| **Drag** | "drag 3 to 7", "drag Inbox onto Archive" | either side a badge number or a label |
| **Set a value** | "set volume to 30", "set theme to dark" | sliders, text fields, checkboxes and dropdowns, set directly via AX |
| Dictation | "start typing" → speak → "stop typing" | types at the cursor; edit words: "new line"/"next line" (soft newline), "enter"/"send", "backspace", "delete that", "tab key" |
| (anything else / mis-worded / failed) | — | escalates to the **brain** (see below) — it acts if it can, asks if needed, or ignores chatter |

## AI handover (the brain)

Anything that isn't a known command — or a known command that finds no target — goes to the LLM ("brain"). It has your running apps + open tabs as context, runs Vox's actions itself, and **speaks** its replies (TTS).

| Intent | Say | Result |
|---|---|---|
| Write / compose text | "write me an email about X", "write a function that sums a list" | composes it and **types it at your cursor** |
| Rewrite selection | "make this pretty", "fix the spelling", "make it formal", "shorten this" | rewrites your **selected** text in place (copy → rewrite → paste) |
| See the screen | "what's on my screen?", "what does this say?", "read this error" | screenshots and describes what's on screen (needs Screen Recording permission) |
| Ask anything | any question, or a fuzzy/unknown request | the brain answers (spoken), or just does it if it's an action |
| Clarify | (it may ask, e.g. "what should I search?") | answer it — your reply keeps context until the task is done |

Small tasks use the **small brain** (fast); complex ones defer to the **big brain** automatically. Background chatter it can't action is **ignored** (no response).

## Known site aliases (for "go to X")

github · gmail · google · youtube · twitter/x · reddit · hacker news · chatgpt · claude · gemini · netflix · spotify · amazon · maps · calendar · drive · docs · notion · linear · slack · figma · stack overflow · wikipedia · twitch

Any real domain (e.g. "github.com") works too. Unknown bare words hand off rather than guessing.

## App-name aliases

chrome → Google Chrome · vs code / vscode / code → Visual Studio Code

## Under the hood

- The recognizer is **biased** (hotwords) toward this vocabulary so "Cursor" beats "Casa", "quit vox" beats "quick fox", etc.
- Default wake backend is **Whisper-wake** (transcribes nearby speech to spot these phrases). The trained **openWakeWord** backend is the efficient alternative (`config.wake_backend`).
- **Deterministic-first:** known phrases run instantly; everything else escalates to the brain. The brain **speaks** its replies (macOS `say`; toggle `tts_enabled`, set `tts_voice`).
