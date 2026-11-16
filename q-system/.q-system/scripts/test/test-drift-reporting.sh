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

printf '\n== minor 3: the two permanent Linear comments a drift round writes ==\n'

# Both comments land on the issue FOREVER, so a drift round that mislabels
# itself mislabels the record a human reads months later. Measured on this very
# issue: its 2026-11-15 and 2026-11-16 threads carry "Attempt 1 of 3" for
# rounds that charged no attempt, and "See the branch/PR for the diff" for a
# round whose stated correct outcome is to change nothing.
#
# Each case extracts the real `$(if ...)` selector and evaluates it, so a
# reworded message still passes while a DELETED branch fails. The extractor
# matches parens so it cannot run past the end of the substitution.
extract_sel() {  # extract_sel <file> <anchor> -> the $(if ...) body on stdout
  python3 - "$1" "$2" <<'PY'
import sys
src = open(sys.argv[1], encoding="utf-8").read()
anchor = src.find(sys.argv[2])
if anchor < 0:
    raise SystemExit(3)
# SEARCH BACKWARD, not forward. Once the site is drift-aware the anchor text
# lives INSIDE its own selector, so a forward find() skips past this block and
# returns the NEXT one -- which is how this harness first "proved" the pickup
# comment by measuring the completion comment. rfind takes the nearest
# PRECEDING opener, which is always this site's own.
start = src.rfind('"$(if', 0, anchor + len(sys.argv[2]))
if start < 0:
    raise SystemExit(3)
i = src.index("(", start)
depth = 0
for j in range(i, len(src)):
    if src[j] == "(":
        depth += 1
    elif src[j] == ")":
        depth -= 1
        if depth == 0:
            sys.stdout.write(src[i + 1:j])
            raise SystemExit(0)
raise SystemExit(3)
PY
}

run_sel() {  # run_sel <body-file> <drift-round-or-empty>
  (
    BRANCH=sana/ask-4899; N=0; MAX_ATTEMPTS=3; MAX_DRIFT_ROUNDS=2
    DRIFT_ROUND="$2"
    # shellcheck disable=SC1090
    . "$1"
  )
}

for pair in "pickup:Picked up by the autonomous worker" "done:Worker run completed. See the branch"; do
  LABEL="${pair%%:*}"; ANCHOR="${pair#*:}"
  if extract_sel "$WORKER" "$ANCHOR" > "$WORK/$LABEL.sh" 2>/dev/null && [ -s "$WORK/$LABEL.sh" ]; then
    ok "minor 3: the $LABEL comment selector could be extracted"
    DRIFTED="$(run_sel "$WORK/$LABEL.sh" 1)"
    NORMAL="$(run_sel "$WORK/$LABEL.sh" "")"
    if [ "$DRIFTED" != "$NORMAL" ]; then
      ok "minor 3: the $LABEL comment differs on a drift round"
    else
      bad "minor 3: the $LABEL comment differs on a drift round" "both read: $NORMAL"
    fi
    case "$LABEL" in
      pickup)
        if printf '%s' "$DRIFTED" | grep -qi 'no attempt is spent' \
           && ! printf '%s' "$DRIFTED" | grep -q 'Attempt 1 of 3'; then
          ok "minor 3: a drift pickup does not claim an attempt"
        else
          bad "minor 3: a drift pickup does not claim an attempt" "$DRIFTED"
        fi
        # NEGATIVE SELF-TEST: a real attempt must still be counted out loud.
        if printf '%s' "$NORMAL" | grep -q 'Attempt 1 of 3'; then
          ok "minor 3: a NON-drift pickup still says Attempt 1 of 3 (negative self-test)"
        else
          bad "minor 3: a NON-drift pickup still says Attempt 1 of 3 (negative self-test)" "$NORMAL"
        fi ;;
      done)
        if printf '%s' "$DRIFTED" | grep -qi 'change NO code\|not for a diff'; then
          ok "minor 3: a drift completion does not point at a diff"
        else
          bad "minor 3: a drift completion does not point at a diff" "$DRIFTED"
        fi
        # NEGATIVE SELF-TEST: an ordinary run still points at its diff.
        if printf '%s' "$NORMAL" | grep -q 'See the branch/PR for the diff'; then
          ok "minor 3: a NON-drift completion still points at the diff (negative self-test)"
        else
          bad "minor 3: a NON-drift completion still points at the diff (negative self-test)" "$NORMAL"
        fi ;;
    esac
  else
    bad "minor 3: the $LABEL comment selector could be extracted" \
        "no drift-aware selector at the $LABEL site -- it still writes one message for both"
  fi
done

printf '\n== major 1: the drift streak ends when THIS round ends the drift ==\n'

# claude-reviewer on PR #30, 2026-11-16 14:36 UTC, major 1. The streak was
# cleared ONLY at the top of a LATER run. A drift round heals the drift inside
# itself (step 5's review repins the record), but nothing cleared the streak
# there -- so a push landing between that heal and the next tick made the NEXT
# run read a streak of already-healed drifts, gave the new drift zero of its two
# rounds, and paged "after 2 re-review round(s)" naming rounds that never ran.
#
# The predicate is deliberately the SAME three-part one the top-of-run clear
# uses, asked again at the one moment its answer can have changed. Both halves
# are load-bearing and both are pinned below: the gate's own 40 (never a second
# sha comparison out here) and BOTH shas readable, because `pr_head_sha` returns
# empty on any gh failure and the gate then falls to 10 -- refilling a budget
# that guards unreviewed code from a state nobody read is the PR #30 round-3
# scar, and it must stay refused at this site too.
python3 - "$WORKER" > "$WORK/step5clear.sh" <<'PY'
import sys
src = open(sys.argv[1], encoding="utf-8").read()
start = src.find('if [ "$FINAL_GATE" != "40" ]')
if start < 0:
    sys.stderr.write("EXTRACT-FAIL: step 5 never clears the drift streak\n")
    raise SystemExit(3)
end = src.find("\n", src.find("\n    fi", start) + 1)
sys.stdout.write(src[start:end])
PY

if [ ! -s "$WORK/step5clear.sh" ]; then
  bad "major 1: step 5 has a drift-streak clear at all" \
      "no clear after the re-review -- only a LATER run can end the streak, so a push landing in between starves the next drift of its rounds"
else
  ok "major 1: step 5 has a drift-streak clear at all"

  run_clear() {  # run_clear <final-gate> <final-reviewed-sha> <final-current-sha>
    (
      ISSUE=ASK-4899
      clear_drift_rounds() { printf 'CLEARED %s\n' "$1"; }
      FINAL_GATE="$1"; FINAL_REVIEWED_SHA="$2"; FINAL_CURRENT_SHA="$3"
      # shellcheck disable=SC1090
      . "$WORK/step5clear.sh"
    )
  }

  # THE FIX ITSELF: the round's own review repinned the record, the gate says so,
  # both shas were read. The streak this round was dispatched for is over NOW.
  HEALED="$(run_clear 10 1a0b2136 1a0b2136)"
  if printf '%s' "$HEALED" | grep -q 'CLEARED ASK-4899'; then
    ok "major 1: a round whose review healed the drift clears the streak"
  else
    bad "major 1: a round whose review healed the drift clears the streak" "$HEALED"
  fi

  # NEGATIVE SELF-TEST 1: still drifted at the end of the round. The streak must
  # SURVIVE -- this is the population the cap exists for (a dead reviewer writes
  # no record, so it never heals and reaches the cap in MAX_DRIFT_ROUNDS).
  STILL="$(run_clear 40 87225b06 1a0b2136)"
  if printf '%s' "$STILL" | grep -q 'CLEARED'; then
    bad "major 1: a still-drifted round does NOT clear the streak (negative self-test)" \
        "clearing here makes the cap unreachable and the page never fire: $STILL"
  else
    ok "major 1: a still-drifted round does NOT clear the streak (negative self-test)"
  fi

  # NEGATIVE SELF-TEST 2: the blind run. gh could not read the head, the gate
  # fell toward terminal and returned 10. "Not 40" is not "no drift" here, and a
  # budget refilled off an unread state is the round-3 major this file already
  # refuses at the top of the loop.
  BLIND="$(run_clear 10 1a0b2136 "")"
  if printf '%s' "$BLIND" | grep -q 'CLEARED'; then
    bad "major 1: an unreadable head does NOT refill the budget (negative self-test)" \
        "$BLIND"
  else
    ok "major 1: an unreadable head does NOT refill the budget (negative self-test)"
  fi

  # NEGATIVE SELF-TEST 3: the record carries no sha (pre-ASK-216, or the
  # reviewer's own gh failed). Same reasoning, the other input.
  NOREC="$(run_clear 10 "" 1a0b2136)"
  if printf '%s' "$NOREC" | grep -q 'CLEARED'; then
    bad "major 1: an unreadable record sha does NOT refill the budget (negative self-test)" \
        "$NOREC"
  else
    ok "major 1: an unreadable record sha does NOT refill the budget (negative self-test)"
  fi
fi

printf '\n== minor 1: an approval pinned to NO commit is never silent ==\n'

# claude-reviewer on PR #30, 2026-11-16 14:36 UTC, minor 1. rework_gate printed
# its NOTE when ONE sha was empty and nothing when BOTH were -- which is exactly
# what a single `gh pr view` outage produces, because both producers of these
# values shell the same command. The run then closed on "converged ... waits on
# founder merge" with nothing anywhere saying the approval is pinned to no
# commit, the same silence PR #30 round 3 minor 2 closed for the one-empty case.
#
# WHY THE GUARD MOVED FROM EMPTINESS TO ARITY. "The caller asked for the sha
# check" and "the caller got answers" are two different statements; reading the
# first off the second is what made the all-failed case indistinguishable from
# the short form. Arity is the caller's intent and cannot be emptied by an API
# outage. The short forms stay byte-identical, pinned below.
# shellcheck disable=SC1090
. "$REPO_SCRIPTS/pr-verdict-lib.sh"

BOTH_EMPTY="$(rework_gate "APPROVE WITH NITS" "" "" "")"; BE_RC=$?
if [ -n "$BOTH_EMPTY" ]; then
  ok "minor 1: both shas unreadable prints a NOTE"
else
  bad "minor 1: both shas unreadable prints a NOTE" \
      "silent -- an approval pinned to no commit closes the run as converged"
fi
if printf '%s' "$BOTH_EMPTY" | grep -qi 'neither\|both'; then
  ok "minor 1: the NOTE says it is BOTH shas, not one of them"
else
  bad "minor 1: the NOTE says it is BOTH shas, not one of them" "$BOTH_EMPTY"
fi
if [ "$BE_RC" = "10" ]; then
  ok "minor 1: the VERDICT is unchanged (still terminal, never a manufactured round)"
else
  bad "minor 1: the VERDICT is unchanged (still terminal, never a manufactured round)" \
      "rc=$BE_RC -- the fix was supposed to add a sentence, not change behaviour"
fi

# NEGATIVE SELF-TEST: the one-argument and two-argument forms must stay SILENT.
# A fix that printed on every worker run would be the noise the original guard
# existed to prevent.
SHORT1="$(rework_gate "APPROVE")"; S1_RC=$?
SHORT2="$(rework_gate "APPROVE" "CLEAN")"; S2_RC=$?
if [ -z "$SHORT1" ] && [ -z "$SHORT2" ] && [ "$S1_RC" = "10" ] && [ "$S2_RC" = "10" ]; then
  ok "minor 1: the short forms stay silent and terminal (negative self-test)"
else
  bad "minor 1: the short forms stay silent and terminal (negative self-test)" \
      "1-arg=[$SHORT1] rc=$S1_RC  2-arg=[$SHORT2] rc=$S2_RC"
fi

# NEGATIVE SELF-TEST: the pre-existing one-empty NOTEs must survive untouched,
# and a fully-read matching pair must still print nothing at all.
ONE_EMPTY="$(rework_gate "APPROVE" "" "" ffffffff)"
MATCHED="$(rework_gate "APPROVE" "" ffffffff ffffffff)"; M_RC=$?
if printf '%s' "$ONE_EMPTY" | grep -q 'ASK-216'; then
  ok "minor 1: the missing-record NOTE still fires (negative self-test)"
else
  bad "minor 1: the missing-record NOTE still fires (negative self-test)" "$ONE_EMPTY"
fi
if [ -z "$MATCHED" ] && [ "$M_RC" = "10" ]; then
  ok "minor 1: a healthy round still prints nothing (negative self-test)"
else
  bad "minor 1: a healthy round still prints nothing (negative self-test)" \
      "[$MATCHED] rc=$M_RC"
fi
rework_gate "APPROVE" "" 87225b06 1a0b2136 >/dev/null; D_RC=$?
if [ "$D_RC" = "40" ]; then
  ok "minor 1: real drift still returns 40 (negative self-test)"
else
  bad "minor 1: real drift still returns 40 (negative self-test)" "rc=$D_RC"
fi

printf '\n== minor 2: the docblock describes the callers that exist ==\n'

# claude-reviewer on PR #30, 2026-11-16 14:36 UTC, minor 2 (and round 4's minor
# on the same block). Two claims outlived their callers: that converge.sh uses
# the one-argument form, and that a caller "can never see" 40. Both read as
# proof that every gate-40 branch in both drivers is dead code. A reader who
# trusts them deletes a live branch, which is why this is pinned rather than
# left to the next reviewer to re-find.
LIB="$REPO_SCRIPTS/pr-verdict-lib.sh"
if grep -q 'because$' "$LIB" && grep -q 'converge.sh calls it that way' "$LIB"; then
  bad "minor 2: the docblock no longer claims converge.sh uses the short form" \
      "still says 'converge.sh calls it that way' while it passes five arguments"
else
  ok "minor 2: the docblock no longer claims converge.sh uses the short form"
fi
if grep -q 'A caller passing 1 or 2 arguments can never see it' "$LIB"; then
  bad "minor 2: the docblock does not assert live callers cannot see 40" \
      "all three live call sites pass four or five arguments"
else
  ok "minor 2: the docblock does not assert live callers cannot see 40"
fi

# DERIVED, NOT ASSERTED. The claim "no live caller uses the short form" is
# re-measured from the call sites themselves on every run, so the comment cannot
# rot back into a false statement while still reading plausibly.
#
# SCOPED TO THE TWO DRIVERS, not the whole scripts dir. A dir-wide sweep reads
# this harness's own deliberate 1-arg and 2-arg probes as production call sites
# and its grep patterns as calls -- it reported six short-form callers on a tree
# that has none, which is a false red that teaches a reader to ignore the case.
#
# The extractor is written to a file and then called, NOT inlined as
# `$(python3 - <<PY ... PY)`: a heredoc carrying `print(...)` inside a command
# substitution leaves bash hunting a matching paren and the whole file stops
# parsing after this line -- which is a file-wide failure wearing the costume of
# one broken case.
cat > "$WORK/arity.py" <<'PY'
import re
import sys

# A CALL, NOT A MENTION. The first pass matched `rework_gate ` anywhere and
# reported converge.sh:798 and :808 as 1-arg and 2-arg callers -- both are
# COMMENT PROSE about the function ("rework_gate reaches 10 from three states",
# "rework_gate owns drift"). It counted the quotes that happened to follow. A
# test that invents two callers teaches the reader to skip the case, so the
# match now requires a quoted first argument AND a non-comment line: every real
# call site in this tree is `$(rework_gate "..." ...)`.
for path in sys.argv[1:]:
    src = open(path, encoding="utf-8").read()
    for m in re.finditer(r'rework_gate "', src):
        line_start = src.rfind("\n", 0, m.start()) + 1
        if src[line_start:m.start()].lstrip().startswith("#"):
            continue
        # The call's own arguments end at the `)` that closes the substitution
        # it sits in; the outer quote comes after, so this never over-reads.
        end = src.find(")", m.end())
        args = re.findall(r'"[^"]*"', src[m.end() - 1:end])
        if len(args) < 3:
            line = src[:m.start()].count("\n") + 1
            print(path.rsplit("/", 1)[-1] + ":" + str(line) + " passes " + str(len(args)))
PY
SHORT_CALLS="$(python3 "$WORK/arity.py" "$CONVERGE" "$WORKER")"
if [ -z "$SHORT_CALLS" ]; then
  ok "minor 2: every live call site passes 3+ arguments (derived from the call sites)"
else
  bad "minor 2: every live call site passes 3+ arguments (derived from the call sites)" \
      "short-form call sites found, so the sha check is skipped there: $SHORT_CALLS"
fi

printf '\n== case r6a/r6b: a drift round is not handed the work phase ==\n'

# EXTRACTED, NOT GREPPED. The claim is that the drift path SELECTS a different
# tail, so the real WORK_PHASE/PROMPT block is lifted out of the real worker and
# evaluated twice with the same stubs and only DRIFT_ROUND changed.
EXTRACTED=1
python3 - "$WORKER" "$WORK/prompt-block.sh" <<'PYEOF' || EXTRACTED=0
import pathlib, sys
src = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8").splitlines(keepends=True)
try:
    start = next(i for i, l in enumerate(src)
                 if l.startswith('  WORK_PHASE="1. Read the issue: '))
    end = next(i for i, l in enumerate(src) if l == '$WORK_PHASE"\n' and i > start)
except StopIteration:
    sys.exit("EXTRACT FAILED: no WORK_PHASE/PROMPT block in %s" % sys.argv[1])
pathlib.Path(sys.argv[2]).write_text("".join(src[start:end + 1]), encoding="utf-8")
PYEOF

render_prompt() {
  (
    ISSUE="ASK-9999"; REWORK="<<REWORK>>"; TREE="/tmp/wt"; BRANCH="sana/ask-9999"
    DEFAULT_BRANCH="main"; TARGET_REPO="/tmp/repo"; SYNC="/tmp/sync.py"
    SKEL="/tmp/skel"; EXISTING_PR="829"; DRIFT_ROUND="$1"
    # shellcheck disable=SC1090
    . "$WORK/prompt-block.sh"
    printf '%s' "$PROMPT"
  )
}

DRIFT_PROMPT="$(render_prompt 3)"
PLAIN_PROMPT="$(render_prompt "")"

# A ZERO MUST PROVE IT IS EMPTY, NOT BROKEN -- and this guard exists because the
# first draft did not have it and mutant 4 caught that. Pointed at the pre-split
# worker via KIPI_WORKER_UNDER_TEST, the extractor found no block, wrote nothing,
# `render_prompt` sourced a missing file, PROMPT came out EMPTY -- and the leak
# case went GREEN, because an empty prompt leaks no work-phase marker. The one
# run that must redden loudest certified the defect instead. So nothing below is
# asked until both renders are proven to be real prompts.
KNOWN_ANSWER="You are Sana, the kipi Systems Engineer"
RENDERS_OK=1
[ "$EXTRACTED" = "1" ] || RENDERS_OK=0
case "$DRIFT_PROMPT" in *"$KNOWN_ANSWER"*) ;; *) RENDERS_OK=0 ;; esac
case "$PLAIN_PROMPT" in *"$KNOWN_ANSWER"*) ;; *) RENDERS_OK=0 ;; esac

if [ "$RENDERS_OK" != "1" ]; then
  for c in "the drift round prompt carries no work-phase instruction" \
           "the drift tail is actually present" \
           "the ordinary dispatch prompt is byte-identical after the split"; do
    bad "$c" "the prompt block did not render (extracted=$EXTRACTED, drift=${#DRIFT_PROMPT}B, plain=${#PLAIN_PROMPT}B) -- an absent prompt is not a passing one"
  done
else

# The four work-phase instructions that contradict a round whose correct outcome
# is no diff. Matched on the step text, so a renumbering does not fake a pass.
#
# EXPANSION-AGNOSTIC ON PURPOSE. The first draft of this array carried the
# commit step as "with the issue id $ISSUE in the message" and the plain case
# went red: these prompts are rendered, so $ISSUE is already ASK-9999 by the
# time the string exists. A marker holding an unexpanded variable can never
# match, which makes the LEAK half of the case pass vacuously -- it would have
# certified a drift prompt that still carried the commit instruction.
WORK_MARKERS=(
  "Work ONLY what the DoR scopes"
  "reproducer first and observed RED"
  "with the issue id "
  "OPEN IT BEFORE YOUR TURN ENDS"
)

leaked=""
for m in "${WORK_MARKERS[@]}"; do
  case "$DRIFT_PROMPT" in *"$m"*) leaked="$leaked | $m" ;; esac
done
if [ -z "$leaked" ]; then
  ok "the drift round prompt carries no work-phase instruction"
else
  bad "the drift round prompt carries no work-phase instruction" \
      "leaked:$leaked"
fi

# And it carries the tail it is supposed to have, so the leak case above cannot
# pass by the prompt coming out empty. The marker stops at the line break: the
# drift tail wraps "... is this / round succeeding", and the first draft matched
# across that break and went red on text that was present.
case "$DRIFT_PROMPT" in
  *"A round that ends with NO DIFF"*)
    ok "the drift tail is actually present" ;;
  *)
    bad "the drift tail is actually present" "no-diff-is-success line missing" ;;
esac

# NEGATIVE SELF-TEST, and the one that matters: the split moved 53 lines of
# escaped shell, so the ORDINARY dispatch prompt must be unchanged. All four
# markers present, and PROMPT must end on exactly the WORK_PHASE value -- which
# is what proves the move was lossless rather than merely syntactically valid.
missing=""
for m in "${WORK_MARKERS[@]}"; do
  case "$PLAIN_PROMPT" in *"$m"*) ;; *) missing="$missing | $m" ;; esac
done
PLAIN_WP="$(
  ISSUE="ASK-9999"; REWORK="<<REWORK>>"; TREE="/tmp/wt"; BRANCH="sana/ask-9999"
  DEFAULT_BRANCH="main"; TARGET_REPO="/tmp/repo"; SYNC="/tmp/sync.py"
  SKEL="/tmp/skel"; EXISTING_PR="829"; DRIFT_ROUND=""
  # shellcheck disable=SC1090
  . "$WORK/prompt-block.sh"; printf '%s' "$WORK_PHASE"
)"
printf '%s' "$PLAIN_PROMPT" > "$WORK/plain.txt"
printf '%s' "$PLAIN_WP"     > "$WORK/plain-wp.txt"
if [ -n "$missing" ]; then
  bad "the ordinary dispatch prompt is byte-identical after the split" \
      "work-phase markers lost:$missing"
elif ! grep -qF -- "$(tail -c 400 "$WORK/plain-wp.txt")" "$WORK/plain.txt"; then
  bad "the ordinary dispatch prompt is byte-identical after the split" \
      "PROMPT does not end on the WORK_PHASE value"
else
  ok "the ordinary dispatch prompt is byte-identical after the split"
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
