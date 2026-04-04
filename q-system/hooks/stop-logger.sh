#!/bin/bash
set -euo pipefail

# Async stop logger - appends session effort entry after each turn
# Runs with async: true (non-blocking)
# Exit 0 always

PROJ_DIR="${CLAUDE_PROJECT_DIR:-.}"
# Auto-detect: subtree instances have q-system/q-system/, skeleton has q-system/
if [ -d "$PROJ_DIR/q-system/q-system/output" ] || [ -d "$PROJ_DIR/q-system/q-system/canonical" ]; then
  OUTPUT_DIR="$PROJ_DIR/q-system/q-system/output"
else
  OUTPUT_DIR="$PROJ_DIR/q-system/output"
fi
TODAY=$(date '+%Y-%m-%d')
LOG_FILE="$OUTPUT_DIR/session-effort-${TODAY}.log"

mkdir -p "$OUTPUT_DIR"

TIMESTAMP=$(date '+%H:%M:%S')
echo "${TIMESTAMP} turn_complete" >> "$LOG_FILE"

exit 0
