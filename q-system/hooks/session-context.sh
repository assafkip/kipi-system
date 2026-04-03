#!/bin/bash
set -euo pipefail

# Session context injection - runs on SessionStart (startup)
# Injects today's date, last handoff summary, and energy mode
# Exit 0 always (never blocks)

PROJ_DIR="${CLAUDE_PROJECT_DIR:-.}"
QROOT="$PROJ_DIR/q-system"

echo "=== Session Context ==="
echo "Date: $(date '+%Y-%m-%d %A')"
echo ""

# Last handoff (first 50 lines)
HANDOFF="$QROOT/memory/last-handoff.md"
if [ -f "$HANDOFF" ] && [ -s "$HANDOFF" ]; then
  echo "--- Last Session Handoff ---"
  head -50 "$HANDOFF"
  echo ""
fi

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
