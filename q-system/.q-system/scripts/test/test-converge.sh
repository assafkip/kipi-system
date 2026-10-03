#!/usr/bin/env bash
# Reproducer + acceptance criteria for the convergence driver (ASK-113).
#
# THE DEFECT IT CLOSES: linear-worker.sh runs exactly one round, so a human had
# to re-dispatch every subsequent round by hand. PR #11 burned four rounds that
# way across one evening. Sana is a robot; the loop should drive itself.
#
# THE RISK IN A DRIVER LIKE THIS is the infinite loop and the false stop, and
# neither shows up in a single happy-path run. So this suite drives the REAL
# converge.sh against a FAKE worker + FAKE gh with scripted verdict sequences.
# Testing against the real worker would cost ~1 hour and real model spend per
# case, which in practice means the loop logic ships untested.
#
# Isolation: KIPI_STATE_DIR, KIPI_CONVERGE_WORKER, KIPI_NOTIFY and PATH all
# point into a mktemp dir. Never runs the real worker, never calls real gh,
# never touches live Linear, never pages Slack.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
CONV="$ROOT/q-system/.q-system/scripts/converge.sh"

PASS=0
fail() { echo "FAIL: $1" >&2; exit 1; }
ok()   { PASS=$((PASS + 1)); echo "  ok: $1"; }

[ -f "$CONV" ] || fail "converge.sh does not exist at $CONV"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/bin" "$WORK/state/pr-reviews"

# --- fake gh: PR number and head sha come from files the fake worker writes ---
cat > "$WORK/bin/gh" <<'EOF'
#!/usr/bin/env bash
# gh pr list --head <branch> --json number -q .[0].number
# gh pr view <n> --json headRefOid -q .headRefOid
case "${1:-} ${2:-}" in
  "pr list") cat "$FAKE_PR_FILE" 2>/dev/null ;;
  "pr view") cat "$FAKE_SHA_FILE" 2>/dev/null ;;
esac
exit 0
EOF
chmod +x "$WORK/bin/gh"

# --- fake worker: emits the Nth scripted verdict, then advances the sha --------
# SEQ is "verdict;sha" per round, pipe-separated. A repeated sha models a rework
# pass that changed no code.
cat > "$WORK/bin/fakeworker" <<'EOF'
#!/usr/bin/env bash
N=$(( $(cat "$FAKE_ROUND_FILE" 2>/dev/null || echo 0) + 1 ))
echo "$N" > "$FAKE_ROUND_FILE"
ENTRY="$(echo "$FAKE_SEQ" | cut -d'|' -f"$N")"
[ -n "$ENTRY" ] || exit 0
V="${ENTRY%%;*}"; S="${ENTRY##*;}"
echo "$S" > "$FAKE_SHA_FILE"
PR="$(cat "$FAKE_PR_FILE")"
[ "$V" = "NONE" ] && exit 0   # review died: no verdict record written
python3 -c "
import json,sys
json.dump({'pr':int(sys.argv[1]),'issue':'ASK-999','verdict':sys.argv[2],
           'review':'x','ts':'t'}, open(sys.argv[3],'w'))
" "$PR" "$V" "$FAKE_STATE/pr-reviews/pr-$PR.verdict.json"
exit 0
EOF
chmod +x "$WORK/bin/fakeworker"

export PATH="$WORK/bin:$PATH"
export KIPI_STATE_DIR="$WORK/state"
export KIPI_CONVERGE_WORKER="$WORK/bin/fakeworker"
export KIPI_NOTIFY="/usr/bin/true"
export FAKE_STATE="$WORK/state"
export FAKE_PR_FILE="$WORK/pr" FAKE_SHA_FILE="$WORK/sha" FAKE_ROUND_FILE="$WORK/round"

# run_case <name> <pr> <seq> <max-rounds> -> sets RC and ROUNDS
run_case() {
  echo "$2" > "$FAKE_PR_FILE"; echo "0" > "$FAKE_ROUND_FILE"; : > "$FAKE_SHA_FILE"
  rm -f "$FAKE_STATE"/pr-reviews/*.verdict.json
  export FAKE_SEQ="$3"
  set +e
  bash "$CONV" --issue ASK-999 --max-rounds "$4" >"$WORK/out" 2>&1
  RC=$?
  set -e
  ROUNDS="$(cat "$FAKE_ROUND_FILE")"
}

# --- exit 1: goal met -------------------------------------------------------
run_case approve-first 101 "APPROVE;sha1" 4
[ "$RC" = "1" ] || fail "clean APPROVE must exit 1 (goal met), got rc=$RC: $(cat "$WORK/out")"
[ "$ROUNDS" = "1" ] || fail "APPROVE on round 1 must not dispatch a second round, ran $ROUNDS"
ok "APPROVE on round 1 -> exit 1, exactly one dispatch"

run_case nits-first 102 "APPROVE WITH NITS;sha1" 4
[ "$RC" = "1" ] || fail "APPROVE WITH NITS must terminate as goal-met, got rc=$RC"
ok "APPROVE WITH NITS -> exit 1 (the severity floor is what makes this reachable)"

# THE headline case: the loop that could never end before the severity floor.
run_case rc-then-nits 103 "REQUEST CHANGES;sha1|APPROVE WITH NITS;sha2" 4
[ "$RC" = "1" ] || fail "RC-then-nits must converge, got rc=$RC: $(cat "$WORK/out")"
[ "$ROUNDS" = "2" ] || fail "must converge in exactly 2 rounds, ran $ROUNDS"
ok "REQUEST CHANGES then APPROVE WITH NITS -> converges in 2 rounds unattended"

# --- exit 2: turn cap -------------------------------------------------------
run_case never-approves 104 "REQUEST CHANGES;s1|REQUEST CHANGES;s2|REQUEST CHANGES;s3|REQUEST CHANGES;s4|REQUEST CHANGES;s5" 3
[ "$RC" = "2" ] || fail "a never-approving reviewer must hit the cap with exit 2, got rc=$RC"
[ "$ROUNDS" = "3" ] || fail "cap of 3 must dispatch exactly 3 rounds, ran $ROUNDS"
ok "never-approves -> exit 2 at the cap, cannot run forever"

# --- exit 5: no progress ----------------------------------------------------
# Same verdict AND the head sha never moved: the rework changed nothing.
run_case stalled 105 "REQUEST CHANGES;same|REQUEST CHANGES;same|REQUEST CHANGES;same" 4
[ "$RC" = "5" ] || fail "same verdict + unchanged sha must exit 5 (no progress), got rc=$RC"
[ "$ROUNDS" = "2" ] || fail "stall must be caught on round 2, not later; ran $ROUNDS"
ok "unchanged code + same verdict -> exit 5 on round 2, stops early"

# The false-stop guard: same verdict but the sha MOVED is real rework, and must
# NOT be treated as a stall. Without the two-part condition this case would stop
# at round 2 and report a stall on a PR that was actively being fixed.
run_case same-verdict-moving 106 "REQUEST CHANGES;a|REQUEST CHANGES;b|APPROVE WITH NITS;c" 4
[ "$RC" = "1" ] || fail "same verdict with a MOVING sha must keep going, got rc=$RC (false stall)"
[ "$ROUNDS" = "3" ] || fail "expected 3 rounds through the moving-sha path, ran $ROUNDS"
ok "same verdict but code changed -> not a stall, converges on round 3"

# --- exit 7: error threshold ------------------------------------------------
echo "" > "$FAKE_PR_FILE"; echo "0" > "$FAKE_ROUND_FILE"
export FAKE_SEQ="REQUEST CHANGES;sha1"
set +e; bash "$CONV" --issue ASK-999 --max-rounds 4 >"$WORK/out" 2>&1; RC=$?; set -e
[ "$RC" = "7" ] || fail "no PR must exit 7, got rc=$RC"
ok "no PR opened -> exit 7, does not loop against nothing"

run_case review-died 107 "NONE;sha1" 4
[ "$RC" = "7" ] || fail "a review that wrote no verdict must exit 7, got rc=$RC"
[ "$ROUNDS" = "1" ] || fail "must stop immediately on a dead review, ran $ROUNDS"
ok "review died (no verdict record) -> exit 7, no blind rework"

# --- ASK-310: an approved PR the record calls unarmed gets ARMED, not a page --
# THE CAPTURED CASE, from the live converge log for ASK-143 (2026-08-15T01:56:44Z):
#   DONE exit-1: PR #2 verdict 'APPROVE WITH NITS' after 2 round(s). Auto-merge
#   is NOT armed on it, so it goes green and sits: gh pr merge --auto --squash 2
# and the page that went with it: "approved but NOT armed -- it will sit green.
# Needs a human: gh pr merge --auto --squash 2". Every fact needed to act was in
# hand, and the loop handed the founder a shell command instead. Branch
# protection (enforce_admins=true, required validate + kipi/reviewer-approved)
# is what makes arming safe: GitHub holds the merge until both are green.
#
# This fake gh LOGS every call, so the assertions read what converge asked
# GitHub to do rather than grepping its source. The refusal text is a STUB
# (marked as such); the live refusal it models is PR #401, a draft, which the
# worker could not arm on 2026-09-21 (worker log, alert ASK-1996).
# The suite's own gh and page sink are put back at the end of this section, so
# no later case inherits a different fake.
cp "$WORK/bin/gh" "$WORK/bin/gh.orig"
cat > "$WORK/bin/gh" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$FAKE_GHLOG"
case "$*" in
  "pr list"*) cat "$FAKE_PR_FILE" 2>/dev/null ;;
  "pr view "*"--json autoMergeRequest"*) cat "$FAKE_ARMED_FILE" 2>/dev/null ;;
  "pr view"*) cat "$FAKE_SHA_FILE" 2>/dev/null ;;
  "pr merge"*)
    RC="$(cat "$FAKE_MERGE_RC_FILE" 2>/dev/null || echo 0)"
    if [ "$RC" = "0" ]; then echo true > "$FAKE_ARMED_FILE"; exit 0; fi
    echo "STUB-REFUSAL: pull request #$4 is still a draft" >&2
    exit "$RC" ;;
esac
exit 0
EOF
chmod +x "$WORK/bin/gh"
cat > "$WORK/bin/pagesink" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$FAKE_PAGES"
EOF
chmod +x "$WORK/bin/pagesink"
export FAKE_GHLOG="$WORK/gh.log" FAKE_ARMED_FILE="$WORK/armed" \
       FAKE_MERGE_RC_FILE="$WORK/merge-rc" FAKE_PAGES="$WORK/pages"

# The record key is the one converge derives, computed the same way: through
# repo-slug-lib.sh against this checkout, never a hand-typed guess.
AM_SLUG="$(bash -c '. "$1/q-system/.q-system/scripts/repo-slug-lib.sh"; slug_for_repo "$1" "$1/instance-registry.json"' _ "$ROOT" 2>/dev/null)"
am_record() { bash -c '. "$1/q-system/.q-system/scripts/repo-slug-lib.sh"; printf "%s/pr-reviews/%s.automerge" "$2" "$(artifact_key "$3" "$4")"' _ "$ROOT" "$FAKE_STATE" "$AM_SLUG" "$1"; }

# arm_case <pr> <record: armed|unarmed|none> <merge-rc>
arm_case() {
  : > "$FAKE_GHLOG"; : > "$FAKE_PAGES"; echo false > "$FAKE_ARMED_FILE"
  echo "$3" > "$FAKE_MERGE_RC_FILE"
  AMREC="$(am_record "$1")"
  rm -f "$AMREC"
  [ "$2" = "none" ] || printf '%s\n' "$2" > "$AMREC"
  export KIPI_NOTIFY="$WORK/bin/pagesink"
  run_case "arm-$1" "$1" "APPROVE WITH NITS;sha-$1" 1
  export KIPI_NOTIFY="/usr/bin/true"
}
arm_calls() { grep -c "^pr merge --auto --squash $1\$" "$FAKE_GHLOG" 2>/dev/null || true; }

arm_case 2 unarmed 0
[ "$RC" = "1" ] || fail "ASK-310 captured case: converge must still exit 1 (goal met), got rc=$RC: $(cat "$WORK/out")"
[ -s "$FAKE_PAGES" ] || fail "ASK-310: the converge run paged nothing at all, so this case cannot judge the page"
[ "$(arm_calls 2)" = "1" ] \
  || fail "ASK-310 THE DEFECT: the worker recorded PR #2 as NOT armed and converge asked GitHub to arm it
      $(arm_calls 2) time(s). It holds every fact needed to act and must arm it itself, exactly once.
      gh calls:
$(sed 's/^/        /' "$FAKE_GHLOG")"
grep -q 'gh pr merge' "$FAKE_PAGES" \
  && fail "ASK-310 THE DEFECT ON THE PHONE: converge armed nothing and paged a merge command to a human.
      Page: $(cat "$FAKE_PAGES")"
grep -q 'NOT armed' "$FAKE_PAGES" \
  && fail "ASK-310: the arm succeeded and the page still says NOT armed: $(cat "$FAKE_PAGES")"
[ "$(tr -d '[:space:]' < "$AMREC")" = "armed" ] \
  || fail "ASK-310: converge armed PR #2 and left the record saying '$(cat "$AMREC" 2>/dev/null)', so the next reader is told a stale state"
ok "ASK-310: approved + recorded unarmed -> converge arms it once, pages no merge command, record says armed"

arm_case 3 unarmed 1
[ "$RC" = "1" ] || fail "ASK-310 refusal: a refused arm must not change converge's exit code, got rc=$RC"
[ "$(arm_calls 3)" = "1" ] || fail "ASK-310 refusal: expected exactly one arm attempt on PR #3, got $(arm_calls 3)"
REFUSALS="$(grep -c 'STUB-REFUSAL' "$FAKE_PAGES" 2>/dev/null || true)"
[ "$REFUSALS" = "1" ] \
  || fail "ASK-310 refusal: gh refused to arm PR #3 and $REFUSALS page(s) carried gh's own words (expected exactly 1).
      Pages: $(cat "$FAKE_PAGES")"
grep -q 'Needs a human: gh pr merge' "$FAKE_PAGES" \
  && fail "ASK-310 refusal: the page names a human and a command instead of the refusal: $(cat "$FAKE_PAGES")"
ok "ASK-310: a refused arm pages ONCE with gh's own refusal, never a command for a human"

arm_case 4 none 0
[ "$(arm_calls 4)" = "1" ] || fail "ASK-310: nothing recorded the arm state for PR #4 and converge armed it $(arm_calls 4) time(s), expected 1"
grep -q 'gh pr merge' "$FAKE_PAGES" && fail "ASK-310: unrecorded arm state still paged a merge command: $(cat "$FAKE_PAGES")"
ok "ASK-310: approved + nothing recorded -> converge arms it instead of handing over the command"

arm_case 5 armed 0
[ "$(arm_calls 5)" = "0" ] || fail "ASK-310: the worker recorded PR #5 armed and converge armed it again ($(arm_calls 5) call(s))"
grep -c 'autoMergeRequest' "$FAKE_GHLOG" >/dev/null 2>&1 \
  && fail "ASK-310: converge re-probed the arm state of a PR the record already calls armed -- a second reader of one input"
ok "ASK-310: approved + recorded armed -> no gh arm call and no re-probe"

# --- PR #429 review nits: automerge_arm's own contract ------------------------
# Driven directly against the lib, with the same logging fake gh.
arm_unit() {  # arm_unit <dir> -> "STATE|ERR", gh calls appended to FAKE_GHLOG
  ( PATH="$WORK/bin:$PATH"; . "$ROOT/q-system/.q-system/scripts/pr-verdict-lib.sh"
    automerge_arm 9 "$1" /dev/null
    printf '%s|%s' "$AUTOMERGE_ARM_STATE" "$AUTOMERGE_ARM_ERR" )
}
# Nit: the header says an EMPTY probe means "could not tell", and the refused
# path's re-probe mapped it to unarmed. gh exits 0 with no answer here.
: > "$FAKE_ARMED_FILE"; echo 1 > "$FAKE_MERGE_RC_FILE"; : > "$FAKE_GHLOG"
GOT="$(arm_unit "$WORK")"
[ "${GOT%%|*}" = "unknown" ] \
  || fail "PR #429 nit: an empty re-probe after a refused arm became '${GOT%%|*}', but an empty answer is 'could not tell' (unknown)"
ok "automerge_arm: an empty probe answer is unknown, never unarmed"
# Nit: a dir that does not exist made every gh call fail on cd, and the page
# said "gh printed no reason" on a run where gh never ran.
: > "$FAKE_GHLOG"
GOT="$(arm_unit "$WORK/no-such-dir")"
[ "${GOT%%|*}" = "unknown" ] || fail "PR #429 nit: a missing dir gave state '${GOT%%|*}', want unknown"
case "${GOT#*|}" in *no-such-dir*) ;; *) fail "PR #429 nit: a missing dir's error does not name the dir: '${GOT#*|}'" ;; esac
[ ! -s "$FAKE_GHLOG" ] || fail "PR #429 nit: gh was called for a dir that does not exist: $(cat "$FAKE_GHLOG")"
ok "automerge_arm: a missing dir is named in the error, and gh never runs"
: > "$FAKE_MERGE_RC_FILE"
cp "$WORK/bin/gh.orig" "$WORK/bin/gh"

# --- dry mode + arg handling -------------------------------------------------
echo "108" > "$FAKE_PR_FILE"; echo "0" > "$FAKE_ROUND_FILE"
set +e; bash "$CONV" --issue ASK-999 --dry >"$WORK/out" 2>&1; RC=$?; set -e
[ "$RC" = "0" ] || fail "--dry must exit 0, got rc=$RC"
[ "$(cat "$FAKE_ROUND_FILE")" = "0" ] || fail "--dry dispatched a real round"
grep -q '\[dry\]' "$WORK/out" || fail "--dry produced no dry-run line"
ok "--dry inspects and dispatches nothing"

set +e; bash "$CONV" --max-rounds 2 >"$WORK/out" 2>&1; RC=$?; set -e
[ "$RC" = "1" ] || fail "missing --issue must be a usage error"
grep -q 'usage:' "$WORK/out" || fail "usage text missing"
ok "missing --issue -> usage error, never guesses an issue"

# --- the ASK-184 stranding: commits pushed, no PR ----------------------------
# Sana pushed two good commits with an observed red-then-green reproducer, then
# ended her turn on "bar 4 is in flight -- I'll report, then open the PR". The
# turn ended, no PR existed, the review never ran, and the driver stopped with
# nothing to look at. The worker now opens the PR itself when the branch is
# ahead of origin/main, because "remember to open it" is not enforcement.
grep -q 'gh pr create' "$ROOT/q-system/.q-system/scripts/linear-worker.sh" \
  || fail "worker cannot open a PR itself; an agent that forgets strands its own work"
grep -q 'rev-list --count origin/main..HEAD' "$ROOT/q-system/.q-system/scripts/linear-worker.sh" \
  || fail "PR auto-open must be gated on commits existing, or an empty branch opens an empty PR"
ok "worker opens the PR in code when commits are pushed but no PR exists"

# The driver must still treat a genuinely empty run as a failure, not paper over
# it: no commits means no PR means exit 7, which is the case above.
grep -q 'exit 7' "$CONV" || fail "converge lost its no-PR error exit"
ok "a run with no commits still exits 7 (auto-open does not mask real failure)"

# --- the ASK-181 wedge: a killed run must not leak its claim ------------------
# Observed 2026-07-27: converge was killed mid-run on ASK-181 and left
# `ASK-181 claimed by sana (session worker-...)`. linear-claim.py does not
# pid-check the claim (by design -- the claiming process exits immediately), so
# nothing reclaimed it, and with the lock still repo-root scoped that ONE dead
# session blocked every issue on the board until a human released it by hand.
#
# This drives the real converge.sh, SIGTERMs it while the fake worker is still
# running, and then reads the lock file back. Asserting on the trap's source
# would prove only that a trap line exists, not that the lock is actually gone.
CLAIMS="$WORK/state/claims.json"
export KIPI_LINEAR_CLAIMS="$CLAIMS"

cat > "$WORK/bin/slowworker" <<'EOF'
#!/usr/bin/env bash
# Hold a claim exactly the way the real worker does, then sit still so the
# parent can be killed while the claim is held.
python3 "$REAL_CLAIM" claim "$ISSUE_UNDER_TEST" --agent sana --session "worker-test-$$" >/dev/null 2>&1
sleep 120
EOF
chmod +x "$WORK/bin/slowworker"

export REAL_CLAIM="$ROOT/q-system/.q-system/scripts/linear-claim.py"
export ISSUE_UNDER_TEST="ASK-999"
echo "301" > "$FAKE_PR_FILE"; echo "0" > "$FAKE_ROUND_FILE"
rm -f "$CLAIMS"

# `set -m` gives this background job its OWN process group (pgid == CONV_PID), so
# cleanup can reap the whole subtree by group instead of by name. Without it,
# `pkill -f bin/slowworker` killed the worker shell but NOT its `sleep 120`
# child, and that orphan outlived the entire suite (ASK-190).
#
# The group id is a CHILD pid, never this shell's pgid, so a group signal below
# can never reach the test harness itself. That distinction is the whole safety
# story here: a cleanup that re-signals its own pid killed its caller once.
set -m
KIPI_CONVERGE_WORKER="$WORK/bin/slowworker" bash "$CONV" --issue ASK-999 --max-rounds 1 \
  >"$WORK/out" 2>&1 &
CONV_PID=$!
set +m
# Nothing from this case may outlive the suite, even on an early `fail`.
trap 'kill -KILL -'"$CONV_PID"' 2>/dev/null; rm -rf "$WORK"' EXIT

# Wait for the claim to actually exist before killing -- killing before the
# claim is taken would pass vacuously and prove nothing.
WAITED=0
until [ -s "$CLAIMS" ] || [ "$WAITED" -ge 60 ]; do sleep 0.5; WAITED=$((WAITED+1)); done
[ -s "$CLAIMS" ] || fail "fake worker never took a claim; the kill case would be vacuous"
ok "claim is held while the run is in flight (kill case is live, not vacuous)"

# `set -e` is active here (run_case restores it), and `wait` on a SIGTERMed job
# returns 143 -- which aborted this suite at exactly this line, reporting rc=143
# with every later case silently unrun. A test harness that dies while asserting
# on a kill is indistinguishable from the bug it is testing for.
#
# Signal the GROUP, not just converge.sh. converge.sh runs the worker as a
# FOREGROUND command (converge.sh:148), and bash defers a trap handler until the
# running foreground command returns -- so a TERM aimed only at CONV_PID sat
# unhandled for the worker's full `sleep 120`, and the `wait` below blocked with
# it. That is what pushed this suite to 122s and made the 60s capability gate
# report a PASSING test as RED (ASK-190). A real `kill` from a terminal or a
# launchd stop signals the group too, so this is also the more faithful case.
set +e
kill -TERM -"$CONV_PID" 2>/dev/null
wait "$CONV_PID" 2>/dev/null
set -e
# Give the trap its moment; it shells python3 to release.
WAITED=0
until [ ! -s "$CLAIMS" ] || python3 -c "
import json,sys
try: d=json.load(open('$CLAIMS'))
except Exception: sys.exit(0)
sys.exit(0 if not d or d.get('issue')!='ASK-999' else 1)" 2>/dev/null || [ "$WAITED" -ge 40 ]; do
  sleep 0.5; WAITED=$((WAITED+1))
done

STILL_HELD="$(python3 -c "
import json
try: d=json.load(open('$CLAIMS'))
except Exception: d=None
print((d or {}).get('issue',''))" 2>/dev/null)"
[ "$STILL_HELD" != "ASK-999" ] \
  || fail "SIGTERM leaked the claim on ASK-999 -- this is the ASK-181 board wedge"
ok "SIGTERM mid-run releases the claim (board is not wedged by a killed run)"

# Reap the group, not the name: `pkill -f bin/slowworker` never matched the
# worker's `sleep 120` child, whose own command line is just "sleep 120".
kill -KILL -"$CONV_PID" 2>/dev/null || true
trap 'rm -rf "$WORK"' EXIT
unset KIPI_LINEAR_CLAIMS REAL_CLAIM ISSUE_UNDER_TEST

# The suite must leave nothing running. An orphan that survives the assertions
# is invisible to `rc=0` and only shows up as a timeout in whatever harness runs
# this next.
# `|| true` inside the substitution: pgrep exits 1 on no-match, and with the
# suite's `pipefail` + `set -e` that clean result would abort the run.
LEAKED="$( { pgrep -g "$CONV_PID" 2>/dev/null || true; } | wc -l | tr -d ' ')"
[ "$LEAKED" = "0" ] || fail "kill case leaked $LEAKED process(es) in group $CONV_PID"
ok "kill case leaves no orphan behind (nothing outlives the suite)"

grep -q 'trap .*TERM' "$CONV" || fail "converge lost its TERM trap"
ok "TERM/INT/HUP traps wired"

# --- ASK-833: a converge that dies before opening a PR must COST an attempt ---
# THE DEFECT: exit-7 stops the run but records nothing. The 3-attempt cap keys on
# the attempts ledger, so an issue that fails this way is re-picked every cycle it
# wins the rotation, forever -- spending a budget slot each time and producing
# nothing. Measured 2026-08-15: ASK-128 stopped at exit-7 twice in one hour and
# was ABSENT from the ledger entirely.
#
# WHY THE WORKER'S OWN BUMP DOES NOT COVER THIS. linear-worker.sh already bumps on
# "exited 0 but opened no PR". That line is only reached by a worker that RUNS TO
# COMPLETION. A worker killed mid-flight -- the account's usage limit, a timeout,
# a SIGTERM -- never reaches it, and that is precisely the case converge sees as
# "no PR". The fake worker here writes no ledger entry, which models exactly that.
ATT="$WORK/state/linear-worker-attempts.json"
att_count() { python3 -c "
import json,sys
try: d=json.load(open(sys.argv[1]))
except Exception: d={}
print(d.get(sys.argv[2],{}).get('count',0))" "$ATT" "$1"; }

rm -f "$ATT"
echo "" > "$FAKE_PR_FILE"; echo "0" > "$FAKE_ROUND_FILE"
export FAKE_SEQ="REQUEST CHANGES;sha1"
set +e; bash "$CONV" --issue ASK-T833 --max-rounds 4 >"$WORK/out" 2>&1; RC=$?; set -e
[ "$RC" = "7" ] || fail "no-PR must still exit 7, got rc=$RC"
[ "$(att_count ASK-T833)" = "1" ] \
  || fail "exit-7 recorded NO attempt, so the cap can never trip (ASK-833): count=$(att_count ASK-T833)"
ok "exit-7 with no PR costs an attempt, so three of them mark the issue stuck"

# IDEMPOTENCE, THE OTHER HALF. When the worker DID reach its own bump, converge
# must not charge a second one for the same round: double-counting would mark a
# genuinely-retryable issue stuck after two failures instead of three, which is
# the same starvation bug pointed the other way.
cat > "$WORK/bin/bumpingworker" <<'EOF'
#!/usr/bin/env bash
python3 "$REAL_LEDGER" "$KIPI_STATE_DIR/linear-worker-attempts.json" \
  bump-attempt "$ISSUE_UNDER_TEST" "worker bumped this one itself"
exit 0
EOF
chmod +x "$WORK/bin/bumpingworker"
export REAL_LEDGER="$ROOT/q-system/.q-system/scripts/attempts-ledger.py"
export ISSUE_UNDER_TEST=ASK-T834
rm -f "$ATT"
echo "" > "$FAKE_PR_FILE"; echo "0" > "$FAKE_ROUND_FILE"
# set +e: this case also ends at exit-7, and run_case leaves `set -e` in effect,
# so an unguarded call aborts the whole suite silently at rc=7 -- which reads as
# a pass to anything that only greps for FAIL.
set +e
KIPI_CONVERGE_WORKER="$WORK/bin/bumpingworker" \
  bash "$CONV" --issue ASK-T834 --max-rounds 4 >"$WORK/out" 2>&1
set -e
[ "$(att_count ASK-T834)" = "1" ] \
  || fail "converge double-charged an attempt the worker already recorded: count=$(att_count ASK-T834)"
ok "an attempt the worker already recorded is not charged twice"
unset REAL_LEDGER ISSUE_UNDER_TEST

# AN ATTEMPT THAT WAS NOT PERSISTED DID NOT HAPPEN (PR #192 review, major).
# The first cut of the fix above ended its bump in `|| true`, so an unwritable
# ledger became a silent success: counter unmoved, run reports the ordinary
# exit-7, and the retry-forever bug returns with a fix in place that reads as
# working. The cap keys on this file; if the write fails the cap cannot trip, so
# that case gets its own exit code instead of blending into the no-PR case the
# dispatcher expects to see repeatedly.
# A DIRECTORY where the ledger file belongs is the portable unwritable path --
# no chmod, no root, and it fails the same way on every platform.
rm -rf "$ATT"; mkdir -p "$ATT"
echo "" > "$FAKE_PR_FILE"; echo "0" > "$FAKE_ROUND_FILE"
export FAKE_SEQ="REQUEST CHANGES;sha1"
set +e; bash "$CONV" --issue ASK-T835 --max-rounds 4 >"$WORK/out" 2>&1; RC=$?; set -e
[ "$RC" = "8" ] \
  || fail "an unrecordable attempt must exit 8, not blend into exit-7: got rc=$RC"
grep -q 'exit-8' "$WORK/out" || fail "exit-8 produced no operator-readable line"
ok "a ledger that cannot be written stops the run loudly, it is not swallowed"
rm -rf "$ATT"

# A REFUSAL COSTS NO ATTEMPT (PR #192 review round 2, major).
# An unchanged counter cannot by itself tell "the worker refused this spec" from
# "the worker was interrupted": both leave no PR and touch nothing. Charging the
# first would let three CORRECT refusals reach the cap and falsely mark the issue
# stuck -- the founder-queue routing ASK-275 removed, re-entering from the driver.
# This worker refuses the way the real one does: it records the refusal marker in
# the shared ledger and opens no PR.
cat > "$WORK/bin/refusingworker" <<'EOF'
#!/usr/bin/env bash
python3 "$REAL_LEDGER" "$KIPI_STATE_DIR/linear-worker-attempts.json" \
  claim-flag "$ISSUE_UNDER_TEST" refused_no_pr >/dev/null 2>&1
exit 0
EOF
chmod +x "$WORK/bin/refusingworker"
export REAL_LEDGER="$ROOT/q-system/.q-system/scripts/attempts-ledger.py"
export ISSUE_UNDER_TEST=ASK-T836
rm -f "$ATT"
echo "" > "$FAKE_PR_FILE"; echo "0" > "$FAKE_ROUND_FILE"
set +e
KIPI_CONVERGE_WORKER="$WORK/bin/refusingworker" \
  bash "$CONV" --issue ASK-T836 --max-rounds 4 >"$WORK/out" 2>&1
RC=$?
set -e
[ "$RC" = "7" ] || fail "a refusal still ends the run at exit 7, got rc=$RC"
[ "$(att_count ASK-T836)" = "0" ] \
  || fail "a REFUSAL was charged as a failed attempt; three would falsely mark the issue stuck (ASK-275): count=$(att_count ASK-T836)"
ok "a refusal costs no attempt, so correct refusals never accumulate into stuck"
unset REAL_LEDGER ISSUE_UNDER_TEST

# --- wiring ------------------------------------------------------------------
grep -q 'pr-verdict-lib.sh' "$CONV" || fail "converge.sh must use the shared verdict lib"
grep -q 'rework_gate'       "$CONV" || fail "converge.sh must gate on rework_gate, not its own regex"
grep -q "converge)" "$ROOT/kipi"    || fail "kipi CLI has no converge subcommand"
bash -n "$CONV"                     || fail "converge.sh does not parse"
ok "wiring: shared gate, registered in the kipi CLI, parses"

echo "PASS: $PASS/$PASS converge checks"
