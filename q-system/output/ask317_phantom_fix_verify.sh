#!/usr/bin/env bash
# Isolates the CAUSE: same capture, two versions of pr-verdict-lib.sh.
# If only the new lib refuses the echo-only review, the fix is the lib (ASK-274,
# PR #87) and not something about how the capture was transcribed.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
CAPTURE="$ROOT/q-system/output/ask317_phantom_review_capture.md"
[ -s "$CAPTURE" ] || { echo "FATAL: capture missing: $CAPTURE" >&2; exit 1; }

T="$(mktemp -d)" || { echo "FATAL: mktemp -d failed" >&2; exit 1; }
trap 'rm -rf "$T"' EXIT

# 25340b59 is this branch's tip BEFORE main was merged in -- the lib as ASK-317
# round 3 saw it.
git -C "$ROOT" show 25340b59:q-system/.q-system/scripts/pr-verdict-lib.sh > "$T/old-lib.sh"
[ -s "$T/old-lib.sh" ] || { echo "FATAL: could not extract the pre-merge lib" >&2; exit 1; }

for which in old new; do
  if [ "$which" = old ]; then LIB="$T/old-lib.sh"; else LIB="$ROOT/q-system/.q-system/scripts/pr-verdict-lib.sh"; fi
  echo "=== $which lib: $LIB ==="
  bash -c '
    set -uo pipefail
    . "$1"
    echo "--- findings_block ---"
    findings_block "$2"
    echo "--- has_complete_findings_block ---"
    rc=0; has_complete_findings_block "$2" || rc=$?
    echo "rc=$rc"
  ' _ "$LIB" "$CAPTURE"
done
