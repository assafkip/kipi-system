#!/usr/bin/env bash
# Reproducer + regression suite for linear-issue-ref-check.py
# Pairs with .claude/rules/linear-first.md (the commit-msg gate).
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHECK="$SCRIPT_DIR/../linear-issue-ref-check.py"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

pass=0
fail=0

# run_case <name> <expected_exit> <message>
run_case() {
  local name="$1" expect="$2" msg="$3"
  local f="$TMP/msg.txt"
  printf '%s\n' "$msg" > "$f"
  LINEAR_BYPASS_LEDGER="$TMP/bypass.jsonl" python3 "$CHECK" "$f" >/dev/null 2>&1
  local got=$?
  if [ "$got" -eq "$expect" ]; then
    echo "  PASS: $name (exit $got)"
    pass=$((pass + 1))
  else
    echo "  FAIL: $name (expected exit $expect, got $got)"
    fail=$((fail + 1))
  fi
}

echo "=== linear-issue-ref-check ==="

# The rule: a commit with no issue reference is refused.
run_case "bare message is refused"            1 "fix(gate): restamp classifier"
run_case "conventional-only is refused"       1 "docs: update handoff"

# An issue reference anywhere in the message satisfies it.
run_case "issue ref in subject"               0 "fix(gate): restamp classifier (ASK-61)"
run_case "issue ref in body"                  0 "$(printf 'fix: something\n\nRefs ASK-61')"
run_case "other team prefix accepted"         0 "feat: thing (CAP-45)"
run_case "bare id accepted"                   0 "ASK-111 quick-plan reflex wording"

# A lowercase id is NOT an issue ref — Linear ids are uppercase.
run_case "lowercase is not an id"             1 "fix: ask-61 mentioned in prose"

# The escape hatch requires a real reason.
run_case "bypass with reason"                 0 "chore: typo [no-issue: docs typo]"
run_case "bypass with empty reason refused"   1 "chore: typo [no-issue: ]"
run_case "bypass without reason refused"      1 "chore: typo [no-issue]"

# Git's own machinery must not be gated.
run_case "merge commit skipped"               0 "Merge branch 'main' into feature"
run_case "revert skipped"                     0 "$(printf "Revert \"fix: thing\"\n\nThis reverts commit abc123.")"
run_case "fixup skipped"                      0 "fixup! fix(gate): restamp classifier"
run_case "comment-only message skipped"       0 "$(printf '# Please enter the commit message\n# with # are ignored.')"

# The bypass ledger must actually record a bypass (silent bypass defeats the point).
echo "=== bypass ledger ==="
LEDGER="$TMP/ledger.jsonl"
printf 'chore: something [no-issue: verified trivial]\n' > "$TMP/m2.txt"
LINEAR_BYPASS_LEDGER="$LEDGER" python3 "$CHECK" "$TMP/m2.txt" >/dev/null 2>&1
if [ -s "$LEDGER" ] && grep -q "verified trivial" "$LEDGER"; then
  echo "  PASS: bypass written to ledger with its reason"
  pass=$((pass + 1))
else
  echo "  FAIL: bypass not recorded in ledger"
  fail=$((fail + 1))
fi

# A compliant commit must NOT write to the ledger.
LEDGER2="$TMP/ledger2.jsonl"
printf 'fix: thing (ASK-61)\n' > "$TMP/m3.txt"
LINEAR_BYPASS_LEDGER="$LEDGER2" python3 "$CHECK" "$TMP/m3.txt" >/dev/null 2>&1
if [ ! -s "$LEDGER2" ]; then
  echo "  PASS: compliant commit leaves the ledger untouched"
  pass=$((pass + 1))
else
  echo "  FAIL: compliant commit polluted the bypass ledger"
  fail=$((fail + 1))
fi

# A missing message file must not hard-error the commit path.
python3 "$CHECK" "$TMP/does-not-exist.txt" >/dev/null 2>&1
if [ $? -eq 0 ]; then
  echo "  PASS: missing message file is a no-op, not a crash"
  pass=$((pass + 1))
else
  echo "  FAIL: missing message file should exit 0"
  fail=$((fail + 1))
fi

echo
echo "passed=$pass failed=$fail"
[ "$fail" -eq 0 ] || exit 1
