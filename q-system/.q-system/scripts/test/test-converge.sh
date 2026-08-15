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

# --- wiring ------------------------------------------------------------------
grep -q 'pr-verdict-lib.sh' "$CONV" || fail "converge.sh must use the shared verdict lib"
grep -q 'rework_gate'       "$CONV" || fail "converge.sh must gate on rework_gate, not its own regex"
grep -q "converge)" "$ROOT/kipi"    || fail "kipi CLI has no converge subcommand"
bash -n "$CONV"                     || fail "converge.sh does not parse"
ok "wiring: shared gate, registered in the kipi CLI, parses"

echo "PASS: $PASS/$PASS converge checks"
