#!/bin/bash
set -euo pipefail

# Post-compaction context recovery
# Re-injects critical context that compaction may have stripped:
#   1. Current operating mode
#   2. Open loop summary
#   3. Canonical positioning snapshot (so Claude doesn't lose product knowledge)
#   4. Voice and validation reminders
# Exit 0 always (never blocks)

PROJ_DIR="${CLAUDE_PROJECT_DIR:-.}"
QROOT="$PROJ_DIR/q-system"

echo "=== Post-Compact Context Recovery ==="

# 1. Current mode
PROGRESS="$QROOT/my-project/progress.md"
if [ -f "$PROGRESS" ]; then
  MODE=$(grep -oE "(CALIBRATE|CREATE|DEBRIEF|PLAN)" "$PROGRESS" | tail -1 2>/dev/null || echo "READY")
  echo "Mode: ${MODE:-READY}"
fi

# 2. Open loops
LOOP_SCRIPT="$QROOT/.q-system/loop-tracker.sh"
if [ -f "$LOOP_SCRIPT" ]; then
  STATS=$(bash "$LOOP_SCRIPT" stats 2>/dev/null || true)
  [ -n "$STATS" ] && echo "Loops: $STATS"
fi

# 3. Canonical positioning snapshot
CURRENT_STATE="$QROOT/my-project/current-state.md"
if [ -f "$CURRENT_STATE" ] && [ -s "$CURRENT_STATE" ]; then
  echo ""
  echo "--- Product Context (current-state.md) ---"
  head -30 "$CURRENT_STATE"
fi

TALK_TRACKS="$QROOT/canonical/talk-tracks.md"
if [ -f "$TALK_TRACKS" ] && [ -s "$TALK_TRACKS" ]; then
  echo ""
  echo "--- Talk Tracks (first 20 lines) ---"
  head -20 "$TALK_TRACKS"
fi

# 4. Reminders
echo ""
echo "ACTIVE RULES:"
echo "- All written output must use founder voice (no hedging, no filler, no AI words)"
echo "- Unvalidated claims must be marked {{UNVALIDATED}}"
echo "- Check canonical files before asserting facts about the product"
echo "- If the founder can't copy-paste it, click it, or check it off, cut it"

exit 0
