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

# Compact earlier (50% instead of 95%) to give long pipelines headroom
export CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=50

echo "=== Session Context ==="
echo "Date: $(date '+%Y-%m-%d %A')"

# Instance identity
INSTANCE_NAME=""
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKELETON_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
REGISTRY="$SKELETON_ROOT/instance-registry.json"
if [ -f "$REGISTRY" ] && command -v python3 >/dev/null 2>&1; then
  INSTANCE_NAME=$(python3 -c "
import json, os
try:
    with open('$REGISTRY') as f:
        data = json.load(f)
    proj = os.path.realpath('$PROJ_DIR')
    for inst in data.get('instances', []):
        if os.path.realpath(inst['path']) == proj:
            print(inst['name'])
            break
    else:
        if proj == os.path.realpath(data.get('skeleton', {}).get('path', '')):
            print('kipi-system (skeleton)')
except Exception:
    pass
" 2>/dev/null || true)
fi
if [ -z "$INSTANCE_NAME" ]; then
  INSTANCE_NAME=$(basename "$PROJ_DIR")
fi
echo "Instance: $INSTANCE_NAME"
echo "Directory: $PROJ_DIR"
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
