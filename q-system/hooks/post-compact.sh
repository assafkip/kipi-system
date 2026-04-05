#!/bin/bash
set -euo pipefail

# Post-compaction context recovery
# Re-injects critical context that compaction may have stripped:
#   1. Current operating mode
#   2. Open loop summary
#   3. Morning pipeline phase progress (bus files completed, next phase)
#   4. Canonical positioning snapshot (so Claude doesn't lose product knowledge)
#   5. Voice and validation reminders
# Exit 0 always (never blocks)

PROJ_DIR="${CLAUDE_PROJECT_DIR:-.}"
# Auto-detect QROOT: subtree instances have q-system/q-system/, skeleton has q-system/
if [ -d "$PROJ_DIR/q-system/q-system/canonical" ]; then
  QROOT="$PROJ_DIR/q-system/q-system"
else
  QROOT="$PROJ_DIR/q-system"
fi

echo "=== Post-Compact Context Recovery ==="

# 1. Current mode
PROGRESS="$QROOT/my-project/progress.md"
if [ -f "$PROGRESS" ]; then
  MODE=$(grep -oE "(CALIBRATE|CREATE|DEBRIEF|PLAN)" "$PROGRESS" | tail -1 2>/dev/null || echo "READY")
  echo "Mode: ${MODE:-READY}"
fi

# 2. Open loops
LOOP_SCRIPT="$QROOT/.q-system/loop-tracker.py"
if [ -f "$LOOP_SCRIPT" ]; then
  STATS=$(python3 "$LOOP_SCRIPT" stats 2>/dev/null || true)
  [ -n "$STATS" ] && echo "Loops: $STATS"
fi

# 3. Morning pipeline phase progress (if bus directory exists for today)
TODAY=$(date +%Y-%m-%d)
BUS_DIR="$QROOT/.q-system/agent-pipeline/bus/$TODAY"
if [ -d "$BUS_DIR" ]; then
  BUS_FILES=$(ls "$BUS_DIR"/*.json 2>/dev/null | xargs -I{} basename {} | tr '\n' ', ' | sed 's/,$//')
  if [ -n "$BUS_FILES" ]; then
    echo ""
    echo "--- Morning Pipeline Progress ---"
    echo "Bus files completed: $BUS_FILES"
    # Infer phase from which files exist
    if ls "$BUS_DIR"/sycophancy-audit.json >/dev/null 2>&1; then
      echo "Phase 6 complete. Next: Phase 7 (synthesis script)"
    elif ls "$BUS_DIR"/hitlist.json >/dev/null 2>&1; then
      echo "Phase 5 complete. Next: Phase 6 (compliance + health)"
    elif ls "$BUS_DIR"/signals.json >/dev/null 2>&1; then
      echo "Phase 4 complete. Next: Phase 5 (pipeline)"
    elif ls "$BUS_DIR"/linkedin-posts.json >/dev/null 2>&1; then
      echo "Phase 3 complete. Next: Phase 4 (content)"
    elif ls "$BUS_DIR"/calendar.json >/dev/null 2>&1; then
      echo "Phase 1 complete. Next: Phase 2 (analysis)"
    elif ls "$BUS_DIR"/preflight.json >/dev/null 2>&1; then
      echo "Phase 0 complete. Next: Phase 1 (data ingest)"
    fi
  fi
fi

# 4. Canonical positioning snapshot
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

# 5. Reminders
echo ""
echo "ACTIVE RULES:"
echo "- All written output must use founder voice (no hedging, no filler, no AI words)"
echo "- Unvalidated claims must be marked {{UNVALIDATED}}"
echo "- Check canonical files before asserting facts about the product"
echo "- If the founder can't copy-paste it, click it, or check it off, cut it"

exit 0
