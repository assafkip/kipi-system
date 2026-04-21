#!/usr/bin/env bash
# init-bus-day.sh - Create today's bus directory and write _meta.json
# This is the ONLY source of truth for the pipeline date.
# Called by the orchestrator before any agent spawns.
# Deterministic: no LLM involvement in date computation.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
QROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Find instance bus dir (q-ktlyst or similar)
INSTANCE_DIR=""
for d in "$QROOT"/../q-*/; do
    if [ -d "${d}.q-system/agent-pipeline/bus" ]; then
        INSTANCE_DIR="$d"
        break
    fi
done

if [ -z "$INSTANCE_DIR" ]; then
    echo "ERROR: No instance with agent-pipeline/bus found" >&2
    exit 1
fi

BUS_ROOT="$(cd "${INSTANCE_DIR}.q-system/agent-pipeline/bus" && pwd)"
TODAY=$(date +%Y-%m-%d)
BUS_DIR="${BUS_ROOT}/${TODAY}"

mkdir -p "$BUS_DIR"

# Write _meta.json - the single source of truth for pipeline date
cat > "${BUS_DIR}/_meta.json" <<EOF
{
  "date": "${TODAY}",
  "created_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "bus_dir": "${BUS_DIR}"
}
EOF

echo "${TODAY}"
