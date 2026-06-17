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
| Open / go to | "open <app>", "go to <app or site>" | app if installed, else a **known** site/domain (new browser tab) |
| Search | "search <query>", "search for <query>" | web search in your browser |
| (anything else) | — | "handing off to the assistant" (no guessing) |

## Known site aliases (for "go to X")

github · gmail · google · youtube · twitter/x · reddit · hacker news · chatgpt · claude · gemini · netflix · spotify · amazon · maps · calendar · drive · docs · notion · linear · slack · figma · stack overflow · wikipedia · twitch

Any real domain (e.g. "github.com") works too. Unknown bare words hand off rather than guessing.

## App-name aliases

chrome → Google Chrome · vs code / vscode / code → Visual Studio Code

## Under the hood

- The recognizer is **biased** (hotwords) toward this vocabulary so "Cursor" beats "Casa", "quit vox" beats "quick fox", etc.
- Default wake backend is **Whisper-wake** (transcribes nearby speech to spot these phrases). The trained **openWakeWord** backend is the efficient alternative (`config.wake_backend`).
