#!/usr/bin/env bash
# REPRO: ENV_NOISE_RE is anchored at column 0; ENV_LINE_RE tolerates 3 leading
# spaces. An indented CLI hook-teardown line beside a real limit line is counted
# as a spoken line, so the outage reads as an agent that ran and the issue is
# CHARGED an attempt. (Round-3 minor, re-checked at HEAD.)
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../../.." && pwd)"
. "$ROOT/q-system/.q-system/scripts/env-failure-lib.sh"

LIMIT="You've hit your weekly limit · resets Sep 22 at 2pm (America/Los_Angeles)"
HOOK='SessionEnd hook [python3 "/Users/x/.claude/hooks/session-end-llma.py"] failed: Hook cancelled'

check() {
  if is_environmental "$2"; then echo "$1 -> OUTAGE   (no attempt charged)"
  else echo "$1 -> ORDINARY (issue CHARGED an attempt)"; fi
}
check "flush hook line   " "$(printf '%s\n%s\n' "$LIMIT" "$HOOK")"
check "1-space indent    " "$(printf '%s\n %s\n' "$LIMIT" "$HOOK")"
check "3-space indent    " "$(printf '%s\n   %s\n' "$LIMIT" "$HOOK")"
echo
echo "for contrast, ENV_LINE_RE tolerates 3 leading spaces on the limit line itself:"
check "limit indented 3  " "$(printf '   %s\n' "$LIMIT")"
