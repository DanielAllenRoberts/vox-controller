#!/usr/bin/env bash
# Builds Vox.app from this package.
#
#   app/build.sh                  dev build → app/build/Vox.app, runs the engine from this checkout
#   app/build.sh --release        optimised build
#   app/build.sh --bundle-engine  self-contained app for download: ships the engine source and uv,
#                                 so first launch installs everything (implies --release)
#
# Signing is ad-hoc with a bundle-id designated requirement, so privacy permissions survive
# rebuilds (see the codesign line at the end). A release for other people needs a Developer ID +
# notarising.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/.." && pwd)"
config=debug
bundle_engine=0
for arg in "$@"; do
  case "$arg" in
    --release) config=release ;;
    --bundle-engine) bundle_engine=1; config=release ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

cd "$here"
swift build -c "$config"
bin="$(swift build -c "$config" --show-bin-path)/Vox"

app="$here/build/Vox.app"
rm -rf "$app"
mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources"
cp "$bin" "$app/Contents/MacOS/Vox"

version="$(sed -n 's/^version = "\(.*\)"/\1/p' "$repo/pyproject.toml" | head -1)"
cat > "$app/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Vox</string>
  <key>CFBundleDisplayName</key><string>Vox</string>
  <key>CFBundleIdentifier</key><string>app.vox.mac</string>
  <key>CFBundleExecutable</key><string>Vox</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>${version:-0.0.1}</string>
  <key>CFBundleVersion</key><string>$(date +%Y%m%d%H%M)</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>LSMinimumSystemVersion</key><string>14.0</string>
  <key>LSApplicationCategoryType</key><string>public.app-category.productivity</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSMicrophoneUsageDescription</key><string>Vox listens for your voice commands. Speech is recognised on this Mac.</string>
  <key>NSAppleEventsUsageDescription</key><string>Vox controls apps like Safari and Finder when you ask it to by voice.</string>
  <key>NSScreenCaptureUsageDescription</key><string>Vox looks at the screen only when you ask it about what's there.</string>
</dict>
</plist>
PLIST

# Icon (drawn by script, cached between builds).
icns="$here/build/AppIcon.icns"
if [ ! -f "$icns" ] || [ "$here/scripts/make-icon.swift" -nt "$icns" ]; then
  tmp="$(mktemp -d)"
  swift "$here/scripts/make-icon.swift" "$tmp/AppIcon.iconset" >/dev/null
  iconutil -c icns "$tmp/AppIcon.iconset" -o "$icns"
  rm -rf "$tmp"
fi
cp "$icns" "$app/Contents/Resources/AppIcon.icns"

if [ "$bundle_engine" = 1 ]; then
  engine="$app/Contents/Resources/engine"
  mkdir -p "$engine" "$app/Contents/Resources/bin"
  rsync -a --exclude '__pycache__' --exclude '*.pyc' "$repo/src" "$repo/mcp" "$engine/"
  cp "$repo/pyproject.toml" "$repo/uv.lock" "$repo/README.md" "$repo/LICENSE" "$engine/"
  uv_bin="$(command -v uv || true)"
  [ -n "$uv_bin" ] || { echo "uv not found; install it to bundle the engine" >&2; exit 1; }
  cp "$uv_bin" "$app/Contents/Resources/bin/uv"
fi

# Ad-hoc signing pins the app's identity to this exact build's hash, so macOS dropped the Microphone
# and Accessibility grants on every rebuild ("Failed to match existing code requirement" in tccd's
# log, while System Settings still showed Vox switched on). An explicit designated requirement makes
# macOS recognise Vox by its bundle id instead, so grants survive rebuilds. Fine for a local build;
# a build for other people should be Developer ID signed and notarised.
codesign --force --deep --sign - -r='designated => identifier "app.vox.mac"' "$app" >/dev/null
echo "built $app ($config$( [ "$bundle_engine" = 1 ] && echo ', engine bundled'))"
