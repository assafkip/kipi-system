#!/usr/bin/env bash
# Mutation harness for linear-agent-receiver.py. Proves the suite can FAIL.
#
# WHY THIS EXISTS
# ---------------
# The first run of this harness "passed" 11/11 on a mutant that was byte-identical to
# the original, because the sed pattern had the wrong indentation and silently matched
# nothing. A mutation that does not apply is a FALSE GREEN that reads as proof. So
# this script refuses to run the suite until it has confirmed the mutant actually
# differs from the original -- the mutation is verified before it is trusted, same
# rule the code under test applies to signatures.
#
# Each mutant breaks ONE guarantee. The suite must go RED for every one of them.
# A mutant that stays GREEN names a guarantee nothing is actually checking.
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$DIR/../linear-agent-receiver.py"
SUITE="$DIR/test-linear-agent-receiver.py"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# name | sed expression | the guarantee it destroys
run_mutant() {
  local name="$1" expr="$2" guarantee="$3"
  local mutant="$WORK/$name.py"

  sed "$expr" "$SRC" > "$mutant"

  if cmp -s "$SRC" "$mutant"; then
    echo "[BROKEN] $name: mutation did not apply -- pattern matched nothing."
    echo "         A non-applying mutant is a false green. Fix the pattern."
    return 2
  fi

  local out
  out="$(KIPI_NOTIFY=/usr/bin/true KIPI_RECEIVER_UNDER_TEST="$mutant" \
         python3 "$SUITE" 2>&1)"
  local rc=$?

  if [ $rc -ne 0 ]; then
    echo "[CAUGHT] $name -- suite went RED as it must ($guarantee)"
    echo "$out" | grep '^\[FAIL\]' | sed 's/^/           /'
    return 0
  else
    echo "[ESCAPED] $name -- suite stayed GREEN. NOTHING CHECKS: $guarantee"
    return 1
  fi
}

echo "=== mutation testing linear-agent-receiver.py ==="
fails=0

run_mutant "no-signature-check" \
  's/^        ok, reason = verify_signature(raw, sig, secret)$/        ok, reason = (True, "MUTANT")/' \
  "a forged webhook must not reach the runner" || fails=$((fails+1))

run_mutant "no-replay-guard" \
  's/^    if abs(now - int(ts)) > MAX_SKEW_MS:$/    if False:/' \
  "a replayed old event must be rejected" || fails=$((fails+1))

run_mutant "no-thought-ack" \
  '/^    # Step 1 -- beat the 10s/,/^    })$/s/^    post_activity(session_id, {$/    _skip = ({/' \
  "the 10s acknowledgement activity must be emitted" || fails=$((fails+1))

run_mutant "runner-not-called" \
  's/^    proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=None)$/    proc = subprocess.CompletedProcess(cmd, 0, "MUTANT", "")/' \
  "the delegated issue must actually reach the local runner" || fails=$((fails+1))

run_mutant "no-terminal-activity" \
  's/^        "type": "response" if ok else "error",$/        "type": "thought",/' \
  "the session must be closed with a terminal activity, not left active" || fails=$((fails+1))

echo "==============================================="
if [ $fails -eq 0 ]; then
  echo "all mutants caught -- the suite has teeth"
else
  echo "$fails mutant(s) escaped or broken -- see above"
fi
exit $fails
