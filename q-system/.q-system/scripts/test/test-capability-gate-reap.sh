#!/usr/bin/env bash
# Reproducer + acceptance criteria for the capability gate's test runner (ASK-190).
#
# THE DEFECT IT CLOSES: the gate ran every declared test through
# `subprocess.run(capture_output=True, timeout=N)`, which waits on pipe EOF, not
# on child exit. A test that backgrounds a child inheriting stdout keeps that
# pipe's write end open after the test itself has exited, so the gate blocks
# until its own deadline and then reports a PASSING test as
# `RED: test-timeout`. Five reviewed PRs sat unmergeable behind exactly that.
#
# The second half is the orphan: on timeout `run()` killed only the direct child,
# so backgrounded grandchildren survived the run and the next reader of the same
# pipe inherited the hang.
#
# WHY THIS DRIVES run_contained DIRECTLY rather than the gate CLI: run_contained
# IS the gate's test runner, and driving it takes seconds against real fixture
# processes instead of scaffolding a whole fake repo root. The wiring block at
# the bottom is what stops the unit from drifting away from its caller.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
GATE="$ROOT/q-system/.q-system/scripts/capability-gate.py"

PASS=0
fail() { echo "FAIL: $1" >&2; exit 1; }
ok()   { PASS=$((PASS + 1)); echo "  ok: $1"; }

[ -f "$GATE" ] || fail "capability-gate.py does not exist at $GATE"

WORK="$(mktemp -d)"
# Sentinels are distinctive sleep durations so pgrep can find a survivor without
# matching some unrelated `sleep` on the machine.
BG_SENTINEL=987
HANG_SENTINEL=986
cleanup() {
  pkill -f "sleep $BG_SENTINEL" 2>/dev/null
  pkill -f "sleep $HANG_SENTINEL" 2>/dev/null
  rm -rf "$WORK"
}
trap cleanup EXIT

# --- fixture 1: exits 0 immediately, but leaves a child holding stdout --------
cat > "$WORK/bg-holder.sh" <<EOF
#!/usr/bin/env bash
echo "assertion-one ok"
sleep $BG_SENTINEL &
echo "assertion-two ok"
exit 0
EOF

# --- fixture 2: hangs itself AND leaves a backgrounded child ------------------
cat > "$WORK/hangs.sh" <<EOF
#!/usr/bin/env bash
echo "started"
sleep $HANG_SENTINEL &
sleep $HANG_SENTINEL
EOF
chmod +x "$WORK/bg-holder.sh" "$WORK/hangs.sh"

run_contained_case() {
  # <script> <timeout> -> prints "<timed_out> <rc> <elapsed_s> <stdout-oneline>"
  python3 - "$GATE" "$1" "$2" <<'PY'
import importlib.util, sys, time
spec = importlib.util.spec_from_file_location("capgate", sys.argv[1])
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
t = time.time()
r = m.run_contained(["bash", sys.argv[2]], None, None, float(sys.argv[3]))
print(r.timed_out, r.returncode, round(time.time() - t, 1),
      " / ".join(r.stdout.split()))
PY
}

# --- the headline case: a passing test must be reported as passing ------------
# Deadline is 15s. The leaked child sleeps 987s, so pre-fix this blocks on pipe
# EOF and comes back `True` (timed out) after 15s on a test that exited 0 in
# milliseconds.
RES="$(run_contained_case "$WORK/bg-holder.sh" 15)"
TIMED_OUT="$(echo "$RES" | cut -d' ' -f1)"
RC="$(echo "$RES" | cut -d' ' -f2)"
ELAPSED="$(echo "$RES" | cut -d' ' -f3)"
[ "$TIMED_OUT" = "False" ] \
  || fail "a test that exits 0 was reported as timed out; the runner waited on pipe EOF, not child exit ($RES)"
[ "$RC" = "0" ] || fail "expected rc=0 from a passing fixture, got rc=$RC ($RES)"
python3 -c "import sys; sys.exit(0 if $ELAPSED < 10 else 1)" \
  || fail "runner took ${ELAPSED}s on a fixture that exits immediately; it is still blocking on the pipe"
ok "a test that exits 0 while leaking a child is reported as PASSED, not test-timeout"

echo "$RES" | grep -q 'assertion-one' \
  || fail "stdout lost: the assertions the fixture printed are missing ($RES)"
ok "stdout is still captured when the child is reaped (a green test keeps its output)"

pgrep -f "sleep $BG_SENTINEL" >/dev/null 2>&1 \
  && fail "the backgrounded child outlived the run; orphans are what re-create this bug"
ok "the backgrounded child is reaped, not left running"

# --- the timeout case: still bounded, still leaves nothing behind -------------
RES2="$(run_contained_case "$WORK/hangs.sh" 3)"
TIMED_OUT2="$(echo "$RES2" | cut -d' ' -f1)"
ELAPSED2="$(echo "$RES2" | cut -d' ' -f3)"
[ "$TIMED_OUT2" = "True" ] || fail "a genuinely hanging test must still time out, got $RES2"
python3 -c "import sys; sys.exit(0 if $ELAPSED2 < 12 else 1)" \
  || fail "timeout path took ${ELAPSED2}s against a 3s deadline; the post-kill read is unbounded"
ok "a real hang still times out, and the deadline is not doubled by the cleanup read"

echo "$RES2" | grep -q 'started' \
  || fail "partial output discarded on timeout; that is what made timeouts undiagnosable"
ok "partial output survives the timeout (the tail names what hung)"

pgrep -f "sleep $HANG_SENTINEL" >/dev/null 2>&1 \
  && fail "timeout killed only the direct child; the backgrounded grandchild survived"
ok "timeout kills the whole process group, grandchildren included"

# --- wiring: the unit above is the one the gate actually uses -----------------
grep -q 'r = run_contained(' "$GATE" \
  || fail "run_tests no longer calls run_contained; this suite would be testing dead code"
grep -q 'start_new_session=True' "$GATE" \
  || fail "no start_new_session: without its own session there is no group to kill"
grep -q 'os.killpg' "$GATE" || fail "gate no longer kills the process group"
grep -q 'proc.wait(timeout=timeout)' "$GATE" \
  || fail "the deadline is no longer on child exit; waiting on pipe EOF is the bug itself"
grep -q 'subprocess.run(cmd' "$GATE" \
  && fail "a test artifact is being run through subprocess.run again; that waits on pipe EOF"
python3 -c "import ast,sys; ast.parse(open(sys.argv[1]).read())" "$GATE" \
  || fail "capability-gate.py does not parse"
ok "wiring: run_tests uses run_contained, own session, group kill, and parses"

echo "PASS: $PASS/$PASS capability-gate reap checks"
