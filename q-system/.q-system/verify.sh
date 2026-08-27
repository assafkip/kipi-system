#!/usr/bin/env bash
# THE floor. One script, run identically at every gate, so the agent, the commit
# and the merge cannot quietly drift apart.
#
# why this exists: this repo had SEVEN different pre-commit commands, a
# hand-written native pre-push (lefthook kept silently skipping its own), and no
# CI at all. Every one of those checks was real; nothing guaranteed the same set
# ran at each door. "It passed" did not say which door it passed.
#
#   verify.sh --staged    what a commit would contain, checked against a COPY
#   verify.sh --full      the working tree, everything
#
# --staged never touches your working tree. It writes the git INDEX out to a
# temporary directory with `git checkout-index` and runs there. The obvious
# alternative, `git stash --keep-index`, puts uncommitted work inside a stash
# that a crash mid-hook can strand. Verifying against a copy costs a few hundred
# milliseconds and cannot eat anybody's work.
#
# THE ONE RULE THAT IS NOT NEGOTIABLE: if this script discovers no checks to
# run, it FAILS. A gate that cannot run must not pass. The alternative is a
# green exit that means "I looked for a linter and did not find one", which is
# indistinguishable from "your code is fine" at every call site that reads only
# the exit code.
set -euo pipefail

MODE="${1:---full}"
REPO="$(git rev-parse --show-toplevel)"
RAN=()
FAILED=()
TMP=""

# `return 0` is LOAD-BEARING, not tidiness. An EXIT trap's last command sets the
# script's exit status. The first version was a bare `[ -n "$TMP" ] && [ -d ...
# ] && rm -rf "$TMP"`, and in --full mode TMP is empty, so the chain returned 1
# and EVERY SUCCESSFUL --full RUN EXITED 1. It printed "verify.sh ok" and then
# failed. Wired at pre-push and CI, that is a floor that blocks every push
# forever, which is the same amount of protection as a floor that blocks
# nothing: both get switched off within a day.
#
# Caught 2026-08-27 by the adversarial suite asserting the exit code of a CLEAN
# repo. No test of the failure cases could have found it: they all expect 1.
cleanup() {
  if [ -n "$TMP" ] && [ -d "$TMP" ]; then rm -rf "$TMP"; fi
  return 0
}
trap cleanup EXIT

case "$MODE" in
  --staged|--full) ;;
  *) echo "usage: verify.sh [--staged|--full]" >&2; exit 2 ;;
esac

STAGED=""
if [ "$MODE" = "--staged" ]; then
  STAGED="$(git -C "$REPO" diff --cached --name-only --diff-filter=ACMR)"
  if [ -z "$STAGED" ]; then
    echo "verify.sh --staged: nothing staged, nothing to verify."
    exit 0
  fi
  # The staged snapshot, materialised. Not the working tree, and not a stash.
  TMP="$(mktemp -d)"
  git -C "$REPO" checkout-index -a -f --prefix="$TMP/"
  TARGET="$TMP"
else
  TARGET="$REPO"
fi

say() { printf '  %-28s %s\n' "$1" "$2"; }

run_check() {
  local name="$1"; shift
  RAN+=("$name")
  if "$@" >/tmp/verify-$$-out 2>&1; then
    say "$name" "ok"
  else
    FAILED+=("$name")
    say "$name" "FAILED"
    sed 's/^/      /' /tmp/verify-$$-out | tail -30
  fi
  rm -f /tmp/verify-$$-out
}

echo "verify.sh ${MODE} in ${TARGET}"

# --- python: syntax, every tracked .py -----------------------------------
# py_compile is not a linter and is not pretending to be one. It is the floor
# under the floor: a file that does not parse cannot be reasoned about by
# anything downstream, and this repo has no ruff installed to catch it.
PYFILES="$(git -C "$REPO" ls-files '*.py' | head -4000)"
if [ -n "$PYFILES" ]; then
  run_check "python syntax" bash -c '
    cd "$1" || exit 1
    fail=0
    while IFS= read -r f; do
      [ -f "$f" ] || continue
      python3 -m py_compile "$f" 2>&1 || fail=1
    done <<< "$2"
    exit $fail
  ' _ "$TARGET" "$PYFILES"
fi

# --- shell: syntax, every tracked .sh ------------------------------------
SHFILES="$(git -C "$REPO" ls-files '*.sh' | head -2000)"
if [ -n "$SHFILES" ]; then
  run_check "shell syntax" bash -c '
    cd "$1" || exit 1
    fail=0
    while IFS= read -r f; do
      [ -f "$f" ] || continue
      bash -n "$f" 2>&1 || fail=1
    done <<< "$2"
    exit $fail
  ' _ "$TARGET" "$SHFILES"
fi

# --- json: every tracked .json parses ------------------------------------
# Config in this fleet IS behaviour: room lists, model tiers, source weights.
# A malformed one fails at 07:30 in a launchd job nobody is watching.
JSONFILES="$(git -C "$REPO" ls-files '*.json' | grep -v -E '(^|/)(dist|node_modules)/' | head -3000)"
if [ -n "$JSONFILES" ]; then
  run_check "json parse" bash -c '
    cd "$1" || exit 1
    fail=0
    while IFS= read -r f; do
      [ -f "$f" ] || continue
      python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$f" 2>&1 || fail=1
    done <<< "$2"
    exit $fail
  ' _ "$TARGET" "$JSONFILES"
fi

# --- ruff, only if the machine has it ------------------------------------
# Optional TOOL, never an optional CHECK: if ruff is installed it must pass.
# The discovery is about what exists, not about what is allowed to fail.
if command -v ruff >/dev/null 2>&1; then
  run_check "ruff" bash -c 'cd "$1" && ruff check .' _ "$TARGET"
fi

# --- tests ---------------------------------------------------------------
# --staged runs the tests from the COPY, which is the point: it proves the
# snapshot being committed passes on its own, not that the working tree does.
# NO PIPE INTO `grep -q` HERE, and that is a scar, not a style preference.
# The first version of this line ended `| grep -q .`. Under `set -o pipefail`,
# grep -q exits the instant it matches, git gets SIGPIPE (141), and the PIPELINE
# reports failure precisely BECAUSE there were tests. Measured on the first live
# run: 400 test files present, pytest silently skipped, exit 0, "verify.sh ok".
# A discovery step that inverts on success is worse than no discovery step.
# FAIL FAST BEFORE THE EXPENSIVE PART. Measured 2026-08-27: a commit with one
# unparseable .py staged blocked correctly and took over two minutes, because
# the syntax check failed and the script then ran the full suite anyway. Nobody
# waits two minutes to be told about a typo; they run --no-verify, and then the
# floor is decorative. Tests cannot tell you anything useful about a tree that
# does not parse, so there is nothing lost by stopping here.
if [ ${#FAILED[@]} -gt 0 ]; then
  echo
  echo "verify.sh FAILED (${#FAILED[@]}/${#RAN[@]}): ${FAILED[*]}" >&2
  echo "Stopped before the test suites: a tree that does not parse cannot be tested." >&2
  exit 1
fi

TESTFILES="$(git -C "$REPO" ls-files 'test_*.py' '*/test_*.py')"

# THE SUITE MANIFEST, `.verify-suites` at the repo root, one `dir` per line.
# Each is a directory pytest is invoked FROM, because that is how these suites
# actually run: q-consult/pipeline/tests imports `pipeline`, which resolves only
# with q-consult as the working directory. A single root-level pytest is the
# obvious design and it is wrong here. Measured: from the repo root, 3526 tests
# collect and 896 error out, most of them belonging to the nested instances
# under projects/ that are separate repos with their own paths. From their own
# directories the two real suites collect 5379 and 486 with zero errors.
#
# A repo with no manifest falls back to one root pytest, which is right for a
# normal repo and is what every instance without the file gets.
if [ -f "$REPO/.verify-suites" ]; then
  if command -v pytest >/dev/null 2>&1 || python3 -c "import pytest" 2>/dev/null; then
    while IFS= read -r suite; do
      case "$suite" in ''|'#'*) continue ;; esac
      if [ ! -d "$TARGET/$suite" ]; then
        # A manifest naming a directory that is gone is a BROKEN FLOOR. Silently
        # skipping it is how a suite stops running and nobody notices.
        RAN+=("pytest:$suite")
        FAILED+=("pytest:$suite (directory missing)")
        say "pytest:$suite" "FAILED (missing)"
        continue
      fi
      # --staged runs only the suites that OWN a staged file. Not a weaker
      # check, a narrower input: the same pytest, on the same snapshot, scoped
      # to what this commit can have broken. The full suite is 5 minutes here,
      # and a 5-minute pre-commit is a hook people delete. Pre-push and CI run
      # --full, so nothing escapes; it just escapes later than the fastest
      # possible door.
      if [ "$MODE" = "--staged" ]; then
        if ! printf '%s\n' "$STAGED" | grep -q "^$suite/"; then
          say "pytest:$suite" "skipped (no staged files)"
          continue
        fi
      fi
      run_check "pytest:$suite" bash -c 'cd "$1/$2" && python3 -m pytest -q --no-header' \
                _ "$TARGET" "$suite"
    done < "$REPO/.verify-suites"
  else
    RAN+=("pytest")
    FAILED+=("pytest: .verify-suites present but pytest is not installed")
    say "pytest" "FAILED (not installed)"
  fi
elif [ -f "$REPO/pytest.ini" ] || [ -f "$REPO/pyproject.toml" ] || \
     [ -d "$REPO/tests" ] || [ -n "$TESTFILES" ]; then
  if command -v pytest >/dev/null 2>&1 || python3 -c "import pytest" 2>/dev/null; then
    run_check "pytest" bash -c 'cd "$1" && python3 -m pytest -q --no-header' _ "$TARGET"
  else
    # Tests exist and the runner does not. That is a broken floor, not a pass.
    RAN+=("pytest")
    FAILED+=("pytest: tests present but pytest is not installed")
    say "pytest" "FAILED (not installed)"
  fi
fi

echo
if [ ${#RAN[@]} -eq 0 ]; then
  echo "verify.sh: NO CHECKS DISCOVERED. Failing." >&2
  echo "A gate that cannot run must not pass. Wire a check or delete this hook." >&2
  exit 1
fi

if [ ${#FAILED[@]} -gt 0 ]; then
  echo "verify.sh FAILED (${#FAILED[@]}/${#RAN[@]}): ${FAILED[*]}" >&2
  exit 1
fi

echo "verify.sh ok (${#RAN[@]} checks: ${RAN[*]})"
