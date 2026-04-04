#!/bin/bash
set -euo pipefail

# Session context injection - runs on SessionStart (startup)
# Injects today's date, last handoff summary, and energy mode
# Exit 0 always (never blocks)

PROJ_DIR="${CLAUDE_PROJECT_DIR:-.}"
# Auto-detect QROOT: subtree instances have q-system/q-system/, skeleton has q-system/
if [ -d "$PROJ_DIR/q-system/q-system/canonical" ]; then
  QROOT="$PROJ_DIR/q-system/q-system"
else
  QROOT="$PROJ_DIR/q-system"
fi

echo "=== Session Context ==="
echo "Date: $(date '+%Y-%m-%d %A')"
echo ""

# Last handoff is loaded by session-start.py (richer context with cards + loops).
# Skip here to avoid duplicate output.

# Energy mode from founder profile
PROFILE="$QROOT/my-project/founder-profile.md"
if [ -f "$PROFILE" ]; then
  ENERGY=$(grep -i "energy\|audhd\|adhd" "$PROFILE" | head -3 2>/dev/null || true)
  if [ -n "$ENERGY" ]; then
    echo "--- Founder Context ---"
    echo "$ENERGY"
    echo ""
  fi
fi

exit 0
