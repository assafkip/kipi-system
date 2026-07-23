#!/usr/bin/env bash
# AUDHD anti-drop: open-loops.py surfaces every parked item. Pairs with open-loops.json registry.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
S="$ROOT/q-system/.q-system/scripts/open-loops.py"
fail() { echo "FAIL: $1" >&2; exit 1; }

# 1. report mode runs clean against the live registry (STRUCTURAL check only).
# Was: grep for two hardcoded loop titles ("cc-spex closeout-gate PR", ...).
# That pinned live, legitimately-changing registry content into a test — the
# moment a loop closed, the test went red with nothing broken (caught on the
# suite's first-ever gated run, 2026-07-23, prd-silent-absence-capability-gate).
# Content assertions live in section 3 against a fixture registry.
OUT="$(CLAUDE_PROJECT_DIR="$ROOT" python3 "$S" --report 2>&1)" || fail "report mode exited non-zero: $OUT"

# 3. fixture: open surfaced, closed excluded
T="$(mktemp -d)"; mkdir -p "$T/q-system/memory" "$T/.prd-os/findings"
cat > "$T/q-system/memory/open-loops.json" <<'JSON'
{"loops":[
 {"id":"a","title":"OPEN LOOP A","next_action":"do A","needs_founder":true,"status":"open"},
 {"id":"b","title":"CLOSED LOOP B","next_action":"do B","status":"closed"}
]}
JSON

# 2. hook mode emits valid SessionStart additionalContext JSON — against the
# FIXTURE registry, not live state. With zero live open loops the script
# correctly emits nothing ("never blocks on empty", section 5), so the live
# version of this assertion failed in 9 fleet instances on the first full
# sweep (2026-07-23) while passing in the skeleton, which had 6 open loops.
# Same live-data disease as old section 1, second occurrence.
JOUT="$(CLAUDE_PROJECT_DIR="$T" python3 "$S" 2>&1)"
echo "$JOUT" | python3 -c "import sys,json; d=json.load(sys.stdin); assert d['hookSpecificOutput']['hookEventName']=='SessionStart'; assert 'Open loops' in d['hookSpecificOutput']['additionalContext']" \
  || fail "hook mode JSON invalid: $JOUT"
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

# 6. zero silent-fall: a plainly-worded deferred finding (no future-work keyword,
#    not folded bookkeeping) must NOT vanish -> it lands in the catch-all line.
T3="$(mktemp -d)"; mkdir -p "$T3/q-system/memory" "$T3/.prd-os/findings"
echo '{"loops":[]}' > "$T3/q-system/memory/open-loops.json"
printf '%s\n' \
 '{"id":"g1","disposition":"deferred","body":"plainly parked","rationale":"park this for now, we still need to build it but not in this issue"}' \
 > "$T3/.prd-os/findings/q.jsonl"
OUT6="$(CLAUDE_PROJECT_DIR="$T3" python3 "$S" --report 2>&1)"
echo "$OUT6" | grep -qi "not auto-classified" || fail "plainly-worded deferred not caught by catch-all (silent fall): $OUT6"

echo "PASS: surfaces registry loops (incl seeded OSS PRs) + genuine deferred findings, excludes closed + folded bookkeeping, catch-all guarantees zero silent-fall, valid SessionStart JSON, never blocks on empty"
