#!/usr/bin/env bash
# verify.sh --changed: the PUSH door runs the tests that own what the branch
# changed, never the whole suite, and never nothing.
#
# why this file: founder-directed 2026-09-30, "find a way to fix this right now
# as a top priority ... its a giant time and token suck." Every change paid the
# full suite twice: pre-push ran verify.sh --full (~6300 tests in consulting, 6
# to 13 min, pushes hitting a 30-min timeout) and CI ran it again as the
# required `validate` check. The full suite now runs once, in CI.
#
# Same method as test_verify_adversarial.sh: a FRESH throwaway repo per case, a
# real bare origin, the real script, the EXIT CODE asserted. Each fixture suite
# holds one RED test that names nothing, test_red_bystander.py. It is the
# witness: a pass proves it was NOT run; a run that must reach the full suite
# proves it WAS, because it blocks.
VERIFY_SRC="${1:?usage: test_verify_changed.sh /path/to/verify.sh}"
SELECT_SRC="$(dirname "$VERIFY_SRC")/verify_select.py"
pass=0; fail=0
ROOTS=()

check() {
  if [ "$2" = "$3" ]; then printf '  PASS  %-52s exit=%s\n' "$1" "$3"; pass=$((pass+1))
  else printf '  FAIL  %-52s exit=%s want=%s\n' "$1" "$3" "$2"; fail=$((fail+1)); fi
}

# A repo on DEFAULT branch $1 with an origin that has it, and a feature branch
# checked out. Everything lives under one temp root so one cleanup removes it.
fixture() {
  local branch="${1:-main}" root d
  root="$(mktemp -d)"; ROOTS+=("$root")
  d="$root/repo"
  git init -q -b "$branch" "$d"
  git -C "$d" config user.email t@t; git -C "$d" config user.name t
  mkdir -p "$d/q-system/.q-system" "$d/suite"
  cp "$VERIFY_SRC" "$d/q-system/.q-system/verify.sh"
  if [ -f "$SELECT_SRC" ]; then cp "$SELECT_SRC" "$d/q-system/.q-system/verify_select.py"; fi
  printf 'suite\n' > "$d/.verify-suites"
  printf 'VALUE = 1\n' > "$d/suite/mod_a.py"
  printf 'import mod_a\ndef test_a():\n    assert mod_a.VALUE == 1\n' > "$d/suite/test_mod_a.py"
  printf 'def test_bystander():\n    assert False\n' > "$d/suite/test_red_bystander.py"
  git -C "$d" add -A; git -C "$d" commit -qm fixture
  git clone -q --bare "$d" "$root/origin.git"
  git -C "$d" remote add origin "$root/origin.git"
  git -C "$d" fetch -q origin
  git -C "$d" checkout -q -b feature
  printf '%s' "$d"
}

run() { ( cd "$1" && shift && bash q-system/.q-system/verify.sh "$@" >/dev/null 2>&1 ); }

# Asserts the FULL suite ran: exit 1 AND the bystander's failure is in the output.
# Exit 1 alone would also pass on a crash for an unrelated reason.
full_ran() {
  local name="$1" r="$2"; shift 2
  local out rc
  out="$( cd "$r" && bash q-system/.q-system/verify.sh "$@" 2>&1 )"; rc=$?
  case "$out" in
    *"test_red_bystander.py::test_bystander"*) check "$name" 1 "$rc" ;;
    *) echo "$out" | tail -5 | sed 's/^/    /'; check "$name (bystander not run)" 1 99 ;;
  esac
}

# --- THE REPRODUCER: a one-module change on a NEW branch (no upstream) runs only
# its owning test. Before --changed existed this was a usage error (exit 2), and
# the door it replaces, --full, blocks on the bystander (exit 1).
R=$(fixture main)
printf 'VALUE = 1\n# touched\n' > "$R/suite/mod_a.py"; git -C "$R" commit -qam touch
OUT="$( cd "$R" && bash q-system/.q-system/verify.sh --changed 2>&1 )"; rc=$?
check "new branch, one module -> only its owning test" 0 $rc
case "$OUT" in
  *"(1 selected)"*) check "selection printed with its count" 0 0 ;;
  *) echo "$OUT" | sed 's/^/    /'; check "selection printed with its count" 0 1 ;;
esac
case "$OUT" in
  *"since merge-base with origin/main"*) check "base named in the output" 0 0 ;;
  *) check "base named in the output" 0 1 ;;
esac
full_ran "control: --full on the same repo blocks" "$R" --full

# THE NEGATIVE SELF-TEST: narrowing must not mean skipping. A red owning test
# still blocks the push.
R=$(fixture main)
printf 'VALUE = 2\n' > "$R/suite/mod_a.py"; git -C "$R" commit -qam break
run "$R" --changed; check "red owning test still BLOCKS" 1 $?

# The default branch may be master (cole-gtm). Found without configuration.
R=$(fixture master)
printf 'VALUE = 1\n# touched\n' > "$R/suite/mod_a.py"; git -C "$R" commit -qam touch
run "$R" --changed; check "origin default master is found" 0 $?

# origin/HEAD, when set, decides over the main/master guess.
R=$(fixture main)
git -C "$R" remote set-head origin main >/dev/null
printf 'VALUE = 1\n# touched\n' > "$R/suite/mod_a.py"; git -C "$R" commit -qam touch
run "$R" --changed; check "origin/HEAD symbolic ref honoured" 0 $?

# SELECTOR FAILURE -> FULL SUITE, never nothing. No selector in the graded tree.
R=$(fixture main)
git -C "$R" rm -q q-system/.q-system/verify_select.py
printf 'VALUE = 1\n# touched\n' > "$R/suite/mod_a.py"; git -C "$R" commit -qam touch
full_ran "missing selector -> full suite" "$R" --changed

# A selector that CRASHES -> full suite as well.
R=$(fixture main)
printf 'import sys\nsys.exit(3)\n' > "$R/q-system/.q-system/verify_select.py"
printf 'VALUE = 1\n# touched\n' > "$R/suite/mod_a.py"; git -C "$R" commit -qam touch
full_ran "crashing selector -> full suite" "$R" --changed

# NO BASE -> FULL SUITE. A repo with no origin cannot say what changed.
R=$(fixture main)
git -C "$R" remote remove origin
printf 'VALUE = 1\n# touched\n' > "$R/suite/mod_a.py"; git -C "$R" commit -qam touch
full_ran "no origin -> full suite" "$R" --changed

# An explicit --base that does not resolve -> full suite, not a pass.
R=$(fixture main)
printf 'VALUE = 1\n# touched\n' > "$R/suite/mod_a.py"; git -C "$R" commit -qam touch
full_ran "unresolvable --base -> full suite" "$R" --changed --base origin/nope

# The COMMIT is graded, not the working tree. Uncommitted breakage is not part
# of the push and must not block it; committed breakage must.
R=$(fixture main)
printf 'VALUE = 1\n# touched\n' > "$R/suite/mod_a.py"; git -C "$R" commit -qam touch
printf 'def (\n' > "$R/suite/mod_a.py"
run "$R" --changed; check "uncommitted breakage not graded" 0 $?
R=$(fixture main)
printf 'def (\n' > "$R/broken.py"; git -C "$R" add broken.py; git -C "$R" commit -qm broken
run "$R" --changed; check "committed syntax error BLOCKS" 1 $?

# --rev grades the pushed commit even when HEAD is elsewhere.
R=$(fixture main)
printf 'VALUE = 2\n' > "$R/suite/mod_a.py"; git -C "$R" commit -qam break
BAD="$(git -C "$R" rev-parse HEAD)"; git -C "$R" checkout -q main
run "$R" --changed --rev "$BAD"; check "--rev grades that commit, not HEAD" 1 $?

# Nothing changed against the base: nothing to verify, exit 0.
R=$(fixture main)
run "$R" --changed; check "no change vs base -> exit 0" 0 $?

# A deletion-only branch is NOT empty: the deleted module's tests still run.
R=$(fixture main)
git -C "$R" rm -q suite/mod_a.py; git -C "$R" commit -qm delete
run "$R" --changed; check "deleting a module runs the tests naming it" 1 $?

# A bad argument is a usage error, not a silent full or empty run.
R=$(fixture main)
run "$R" --changed --bogus; check "unknown flag -> usage error" 2 $?

# A NON-ASCII path. git quotes it by default ("suite/test_caf\303\251.py"), which
# no `^suite/` gate matches, so the suite was skipped at exit 0 (PR #489 review).
R=$(fixture main)
printf 'def test_accent():\n    assert False\n' > "$R/suite/test_café.py"
git -C "$R" add "suite/test_café.py"; git -C "$R" commit -qm accent
run "$R" --changed; check "non-ASCII red test path still BLOCKS" 1 $?

for r in "${ROOTS[@]}"; do rm -rf "$r"; done
echo
echo "changed: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
