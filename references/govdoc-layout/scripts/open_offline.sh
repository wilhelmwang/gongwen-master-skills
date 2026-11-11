#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
OFFLINE_HTML="$SKILL_DIR/assets/gongwen-offline.html"
RELEASE_HTML="$SKILL_DIR/assets/gongwen-release.html"

if [ -f "$OFFLINE_HTML" ]; then
  TARGET="$OFFLINE_HTML"
else
  TARGET="$RELEASE_HTML"
fi

if [ ! -f "$TARGET" ]; then
  printf 'No offline HTML found. Run scripts/build_offline.sh first.\n' >&2
  exit 1
fi

if command -v open >/dev/null 2>&1; then
  open "$TARGET"
else
  printf '%s\n' "$TARGET"
fi
