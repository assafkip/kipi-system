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
  run_case_with "$CHECK" "$name" "$expect" "$msg"
}

# run_case_with <script> <name> <expected_exit> <message>
# Same as run_case but against an arbitrary copy of the gate, so the mutant
# block below can re-run the same strings against the pre-fix regex.
run_case_with() {
  local script="$1" name="$2" expect="$3" msg="$4"
  local f="$TMP/msg.txt"
  printf '%s\n' "$msg" > "$f"
  LINEAR_BYPASS_LEDGER="$TMP/bypass.jsonl" python3 "$script" "$f" >/dev/null 2>&1
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
run_case "bare id accepted"                   0 "ASK-111 quick-plan reflex wording"

# A lowercase id is NOT an issue ref — Linear ids are uppercase.
run_case "lowercase is not an id"             1 "fix: ask-61 mentioned in prose"

# ASK-2810: ANY uppercase token + dash + number used to pass, so a commit that
# merely quoted a decisions.md tag or a standards name cleared the gate citing
# no issue. Measured on this repo's own history 2026-10-22: 16 commits passed
# ONLY via such a match, HEAD (829cdca2, 'RULE-2026') among them.
echo "=== ASK-2810: a non-issue token is not an issue ref ==="
run_case "RULE-YYYY decision tag refused"     1 "docs(fleet): RULE-2026-10-20-A record it"
run_case "standards tokens refused"           1 "fix(encoding): UTF-8 and SHA-256 handling"
run_case "real id in same shape accepted"     0 "fix(canary): ASK-2768 real"
# CAP-01 / CAP-22 appear in this repo's history and are CAPABILITY ids, not
# Linear ones (zero-padded; Linear never pads). The live workspace has exactly
# one team, key ASK (teams query, 2026-10-22), so an undeclared prefix is noise.
run_case "undeclared team prefix refused"     1 "feat: thing (CAP-45)"

# The team key is read from the fleet's one place for it, KIPI_LINEAR_TEAM, so
# an instance on another workspace is configured rather than stranded.
echo "=== team key comes from KIPI_LINEAR_TEAM ==="
printf 'feat: thing (LIN-7)\n' > "$TMP/env.txt"
KIPI_LINEAR_TEAM="ASK,LIN" LINEAR_BYPASS_LEDGER="$TMP/bypass.jsonl" \
  python3 "$CHECK" "$TMP/env.txt" >/dev/null 2>&1
if [ $? -eq 0 ]; then
  echo "  PASS: a key declared in KIPI_LINEAR_TEAM is accepted"
  pass=$((pass + 1))
else
  echo "  FAIL: KIPI_LINEAR_TEAM key was not accepted"
  fail=$((fail + 1))
fi
printf 'feat: thing (LIN-7)\n' > "$TMP/env2.txt"
LINEAR_BYPASS_LEDGER="$TMP/bypass.jsonl" python3 "$CHECK" "$TMP/env2.txt" >/dev/null 2>&1
if [ $? -eq 1 ]; then
  echo "  PASS: the same key is refused when it is not declared"
  pass=$((pass + 1))
else
  echo "  FAIL: an undeclared key was accepted anyway"
  fail=$((fail + 1))
fi

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

# A mutant that restores the pre-ASK-2810 regex must make the three reproducer
# strings accepted again. Without this the cases above could be passing because
# of some unrelated refusal rather than because the prefix scope is real.
echo "=== mutant: the permissive regex is restored ==="
MUT="$TMP/mutant.py"
sed -E 's/^ISSUE_RE = .*$/ISSUE_RE = re.compile(r"\\b[A-Z][A-Z0-9]{1,9}-\\d+\\b")/' \
  "$CHECK" > "$MUT"
if grep -qE '^ISSUE_RE = re\.compile\(r"\\b\[A-Z\]\[A-Z0-9\]\{1,9\}-\\d\+\\b"\)$' "$MUT"; then
  echo "  PASS: mutant applied (old regex is back)"
  pass=$((pass + 1))
else
  echo "  FAIL: mutant NOT applied, so these negatives prove nothing"
  fail=$((fail + 1))
fi
run_case_with "$MUT" "mutant accepts RULE-YYYY (the shipped defect)"  0 \
  "docs(fleet): RULE-2026-10-20-A record it"
run_case_with "$MUT" "mutant accepts UTF-8 (the shipped defect)"      0 \
  "fix(encoding): UTF-8 and SHA-256 handling"
run_case_with "$MUT" "mutant still accepts the real id"               0 \
  "fix(canary): ASK-2768 real"

echo
echo "passed=$pass failed=$fail"
[ "$fail" -eq 0 ] || exit 1
