# Vox — Known Phrases (cheat sheet)

> Everything Vox currently understands: the hard-coded phrases and command patterns. Keep in sync with `src/vox/config.py` and `src/vox/actions.py`. Matching is lowercased and punctuation-insensitive.

## Activation (from idle)

| Intent | Say | Notes |
|---|---|---|
| Enter **control** mode | "take control", "control mode", "start control" | |
| Enter **assistant** mode | "Hey Vox" | + variants Whisper may hear: hey vaux, hey vocks, a vox, hey fox, hey box |
| **Quit** Vox | "quit Vox", "close Vox", "exit Vox", "shut down Vox" | + quit/quick/close/exit × vox/fox/box variants (keyed to "vox" so idle chatter can't trigger it) |

## While in a mode

| Intent | Say |
|---|---|
| Back to idle (**sleep**) | "stand down", "go to sleep" |
| **Switch** control → assistant | "Hey Vox" |
| **Switch** assistant → control | "take control" |
| **Quit** | any quit phrase above |

## Control-mode commands

| Command | Say | Result |
|---|---|---|
| Open / go to | "open <app>", "go to <site>", "open a new <site>" | app if installed; known site **reuses an open tab** ("open new" forces a fresh one) |
| Search | "search <query>", "search for <query>" | web search in your browser |
| Switch browser tab | "go to my <name> tab" (**fuzzy** — mishears OK), "next/previous tab" | by name is reliable; index ("tab 10") is unreliable in Arc (52 tabs span spaces) |
| Switch app window | "next window", "switch to my <name> window" | cycles front app's windows (⌘`); can't cross macOS Spaces (needs Accessibility) |
| Switch desktop/Space | "next desktop", "previous desktop", "go to desktop <n>" | Ctrl+→/← (index needs the macOS shortcut enabled) |
| Show/hide tabs | "show tabs", "hide tabs", "toggle sidebar" | toggles Arc's sidebar |
| (anything else) | — | "handing off to the assistant" (no guessing) |

## Known site aliases (for "go to X")

github · gmail · google · youtube · twitter/x · reddit · hacker news · chatgpt · claude · gemini · netflix · spotify · amazon · maps · calendar · drive · docs · notion · linear · slack · figma · stack overflow · wikipedia · twitch

Any real domain (e.g. "github.com") works too. Unknown bare words hand off rather than guessing.

## App-name aliases

chrome → Google Chrome · vs code / vscode / code → Visual Studio Code

## Under the hood

- The recognizer is **biased** (hotwords) toward this vocabulary so "Cursor" beats "Casa", "quit vox" beats "quick fox", etc.
- Default wake backend is **Whisper-wake** (transcribes nearby speech to spot these phrases). The trained **openWakeWord** backend is the efficient alternative (`config.wake_backend`).
