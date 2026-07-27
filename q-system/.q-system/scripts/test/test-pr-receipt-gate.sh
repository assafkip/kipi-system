#!/usr/bin/env bash
# Reproducer + regression suite for pr-receipt-gate.py
# Pairs with the "Receipt gate (PR only)" step in .github/workflows/validate.yml.
#
# The bug being pinned: on 2026-07-27 seven agent PRs merged with zero prd-os
# receipts and nothing noticed. Case 1 below is that exact shape and must exit 1.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GATE="$SCRIPT_DIR/../pr-receipt-gate.py"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

pass=0
fail=0

# run_case <name> <expected_exit> <branch> <receipts-file-or-MISSING>
run_case() {
  local name="$1" expect="$2" branch="$3" receipts="$4"
  python3 "$GATE" --branch "$branch" --receipts "$receipts" >/dev/null 2>&1
  local got=$?
  if [ "$got" -eq "$expect" ]; then
    echo "  PASS: $name (exit $got)"
    pass=$((pass + 1))
  else
    echo "  FAIL: $name (expected exit $expect, got $got)"
    fail=$((fail + 1))
  fi
}

# assert_output <name> <branch> <receipts> <needle>
assert_output() {
  local name="$1" branch="$2" receipts="$3" needle="$4"
  local out
  out="$(python3 "$GATE" --branch "$branch" --receipts "$receipts" 2>&1)"
  if printf '%s' "$out" | grep -qF -- "$needle"; then
    echo "  PASS: $name"
    pass=$((pass + 1))
  else
    echo "  FAIL: $name (output did not contain '$needle')"
    echo "        got: $out"
    fail=$((fail + 1))
  fi
}

EMPTY="$TMP/empty.jsonl"
: > "$EMPTY"

MATCH="$TMP/match.jsonl"
cat > "$MATCH" <<'JSON'
{"issue_id": "unrelated-thing-2026-07-01", "prd_id": "prd-x", "closed_at": "2026-07-01T00:00:00Z"}
{"issue_id": "ask-999-receipt-gate", "prd_id": "prd-x", "closed_at": "2026-07-27T00:00:00Z"}
JSON

UPPER="$TMP/upper.jsonl"
cat > "$UPPER" <<'JSON'
{"issue_id": "ASK-999-receipt-gate", "prd_id": "prd-x", "closed_at": "2026-07-27T00:00:00Z"}
JSON

# The id lives in a non-issue_id field. A receipt "carrying that issue id"
# anywhere is proof of closeout; pinning it to one key would make the gate
# brittle against a spec-naming convention nobody has committed to yet.
OTHERFIELD="$TMP/otherfield.jsonl"
cat > "$OTHERFIELD" <<'JSON'
{"issue_id": "receipt-gate-2026-07-27", "prd_id": "prd-x", "linear_issue": "ASK-999", "closed_at": "2026-07-27T00:00:00Z"}
JSON

# ask-9990 must NOT satisfy ask-999. A prefix match would let an unrelated
# issue's receipt wave through the wrong PR.
PREFIX="$TMP/prefix.jsonl"
cat > "$PREFIX" <<'JSON'
{"issue_id": "ask-9990-other-work", "prd_id": "prd-x", "closed_at": "2026-07-27T00:00:00Z"}
JSON

# A garbage line must not be readable as a receipt. Strict JSON parsing is the
# point: a raw-text fallback would let `echo 'ASK-999' >> receipts.jsonl` pass.
GARBAGE="$TMP/garbage.jsonl"
cat > "$GARBAGE" <<'JSON'
this is not json but it mentions ASK-999
JSON

echo "=== gated branches (sana/ask-*) ==="
run_case "no receipt for the issue is fatal"        1 "sana/ask-999"                "$EMPTY"
run_case "receipt present passes"                   0 "sana/ask-999"                "$MATCH"
run_case "receipt id is case-insensitive"           0 "sana/ask-999"                "$UPPER"
run_case "id in any receipt field counts"           0 "sana/ask-999"                "$OTHERFIELD"
run_case "ask-9990 does not satisfy ask-999"        1 "sana/ask-999"                "$PREFIX"
run_case "malformed line is not a receipt"          1 "sana/ask-999"                "$GARBAGE"
run_case "trailing slug still resolves the id"      0 "sana/ask-999-receipt-gate"   "$MATCH"
run_case "missing receipts file is fatal"           1 "sana/ask-999"                "$TMP/does-not-exist.jsonl"

echo "=== ungated branches (the declared blind spot) ==="
# Bootstrap decision: only agent-authored sana/ask-* branches are gated. Every
# other branch passes DELIBERATELY. Pinned here so the blind spot cannot be
# widened or narrowed silently.
run_case "human branch is not gated"                0 "chore/sweep-scratch"         "$EMPTY"
run_case "main is not gated"                        0 "main"                        "$EMPTY"
run_case "other agent prefix is not gated"          0 "codex/ask-999"               "$EMPTY"

echo "=== messages ==="
assert_output "failure names the closeout command" \
  "sana/ask-999" "$EMPTY" "issue_runner.py close"
assert_output "failure names the issue it wanted" \
  "sana/ask-999" "$EMPTY" "ASK-999"
assert_output "ungated pass states what is uncovered" \
  "chore/sweep-scratch" "$EMPTY" "not gated"

echo
echo "passed: $pass  failed: $fail"
[ "$fail" -eq 0 ] || exit 1
echo "OK"
