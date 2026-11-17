#!/usr/bin/env bash
# Install Vox with one line, no git clone, no developer tools:
#
#   curl -fsSL https://raw.githubusercontent.com/DanielAllenRoberts/vox-controller/main/install.sh | bash
#
# Downloads the latest Vox.app from GitHub Releases, puts it in /Applications (or ~/Applications
# when /Applications isn't writable) and opens it. Vox.app then walks you through the rest:
# permissions, a private copy of Python and the speech libraries, a brain, a voice.
#
# Files downloaded with curl aren't quarantined by macOS, so Vox opens without the "Apple could not
# verify Vox is free of malware" block a browser download of an unsigned app hits.
#
# Options (environment variables):
#   VOX_VERSION=v0.2.0   install that release instead of the latest
#   VOX_INSTALL_DIR=…    install somewhere else
#   VOX_NO_OPEN=1        don't open Vox afterwards
#   VOX_ZIP_URL=…        download Vox.zip from this URL (testing)
set -euo pipefail

repo="DanielAllenRoberts/vox-controller"
need_gb=3   # app + private Python + speech libraries + speech models, with room to spare

say() { printf '%s\n' "$*"; }
fail() { printf 'Vox install: %s\n' "$*" >&2; exit 1; }

# --- Can this Mac run Vox? ---
[ "$(uname -s)" = Darwin ] || fail "Vox runs on macOS only."
[ "$(uname -m)" = arm64 ] || fail "Vox needs an Apple Silicon Mac (M1 or later). This one is $(uname -m)."
major="$(sw_vers -productVersion | cut -d. -f1)"
[ "$major" -ge 14 ] || fail "Vox needs macOS 14 (Sonoma) or later. This Mac has $(sw_vers -productVersion)."
free_gb="$(df -g "$HOME" | awk 'NR==2 {print $4}')"
[ "${free_gb:-0}" -ge "$need_gb" ] || fail "Vox needs about ${need_gb} GB free, and this Mac has ${free_gb} GB. Free some space and run this again."

# --- Where it goes ---
if [ -n "${VOX_INSTALL_DIR:-}" ]; then
  dest="$VOX_INSTALL_DIR"
elif [ -w /Applications ]; then
  dest="/Applications"
else
  dest="$HOME/Applications"
fi
mkdir -p "$dest"
app="$dest/Vox.app"

if [ -n "${VOX_ZIP_URL:-}" ]; then
  url="$VOX_ZIP_URL"
elif [ -n "${VOX_VERSION:-}" ]; then
  url="https://github.com/$repo/releases/download/$VOX_VERSION/Vox.zip"
else
  url="https://github.com/$repo/releases/latest/download/Vox.zip"
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

# --- Download ---
say "Downloading Vox…"
if ! curl -fL --progress-bar -o "$tmp/Vox.zip" "$url"; then
  fail "couldn't download $url. Check your internet connection, or see https://github.com/$repo/releases."
fi
ditto -x -k "$tmp/Vox.zip" "$tmp/unzipped" || fail "the download looks damaged. Run this again."
[ -d "$tmp/unzipped/Vox.app" ] || fail "the download didn't contain Vox.app."

# --- Replace an older copy (an update) ---
# Only the copy being replaced: another Vox elsewhere (a developer build) is left alone.
running() { pgrep -f "$app/Contents/MacOS/Vox" >/dev/null; }
if running; then
  say "Closing the running Vox so it can be updated…"
  osascript -e "quit app \"$app\"" >/dev/null 2>&1 || true
  for _ in $(seq 1 20); do running || break; sleep 0.5; done
  running && fail "Vox is still running. Quit it from the menu bar icon, then run this again."
fi
rm -rf "$app"
mv "$tmp/unzipped/Vox.app" "$app"
xattr -dr com.apple.quarantine "$app" 2>/dev/null || true

say ""
say "Vox is installed in $dest."
if [ -z "${VOX_NO_OPEN:-}" ]; then
  open "$app"
  say "It's opening now. Follow the setup window; it takes about five minutes."
else
  say "Open it from $dest when you're ready."
fi
say "Afterwards Vox lives in your menu bar. To remove it, drag Vox to the Bin and delete"
say "~/Library/Application Support/Vox."
