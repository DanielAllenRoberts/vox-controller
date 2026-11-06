# App Onboarding & Packaging — Research for the Vox.app overhaul

How shipped open-source Mac apps do first-run onboarding, permissions, and Python-env bootstrap,
distilled into patterns for Vox's planned SwiftUI shell (SwiftPM, no Xcode) that owns the Python
daemon as a child process and bootstraps it with a bundled `uv` into `~/Library/Application Support/Vox`.

Researched 2026-11. Sources were read at source level (links at each section).

> **Licence warning.** VoiceInk and ComfyUI Desktop are **GPL-3.0**; Vox is **MIT**. Copy *patterns
> and API names* (not copyrightable), never paste their code. The snippets below are our own minimal
> API-call examples. Clicky and OpenClicky are MIT.

---

## 1. Permission APIs (check without prompting / request / deep link)

Deep-link anchors were checked on macOS **26.6 (Tahoe)** without opening anything: the System Settings
privacy extension (`SecurityPrivacyExtension.appex`) still declares
`legacyBundleIdentifier = com.apple.preference.security`, its binary contains the anchors
`Privacy_Microphone`, `Privacy_Accessibility`, `Privacy_ScreenCapture`, `Privacy_Automation`, and its
`TCCServiceList.plist` maps `Privacy_ListenEvent` (Input Monitoring). VoiceInk ships the legacy URL
form today. The new form `x-apple.systempreferences:com.apple.settings.PrivacySecurity.extension?<anchor>`
should also resolve. **Still to do:** click each link once on Tahoe to confirm it lands on the right sub-pane.

| Permission | Check (no prompt) | Request | Deep link |
|---|---|---|---|
| Microphone | `AVCaptureDevice.authorizationStatus(for: .audio)` (or `AVAudioApplication.shared.recordPermission`, macOS 14+) | `AVCaptureDevice.requestAccess(for: .audio)`. Prompts only when `.notDetermined`; if `.denied`, open Settings | `x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone` |
| Accessibility (AX + `CGEventPost`) | `AXIsProcessTrusted()` | `AXIsProcessTrustedWithOptions([kAXTrustedCheckOptionPrompt: true])`, then open the pane and **poll** | `...?Privacy_Accessibility` |
| Screen Recording | `CGPreflightScreenCaptureAccess()` | `CGRequestScreenCaptureAccess()`. If it returns false, call `SCShareableContent.excludingDesktopWindows(...)` to get the app *listed*, then open the pane | `...?Privacy_ScreenCapture` |
| Post events only | `CGPreflightPostEventAccess()` | `CGRequestPostEventAccess()` (lands in the Accessibility list) | `...?Privacy_Accessibility` |
| Input Monitoring | `CGPreflightListenEventAccess()` | `CGRequestListenEventAccess()` | `...?Privacy_ListenEvent` |
| Automation (Apple Events) | `AEDeterminePermissionToAutomateTarget(target, typeWildCard, typeWildCard, false)` | Same call with `askUserIfNeeded: true`, or just the first real `osascript` call | `...?Privacy_Automation` |

**Vox needs:** Microphone (required), Accessibility (required: Vox reads the AX tree and posts events with
`CGEventPost`/`CGEventPostToPid` in `src/vox/input.py` and `src/vox/ax.py`), Automation (per target app,
prompted lazily on first `osascript` use), Screen Recording (optional, for screenshots/vision).
**Input Monitoring is not needed:** Vox posts events but never taps or listens to the keyboard. Revisit
if a global hotkey is added via `CGEventTap`.

Minimal Swift (our own):

```swift
import AVFoundation, ApplicationServices, CoreGraphics, ScreenCaptureKit, AppKit

func micStatus() -> AVAuthorizationStatus { AVCaptureDevice.authorizationStatus(for: .audio) }
func requestMic() async -> Bool { await AVCaptureDevice.requestAccess(for: .audio) }

func axTrusted(prompt: Bool) -> Bool {
    AXIsProcessTrustedWithOptions([kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: prompt] as CFDictionary)
}

func requestScreenRecording() async -> Bool {
    if CGPreflightScreenCaptureAccess() || CGRequestScreenCaptureAccess() { return true }
    _ = try? await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true) // registers the app in the list
    return CGPreflightScreenCaptureAccess()
}

func openPane(_ anchor: String) {   // "Privacy_Accessibility", ...
    NSWorkspace.shared.open(URL(string: "x-apple.systempreferences:com.apple.preference.security?\(anchor)")!)
}
```

Polling, as VoiceInk does it: after the user clicks Allow, start a `Task` that re-checks every **1 s for
up to 60 s** and stops early once all required permissions are granted. Also re-check on
`NSApplication.didBecomeActiveNotification`, which fires when the user comes back from System Settings.

---

## 2. TCC attribution when Vox.app spawns the Python daemon (critical)

**Answer:** if Vox.app launches `python` directly as a child (`Process`/`posix_spawn`) and does **not**
disclaim it, TCC attributes the child's mic, Accessibility, Screen Recording and Automation access to
**Vox.app** (the "responsible process"). The grant, the prompt text and the System Settings entry all
belong to Vox.app, not to the uv-managed `python3.12` binary. **Confidence: high** for the mechanism,
**medium** on the details flagged below.

Evidence:
- Qt, ["The Curious Case of the Responsible Process"](https://www.qt.io/blog/the-curious-case-of-the-responsible-process)
  ([summary](https://mjtsai.com/blog/2025/07/07/the-curious-case-of-the-responsible-process/)) says
  "permissions are inherited by child processes". When a protected resource is accessed, TCC identifies the
  responsible process and "uses that as basis for requesting and persisting the result". Apps launched
  from Qt Creator needed their usage descriptions **added to Qt Creator** (the responsible process). You
  can inspect this with `sudo launchctl procinfo <pid> | grep responsible`.
- Apple DTS (Quinn), [forum thread 701094](https://developer.apple.com/forums/thread/701094): "TCC works
  hard to find the *responsible code* for any given privacy prompt". In that thread, a helper spawned by
  an app only got its camera/mic prompt once the keys were in the **parent app's** Info.plist.
- [t3code discussion #7268](https://github.com/pingdotgg/t3code/discussions/7268) is the exact Vox case: a
  Python `sounddevice` child (and `ffmpeg`) of a desktop app. TCC resolved it to the parent app, which
  had no grant, so capture returned **digital silence** (-91 dB, all zeros) with no error and no prompt.
  Granting the python binary did nothing. The fix was for the parent app to request mic access itself.
- Disclaiming breaks the chain. The private `responsibility_spawnattrs_setdisclaim()` (used by LLDB,
  [Firefox](https://bugzilla.mozilla.org/show_bug.cgi?id=1576733) and Chromium) makes the child its own
  responsible process. One report says a disclaimed child then has no grants and
  [can't be prompted](https://claudeissues.com/issue/90373-bug-macos-desktop-hosted-claude-code-is-spawned-via-helpers-disclaimer-so-all-tc).
  **Vox must not disclaim.**
- On macOS 26.1+, plain Unix executables reportedly no longer appear in the Screen Recording / Full Disk
  Access lists at all ([forum 807323](https://developer.apple.com/forums/thread/807323)). A bare python
  process being responsible for itself is a dead end. The app bundle has to own the grants.

Rules that follow:
1. **The Swift app requests every permission itself** (mic, AX, screen) before it starts the daemon. Never
   rely on Python triggering the first prompt.
2. **Spawn with `Process()`** (posix_spawn) and run the venv's python directly
   (`<support>/venv/bin/python -m vox`). Running it under `uv run` is fine too, since uv is still in the tree.
   **Do not** launch the daemon via a LaunchAgent, `launchctl`, `SMAppService` or `open`. Those parent it
   to launchd, which makes python responsible for itself.
3. **Daemonising doesn't escape it.** Responsibility follows fork/exec in the tree. Keep the daemon a plain
   child and let the app supervise and restart it.
4. **Restart the daemon after any permission change.** A long-running process can keep a cached
   `AXIsProcessTrusted()` result after the entry is removed ([mousehop probe notes](https://docs.rs/crate/mousehop/0.13.0/source/src/macos_tcc_probe.rs)),
   and Screen Recording historically needs a relaunch to take effect. *Unverified:* whether restarting only
   the child, without relaunching Vox.app, is enough for Screen Recording on Tahoe. Test it.
5. **Dev trap:** if you run `Vox.app/Contents/MacOS/Vox` from Terminal, **Terminal** becomes responsible
   and every grant is checked against Terminal, which hides bugs. Launch dev builds with `open Vox.app`.

---

## 3. Signing, Info.plist, entitlements

**Info.plist usage keys do matter, and they must be on the responsible app (Vox.app):**
- `NSMicrophoneUsageDescription`: without it the mic request is denied (no prompt).
- `NSAppleEventsUsageDescription`: without it `osascript` to other apps fails with `-1743` and no prompt.
  Vox uses AppleScript heavily (`actions.py`, `agent.py`, `webdom.py`, `scheduler.py`).
- `NSScreenCaptureUsageDescription`: VoiceInk sets it; cheap to include.
- Accessibility has no usage key.
- `LSUIElement`: VoiceInk keeps it `false` and switches `NSApp.setActivationPolicy(.accessory/.regular)`
  at runtime for "menu-bar only" mode (`MenuBarManager.swift`). That's a good fit: a regular window during
  onboarding, then accessory mode.

**Hardened runtime (needed later for notarisation):** permissions used by the children are checked
against the *app's* entitlements. Qt's release note: children "will no longer inherit hardened runtime
entitlements" once disclaimed, which implies they do while attributed. So Vox.app needs
`com.apple.security.device.audio-input` and `com.apple.security.automation.apple-events`. VoiceInk's
`VoiceInk.entitlements` also has `screen-capture`, `network.client/server` and `app-sandbox = false`.
Don't sandbox: the sandbox forbids spawning a uv-managed python. The bundled `uv` Mach-O must be
codesigned with the app identity for notarisation.

**Ad-hoc signing (`codesign -s -`) pitfall:** TCC stores the app's *designated requirement*. For an
ad-hoc signature that requirement is the **cdhash**, which changes on every build. After a rebuild, the
System Settings entry still shows **ticked** but no longer applies, and toggling it doesn't fix it
(practitioner reports, e.g. [shannoncoat stable-identity commit](https://git.bdeshi.space/bdeshi/shannoncoat/src/tag/0.0.8)).
What to do in dev:
- Create a **self-signed "Code Signing" certificate** once (Keychain Access → Certificate Assistant) and
  run `codesign --force --options runtime --entitlements Vox.entitlements -s "Vox Dev" Vox.app`. The
  requirement then becomes identifier + cert, which survives rebuilds. Keep the bundle id fixed. Losing or
  rotating the cert resets every grant.
- Clean up stale rows with `tccutil reset Accessibility <bundle-id>` (and `Microphone`, `ScreenCapture`,
  `AppleEvents`).
- For release, use Developer ID + notarisation. Self-signed builds still trip Gatekeeper.

---

## 4. Onboarding flow: what VoiceInk does

Source: [`OnboardingPermissionModels.swift`](https://github.com/Beingpax/VoiceInk/blob/main/VoiceInk/Features/Onboarding/State/OnboardingPermissionModels.swift),
[`OnboardingPermissionController.swift`](https://github.com/Beingpax/VoiceInk/blob/main/VoiceInk/Features/Onboarding/State/OnboardingPermissionController.swift),
[`OnboardingFlowController.swift`](https://github.com/Beingpax/VoiceInk/blob/main/VoiceInk/Features/Onboarding/State/OnboardingFlowController.swift),
[`ScreenCaptureService.swift`](https://github.com/Beingpax/VoiceInk/blob/main/VoiceInk/Infrastructure/SystemIntegration/ScreenCapture/ScreenCaptureService.swift),
[`WhisperModelManager.swift`](https://github.com/Beingpax/VoiceInk/blob/main/VoiceInk/Features/ModelLibrary/State/WhisperModelManager.swift),
[`Info.plist`](https://github.com/Beingpax/VoiceInk/blob/main/VoiceInk/Info.plist). Licence: GPL-3.0.

- **Stages:** 1 Permissions → 2 Choose microphone → 3 Transcription model (download) → 4 Verify API key
  (*skippable with a warning*) → 5 "Experience it" (guided practice) → 6 Context awareness → 7 "Open
  source / private" trust → 8 Licence.
- **Permissions screen:** a single checklist of Microphone, Accessibility and Screen Recording, one row
  each with "Allow / Open Settings / Done". **Required = mic + accessibility.** Screen Recording is on the
  list but optional. Rows are *locked* until the earlier required ones are granted, and the active row
  jumps to the first missing required permission.
- **Status model:** `granted / needsAccess / denied / restricted / unknown`. For mic, `denied` or
  `restricted` switches the button from "Allow" to "Open Settings", because `requestAccess` won't prompt again.
- **Accessibility:** prompt via `AXIsProcessTrustedWithOptions`, *also* open the pane immediately, then poll.
- **Gating and persistence:** the current stage is stored in `@AppStorage`. On launch,
  `reconcileStage`/`goToFirstIncompleteSetupStep` sends the user back to the first unmet prerequisite, so
  revoking a permission later puts them back on the permissions step.
- **Model download:** `URLSession.downloadTask` with KVO on `task.progress.fractionCompleted`, UI updates
  throttled to at most every 0.5 s / 1%. The file is downloaded to a temp location, moved into place
  atomically, and partials are deleted on failure. No resume support.

Clicky / OpenClicky (MIT) add nothing new on permissions. OpenClicky's
[`ClaudeAgentSDKAPI.swift`](https://github.com/jasonkneen/openclicky/blob/main/cursor-buddy/ClaudeAgentSDKAPI.swift)
is useful for *finding the claude CLI* (see §6).

---

## 5. Python env bootstrap: what ComfyUI Desktop does

Source: [`virtualEnvironment.ts`](https://github.com/Comfy-Org/desktop/blob/main/src/virtualEnvironment.ts),
[`scripts/downloadUV.js`](https://github.com/Comfy-Org/desktop/blob/main/scripts/downloadUV.js),
[`installationManager.ts`](https://github.com/Comfy-Org/desktop/blob/main/src/install/installationManager.ts),
[`comfyInstallation.ts`](https://github.com/Comfy-Org/desktop/blob/main/src/main-process/comfyInstallation.ts),
[`troubleshooting.ts`](https://github.com/Comfy-Org/desktop/blob/main/src/install/troubleshooting.ts),
[`pythonImportVerifier.ts`](https://github.com/Comfy-Org/desktop/blob/main/src/services/pythonImportVerifier.ts),
[`installStages.ts`](https://github.com/Comfy-Org/desktop/blob/main/src/main-process/installStages.ts). Licence: GPL-3.0.

- **Bundling uv:** at build time it downloads a *pinned* uv release (`package.json config.uvVersion`)
  from `github.com/astral-sh/uv/releases/download/<ver>/uv-aarch64-apple-darwin.tar.gz` into `assets/uv/macos/uv`.
- **Creating the venv:** `uv venv --python 3.12 --python-preference only-managed`, which never picks up a
  Homebrew or system python. The venv is `<basePath>/.venv`, where basePath is a user-chosen folder.
  Environment: `VIRTUAL_ENV`, plus an optional `UV_PYTHON_INSTALL_MIRROR`.
- **Installing deps:** first try a pre-compiled, pinned requirements file
  (`uv pip install -r requirements.compiled --index-strategy unsafe-best-match` with fallback
  `--extra-index-url`s). If that exits non-zero, fall back to plain `requirements.txt`. Torch comes from a
  device-specific mirror (CPU/nightly for MPS). It's all just uv; nothing torch-specific beyond picking the index.
- **Progress:** coarse *stages* (`python_environment_setup`, `installing_requirements` at 25%,
  `installing_pytorch`, ...) with a percent and message, plus raw uv output streamed into a terminal view.
  Byte-level progress is never parsed.
- **Persistence and resume:** `installState` is set to `started` and becomes `installed` on success. If
  the app launches with `started`, it re-runs the install (the code has a TODO for true resume). Existing
  venvs are checked with `uv pip install --dry-run -r ...` and only the missing parts get installed.
- **Every-launch validation:** checks the base path, venv, uv and requirements, plus a Python import smoke
  test (runs a script that `__import__`s key modules and prints JSON). Any error opens a **Maintenance
  page** with one-click fixes: *reinstall requirements*, *clear uv cache* (`uv cache clean`), *reset venv*
  (delete + recreate). It also refuses unsafe locations: inside the app bundle, the updater cache, or OneDrive.

**Vox adaptation:** we already have `uv.lock`, so the better analogue is
`UV_PROJECT_ENVIRONMENT=<support>/venv UV_PYTHON_INSTALL_DIR=<support>/python UV_CACHE_DIR=<support>/uv-cache
uv sync --frozen --no-dev --python 3.12 --python-preference only-managed`, run against a copy of the
project bundled in `Contents/Resources`. That keeps everything self-contained in App Support, so an
uninstall removes it all. ComfyUI leaves python and cache in uv's global dirs.

---

## 6. External-tool check: claude CLI

- **Find it:** a Finder-launched app has a minimal `PATH` (`/usr/bin:/bin:/usr/sbin:/sbin`). OpenClicky
  checks fixed locations **first** (`~/.local/bin/claude`, `/opt/homebrew/bin/claude`,
  `/usr/local/bin/claude`) and only then scans `PATH`. Its comment explains why: wrappers that shim `PATH`
  often misbehave non-interactively. Allow an override env/setting.
- **Logged in?** `claude auth status --json` (current Claude Code) prints `{"loggedIn": true,
  "authMethod": "claude.ai", ...}`. Read `loggedIn`, and don't log the rest because it includes the account
  email. *Unverified:* the exit code when logged out. Parse the JSON rather than relying on it.
- If it's missing or logged out, offer: "Install Claude Code" (link) / run `claude auth login` in Terminal
  / use an API key / use local Ollama instead. Test the chosen brain with a 1-token request before moving on.

---

## 7. Recommended Vox onboarding order

1. **Welcome**: what Vox does, that it's local-first, and what will be downloaded (~1–1.5 GB).
   **Start the engine bootstrap in the background now** (`uv sync`, then model downloads) so it overlaps
   the permission steps.
2. **Microphone** (required). The app requests it itself, and the step shows a live level meter so the
   user sees it working.
3. **Accessibility** (required for control). Prompt + open pane + 1 s polling + `didBecomeActive` re-check.
4. **Brain**: detect claude CLI + `auth status`, otherwise API key / OpenAI-compatible / Ollama, with a test call.
   Skippable (dictation-only), with a warning, as VoiceInk does for API keys.
5. **Engine ready**: show install and model progress by stage (ComfyUI-style), with Retry / Repair / Show log.
6. **Try it**: say the wake word, get a spoken reply. This is the "aha" step VoiceInk ends on.
7. **Done**: switch to menu-bar (accessory) mode and start the daemon (only now, after the grants exist).

**Deferred until first needed:** Screen Recording (the first screenshot/vision request opens a sheet
explaining why), Automation (macOS prompts per target app on the first `osascript`, which can't be
batched), and launch at login (offer at the end, via `SMAppService.mainApp`, which registers the *app* and
not the daemon). **Skip:** Input Monitoring.

---

## 8. Top gotchas

1. **Silent mic.** If Vox.app never requested the mic itself, the python child records zeros with no
   error. The app must hold the grant, with `NSMicrophoneUsageDescription` and (when hardened)
   `device.audio-input` on the app.
2. **Ad-hoc signatures orphan grants on every rebuild.** Use a stable self-signed dev cert, and
   `tccutil reset` when an entry goes stale while still showing as ticked.
3. **Launch topology decides attribution.** Run the daemon via `Process()` as a child: no launchd, no
   disclaim. Don't launch dev builds from Terminal, or Terminal gets the grants. Restart the daemon after
   any permission change.
