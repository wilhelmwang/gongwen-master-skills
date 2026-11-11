#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
APP_DIR="$SKILL_DIR/assets/gongwen"
OUTPUT_PATH="${1:-$SKILL_DIR/assets/gongwen-offline.html}"

cd "$APP_DIR"

fix_macos_native_bindings() {
  if [ "$(uname -s)" != "Darwin" ] || ! command -v codesign >/dev/null 2>&1; then
    return 0
  fi

  find node_modules -type f -name '*.node' \
    \( -path '*/@rollup/*' -o -path '*/@rolldown/*' \) \
    -exec codesign --force --sign - {} >/dev/null 2>&1 \; || true
}

if [ ! -d node_modules ]; then
  npm ci || npm install
fi

fix_macos_native_bindings
if SINGLE_FILE=1 npm run build:single; then
  cp dist/index.html "$OUTPUT_PATH"
else
  RELEASE_HTML="$SKILL_DIR/assets/gongwen-release.html"
  if [ ! -f "$RELEASE_HTML" ]; then
    exit 1
  fi
  cp "$RELEASE_HTML" "$OUTPUT_PATH"
  printf 'Local build failed; copied bundled release fallback.\n' >&2
fi
printf '%s\n' "$OUTPUT_PATH"
