#!/bin/bash
# ASK-4511. Two pins on pr-review-agent.sh, sliced out of the real script:
#   1. KIPI_REVIEW_TIMEOUT overrides the per-run cap (default 2400, a bad value
#      falls back to the default instead of becoming a cap of zero or a crash).
#   2. The reviewer prompt bounds test runs. Scar: two of two Opus fallback
#      reviews on a repo whose review tree has no venv were killed at the cap
#      after the model ran that repo's WHOLE suite six times, re-slicing the
#      same output through tail, grep and grep -c. The transcript showed the
#      same command re-run to read a different piece of its output.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENT="$HERE/../pr-review-agent.sh"
T="$(mktemp -d)"
fail=0
check() { if eval "$2"; then echo "PASS $1"; else echo "FAIL $1"; fail=1; fi; }

# --- 1. the cap ---
# From the first TIMEOUT_SECONDS assignment up to the NOTIFY= line that follows.
awk '/^TIMEOUT_SECONDS=/{on=1} /^NOTIFY=/{exit} on{print}' "$AGENT" > "$T/cap.sh"
check "the cap block was found" '[ -s "$T/cap.sh" ]'
cap() { env -i PATH="$PATH" "$@" bash -c 'source "$1" 2>/dev/null; echo "$TIMEOUT_SECONDS"' _ "$T/cap.sh"; }
check "default cap is 2400"                   '[ "$(cap)" = 2400 ]'
check "KIPI_REVIEW_TIMEOUT=600 sets the cap"  '[ "$(cap KIPI_REVIEW_TIMEOUT=600)" = 600 ]'
check "a non-number falls back to 2400"       '[ "$(cap KIPI_REVIEW_TIMEOUT=soon)" = 2400 ]'
check "zero falls back to 2400"               '[ "$(cap KIPI_REVIEW_TIMEOUT=0)" = 2400 ]'
check "empty falls back to 2400"              '[ "$(cap KIPI_REVIEW_TIMEOUT=)" = 2400 ]'
check "1 second falls back to 2400 (floor)"   '[ "$(cap KIPI_REVIEW_TIMEOUT=1)" = 2400 ]'
check "299 falls back to 2400 (floor)"        '[ "$(cap KIPI_REVIEW_TIMEOUT=299)" = 2400 ]'
check "300 is accepted (floor edge)"          '[ "$(cap KIPI_REVIEW_TIMEOUT=300)" = 300 ]'
check "the floor says why on stderr"          'env -i PATH="$PATH" KIPI_REVIEW_TIMEOUT=2 bash -c "source \"$T/cap.sh\"" 2>&1 | grep -q "below the 300s floor"'
# Scar: the slice above stops at NOTIFY=, so a later assignment would override the
# cap at runtime while every check above stayed green. No assignment may follow it.
later="$(awk '/^NOTIFY=/{on=1} on && /(^|[^A-Za-z_])TIMEOUT_SECONDS=/{print NR": "$0}' "$AGENT")"
check "no TIMEOUT_SECONDS assignment after the cap block" '[ -z "$later" ]'

# --- 2. the prompt ---
awk '/^PROMPT="You are a SENIOR STAFF/{on=1} on{print} on && /^END FINDINGS"$/{exit}' "$AGENT" > "$T/prompt.sh"
check "the prompt block was found" '[ -s "$T/prompt.sh" ]'
PROMPT="$(env -i PATH="$PATH" bash -c 'source "$1"; printf "%s" "$PROMPT"' _ "$T/prompt.sh")"
check "prompt forbids running the whole suite" \
  'printf "%s" "$PROMPT" | grep -qi "never run the whole test suite"'
check "prompt limits a command to one run and says to read the saved output" \
  'printf "%s" "$PROMPT" | grep -qi "at most once" && printf "%s" "$PROMPT" | grep -q "TMPDIR"'
check "prompt says a missing venv is not a reason to hunt for one" \
  'printf "%s" "$PROMPT" | grep -qi "no virtualenv"'

find "$T" -mindepth 1 -delete 2>/dev/null; rmdir "$T" 2>/dev/null
exit "$fail"
