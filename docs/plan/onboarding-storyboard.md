# Onboarding storyboard: from "never heard of it" to "it works"

The whole first-run journey for someone who knows nothing about Vox and has never seen this repo: no
clone, no Xcode, no Python, no API keys, no Claude Code. Each frame lists what they see, what they
do, and what we're assuming they already know. Wherever that assumption isn't safe, it's a **gap**.

Status key: ✅ works today · 🟡 works with a catch · ❌ missing.

## The persona

Sam has a Mac (Apple Silicon, macOS 14+). They saw a Vox demo and want to try it. They can paste one
line into Terminal if told exactly what to paste, but they've never used `git`, `uv` or Homebrew. They
may have a ChatGPT or Claude subscription, or no AI account at all.

## Frames

### 1. Hears about Vox → lands on the README

| | |
|---|---|
| Sees | The GitHub README. |
| Does | Looks for a download button or one line to paste. |
| Today | 🟡 Built: an **Install** section at the top of the README with the one line, `curl -fsSL https://raw.githubusercontent.com/DanielAllenRoberts/vox-controller/main/install.sh \| bash`, plus how to uninstall. It only works once this branch is on `main` and a release exists (G3). |

### 2. Runs the one-line install

| | |
|---|---|
| Sees | Terminal output: what's being downloaded, where it's going, how big. |
| Does | Waits about a minute. |
| Today | ✅ `install.sh` (G2): checks Apple Silicon, macOS 14+ and 3 GB free, downloads `Vox.zip` from the latest GitHub release, puts Vox.app in `/Applications` (or `~/Applications` if that isn't writable), and opens it. An update closes only the copy it's replacing. curl downloads aren't quarantined, so the unsigned app opens without Gatekeeper's "could not verify" block. |
| Today | 🟡 `scripts/release.sh` (G3) builds the 23 MB `app/build/Vox.zip` (engine source plus `uv`), refusing if `src/`, `mcp/` or the lockfile have uncommitted changes. `--publish` creates the GitHub release. **Not published yet: needs the user's go-ahead.** |
| Gap G15 | Vox.app is ad-hoc signed. That's fine through curl, but a browser download of the zip is quarantined and blocked. A Developer ID plus notarisation would fix it (Apple Developer account, $99 a year). Until then the README only offers the curl line. |

### 3. First launch: Welcome

| | |
|---|---|
| Sees | "Welcome to Vox" and three bullets: on-device, about five minutes, lives in the menu bar. |
| Does | Get Started. That starts the engine install in the background. |
| Today | ✅ |

### 4. Microphone permission

| | |
|---|---|
| Today | ✅ Asks, polls every second, explains how to fix it if they denied it before. |

### 5. Accessibility permission

| | |
|---|---|
| Today | ✅ With the "already on but still says no" escape hatch. |
| Assumes | 🟡 They understand why a voice app wants Accessibility. The copy says why. |

### 6. Engine install ("Getting Vox ready")

| | |
|---|---|
| Today | ✅ Progress bar, details log, Try Again. |
| G4 ✅ | The first start also downloads the speech models, with no progress of its own. The step now shows a running clock ("Starting the speech engine… 1:12") and says the first start downloads about 0.6 GB, which takes a few minutes on a slow connection. |

### 7. Test your microphone (new)

| | |
|---|---|
| Sees | A live level bar that jumps when they talk, a line marking the speech threshold, "Vox can hear you" once they cross it, and the microphone picker. |
| Does | Says "testing, one, two, three". If the bar stays flat, picks another mic. |
| Today | ✅ Built 2026-11-17 (G5). The same meter is on the Home page of the Vox window. |

### 8. Choose a brain

| | |
|---|---|
| Sees | Claude subscription · Claude via API · ChatGPT models via API · Fast and cheap (DeepSeek plus Claude). "Keep my current setup" only appears if the brains already set up answer a test. |
| Does | Picks one. Pastes a key (with a **Get a key** link beside it), or signs in to Claude. |
| Today | ✅ Reworked 2026-11-17. |
| G6 ✅ | A fresh install's defaults (DeepSeek plus Claude Code) need accounts a new user doesn't have. Vox now tests the current setup quietly first. If it doesn't answer, "Keep my current setup" stays hidden and Claude subscription is selected, with no red error for a setup they never chose. |
| G7 ✅ | **ChatGPT models via API**: an OpenAI key. The models are read from the account (its newest `gpt-N…-mini` for everyday replies, the newest full model for hard ones) rather than hard-coded. The copy says a ChatGPT plan doesn't cover it. |
| G8 ✅ | **Claude subscription** no longer needs Claude Code installed. The engine's Agent SDK ships its own `claude`, which shares the sign-in. **Sign in to Claude…** opens a Terminal window running `claude auth login --claudeai` (through a `.command` file, so no Automation permission), then **Check Again**. |
| G9 ✅ | A **Get a key** link beside every key field (Anthropic, OpenAI, DeepSeek). |
| G10 ✅ | "No AI account? Choose Set Up Later: Vox's built-in commands work without one." |
| Not tested live | Pressing Sign in to Claude: this Mac is already signed in, and signing in again would replace that login. The script it writes was checked by reading it. Choosing ChatGPT with a real OpenAI key: no OpenAI key on this Mac. |

### 9. Pick a voice

| | |
|---|---|
| Today | ✅ Kokoro voices with previews. |
| G11 ✅ | With no engine there are no voices to play, `say` ones included (previews go through the engine). It now says so and points to Settings → Voice for later, and Vox keeps using the Mac's own voice. |
| Gap G12 | No mention of ElevenLabs (the key store knows `ELEVENLABS_API_KEY`). Optional, low priority. |

### 10. Connect your apps

| | |
|---|---|
| Today | ✅ Mac Calendar, MCP servers (Composio etc.), Spotify. |
| Gap G13 | 🟡 "Add an MCP server by URL or command" assumes they know what MCP is. One-click presets (Composio, Notion) with "what this lets Vox do" would help. |

### 11. A little about you

| | |
|---|---|
| Today | ✅ |

### 12. Say hello

| | |
|---|---|
| Today | ✅ Now shows the live mic meter while it waits, so silence is visibly "no sound", not "broken". |

### 13. Done

| | |
|---|---|
| Today | ✅ Teaches "take control", "Hey Vox", "start typing". |
| G14 ✅ | Now also says "Or hold the right ⌥ Option key, talk, and let go. No wake word needed." |

## Open gaps, in order

1. **G3: publish the first release** (user's call), then merge so the README's install line resolves.
2. **G13, G12: nice to have.**
3. **G15: Developer ID signing and notarisation** (needs an Apple Developer account).

## Progress log

- **2026-11-17**: Storyboard written. **G5 done**: the engine records each mic frame's loudness
  (`audio.level()`), and `GET /api/mic/level` reports it on a 0–1 scale with the speech threshold.
  `MicLevelMeter` (SwiftUI) polls it. It's used in a new **Test your microphone** onboarding step
  (with the mic picker), in **Say hello**, and in a **Microphone** card on the Vox window's Home page.
  Tests: `tests/test_mic_level.py`. Checked live against the running engine and with `Vox --snapshot`.
- **2026-11-17** (side fix, reported live): a mis-heard "Hey Vox, open Claude" ("i think lord") came
  back from the brain as DICTATE, so the next four commands were typed into the terminal. Dictation
  now only starts when the words themselves ask to type (`executor._ASKS_TO_TYPE`). Test:
  `tests/test_dictate_guard.py`. Still open: a way out of dictation that doesn't rely on knowing to
  say "stop typing", e.g. "Vox, open Claude" while dictating runs as a command.
- **2026-11-17**: **G1, G2 built; G3 ready but not published.** `install.sh` and `scripts/release.sh`
  added, with the install line at the top of the README. Checked: `release.sh` builds a 23 MB zip.
  `install.sh` with `VOX_ZIP_URL=file://…` installs into a scratch folder, keeps a valid signature
  and leaves no quarantine flag. Running it twice updates in place, and a bad URL or a missing
  release fails with a plain message. The bundled engine was installed the way first launch does
  it (bundled `uv`, `sync --frozen --no-dev`, managed Python 3.12) and `import vox, faster_whisper,
  sounddevice` passed. Not tested: opening the installed copy, since a second Vox would fight the
  running one over the mic and port 8765.
- **2026-11-17**: **G6–G10 done** (brain step). Checked with `Vox --snapshot` in three states:
  checking the current setup; subscription selected and not signed in (Sign in and Check Again
  buttons); Fast and cheap with two key fields. All three fit the fixed 620-point window. The copy
  was cut twice to make that true.
- **2026-11-17**: **G4, G11, G14 done.** Checked with `Vox --snapshot` (engine, voice and done steps).
