#!/usr/bin/env bash
# Reproducer for the phantom finding on PR #79 round 3 and PR #80 round 1.
# A crashed codex run echoes the prompt (which contains the literal FINDINGS
# template) and writes nothing else. findings_block takes the LAST COMPLETE
# block to avoid the echo -- but when the echo is the ONLY block, last == echo.
#
# THE FIXTURE IS NOT INVENTED (round-1 review finding, PR #80). Its lines are
# transcribed verbatim from the review pr-review-agent.sh actually posted to
# PR #80 on 2026-08-02, whose on-disk original is
# ~/.config/kipi/pr-reviews/codex/pr-80-20260802-234516.md (7493 bytes). Pass
# that path -- or any real captured review -- as $1 to run against the producer's
# own file instead of the committed transcription.
#
# set -e, not the earlier set -u only (round-1 review finding, PR #80): the
# script used to exit 0 after mktemp and the fixture write both failed, so
# automation could accept evidence that never ran.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
. "$ROOT/q-system/.q-system/scripts/pr-verdict-lib.sh"

CAPTURE="${1:-$ROOT/q-system/output/ask317_phantom_review_capture.md}"
[ -s "$CAPTURE" ] || { echo "FATAL: capture is missing or empty: $CAPTURE" >&2; exit 1; }

T="$(mktemp -d)" || { echo "FATAL: mktemp -d failed" >&2; exit 1; }
trap 'rm -rf "$T"' EXIT
F="$T/echo_only.md"
cp "$CAPTURE" "$F" || { echo "FATAL: could not stage fixture at $F" >&2; exit 1; }
[ -s "$F" ] || { echo "FATAL: staged fixture is empty: $F" >&2; exit 1; }

echo "=== source ==="
echo "$CAPTURE"
echo "=== findings_block on a prompt-echo-only review ==="
findings_block "$F"
echo "=== has_complete_findings_block ==="
rc=0
has_complete_findings_block "$F" || rc=$?
echo "rc=$rc"
