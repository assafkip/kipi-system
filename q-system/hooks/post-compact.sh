#!/bin/bash
set -euo pipefail

# Post-compaction context recovery
# Re-injects critical context that may have been stripped during compaction
# Exit 0 always (never blocks)

PROJ_DIR="${CLAUDE_PROJECT_DIR:-.}"
QROOT="$PROJ_DIR/q-system"

echo "=== Post-Compact Context Recovery ==="

# Current mode from progress.md
PROGRESS="$QROOT/my-project/progress.md"
if [ -f "$PROGRESS" ]; then
  MODE=$(grep -oE "(CALIBRATE|CREATE|DEBRIEF|PLAN)" "$PROGRESS" | tail -1 2>/dev/null || echo "READY")
  echo "Current mode: ${MODE:-READY}"
fi

# Open loop count
LOOP_SCRIPT="$QROOT/.q-system/loop-tracker.sh"
if [ -f "$LOOP_SCRIPT" ]; then
  STATS=$(bash "$LOOP_SCRIPT" stats 2>/dev/null || true)
  if [ -n "$STATS" ]; then
    echo "Loops: $STATS"
  fi
fi

# Voice reminder
echo ""
echo "REMINDER: All written output must use founder voice. No hedging, no filler, no AI words."
echo "REMINDER: Unvalidated claims must be marked {{UNVALIDATED}}."

exit 0
