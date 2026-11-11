#!/usr/bin/env bash
set -euo pipefail

PORT="${1:-5173}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
APP_DIR="$SKILL_DIR/assets/gongwen"

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
npm run dev -- --host 127.0.0.1 --port "$PORT"
