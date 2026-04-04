#!/bin/bash
set -euo pipefail

# StatusLine script - outputs a compact status string
# Format: [MODE] | N loops (M hot) | pipeline: phase X

PROJ_DIR="${CLAUDE_PROJECT_DIR:-.}"
# Auto-detect QROOT: subtree instances have q-system/q-system/, skeleton has q-system/
if [ -d "$PROJ_DIR/q-system/q-system/canonical" ]; then
  QROOT="$PROJ_DIR/q-system/q-system"
else
  QROOT="$PROJ_DIR/q-system"
fi

# 1. Current mode
MODE="READY"
PROGRESS="$QROOT/my-project/progress.md"
if [ -f "$PROGRESS" ]; then
  FOUND=$(grep -oE "(CALIBRATE|CREATE|DEBRIEF|PLAN)" "$PROGRESS" 2>/dev/null | tail -1 || true)
  [ -n "$FOUND" ] && MODE="$FOUND"
fi

# 2. Loop counts + pipeline phase (single python call)
LOOPS="--"
LOOP_FILE="$QROOT/output/open-loops.json"
TODAY=$(date '+%Y-%m-%d')
LOG="$QROOT/output/morning-log-${TODAY}.json"

# Single python call for loops + pipeline phase
read -r LOOPS PHASE <<< "$(python3 -c "
import json, os
loops_str = '--'
phase_str = ''
try:
    with open('$LOOP_FILE') as f:
        d = json.load(f)
    all_loops = [l for l in d.get('loops', []) if l.get('status') == 'open']
    hot = [l for l in all_loops if l.get('escalation_level', 0) >= 2]
    loops_str = f'{len(all_loops)}loops'
    if hot: loops_str += f'({len(hot)}hot)'
except: pass
try:
    with open('$LOG') as f:
        log = json.load(f)
    done = [k for k, v in log.get('steps', {}).items() if v.get('status') == 'done']
    if done: phase_str = f'phase{max(int(s[0]) for s in done if s[0].isdigit())}'
except: pass
print(f'{loops_str} {phase_str}')
" 2>/dev/null || echo "-- ")"

# Build output (keep under 80 chars)
OUTPUT="[$MODE]"
[ "$LOOPS" != "--" ] && OUTPUT="$OUTPUT | $(echo "$LOOPS" | tr -d ' ')"
[ -n "$PHASE" ] && OUTPUT="$OUTPUT | $(echo "$PHASE" | tr -d ' ')"

echo "$OUTPUT"
