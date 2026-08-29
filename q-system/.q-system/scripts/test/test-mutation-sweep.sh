#!/usr/bin/env bash
# Paired check for q-system/.q-system/scripts/mutation-sweep.py.
#
# The sweep's whole output is a survival number, and a survival number from a
# harness that applied no mutants or ran no tests looks EXACTLY like a survival
# number from a healthy one. Two of the 17 instances that motivated the sweep
# were mutation harnesses in precisely that state, each reporting clean results
# for months. So the harness's own negative control runs on every commit, not
# on the day someone remembers to check it.
#
# --self-test builds a fixture whose answers are known by construction and
# asserts all four: a test that reads its subject's verdict is KILLED, one that
# only checks "something was printed" is SURVIVED-ABSENT, one that calls the
# subject and ignores the answer is SURVIVED, and one that names no subject
# yields no candidate. It also asserts four baselines actually executed and
# that every scored mutant changed the file's sha.
#
# It went red twice during development before it went green (an operator whose
# trailing \s* anchor ate the newline and welded two statements into a syntax
# error; a paren scan that turned sys.exit(main()) into sys.exit(0)) ). That is
# the point: this check can fail, and has.
set -euo pipefail

# BASH_SOURCE, never $PWD: the gate invokes tests from the repo root, but a
# developer runs them from anywhere, and the root has to follow the code.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
SWEEP="$ROOT/q-system/.q-system/scripts/mutation-sweep.py"

if [ ! -f "$SWEEP" ]; then
  echo "FAIL: mutation-sweep.py missing at $SWEEP" >&2
  exit 1
fi

out="$(python3 "$SWEEP" --self-test 2>&1)" || {
  echo "$out"
  echo "FAIL: mutation-sweep --self-test did not pass" >&2
  exit 1
}

# Match the text, not just the exit code: a harness that stopped discriminating
# could still exit 0 while reporting nothing. This is the same failure shape the
# sweep exists to find, so it is not left to $?.
case "$out" in
  *"sighted=KILLED"*"blind=SURVIVED-ABSENT"*"shallow=SURVIVED"*)
    echo "ok: mutation-sweep self-test discriminated all four fixture shapes"
    ;;
  *)
    echo "$out"
    echo "FAIL: self-test exited 0 without reporting the four verdicts" >&2
    exit 1
    ;;
esac
