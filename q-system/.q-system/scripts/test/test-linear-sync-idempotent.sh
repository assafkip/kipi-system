#!/usr/bin/env bash
# Reproducer + regression suite for linear-sync.py.
# Pairs with q-system/output/plans/linear-sdlc-standard-2026-07-26.md (Part 2).
#
# WHY THIS TEST EXISTS (ASK-113): mcp__linear__*delete* and archive are both
# blocked by ~/.claude/hooks/destructive-op-deny.sh and an agent cannot set
# ALLOW_DESTRUCTIVE=1 for itself. A duplicate Linear issue is therefore permanent.
# The dedup key has to be proven before ~200-400 issues get created, not after.
#
# Test isolation: every case runs against $TMP via KIPI_LINEAR_LEDGER. The live
# ledger at q-system/output/linear-ledger.jsonl is never opened by this suite.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYNC="$SCRIPT_DIR/../linear-sync.py"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

pass=0
fail=0

ok() { echo "  PASS: $1"; pass=$((pass + 1)); }
no() { echo "  FAIL: $1 -- $2"; fail=$((fail + 1)); }

# assert_plan_count <name> <expected_issue_creates> <plan_json_file>
assert_plan_count() {
  local name="$1" expect="$2" f="$3"
  local got
  got=$(python3 -c "import json,sys; print(len(json.load(open(sys.argv[1]))['create_issues']))" "$f" 2>/dev/null)
  if [ "$got" = "$expect" ]; then ok "$name (planned $got)"; else no "$name" "expected $expect creates, got ${got:-ERROR}"; fi
}

# --- fixtures -----------------------------------------------------------------

cat > "$TMP/map.json" <<'JSON'
{
  "repo": "demo_repo",
  "capabilities": [
    {"name": "kipi CLI",       "layer": "L1", "status": "LIVE",       "summary": "entry point"},
    {"name": "Case Intake",    "layer": "L2", "status": "NEEDS_WORK", "summary": "ingest"},
    {"name": "Slack notify",   "layer": "L3", "status": "LIVE",       "summary": "pings"}
  ]
}
JSON

echo '{"project": null, "issues": []}' > "$TMP/remote-empty.json"

echo "=== linear-sync idempotency ==="

# -- Case 1: cold start plans every capability --------------------------------
KIPI_LINEAR_LEDGER="$TMP/ledger.jsonl" python3 "$SYNC" plan \
  --map "$TMP/map.json" --remote "$TMP/remote-empty.json" \
  --out "$TMP/plan1.json" >/dev/null 2>&1
assert_plan_count "cold start plans all 3" 3 "$TMP/plan1.json"

# the project itself is planned exactly once when remote has none
proj=$(python3 -c "import json;print(json.load(open('$TMP/plan1.json'))['create_project'] is not None)" 2>/dev/null)
[ "$proj" = "True" ] && ok "cold start plans the project" || no "cold start plans the project" "got $proj"

# -- Case 2: THE CORE CASE. Record the creates, re-plan, expect zero ----------
python3 - "$TMP" <<'PY'
import json, sys
tmp = sys.argv[1]
plan = json.load(open(f"{tmp}/plan1.json"))
results = {"project": {"key": plan["create_project"]["key"], "linear_id": "proj-uuid-1", "identifier": "demo_repo"},
           "issues": [{"key": c["key"], "linear_id": f"uuid-{i}", "identifier": f"ASK-{200+i}"}
                      for i, c in enumerate(plan["create_issues"])]}
json.dump(results, open(f"{tmp}/results1.json", "w"))
PY
KIPI_LINEAR_LEDGER="$TMP/ledger.jsonl" python3 "$SYNC" record --results "$TMP/results1.json" >/dev/null 2>&1

KIPI_LINEAR_LEDGER="$TMP/ledger.jsonl" python3 "$SYNC" plan \
  --map "$TMP/map.json" --remote "$TMP/remote-empty.json" \
  --out "$TMP/plan2.json" >/dev/null 2>&1
assert_plan_count "SECOND RUN IS A NO-OP (ledger guard)" 0 "$TMP/plan2.json"

proj2=$(python3 -c "import json;print(json.load(open('$TMP/plan2.json'))['create_project'] is None)" 2>/dev/null)
[ "$proj2" = "True" ] && ok "second run plans no project" || no "second run plans no project" "got $proj2"

# -- Case 3: ledger loss is recoverable from the remote marker ----------------
# Rebuild a remote snapshot carrying the kipi-key markers, then delete the ledger.
python3 - "$TMP" <<'PY'
import json, sys
tmp = sys.argv[1]
plan = json.load(open(f"{tmp}/plan1.json"))
issues = [{"id": f"uuid-{i}", "identifier": f"ASK-{200+i}", "title": c["title"],
           "description": f"blah blah\n<!-- kipi-key: {c['key']} -->\nmore text"}
          for i, c in enumerate(plan["create_issues"])]
json.dump({"project": {"id": "proj-uuid-1", "name": "demo_repo"}, "issues": issues},
          open(f"{tmp}/remote-full.json", "w"))
PY
rm -f "$TMP/ledger.jsonl"
KIPI_LINEAR_LEDGER="$TMP/ledger.jsonl" python3 "$SYNC" plan \
  --map "$TMP/map.json" --remote "$TMP/remote-full.json" \
  --out "$TMP/plan3.json" >/dev/null 2>&1
assert_plan_count "LEDGER LOSS IS A NO-OP (remote guard)" 0 "$TMP/plan3.json"

# and the remote guard rehydrates the ledger so the fast path works next time
lines=$(wc -l < "$TMP/ledger.jsonl" 2>/dev/null | tr -d ' ')
[ "${lines:-0}" -ge 3 ] && ok "remote guard rehydrates the ledger ($lines lines)" \
  || no "remote guard rehydrates the ledger" "got ${lines:-0} lines"

# -- Case 4: partial state plans exactly the gap ------------------------------
rm -f "$TMP/ledger.jsonl"
python3 - "$TMP" <<'PY'
import json, sys
tmp = sys.argv[1]
plan = json.load(open(f"{tmp}/plan1.json"))
# ledger knows capability 0; remote knows capability 1; capability 2 is unknown to both
with open(f"{tmp}/ledger.jsonl", "w") as fh:
    c = plan["create_issues"][0]
    fh.write(json.dumps({"key": c["key"], "kind": "issue", "linear_id": "uuid-0",
                         "identifier": "ASK-200", "created_at": "2026-07-26T00:00:00Z"}) + "\n")
c1 = plan["create_issues"][1]
json.dump({"project": {"id": "proj-uuid-1", "name": "demo_repo"},
           "issues": [{"id": "uuid-1", "identifier": "ASK-201", "title": c1["title"],
                       "description": f"<!-- kipi-key: {c1['key']} -->"}]},
          open(f"{tmp}/remote-partial.json", "w"))
PY
KIPI_LINEAR_LEDGER="$TMP/ledger.jsonl" python3 "$SYNC" plan \
  --map "$TMP/map.json" --remote "$TMP/remote-partial.json" \
  --out "$TMP/plan4.json" >/dev/null 2>&1
assert_plan_count "partial state plans exactly the gap" 1 "$TMP/plan4.json"

# -- Case 5: a description WITHOUT a marker must not false-match --------------
# A false match would SKIP a create that is actually needed, silently losing work.
rm -f "$TMP/ledger.jsonl"
python3 - "$TMP" <<'PY'
import json, sys
tmp = sys.argv[1]
plan = json.load(open(f"{tmp}/plan1.json"))
# same titles, no kipi-key markers anywhere
issues = [{"id": f"x{i}", "identifier": f"ASK-{300+i}", "title": c["title"],
           "description": "a human wrote this by hand and there is no marker"}
          for i, c in enumerate(plan["create_issues"])]
json.dump({"project": {"id": "proj-uuid-1", "name": "demo_repo"}, "issues": issues},
          open(f"{tmp}/remote-nomarker.json", "w"))
PY
KIPI_LINEAR_LEDGER="$TMP/ledger.jsonl" python3 "$SYNC" plan \
  --map "$TMP/map.json" --remote "$TMP/remote-nomarker.json" \
  --out "$TMP/plan5.json" >/dev/null 2>&1
assert_plan_count "title-only match does NOT dedup" 3 "$TMP/plan5.json"

# -- Case 6: key derivation is stable and collision-free ----------------------
k=$(python3 "$SYNC" key --repo "4_points_consulting" --capability "Case Intake" 2>/dev/null)
[ "$k" = "4-points-consulting/case-intake" ] && ok "key slug is stable" || no "key slug is stable" "got '$k'"
k2=$(python3 "$SYNC" key --repo "4_Points  Consulting" --capability "case   intake!" 2>/dev/null)
# -n guard: without it, two empty strings compare equal and this passes with no script.
[ -n "$k2" ] && [ "$k2" = "$k" ] && ok "key normalizes case/punctuation/whitespace" \
  || no "key normalizes" "got '$k2' vs '$k'"
k3=$(python3 "$SYNC" key --repo "demo" --capability "A/B split" 2>/dev/null)
[ "$k3" = "demo/a-b-split" ] && ok "slash inside a name cannot forge a key" || no "slash is escaped" "got '$k3'"

# -- Case 7: the ledger is append-only ----------------------------------------
before=$(wc -l < "$TMP/ledger.jsonl" 2>/dev/null | tr -d ' ')
KIPI_LINEAR_LEDGER="$TMP/ledger.jsonl" python3 "$SYNC" record --results "$TMP/results1.json" >/dev/null 2>&1
KIPI_LINEAR_LEDGER="$TMP/ledger.jsonl" python3 "$SYNC" record --results "$TMP/results1.json" >/dev/null 2>&1
after=$(wc -l < "$TMP/ledger.jsonl" 2>/dev/null | tr -d ' ')
# before>0 guard: 0 -ge 0 passes with no script at all, which is not the claim.
[ "${before:-0}" -gt 0 ] && [ "${after:-0}" -ge "${before:-0}" ] \
  && ok "ledger only grows ($before -> $after)" || no "ledger only grows" "$before -> $after"
# re-recording the same keys must still leave the plan empty
KIPI_LINEAR_LEDGER="$TMP/ledger.jsonl" python3 "$SYNC" plan \
  --map "$TMP/map.json" --remote "$TMP/remote-empty.json" \
  --out "$TMP/plan6.json" >/dev/null 2>&1
assert_plan_count "double-record still plans zero" 0 "$TMP/plan6.json"

# -- Case 8: a map with a duplicate capability name is refused, not deduped ---
cat > "$TMP/map-dupe.json" <<'JSON'
{"repo": "demo_repo", "capabilities": [
  {"name": "kipi CLI", "layer": "L1", "status": "LIVE", "summary": "a"},
  {"name": "kipi  CLI", "layer": "L2", "status": "LIVE", "summary": "b"}
]}
JSON
KIPI_LINEAR_LEDGER="$TMP/ledger8.jsonl" python3 "$SYNC" plan \
  --map "$TMP/map-dupe.json" --remote "$TMP/remote-empty.json" \
  --out "$TMP/plan8.json" >/dev/null 2>&1
rc=$?
# Exactly 3 (EXIT_COLLISION), not merely non-zero: python exits 2 for a missing
# file, so "non-zero" would pass with no script present.
[ "$rc" -eq 3 ] && ok "colliding capability names are refused (exit 3)" \
  || no "colliding capability names are refused" "expected exit 3, got $rc"

echo
echo "  pass=$pass fail=$fail"
[ "$fail" -eq 0 ] || exit 1
