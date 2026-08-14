#!/usr/bin/env bash
# Pairs with the PER-REPO CONCURRENCY block in kipi-dispatch.sh (sp-e45251f7).
#
# The claim under test: dispatch may run several converges at once ACROSS repos,
# and never two in ONE repo. That is what lets KIPI_DISPATCH_MAX rise above 1
# without rebuilding the same-file collision the cap was set to 1 to avoid.
#
# THIS TEST READS THE REAL SCRIPT, IT DOES NOT RESTATE IT. Both the helper
# functions and the selection loop are cut out of kipi-dispatch.sh by marker and
# sourced. A copy of the logic here would pass forever while the shipped code
# drifted -- which is the failure mode the fixture scar in test-repo-preflight.sh
# is about. If a marker below stops matching, that is a REAL failure: the code
# moved and this test must be re-pointed, not a green to be waved through.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DISPATCH="$(cd "$HERE/../../../.." && pwd)/kipi-dispatch.sh"
[ -f "$DISPATCH" ] || { echo "FATAL: no kipi-dispatch.sh at $DISPATCH" >&2; exit 1; }

PASS=0; FAIL=0
ok()  { echo "  PASS: $*"; PASS=$((PASS+1)); }
bad() { echo "  FAIL: $*"; FAIL=$((FAIL+1)); }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# --- extract the helpers from the shipped script -----------------------------
HELPERS="$WORK/helpers.sh"
# Starts at live_converges(), NOT at LIVE_LEDGER=. The selection loop calls
# live_converges to compare the pgrep total against the attributed count, so a
# cut that began one line lower produced a loop that died on
# "live_converges: command not found" -- and the surrounding `||` made that read
# as a PASS on the case it was meant to fail. Extract everything the loop calls.
sed -n '/^live_converges()/,/^# --- END PER-REPO CONCURRENCY ---$/p' "$DISPATCH" > "$HELPERS"
for fn in live_converges live_repos record_live_run compact_live_ledger; do
  grep -q "$fn" "$HELPERS" \
    || { echo "FATAL: $fn missing from the extract of $DISPATCH" >&2; exit 1; }
done

export KIPI_DISPATCH_LIVE_LEDGER="$WORK/live.tsv"
# shellcheck disable=SC1090
. "$HELPERS"

# A stand-in for a converge run: a real process whose argv carries `--issue N`,
# so the pid-reuse guard has something true to match on. `sleep` alone would not
# carry the issue id and every guard below would read as a false negative.
#
# STDOUT AND STDERR GO TO /dev/null, AND THAT IS NOT TIDINESS. This function is
# called inside `$( )`, so a backgrounded child inheriting the substitution pipe
# keeps it open and the substitution blocks until the child exits -- a 60s hang
# per spawn, which is what the first run of this file did. Detaching the fds is
# what makes the pid readable immediately.
spawn_fake_converge() {
  bash -c 'exec -a "converge.sh --issue '"$1"' --max-rounds 3" sleep 60' >/dev/null 2>&1 &
  echo $!
}

echo "== 1. a live run in one repo does not hide the others =="
PID_A="$(spawn_fake_converge ASK-100)"
record_live_run "$PID_A" "ASK-100" "/repos/alpha"
OUT="$(live_repos)"
printf '%s\n' "$OUT" | grep -qxF -- "/repos/alpha" \
  && ok "the repo holding a live run is reported" \
  || bad "a live run was not attributed to its repo (got: $OUT)"
printf '%s\n' "$OUT" | grep -qxF -- "/repos/beta" \
  && bad "a repo with NO live run was reported as busy" \
  || ok "a repo with no live run is absent"

echo "== 2. the selection loop SKIPS a busy repo and picks the next (the throughput win) =="
# The real loop, cut from the shipped script by its own marker comment.
LOOPF="$WORK/loop.sh"
sed -n '/^LIVE_REPOS="\$(live_repos)"$/,/^PICKEOF$/p' "$DISPATCH" > "$LOOPF"
grep -q 'one run per repo' "$LOOPF" \
  || { echo "FATAL: could not extract the selection loop from $DISPATCH" >&2; exit 1; }

run_selection() {
  PICKS="$1" bash -c '
    set -uo pipefail
    say() { echo "SAY: $*"; }
    export KIPI_DISPATCH_LIVE_LEDGER="'"$KIPI_DISPATCH_LIVE_LEDGER"'"
    . "'"$HELPERS"'"
    TARGET_NAME=""
    . "'"$LOOPF"'"
    echo "PICKED=$TARGET_NAME"
  '
}
SEL="$(run_selection "$(printf 'alpha\t/repos/alpha\nbeta\t/repos/beta\n')")"
echo "$SEL" | grep -q 'PICKED=beta' \
  && ok "alpha is busy, so beta is dispatched -- the fleet does not stall" \
  || bad "the busy repo was not skipped to the next one (got: $SEL)"
echo "$SEL" | grep -q 'one run per repo' \
  && ok "the skip states WHY, so the log explains the decision" \
  || bad "the skip was silent"

echo "== 3. the SAME repo is still serialized (the cap-1 guarantee is kept) =="
SEL_ONE="$(run_selection "$(printf 'alpha\t/repos/alpha\n')")"
echo "$SEL_ONE" | grep -q 'PICKED=$' || echo "$SEL_ONE" | grep -qv 'PICKED=alpha' \
  && ok "alpha alone and busy yields no pick -- no second run in one repo" \
  || bad "a second concurrent run was allowed in the SAME repo (got: $SEL_ONE)"

echo "== 4. MUTATION: break the skip and case 2 must go RED =="
MUT="$WORK/loop-mutant.sh"
sed 's/^    continue$/    :/' "$LOOPF" > "$MUT"
MUT_OUT="$(PICKS="$(printf 'alpha\t/repos/alpha\nbeta\t/repos/beta\n')" bash -c '
  set -uo pipefail
  say() { echo "SAY: $*"; }
  export KIPI_DISPATCH_LIVE_LEDGER="'"$KIPI_DISPATCH_LIVE_LEDGER"'"
  . "'"$HELPERS"'"
  TARGET_NAME=""
  . "'"$MUT"'"
  echo "PICKED=$TARGET_NAME"
')"
echo "$MUT_OUT" | grep -q 'PICKED=alpha' \
  && ok "with the skip removed the busy repo IS picked -- case 2 is load-bearing" \
  || bad "the mutant behaved identically, so case 2 proves nothing (got: $MUT_OUT)"

echo "== 5. a DEAD run does not hold its repo hostage =="
kill "$PID_A" 2>/dev/null; wait "$PID_A" 2>/dev/null
live_repos | grep -qxF -- "/repos/alpha" \
  && bad "a dead converge still blocks its repo -- dispatch would starve forever" \
  || ok "the dead run is reaped on read, so the repo frees itself"

echo "== 6. PID REUSE: a live pid that is not this converge does not hold the repo =="
# The pid is alive, but its argv carries a DIFFERENT issue. Both halves of the
# guard must agree, or a recycled pid pins a repo permanently.
PID_C="$(spawn_fake_converge ASK-999)"
record_live_run "$PID_C" "ASK-777" "/repos/gamma"
live_repos | grep -qxF -- "/repos/gamma" \
  && bad "a pid whose argv names another issue was accepted as this run" \
  || ok "pid liveness alone is not enough; the issue must match too"
kill "$PID_C" 2>/dev/null; wait "$PID_C" 2>/dev/null

echo "== 7. path matching is EXACT, not substring =="
PID_D="$(spawn_fake_converge ASK-200)"
record_live_run "$PID_D" "ASK-200" "/repos/foo"
SEL2="$(run_selection "$(printf 'foobar\t/repos/foo-bar\n')")"
echo "$SEL2" | grep -q 'PICKED=foobar' \
  && ok "/repos/foo being busy does not suppress /repos/foo-bar" \
  || bad "a prefix match starved an unrelated repo (got: $SEL2)"
kill "$PID_D" 2>/dev/null; wait "$PID_D" 2>/dev/null

echo "== 8. compaction drops dead rows and keeps live ones =="
PID_E="$(spawn_fake_converge ASK-300)"
record_live_run "$PID_E" "ASK-300" "/repos/live"
record_live_run "999999" "ASK-301" "/repos/dead"
compact_live_ledger
grep -qF -- "/repos/live" "$KIPI_DISPATCH_LIVE_LEDGER" \
  && ok "compaction keeps the live row" \
  || bad "compaction dropped a LIVE run, which would let a second run into that repo"
grep -qF -- "/repos/dead" "$KIPI_DISPATCH_LIVE_LEDGER" \
  && bad "compaction kept a dead row, so the ledger grows without bound" \
  || ok "compaction drops the dead row"
kill "$PID_E" 2>/dev/null; wait "$PID_E" 2>/dev/null

echo "== 9. an UNATTRIBUTED live run stops the cycle (disjointness is unprovable) =="
# live_repos() only sees runs THIS script recorded. A hand-run `kipi converge`
# is live in the process table and absent from the ledger, and it could be in the
# very repo about to be entered. The two counts must agree or we enter nothing.
PID_H="$(spawn_fake_converge ASK-500)"       # live, deliberately NOT recorded
SEL_U="$(run_selection "$(printf 'beta\t/repos/beta\n')")"
echo "$SEL_U" | grep -q 'PICKED=beta' \
  && bad "an unattributed live run did not stop the cycle" "dispatch entered a repo while a run it cannot see is live (got: $SEL_U)" \
  || ok "an unattributed live run stops the cycle"
echo "$SEL_U" | grep -q 'cannot prove disjointness' \
  && ok "the refusal says WHY, so the log is not a mystery" \
  || bad "the refusal explains itself" "no reason logged (got: $SEL_U)"

# T9-neg: record that same run, and the cycle must proceed again. Without this,
# case 9 could not tell "stopped because unattributed" from "stopped always".
record_live_run "$PID_H" "ASK-500" "/repos/gamma"
SEL_K="$(run_selection "$(printf 'beta\t/repos/beta\n')")"
echo "$SEL_K" | grep -q 'PICKED=beta' \
  && ok "T9-neg once the run IS attributed, an unrelated repo is entered again" \
  || bad "T9-neg the assertion CAN fail" "attributing the run did not unblock selection (got: $SEL_K)"
kill "$PID_H" 2>/dev/null; wait "$PID_H" 2>/dev/null

echo
echo "-------- $PASS passed, $FAIL failed --------"
[ "$FAIL" -eq 0 ] || exit 1
echo "PASS: dispatch-per-repo-concurrency"
