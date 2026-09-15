#!/usr/bin/env bash
# Reproducer for sp-46c73c76: kipi-update.sh guarded its system-state
# auto-commit on `[ "$DRY_RUN" != "1" ]`, but DRY_RUN only ever holds "" or the
# string "--dry-run". The comparison could never be false, so the guard was
# indistinguishable from its own absence.
#
# Pairs with: the dry-run/live-path assertion in kipi-update.sh.
#
# WHY THE OBVIOUS TEST IS THE WRONG ONE. Asserting "a dry run does not commit"
# passes against the BROKEN script too -- the commit lands on the throwaway
# clone either way, so the outcome is identical with the guard, without it, and
# with the dead version. A test that cannot distinguish those three is exactly
# the green-for-the-wrong-reason shape this repo keeps shipping. So this test
# asserts two things the outcome cannot hide:
#   1. no $DRY_RUN comparison anywhere tests a value the variable can never hold
#      (the CLASS check -- this is what would have caught the original bug)
#   2. the replacement assertion actually FIRES on the condition it names
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../../../.." && pwd)"
AGENT="$ROOT/kipi-update.sh"
[ -f "$AGENT" ] || { echo "missing $AGENT"; exit 1; }

PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  PASS: $1"; }
bad() { FAIL=$((FAIL+1)); echo "  FAIL: $1"; }

# The only values DRY_RUN is ever assigned. Kept next to the check that uses it.
#
# `^(--dry-run)?$`, NOT `^(|--dry-run)$`. BSD grep rejects an empty alternation
# branch with "empty (sub)expression" and exits NON-ZERO, which this case reads
# as "illegal value" -- so the first cut reported all 8 comparisons defective,
# including the 7 correct ones. A broken checker that fails LOUD is lucky; the
# same mistake in the other direction (matching everything) would have reported
# green forever. Caught 2026-08-06 by reading grep's stderr, not the verdict.
LEGAL_RE='^(--dry-run)?$'

echo "== 1. THE CLASS: no \$DRY_RUN comparison tests an impossible value =="
# Enumerate every literal string comparison against $DRY_RUN and check its RHS.
BOGUS=0; SEEN=0
while IFS= read -r rhs; do
  [ -n "${rhs+x}" ] || continue
  SEEN=$((SEEN+1))
  if ! printf '%s' "$rhs" | grep -Eq "$LEGAL_RE"; then
    BOGUS=$((BOGUS+1))
    echo "      impossible comparison: \$DRY_RUN vs \"$rhs\""
  fi
# COMMENT LINES ARE STRIPPED FIRST. The fix's own why-comment QUOTES the dead
# comparison it removed, so scanning raw lines re-detects the defect in the
# documentation of the defect and reports it as live code. Found on the second
# run of this test. Whole-line comments only: a trailing comment stays in scope,
# which errs toward over-detection, and over-detection is the safe direction for
# a check whose failure mode is missing a dead guard.
done < <(grep -v '^[[:space:]]*#' "$AGENT" \
         | grep -oE '"\$DRY_RUN"[[:space:]]*!?=[[:space:]]*"[^"]*"' \
         | sed -E 's/.*!?=[[:space:]]*"([^"]*)"$/\1/')

# NEGATIVE SELF-TEST ON THE ENUMERATION. If the grep matches nothing, every
# comparison is vacuously legal and this case reports green about a check it
# never ran -- the same empty-extraction trap the provenance suite guards.
if [ "$SEEN" -eq 0 ]; then
  bad "enumerated ZERO \$DRY_RUN comparisons -- the pattern is wrong, case is vacuous"
elif [ "$BOGUS" -eq 0 ]; then
  ok "all $SEEN \$DRY_RUN comparison(s) test a value DRY_RUN can actually hold"
else
  bad "THE DEFECT: $BOGUS of $SEEN \$DRY_RUN comparison(s) can never be false"
fi

echo
echo "== 2. the replacement assertion FIRES when \$path is still the live instance =="
# Drive the shipped condition rather than a copy of it.
COND="$(grep -n 'if \[ "\$DRY_RUN" = "--dry-run" \] && \[ "\$path" = "\$ORIGINAL_PATH" \]; then' "$AGENT" | head -1)"
if [ -z "$COND" ]; then
  bad "the assertion is not present in $AGENT (anchor moved or fix reverted)"
else
  ok "assertion present at kipi-update.sh:${COND%%:*}"
  fired() {  # fired <dry_run> <path> <original_path> -> FIRED|quiet
    (
      DRY_RUN="$1"; path="$2"; ORIGINAL_PATH="$3"
      if [ "$DRY_RUN" = "--dry-run" ] && [ "$path" = "$ORIGINAL_PATH" ]; then
        echo FIRED
      else
        echo quiet
      fi
    )
  }
  # The failure it exists to catch: dry run, repointing did NOT happen.
  if [ "$(fired --dry-run /live/inst /live/inst)" = "FIRED" ]; then
    ok "dry run with \$path still on the live instance is REFUSED"
  else
    bad "THE DEFECT: dry run would auto-commit into the live instance and said nothing"
  fi
  # And it must stay quiet on the two healthy shapes, or it is a false positive
  # that gets the guard switched off (the PR #111 scar).
  if [ "$(fired --dry-run /tmp/model/instance /live/inst)" = "quiet" ]; then
    ok "a correctly repointed dry run is NOT refused"
  else
    bad "false positive: a properly repointed dry run was refused"
  fi
  if [ "$(fired '' /live/inst /live/inst)" = "quiet" ]; then
    ok "a REAL run committing into the live instance is NOT refused (that is its job)"
  else
    bad "false positive: a real run was refused"
  fi
fi

echo
echo "-------- $PASS passed, $FAIL failed --------"
[ "$FAIL" -eq 0 ] || exit 1
echo "PASS: the dry-run guard tests a condition that can actually be false"
