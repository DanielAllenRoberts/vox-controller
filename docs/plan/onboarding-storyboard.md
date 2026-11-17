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
| Today | ❌ The README's "Getting started" begins with `app/build.sh`, which needs a clone, the Xcode Command Line Tools and Swift. The terminal route needs `uv`. Nothing to download. |
| Gap G1 | A one-line install at the top of the README: `curl -fsSL https://raw.githubusercontent.com/DanielAllenRoberts/vox-controller/main/install.sh \| bash` |

### 2. Runs the one-line install

| | |
|---|---|
| Sees | Terminal output: what's being downloaded, where it's going, how big. |
| Does | Waits about a minute. |
| Today | ❌ No `install.sh`, no published build. |
| Gap G2 | `install.sh`: checks macOS version and Apple Silicon, downloads the latest `Vox.zip` from GitHub Releases, unzips it to `/Applications` (or `~/Applications` without admin rights), and opens it. Files curl downloads aren't quarantined, so the unsigned app opens without the "can't be checked for malicious software" wall a browser download hits. |
| Gap G3 | A release to download: `scripts/release.sh` runs `app/build.sh --bundle-engine`, zips `Vox.app` and uploads it with `gh release create`. Publishing needs the user's go-ahead: it's a push. |
| Assumes | They have about 2 GB free (app plus private Python plus speech models). The script should check and say so. |

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
| Gap G4 | 🟡 The first start downloads the Whisper and Kokoro models too. On a slow connection, "Loading speech models. The first start can take a minute" can be much longer than a minute, with no progress. The copy should say it's downloading, and roughly how much. |

### 7. Test your microphone (new)

| | |
|---|---|
| Sees | A live level bar that jumps when they talk, a line marking the speech threshold, "Vox can hear you" once they cross it, and the microphone picker. |
| Does | Says "testing, one, two, three". If the bar stays flat, picks another mic. |
| Today | ✅ Built 2026-11-17 (G5). The same meter is on the Home page of the Vox window. |

### 8. Choose a brain

| | |
|---|---|
| Sees | Four options: Keep my current setup · Fast and cheap (DeepSeek plus Claude API) · Claude via API · Claude subscription. |
| Today | 🟡 Works for people who already have the right accounts. |
| Gap G6 | "Keep my current setup" means nothing to a new user. On a fresh install the defaults are DeepSeek (needs a key they don't have) plus the Claude subscription (needs Claude Code). Hide it on a fresh install, or make it pick a working default. |
| Gap G7 | No OpenAI/ChatGPT option, though the engine supports `openai` and `chatgpt` providers. Many people have an OpenAI key or a ChatGPT plan rather than Anthropic. |
| Gap G8 | "Claude subscription" says "Install it from claude.com/code, then run `claude` once". A zero-knowledge user can't act on that. Give them a button that opens the install page, and a "Check again" that re-runs the sign-in check. |
| Gap G9 | No "where do I get a key?" link next to each key field (console.anthropic.com, platform.deepseek.com, platform.openai.com). |
| Gap G10 | No way to say "I have no AI account". Vox still does a lot without a brain (the command database and the Vosk fast lane). Say so, and let them continue. |

### 9. Pick a voice

| | |
|---|---|
| Today | ✅ Kokoro voices with previews. |
| Gap G11 | 🟡 "Voices appear once the engine is running" is a dead end if the engine failed. Fall back to the macOS `say` voices. |
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
| Gap G14 | 🟡 Doesn't mention hold Right ⌥ to talk, which is the most reliable way in. |

## Open gaps, in order

1. **G1–G3: one-line install plus a release.** Without this nobody outside can start. Highest value.
2. **G6, G10: fresh-install brain choice that can't strand them.**
3. **G8, G9: help links for keys and Claude Code.**
4. **G7: OpenAI/ChatGPT preset.**
5. **G4, G11, G14: copy and fallback fixes.**
6. **G13, G12: nice to have.**

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
