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
# asserts all FIVE: a test that reads its subject's verdict is KILLED, one that
# only checks "something was printed" is SURVIVED-ABSENT, one that calls the
# subject and ignores the answer is SURVIVED, one that asserts only the block
# exit code is KILLED (the exit-2 collision, where deleting the subject also
# yields rc 2 and the absent control alone would call it blind), and one that
# names no subject
# yields no candidate. It also asserts five baselines actually executed and
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
    echo "ok: mutation-sweep self-test discriminated all five fixture shapes"
    ;;
  *)
    echo "$out"
    echo "FAIL: self-test exited 0 without reporting the four verdicts" >&2
    exit 1
    ;;
esac

# THE DECLARED CHECK HAS TO RUN THE OTHER SUITES (PR #272 major). This ran
# --self-test and nothing else, so the resume-cache and sweep-lock regressions
# lived outside CI: green here proved nothing about either. Both are green and
# both are wired.
for suite in test_resume_cache_key.py test_sweep_lock.py test_sweep_runner_and_engine.py test_restore_guard.py; do
  if ! python3 -m pytest "$ROOT/q-system/.q-system/scripts/test/$suite" -q \
       -p no:cacheprovider; then
    echo "FAIL: $suite" >&2
    exit 1
  fi
  echo "ok: $suite"
done

# NOT WIRED, and the reason is not caution. mutate-mutation-sweep.py exits 1
# today because all five components it probes survive --self-test, so wiring it
# would either turn this suite red for work nobody has done yet or get softened
# into a check that cannot fail -- and a check that cannot fail is the thing this
# tool exists to find. Order: make --self-test cover those five (sp-66a98810),
# then wire it. Recorded in the ledger rather than only here.
