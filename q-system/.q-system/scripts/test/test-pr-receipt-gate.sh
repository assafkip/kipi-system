#!/usr/bin/env bash
# Reproducer + regression suite for pr-receipt-gate.py
# Pairs with the "Receipt gate (PR only)" step in .github/workflows/validate.yml.
#
# The bug being pinned: on 2026-07-27 seven agent PRs merged with zero prd-os
# receipts and nothing noticed. Case 1 below is that exact shape and must exit 1.
#
# Fixture rule (ASK-210 review round 3): every receipt fixture here must be a
# record the repo would actually accept into the ledger. The first version of
# this suite justified its central design decision -- match any string field --
# with a `linear_issue` key that receipts-ledger-check.py refuses at pre-commit,
# so the decision was pinned by a shape that could never exist. The
# LEDGER-COMMITTABLE section at the bottom now enforces that rule mechanically
# instead of trusting whoever adds the next fixture.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GATE="$SCRIPT_DIR/../pr-receipt-gate.py"
LEDGER_CHECK="$SCRIPT_DIR/../receipts-ledger-check.py"
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

# The real producer shape. issue_runner.py::cmd_close emits exactly these keys
# (linear_issue_id added by ASK-210); `receipt-gate-e2e` is the kind of
# descriptive slug prd_split.py actually mints -- it carries no Linear id, which
# is why the dedicated field has to exist.
MATCH="$TMP/match.jsonl"
cat > "$MATCH" <<'JSON'
{"issue_id": "unrelated-thing-2026-07-01", "prd_id": "prd-x", "finding_id": "finding-1", "commit_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "closed_at": "2026-07-01T00:00:00Z"}
{"issue_id": "receipt-gate-e2e", "prd_id": "prd-x", "finding_id": "finding-1", "linear_issue_id": "ASK-999", "commit_sha": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "closed_at": "2026-07-27T00:00:00Z"}
JSON

# Case: the branch resolves ASK-999 uppercase, the ledger may carry either case.
LOWER="$TMP/lower.jsonl"
cat > "$LOWER" <<'JSON'
{"issue_id": "receipt-gate-e2e", "prd_id": "prd-x", "linear_issue_id": "ask-999", "closed_at": "2026-07-27T00:00:00Z"}
JSON

# The id lives in issue_id rather than the dedicated field: a DSSE spec
# deliberately named for its Linear issue is equally good proof. prd_split.py's
# ISSUE_ID_RE (^[a-z0-9][a-z0-9-]*[a-z0-9]$) can mint this one, unlike the
# uppercase `ASK-999-receipt-gate` the first version of this suite used.
SPECNAMED="$TMP/specnamed.jsonl"
cat > "$SPECNAMED" <<'JSON'
{"issue_id": "ask-999-receipt-gate", "prd_id": "prd-x", "closed_at": "2026-07-27T00:00:00Z"}
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
run_case "producer-shaped receipt passes"           0 "sana/ask-999"                "$MATCH"
run_case "receipt id is case-insensitive"           0 "sana/ask-999"                "$LOWER"
run_case "id in any receipt field counts"           0 "sana/ask-999"                "$SPECNAMED"
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
assert_output "failure tells the operator to commit and push the receipt" \
  "sana/ask-999" "$EMPTY" "git add .prd-os"
assert_output "failure names the issue it wanted" \
  "sana/ask-999" "$EMPTY" "ASK-999"
assert_output "ungated pass states what is uncovered" \
  "chore/sweep-scratch" "$EMPTY" "not gated"
# Without --head-sha the gate checks less than its name implies. It has to say
# so: an unstated reduction in coverage is the failure class this issue is about.
assert_output "existence-only pass declares the coverage it skipped" \
  "sana/ask-999" "$MATCH" "existence only"

echo "=== ledger-committable (every fixture must be a real receipt) ==="
# The gate matches ANY string field, which is only defensible because
# receipts-ledger-check.py bounds which fields can reach the ledger at all. That
# makes the two readers coupled, so the fixtures must satisfy both. A fixture
# the repo would refuse to commit cannot justify a design decision.
LEDGER_REPO="$TMP/ledgerrepo"
mkdir -p "$LEDGER_REPO/.prd-os"
git -C "$LEDGER_REPO" init -q
git -C "$LEDGER_REPO" config user.email "test@kipi.invalid"
git -C "$LEDGER_REPO" config user.name "kipi-test"
for fixture in "$MATCH" "$LOWER" "$SPECNAMED" "$PREFIX"; do
  cp "$fixture" "$LEDGER_REPO/.prd-os/receipts.jsonl"
  git -C "$LEDGER_REPO" add -f .prd-os/receipts.jsonl >/dev/null 2>&1
  if (cd "$LEDGER_REPO" && python3 "$LEDGER_CHECK") >/dev/null 2>&1; then
    echo "  PASS: $(basename "$fixture") is a committable ledger record"
    pass=$((pass + 1))
  else
    echo "  FAIL: $(basename "$fixture") would be refused by receipts-ledger-check.py"
    echo "        $( (cd "$LEDGER_REPO" && python3 "$LEDGER_CHECK") 2>&1 | head -3 | tr '\n' ' ')"
    fail=$((fail + 1))
  fi
done

# And the guard on that guard: a key the ledger checker does NOT allow must be
# caught, otherwise the loop above would pass vacuously.
cat > "$LEDGER_REPO/.prd-os/receipts.jsonl" <<'JSON'
{"issue_id": "receipt-gate-e2e", "prd_id": "prd-x", "linear_issue": "ASK-999", "closed_at": "2026-07-27T00:00:00Z"}
JSON
git -C "$LEDGER_REPO" add -f .prd-os/receipts.jsonl >/dev/null 2>&1
if (cd "$LEDGER_REPO" && python3 "$LEDGER_CHECK") >/dev/null 2>&1; then
  echo "  FAIL: the ledger checker accepted an unknown key, so the loop above proves nothing"
  fail=$((fail + 1))
else
  echo "  PASS: an unknown-key receipt is still refused (the check above has teeth)"
  pass=$((pass + 1))
fi

echo
echo "passed: $pass  failed: $fail"
[ "$fail" -eq 0 ] || exit 1
echo "OK"
