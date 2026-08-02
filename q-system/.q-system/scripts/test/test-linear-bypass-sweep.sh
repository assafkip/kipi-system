#!/usr/bin/env bash
# Reproducer + regression suite for linear-bypass-sweep.py (ASK-284).
#
# The hole this pins: `git commit --no-verify` skips the commit-msg gate, so a
# commit with no Linear id and no [no-issue:] tag reaches origin and the bypass
# ledger never sees it. The ledger then reports a number LOWER than the truth
# and reads as clean. The sweep is the verify path that reads git directly, so
# skipping the hook does not skip the accounting.
#
# Every case runs against a REAL git repo pushed to a REAL bare origin, because
# the thing under test is "what actually reached origin", not a string.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SWEEP="$SCRIPT_DIR/../linear-bypass-sweep.py"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

pass=0
fail=0

ok() { echo "  PASS: $1"; pass=$((pass + 1)); }
no() { echo "  FAIL: $1"; fail=$((fail + 1)); }

check() {
  # check <name> <expected> <actual>
  if [ "$2" = "$3" ]; then ok "$1 ($3)"; else no "$1 (expected $2, got $3)"; fi
}

# --- build a repo with a real origin -----------------------------------------
ORIGIN="$TMP/origin.git"
WORK="$TMP/work"
LEDGER="$TMP/bypass.jsonl"

git init --bare -q "$ORIGIN"
git init -q -b main "$WORK"
cd "$WORK" || exit 1
git config user.email sweep@test.local
git config user.name "Sweep Test"
git config commit.gpgsign false
git remote add origin "$ORIGIN"

commit() {
  # commit <message>  — --no-verify mirrors the incident: the gate never runs.
  echo "$RANDOM$RANDOM" >> file.txt
  git add file.txt
  git commit -q --no-verify -m "$1"
  git rev-parse HEAD
}

SHA_OK=$(commit "feat: compliant thing (ASK-1)")
SHA_HATCH=$(commit "chore: typo [no-issue: docs typo]")
SHA_HOLE=$(commit "fix(gate): the bypassed one")
git merge -q --no-ff --no-verify -m "Merge branch 'side' into main" HEAD >/dev/null 2>&1 || true
git push -q origin main

sweep() {
  LINEAR_BYPASS_LEDGER="$LEDGER" python3 "$SWEEP" --rev origin/main --json 2>/dev/null
}

field() { python3 -c "import json,sys; print(json.loads(sys.stdin.read())[sys.argv[1]])" "$1"; }

echo "=== linear-bypass-sweep: the hole ==="

OUT="$(sweep)"
check "first sweep records the unaccounted commit" 1 "$(printf '%s' "$OUT" | field recorded)"

# The ledger is the thing the founder counts. It has to change.
LEDGER_LINES=$(wc -l < "$LEDGER" | tr -d ' ')
check "ledger count changed" 1 "$LEDGER_LINES"

if grep -q "$SHA_HOLE" "$LEDGER"; then
  ok "the bypassed commit's sha is in the ledger"
else
  no "the bypassed commit's sha is NOT in the ledger"
fi

echo "=== negative controls ==="

# Without this the three greps below pass vacuously on a missing file, which is
# the classic green-but-wrong shape: a negative control that cannot fail.
if [ -s "$LEDGER" ]; then
  ok "ledger exists, so the negative controls below can actually fail"
else
  no "ledger missing — the negative controls below prove nothing"
fi

if grep -q "$SHA_OK" "$LEDGER"; then
  no "a commit naming an issue was recorded (false positive)"
else
  ok "a commit naming an issue is not recorded"
fi

if grep -q "$SHA_HATCH" "$LEDGER"; then
  no "a hook-path [no-issue:] commit was recorded twice (hook + sweep)"
else
  ok "a hook-path [no-issue:] commit is not double-counted"
fi

# Merge machinery inherits provenance; gating it would break merges for no gain.
if grep -qi "merge branch" "$LEDGER"; then
  no "a merge commit was recorded"
else
  ok "merge machinery is not recorded"
fi

echo "=== idempotence (must not re-ping the same fact every cycle) ==="

OUT2="$(sweep)"
check "second sweep records nothing new" 0 "$(printf '%s' "$OUT2" | field recorded)"
check "ledger unchanged on re-run" 1 "$(wc -l < "$LEDGER" | tr -d ' ')"

echo "=== a new occurrence is still caught ==="

SHA_HOLE2=$(commit "docs: another bypassed one")
git push -q origin main
OUT3="$(sweep)"
check "third sweep records the new one only" 1 "$(printf '%s' "$OUT3" | field recorded)"
check "ledger grew by exactly one" 2 "$(wc -l < "$LEDGER" | tr -d ' ')"

if grep -q "$SHA_HOLE2" "$LEDGER"; then
  ok "the new bypassed sha is in the ledger"
else
  no "the new bypassed sha is missing"
fi

echo "=== entry shape ==="

ENTRY=$(grep "$SHA_HOLE2" "$LEDGER")
SRC=$(printf '%s' "$ENTRY" | python3 -c "import json,sys; print(json.loads(sys.stdin.read()).get('source'))")
check "sweep entries are tagged source=sweep" "sweep" "$SRC"

REASON=$(printf '%s' "$ENTRY" | python3 -c "import json,sys; print(bool(json.loads(sys.stdin.read()).get('reason')))")
check "sweep entries carry a reason like hook entries" "True" "$REASON"

echo "=== unreachable rev is a no-op, not a crash ==="

LINEAR_BYPASS_LEDGER="$LEDGER" python3 "$SWEEP" --rev refs/heads/does-not-exist --json >/dev/null 2>&1
check "missing rev exits 0" 0 "$?"
check "ledger untouched by a missing rev" 2 "$(wc -l < "$LEDGER" | tr -d ' ')"

echo "=== a pre-existing hook entry (no sha) does not break dedup ==="

printf '{"at":"2026-08-01T19:48:50+00:00","reason":"legacy hook entry","subject":"chore: old"}\n' >> "$LEDGER"
OUT4="$(sweep)"
check "sweep still records nothing new alongside a legacy entry" 0 "$(printf '%s' "$OUT4" | field recorded)"

echo
echo "passed=$pass failed=$fail"
[ "$fail" -eq 0 ] || exit 1
