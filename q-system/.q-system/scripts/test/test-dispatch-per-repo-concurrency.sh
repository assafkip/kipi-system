#!/usr/bin/env bash
# Pairs with the PER-REPO CONCURRENCY block in kipi-dispatch.sh (sp-e45251f7).
#
# The claim under test: dispatch may run several converges at once ACROSS repos,
# and PREFERS a repo with nothing live. That is what lets KIPI_DISPATCH_MAX rise
# above 1 without rebuilding the same-file collision the cap was set to 1 to
# avoid.
#
# IT IS NOT "never two in ONE repo", and this file used to say that it was. When
# only one repo is dispatchable, dispatch takes it anyway -- case 3 asserts
# exactly that -- because an absolute rule re-created the ready-queue starvation
# test-ci-redrive 14g exists to prevent. A test file that overstates its own
# guarantee is how a reader concludes the cap is safer than it is (ASK-811).
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
trap 'kill_all_fakes 2>/dev/null; rm -rf "$WORK"' EXIT

# THE NOTIFIER IS STUBBED FOR THE WHOLE SUITE, AND NOT AS A FORMALITY.
# Case 10's fixture carries `pr-review-agent.sh ... --issue` in its argv (via
# exec -a) so that live_converges has a realistic re-review shape to count. It is
# a renamed `sleep` and executes nothing -- but a test that merely LOOKS like it
# can reach the founder's phone is one edit away from actually doing it. Scar
# 2026-08-01: a suite reporting 14/14 green paged the founder twice.
export KIPI_NOTIFY=/usr/bin/true

# --- extract the helpers from the shipped script -----------------------------
HELPERS="$WORK/helpers.sh"
# THE CUT MUST START AT THE TOP OF THE BLOCK, AND THIS HAS BITTEN THREE TIMES.
#   - `/^LIVE_LEDGER=/,/^}$/` ended at the FIRST closing brace: 1 of 3 functions.
#   - `/^live_converges()/` missed the LIVE_PATTERN= assignment one line above it,
#     so every sourced copy died on "LIVE_PATTERN: unbound variable".
# Each time the harness CRASHED and the `cmd && ok || bad` idiom reported the
# crash as a PASS. So the extract is anchored at the first line of the block and
# every symbol the loop needs is asserted present -- a missing one is a loud
# FATAL, never a silent green.
sed -n '/^LIVE_PATTERN=/,/^# --- END PER-REPO CONCURRENCY ---$/p' "$DISPATCH" > "$HELPERS"
for sym in LIVE_PATTERN live_converges LIVE_LEDGER live_repos record_live_run compact_live_ledger; do
  grep -q "$sym" "$HELPERS" \
    || { echo "FATAL: $sym missing from the extract of $DISPATCH" >&2; exit 1; }
done
# A sourced extract that cannot even run is not a test. Prove it executes before
# any case depends on it.
bash -c "set -u; . '$HELPERS'; live_converges >/dev/null" \
  || { echo "FATAL: the extracted helper block does not execute cleanly" >&2; exit 1; }

export KIPI_DISPATCH_LIVE_LEDGER="$WORK/live.tsv"
# HERMETIC COUNTING. live_converges() scans the machine-wide process table, so a
# real pr-review-agent running in another terminal counted as a fixture and the
# counting cases went red against correct code. Every fixture below carries the
# FIXTURETAG marker and the counter is scoped to it, so this suite measures only
# processes it started.
export KIPI_DISPATCH_LIVE_PATTERN="FIXTURETAG.*--issue"
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
  bash -c 'exec -a "FIXTURETAG converge.sh --issue '"$1"' --max-rounds 3" sleep 60' >/dev/null 2>&1 &
  echo $! >> "$WORK/pids"
  echo $!
}

# live_converges() reads the GLOBAL process table, so any fake left behind by an
# earlier case is counted by a later one. That is not a nit: cases 9 and 10 read
# counts, and a leftover turns a correct implementation red (observed -- case 9
# saw "4 live, 1 attributed" from three stragglers). Every spawn is registered
# above and reaped here, so each counting case starts from a known floor.
kill_all_fakes() {
  [ -f "$WORK/pids" ] || return 0
  while read -r fp; do kill "$fp" 2>/dev/null || true; done < "$WORK/pids"
  : > "$WORK/pids"
  # Give the table a moment to actually drop them, or the next count races.
  for _ in 1 2 3 4 5; do
    [ "$(pgrep -f 'FIXTURETAG.*--issue' 2>/dev/null | grep -c . || true)" = "0" ] && break
    sleep 1
  done
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
sed -n '/^LIVE_REPOS="\$(live_repos)"$/,/^# --- END REPO SELECTION ---$/p' "$DISPATCH" > "$LOOPF"
# Ending the cut at PICKEOF stopped one line short of the fallback, so the suite
# tested a loop that could never fall back and blamed the code. Assert both
# halves are present -- the skip AND the fallback.
for sym in deprioritising FALLBACK_NAME 'every dispatchable repo has a live run'; do
  grep -q "$sym" "$LOOPF" \
    || { echo "FATAL: '$sym' missing from the selection-loop extract of $DISPATCH" >&2; exit 1; }
done

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
echo "$SEL" | grep -q 'deprioritising' \
  && ok "the skip states WHY, so the log explains the decision" \
  || bad "the skip was silent"

echo "== 3. a LONE busy repo is still taken (starvation is worse than overlap) =="
# test-ci-redrive 14g exists because a live converge used to starve the ready
# queue. An absolute one-run-per-repo rule re-creates exactly that, so the rule
# is a PREFERENCE: fall back to the busy repo when it is the only candidate. The
# per-ISSUE duplicate guard downstream still stops a second run of the SAME issue.
SEL_ONE="$(run_selection "$(printf 'alpha\t/repos/alpha\n')")"
echo "$SEL_ONE" | grep -q 'PICKED=alpha' \
  && ok "alpha alone and busy is still dispatched -- the ready queue is not starved" \
  || bad "a lone busy repo yielded no pick, which is the 14g starvation (got: $SEL_ONE)"
echo "$SEL_ONE" | grep -q 'every dispatchable repo has a live run' \
  && ok "the fallback says it is a fallback" \
  || bad "the fallback was silent"

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

kill_all_fakes   # cases 9 and 10 read COUNTS; start them from a known floor
echo "== 9. an UNATTRIBUTED live run does NOT stall the fleet =="
# An earlier cut halted the whole cycle when pgrep exceeded the attributed count.
# That broke test-dispatch-liveness 6a (it exited before the per-issue duplicate
# guard could fire) and turned one hand-run converge into a fleet-wide stall.
# Unattributed simply means "not known-busy".
PID_H="$(spawn_fake_converge ASK-500)"       # live, deliberately NOT recorded
SEL_U="$(run_selection "$(printf 'beta\t/repos/beta\n')")"
echo "$SEL_U" | grep -q 'PICKED=beta' \
  && ok "a run this script never launched does not stop an unrelated repo" \
  || bad "an unattributed run stalled the fleet (got: $SEL_U)"
kill "$PID_H" 2>/dev/null; wait "$PID_H" 2>/dev/null

kill_all_fakes
echo "== 10. a RE-REVIEW child counts against the concurrency cap =="
# A dispatch does not always launch a converge. On a reviewer redrive it runs
#   bash .../pr-review-agent.sh <PR> --issue ASK-nnn --post
# which the old `converge.sh --issue` pattern never matched, so re-review
# children spent a `claude -p` pair outside the cap entirely.
spawn_fake_rereview() {
  bash -c 'exec -a "FIXTURETAG bash /x/pr-review-agent.sh 163 --issue '"$1"' --post" sleep 60' >/dev/null 2>&1 &
  echo $! >> "$WORK/pids"
  echo $!
}
BASE="$(live_converges)"; BASE="${BASE:-0}"
PID_R="$(spawn_fake_rereview ASK-600)"
sleep 1
NOW="$(live_converges)"; NOW="${NOW:-0}"
[ "$NOW" -gt "$BASE" ] \
  && ok "a live re-review child is counted by live_converges ($BASE -> $NOW)" \
  || bad "a re-review child is invisible to the cap" "count stayed $BASE; it would run outside the spend bound"

# T10-neg: the OLD pattern must NOT see it, or case 10 proves nothing.
OLD="$(pgrep -f 'FIXTURETAG converge\.sh --issue' 2>/dev/null | grep -c . || true)"; OLD="${OLD:-0}"
[ "$OLD" -eq "$BASE" ] \
  && ok "T10-neg the old converge-only pattern is blind to it (the gap was real)" \
  || bad "T10-neg the assertion CAN fail" "the old pattern already matched, so nothing was fixed"
kill "$PID_R" 2>/dev/null; wait "$PID_R" 2>/dev/null

echo "== 11. a FAILED ledger write is loud, not silently successful =="
# An unwritten row silently disables per-repo exclusion for that repo. Point the
# ledger at an unwritable path and require a non-zero return plus a said reason.
SAID="$WORK/said.txt"
RC_OUT="$(
  KIPI_DISPATCH_LIVE_LEDGER=/dev/null/impossible/live.tsv bash -c '
    set -uo pipefail
    say()  { echo "SAY: $*" >> "'"$SAID"'"; }
    page() { echo "PAGE: $*" >> "'"$SAID"'"; }
    export KIPI_DISPATCH_LIVE_LEDGER=/dev/null/impossible/live.tsv
    . "'"$HELPERS"'"
    record_live_run 1234 ASK-700 /repos/delta && echo "RETURNED_OK" || echo "RETURNED_FAIL"
  '
)"
echo "$RC_OUT" | grep -q RETURNED_FAIL \
  && ok "an unwritable ledger returns failure instead of a silent success" \
  || bad "a failed ledger write reported success" "per-repo exclusion would be off with nothing saying so"
grep -q 'LEDGER WRITE FAILED' "$SAID" 2>/dev/null \
  && ok "the failure is said, so the log names it" \
  || bad "the ledger failure is logged" "no reason recorded"
grep -q '^PAGE:' "$SAID" 2>/dev/null \
  && ok "the failure pages, because a disabled guard is not a log-only event" \
  || bad "the ledger failure pages" "nobody would learn the guard went blind"

kill_all_fakes
echo "== 12. an issue id is matched WHOLE: ASK-10 is not ASK-100 (codex minor) =="
# A plain substring match let a live ASK-100 converge satisfy the identity check
# for a dead ASK-10 row, marking the wrong repo busy until the real run exited.
PID_P="$(spawn_fake_converge ASK-100)"
record_live_run "$PID_P" "ASK-10" "/repos/prefix"     # DIFFERENT issue, same prefix
live_repos | grep -qxF -- "/repos/prefix" \
  && bad "ASK-10 accepted an ASK-100 process" "a prefix collision marks the wrong repo busy" \
  || ok "ASK-10 does not accept an ASK-100 process"

# T12-neg: the exact id must still match, or the guard rejects everything.
record_live_run "$PID_P" "ASK-100" "/repos/exact"
live_repos | grep -qxF -- "/repos/exact" \
  && ok "T12-neg the exact id still matches (the guard did not go blind)" \
  || bad "T12-neg the assertion CAN fail" "bounding the match broke legitimate identity"
kill "$PID_P" 2>/dev/null; wait "$PID_P" 2>/dev/null

echo
echo "-------- $PASS passed, $FAIL failed --------"
[ "$FAIL" -eq 0 ] || exit 1
echo "PASS: dispatch-per-repo-concurrency"
