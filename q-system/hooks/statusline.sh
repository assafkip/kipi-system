#!/bin/bash
set -euo pipefail

# StatusLine script - outputs a compact status string
# Format: [MODE] | Nloops(Mhot) | phaseX | todo:K
#   todo:K = K open parked items in q-system/memory/open-loops.json (the AUDHD
#   anti-drop registry: decisions genuinely reserved to the founder). Always visible so
#   nothing falls. Distinct from the pre-existing session "loops" badge.

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

# 2. Session loops + pipeline phase + parked open-loops (single python call,
#    space-separated with '-' placeholders so empty fields never shift positions)
TODAY=$(date '+%Y-%m-%d')
read -r LOOPS PHASE PARKED <<< "$(python3 -c "
import json
loops_str='--'; phase_str='-'; parked_str='-'
try:
    with open('$QROOT/output/open-loops.json') as f:
        d=json.load(f)
    al=[l for l in d.get('loops',[]) if l.get('status')=='open']
    hot=[l for l in al if l.get('escalation_level',0)>=2]
    loops_str=f'{len(al)}loops'+(f'({len(hot)}hot)' if hot else '')
except Exception: pass
try:
    with open('$QROOT/output/morning-log-${TODAY}.json') as f:
        log=json.load(f)
    done=[k for k,v in log.get('steps',{}).items() if v.get('status')=='done']
    if done: phase_str=f'phase{max(int(s[0]) for s in done if s[0].isdigit())}'
except Exception: pass
try:
    with open('$QROOT/memory/open-loops.json') as f:
        reg=json.load(f)
    op=[l for l in reg.get('loops',[]) if str(l.get('status','open')).lower()!='closed']
    if op: parked_str=f'todo:{len(op)}'
except Exception: pass
print(loops_str, phase_str, parked_str)
" 2>/dev/null || echo "-- - -")"

# 3. Build output (keep compact). '-' / '--' mean 'nothing to show'.
OUTPUT="[$MODE]"
[ "$LOOPS" != "--" ] && [ "$LOOPS" != "-" ] && OUTPUT="$OUTPUT | $LOOPS"
[ "$PHASE" != "-" ] && OUTPUT="$OUTPUT | $PHASE"
[ "$PARKED" != "-" ] && OUTPUT="$OUTPUT | $PARKED"

echo "$OUTPUT"
