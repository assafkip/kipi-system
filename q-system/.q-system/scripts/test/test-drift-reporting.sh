#!/usr/bin/env bash
# ASK-4899: a drifted PR must be DESCRIBED as drifted, everywhere a human or a
# machine reads about it.
#
# Pairs with the exit-2 cap-out in converge.sh and the step-5 drift report in
# linear-worker.sh. Both told an operator something false about a PR whose
# reviewer had approved it and whose head had moved on (claude-reviewer on
# PR #30, 2026-11-16 13:51 UTC, minors 1 and 2).
#
# WHY THE BLOCKS ARE EXTRACTED AND EVALUATED
# ------------------------------------------
# A grep proves the new wording exists in the file. It cannot prove the wording
# is SELECTED on the drift path and not on the healthy one, which is the whole
# claim. So each case extracts the real block out of the real file and evals it
# with the variables production sets, the same technique test-dor-target-repo.sh
# uses on ready(). Deleting the branch turns these red.
#
# GATE 40 IS REACHABLE IN BOTH CALLERS, MEASURED NOT ASSUMED. rework_gate
# (pr-verdict-lib.sh) returns 40 only when BOTH shas are non-empty and differ;
# an empty reviewed_sha prints a NOTE and falls through to 10/30. So the
# "wrote no record" arm is reachable ONLY with a non-empty record sha, which is
# exactly what the minor-2 fix guards on. And converge.sh passes FIVE arguments
# including both shas, so it does see 40 -- the "callers passing 1 or 2
# arguments (converge.sh, linear-worker.sh) ... can never see it" comment above
# rework_gate is STALE. Case 0 pins the call site, so a future arity change
# cannot silently turn the minor-1 branch into dead text that still passes.
#
# NO LIVE GH, NO LIVE LINEAR, NO NOTIFIER. Nothing here runs converge.sh or
# linear-worker.sh; only the extracted assignment blocks are evaluated, with
# say and drift_rounds_for stubbed as local functions. That is deliberate: both
# scripts reach slack-notify.sh, and a suite that pages a real phone is the
# 2026-08-01 scar.
set -uo pipefail

# THE NOTIFIER IS STUBBED FOR THE WHOLE SUITE, belt and braces. Nothing here
# executes converge.sh or linear-worker.sh today -- every reference to them is a
# grep or a python read that extracts a block -- so no notifier is reachable
# from this file as written. The export exists so that stays true if a later
# case does run one: both scripts resolve their notifier from KIPI_NOTIFY
# (converge.sh and linear-worker.sh both default NOTIFY to slack-notify.sh and
# let the env win), and /usr/bin/true accepts any argument and does nothing.
# Scar 2026-08-01: a suite reporting 14/14 green paged the founder twice.
export KIPI_NOTIFY=/usr/bin/true

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_SCRIPTS="$(cd "$SCRIPT_DIR/.." && pwd)"
CONVERGE="${KIPI_CONVERGE_UNDER_TEST:-$REPO_SCRIPTS/converge.sh}"
WORKER="${KIPI_WORKER_UNDER_TEST:-$REPO_SCRIPTS/linear-worker.sh}"

PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); printf '  ok   %s\n' "$1"; }
bad() { FAIL=$((FAIL+1)); printf '  FAIL %s\n     %s\n' "$1" "${2:-}"; }

WORK="$(mktemp -d)"
cleanup() { [ -n "${WORK:-}" ] && [ -d "$WORK" ] && /bin/rm -r -- "$WORK"; }
trap cleanup EXIT

printf '\n== case 0: the gate everything here depends on is reachable ==\n'

if grep -qE 'rework_gate "\$VERDICT" "" "\$REVIEWED_SHA" "\$SHA"' "$CONVERGE"; then
  ok "converge.sh passes both shas to rework_gate (so gate 40 is reachable)"
else
  bad "converge.sh passes both shas to rework_gate (so gate 40 is reachable)" \
      "$(grep -n 'rework_gate "' "$CONVERGE" || echo 'no rework_gate call found')"
fi

printf '\n== minor 1: the exit-2 cap-out ==\n'

python3 - "$CONVERGE" > "$WORK/capout.sh" <<'PY'
import sys
src = open(sys.argv[1], encoding="utf-8").read()
start = src.find('CAPOUT_WHY="hit the $MAX_ROUNDS-round cap')
if start < 0:
    sys.stderr.write("EXTRACT-FAIL: no CAPOUT_WHY assignment in converge.sh\n")
    raise SystemExit(3)
end = src.find("\n", src.find('say "STOP exit-2:', start))
sys.stdout.write(src[start:end])
PY

if [ ! -s "$WORK/capout.sh" ]; then
  bad "minor 1: the cap-out block could be extracted" "extraction produced nothing"
else
  ok "minor 1: the cap-out block could be extracted"

  run_capout() {  # run_capout <gate>
    (
      say() { printf '%s\n' "$1"; }
      MAX_ROUNDS=3; LAST_VERDICT="APPROVE WITH NITS"; PR=829
      REVIEWED_SHA=87225b06; SHA=1a0b2136; GATE="$1"
      # shellcheck disable=SC1090
      . "$WORK/capout.sh"
      printf 'WHY=%s\n' "$CAPOUT_WHY"
    )
  }

  DRIFTED="$(run_capout 40)"
  # The page AND the ledger both read CAPOUT_WHY, so the shas have to be IN it,
  # not only in the advice sentence beside it. Fixing the log line alone would
  # leave the stored record still lying.
  if printf '%s' "$DRIFTED" | grep -q 'WHY=.*87225b06' \
     && printf '%s' "$DRIFTED" | grep -q 'WHY=.*1a0b2136'; then
    ok "minor 1: a drifted cap-out names both shas in the STORED reason"
  else
    bad "minor 1: a drifted cap-out names both shas in the STORED reason" "$DRIFTED"
  fi
  if printf '%s' "$DRIFTED" | grep -qi 'never reviewed\|unreviewed'; then
    ok "minor 1: a drifted cap-out says the head was never reviewed"
  else
    bad "minor 1: a drifted cap-out says the head was never reviewed" "$DRIFTED"
  fi
  if printf '%s' "$DRIFTED" | grep -q 'disagree persistently'; then
    bad "minor 1: a drifted cap-out does not claim disagreement" \
        "on drift the reviewer APPROVED, so there is no disagreement: $DRIFTED"
  else
    ok "minor 1: a drifted cap-out does not claim disagreement"
  fi

  # NEGATIVE SELF-TEST. A real cap-out -- rounds spent, record and head in step
  # -- must KEEP the disagreement reading. A fix that relabelled every cap-out
  # as drift would be wrong in the other direction, and this is what catches it.
  HEALTHY="$(run_capout 10)"
  if printf '%s' "$HEALTHY" | grep -q 'disagree persistently'; then
    ok "minor 1: a NON-drift cap-out still reads as disagreement (negative self-test)"
  else
    bad "minor 1: a NON-drift cap-out still reads as disagreement (negative self-test)" "$HEALTHY"
  fi
  if printf '%s' "$HEALTHY" | grep -q "WHY=hit the 3-round cap still at 'APPROVE WITH NITS'"; then
    ok "minor 1: the non-drift reason is byte-unchanged (no collateral rewording)"
  else
    bad "minor 1: the non-drift reason is byte-unchanged (no collateral rewording)" "$HEALTHY"
  fi
  # test-converge-capout.sh matches the "3-round cap" substring to prove the
  # record says why. Pinned on BOTH branches here so a later reword cannot
  # quietly make that assertion vacuous on the drift path.
  if printf '%s' "$DRIFTED" | grep -q '3-round cap' \
     && printf '%s' "$HEALTHY" | grep -q '3-round cap'; then
    ok "minor 1: both branches keep the substring test-converge-capout.sh pins"
  else
    bad "minor 1: both branches keep the substring test-converge-capout.sh pins" \
        "drift=$DRIFTED healthy=$HEALTHY"
  fi
  # The failed-record page had its own hardcoded verdict text and is the half
  # that reaches a phone. It has to read the same variable, or the page and the
  # log can describe one PR two different ways.
  if grep -q 'converge \$ISSUE: \$CAPOUT_WHY, and the cap-out could NOT be recorded' "$CONVERGE"; then
    ok "minor 1: the failed-record page reuses CAPOUT_WHY (one description, not two)"
  else
    bad "minor 1: the failed-record page reuses CAPOUT_WHY (one description, not two)" \
        "the page still states the verdict itself"
  fi
fi

printf '\n== minor 2: the step-5 drift report ==\n'

python3 - "$WORKER" > "$WORK/drift.sh" <<'PY'
import sys
src = open(sys.argv[1], encoding="utf-8").read()
start = src.find('DRIFT_CAUSE="this round')
if start < 0:
    sys.stderr.write("EXTRACT-FAIL: no DRIFT_CAUSE assignment in linear-worker.sh\n")
    raise SystemExit(3)
end = src.find("\n", src.find('say "$ISSUE NOT converged:', start))
sys.stdout.write(src[start:end])
PY

if [ ! -s "$WORK/drift.sh" ]; then
  bad "minor 2: the drift-report block could be extracted" \
      "no DRIFT_CAUSE assignment -- the report still hard-codes a single cause"
else
  ok "minor 2: the drift-report block could be extracted"

  run_drift() {  # run_drift <reviewed-sha-at-run-start> <reviewed-sha-now>
    (
      say() { printf '%s\n' "$1"; }
      drift_rounds_for() { printf '1'; }
      ISSUE=ASK-4899; PR_NUM=30; FINAL_VERDICT="APPROVE WITH NITS"
      MAX_DRIFT_ROUNDS=2
      REVIEWED_SHA="$1"; FINAL_REVIEWED_SHA="$2"; FINAL_CURRENT_SHA=ffffffff
      # shellcheck disable=SC1090
      . "$WORK/drift.sh"
    )
  }

  # CASE (b): a record WAS written this round, then a push moved the head. The
  # reviewer ran. Blaming it is the false accusation the finding names.
  RAN="$(run_drift 87225b06 1a0b2136)"
  if printf '%s' "$RAN" | grep -q 'DID write a record'; then
    ok "minor 2: a review that ran is credited, not blamed"
  else
    bad "minor 2: a review that ran is credited, not blamed" "$RAN"
  fi
  if printf '%s' "$RAN" | grep -q 'wrote no record'; then
    bad "minor 2: a review that ran is not accused of writing nothing" "$RAN"
  else
    ok "minor 2: a review that ran is not accused of writing nothing"
  fi

  # CASE (a), NEGATIVE SELF-TEST: the record did not move, so no review wrote
  # one this round and the ORIGINAL sentence is the true one. It has to survive.
  # Gate 40 still fires here because the record sha differs from the head.
  SILENT="$(run_drift 87225b06 87225b06)"
  if printf '%s' "$SILENT" | grep -q 'wrote no record'; then
    ok "minor 2: a review that did NOT run still reads 'wrote no record' (negative self-test)"
  else
    bad "minor 2: a review that did NOT run still reads 'wrote no record' (negative self-test)" "$SILENT"
  fi

  # The first record on a PR created this run: absent at the start, present now.
  # Case (b) as well, and it must not read as "nothing happened".
  FIRST="$(run_drift "" 1a0b2136)"
  if printf '%s' "$FIRST" | grep -q 'DID write a record'; then
    ok "minor 2: a first-ever record counts as a review that ran"
  else
    bad "minor 2: a first-ever record counts as a review that ran" "$FIRST"
  fi
fi

printf '\n== both files still parse ==\n'
for f in "$CONVERGE" "$WORKER"; do
  if bash -n "$f" 2>/dev/null; then
    ok "bash -n $(basename "$f")"
  else
    bad "bash -n $(basename "$f")" "syntax error"
  fi
done

printf '\n%s passed, %s failed\n' "$PASS" "$FAIL"
[ "$FAIL" = "0" ]
