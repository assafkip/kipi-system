#!/bin/bash
set -euo pipefail

# StatusLine script - outputs a compact status string
# Format: [MODE] | N loops (M hot) | pipeline: phase X

PROJ_DIR="${CLAUDE_PROJECT_DIR:-.}"
QROOT="$PROJ_DIR/q-system"

# 1. Current mode
MODE="READY"
PROGRESS="$QROOT/my-project/progress.md"
if [ -f "$PROGRESS" ]; then
  FOUND=$(grep -oE "(CALIBRATE|CREATE|DEBRIEF|PLAN)" "$PROGRESS" 2>/dev/null | tail -1 || true)
  [ -n "$FOUND" ] && MODE="$FOUND"
fi

# 2. Loop counts
LOOPS="--"
HOT=""
LOOP_FILE="$QROOT/output/open-loops.json"
if [ -f "$LOOP_FILE" ]; then
  TOTAL=$(python3 -c "
import json
try:
    d = json.load(open('$LOOP_FILE'))
    loops = [l for l in d if l.get('status') == 'open']
    hot = [l for l in loops if l.get('escalation_level', 0) >= 2]
    print(f'{len(loops)} loops')
    if hot: print(f'({len(hot)} hot)')
except: print('--')
" 2>/dev/null || echo "--")
  LOOPS="$TOTAL"
fi

# 3. Pipeline phase
PHASE=""
TODAY=$(date '+%Y-%m-%d')
LOG="$QROOT/output/morning-log-${TODAY}.json"
if [ -f "$LOG" ]; then
  PHASE=$(python3 -c "
import json
try:
    d = json.load(open('$LOG'))
    steps = d.get('steps', {})
    done = [k for k, v in steps.items() if v.get('status') == 'done']
    if done: print(f'phase {max(int(s[0]) for s in done if s[0].isdigit())}')
except: pass
" 2>/dev/null || true)
fi

# Build output (keep under 80 chars)
OUTPUT="[$MODE]"
[ "$LOOPS" != "--" ] && OUTPUT="$OUTPUT | $LOOPS"
[ -n "$PHASE" ] && OUTPUT="$OUTPUT | $PHASE"

echo "$OUTPUT"
