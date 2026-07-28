#!/bin/bash
# lesson-note.sh -- drop a NON-failure learning into the corpus intake.
#
# For a lesson from a build, a near-miss, or a self-caught error that never
# produced an RCA. The daily lessons-distill sweep turns it into a HOW-only,
# client-scrubbed, fleet-wide lesson -- the same path RCAs take. This exists so
# the learnings/ intake has a real producer, not a dead directory.
#
# Pairs with: lessons-distill.py new_learnings(); q-system/lessons/README.md.
# Writes to THIS instance's q-system/output/learnings/ (instance-protected by
# kipi update, so notes survive fan-out).
#
# Usage: lesson-note.sh "<title>" ["<body>"]   (body from stdin if omitted)
set -euo pipefail
QROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"   # scripts -> .q-system -> q-system
DIR="$QROOT/output/learnings"
mkdir -p "$DIR"
TITLE="${1:?usage: lesson-note.sh \"<title>\" [\"<body>\"]}"
BODY="${2:-}"
[ -z "$BODY" ] && BODY="$(cat)"
TS="$(date +%Y%m%d-%H%M%S)"
SLUG="$(printf '%s' "$TITLE" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' '-' | sed 's/^-//; s/-$//' | cut -c1-50)"
FILE="$DIR/NOTE-$TS-${SLUG:-note}.md"
printf '# %s\n\n%s\n' "$TITLE" "$BODY" > "$FILE"
echo "wrote learning note: $FILE"
