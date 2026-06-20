#!/usr/bin/env bash
# AUDHD anti-drop: open-loops.py surfaces every parked item. Pairs with open-loops.json registry.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
S="$ROOT/q-system/.q-system/scripts/open-loops.py"
fail() { echo "FAIL: $1" >&2; exit 1; }

# 1. the real seeded registry surfaces both OSS PRs, tagged needs-you
OUT="$(CLAUDE_PROJECT_DIR="$ROOT" python3 "$S" --report 2>&1)"
echo "$OUT" | grep -q "cc-spex closeout-gate PR" || fail "cc-spex loop not surfaced: $OUT"
echo "$OUT" | grep -q "capability-token PR" || fail "captoken loop not surfaced: $OUT"
echo "$OUT" | grep -q "needs you" || fail "needs-you tag missing: $OUT"

# 2. hook mode emits valid SessionStart additionalContext JSON
JOUT="$(CLAUDE_PROJECT_DIR="$ROOT" python3 "$S" 2>&1)"
echo "$JOUT" | python3 -c "import sys,json; d=json.load(sys.stdin); assert d['hookSpecificOutput']['hookEventName']=='SessionStart'; assert 'Open loops' in d['hookSpecificOutput']['additionalContext']" \
  || fail "hook mode JSON invalid: $JOUT"

# 3. fixture: open surfaced, closed excluded
T="$(mktemp -d)"; mkdir -p "$T/q-system/memory" "$T/.prd-os/findings"
cat > "$T/q-system/memory/open-loops.json" <<'JSON'
{"loops":[
 {"id":"a","title":"OPEN LOOP A","next_action":"do A","needs_founder":true,"status":"open"},
 {"id":"b","title":"CLOSED LOOP B","next_action":"do B","status":"closed"}
]}
JSON
OUT3="$(CLAUDE_PROJECT_DIR="$T" python3 "$S" --report 2>&1)"
echo "$OUT3" | grep -q "OPEN LOOP A" || fail "open loop A not surfaced: $OUT3"
echo "$OUT3" | grep -q "CLOSED LOOP B" && fail "closed loop B wrongly surfaced: $OUT3" || true

# 4. deferred findings: genuine future-work surfaced, 'folded into' bookkeeping excluded
printf '%s\n' \
 '{"id":"f1","disposition":"deferred","body":"provenance ledger missing","rationale":"deferred to v2; documented residual risk"}' \
 '{"id":"f2","disposition":"deferred","body":"bookkeeping item","rationale":"Folded into issue X; refinement, not a standalone work item"}' \
 '{"id":"f3","disposition":"accepted","body":"not deferred","rationale":"fixed"}' \
 > "$T/.prd-os/findings/p.jsonl"
OUT4="$(CLAUDE_PROJECT_DIR="$T" python3 "$S" --report 2>&1)"
echo "$OUT4" | grep -qi "provenance ledger" || fail "genuine deferred (v2) not surfaced: $OUT4"
echo "$OUT4" | grep -qi "bookkeeping item" && fail "folded-into finding wrongly surfaced: $OUT4" || true

# 5. empty (no registry, no findings) -> never blocks, hook mode emits nothing, exit 0
T2="$(mktemp -d)"; mkdir -p "$T2/q-system"
CLAUDE_PROJECT_DIR="$T2" python3 "$S" >/dev/null 2>&1 && rc=0 || rc=$?
[ "${rc:-1}" -eq 0 ] || fail "empty case did not exit 0 (got ${rc:-1})"
EOUT="$(CLAUDE_PROJECT_DIR="$T2" python3 "$S" 2>&1)"
[ -z "$EOUT" ] || fail "empty case should emit nothing in hook mode, got: $EOUT"

echo "PASS: surfaces registry loops (incl seeded OSS PRs) + genuine deferred findings, excludes closed + folded-into, valid SessionStart JSON, never blocks on empty"
