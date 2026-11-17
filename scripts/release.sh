#!/usr/bin/env bash
# Build the downloadable Vox.zip that install.sh fetches, and optionally publish it.
#
#   scripts/release.sh             build app/build/Vox.zip (self-contained: engine source + uv)
#   scripts/release.sh --publish   …then create GitHub release v<version> with it (needs `gh`)
#
# The version comes from pyproject.toml. Publishing is public and permanent, so it's a separate
# flag: build, try the zip with `VOX_ZIP_URL=file://$PWD/app/build/Vox.zip bash install.sh`, then
# publish.
set -euo pipefail

repo="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo"
publish=0
for arg in "$@"; do
  case "$arg" in
    --publish) publish=1 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

# The bundle copies src/ and mcp/ from the working tree, so ship only what's committed: an
# uncommitted or untracked file there could be anything, including personal data.
if [ -n "$(git status --porcelain -- src mcp pyproject.toml uv.lock)" ]; then
  echo "src/, mcp/ or the lockfile has uncommitted changes. Commit or stash them first:" >&2
  git status --short -- src mcp pyproject.toml uv.lock >&2
  exit 1
fi

version="$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml | head -1)"
app/build.sh --bundle-engine
zip="app/build/Vox.zip"
rm -f "$zip"
ditto -c -k --sequesterRsrc --keepParent app/build/Vox.app "$zip"
echo "built $zip ($(du -h "$zip" | cut -f1), version $version)"

if [ "$publish" = 1 ]; then
  tag="v$version"
  gh release create "$tag" "$zip" --title "Vox $version" \
    --notes "Install with: curl -fsSL https://raw.githubusercontent.com/DanielAllenRoberts/vox-controller/main/install.sh | bash"
  echo "published $tag"
fi
