#!/usr/bin/env bash
# Pairs with linear-triage.py. Asserts the DETERMINISTIC slice only: the parts
# that are code, not judgement. Whether the model picks a good bucket is not
# testable here and is not claimed to be -- what IS testable is that a verdict
# contradicting disk evidence never reaches a permanent Linear object.
#
# No network. Every case drives the pure functions directly.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TRIAGE="$HERE/../linear-triage.py"
PASS=0; FAIL=0

check() {  # check <name> <expected> <actual>
  if [ "$2" = "$3" ]; then PASS=$((PASS+1)); echo "  ok   $1"
  else FAIL=$((FAIL+1)); echo "  FAIL $1: expected [$2] got [$3]"; fi
}

run() { python3 - "$TRIAGE" "$@" <<'PY'
import importlib.util, json, sys, pathlib
spec = importlib.util.spec_from_file_location("t", sys.argv[1])
t = importlib.util.module_from_spec(spec); spec.loader.exec_module(t)
print(json.dumps(eval(sys.argv[-1], {"t": t, "json": json})))
PY
}

echo "== enforce_flags: the override that makes the prompt rule real =="

# THE CORE CASE. Without enforce_flags this returns "do-now" and the worker gets
# handed an issue it can never finish -- the 13-of-56 shape measured 2026-07-27.
check "do-now + no-Files-line -> needs-scope" '"needs-scope"' \
  "$(run '' 't.enforce_flags({"id":"ASK-1","category":"do-now","why":"looks ready","action":"go"},["no-Files-line"])["category"]')"

check "do-now + all-paths-outside-repo -> needs-scope" '"needs-scope"' \
  "$(run '' 't.enforce_flags({"id":"ASK-1","category":"do-now","why":"w","action":"a"},["all-paths-outside-repo"])["category"]')"

# The original verdict must survive, or miscalibration becomes invisible.
check "override records what it overrode" '"do-now"' \
  "$(run '' 't.enforce_flags({"id":"ASK-1","category":"do-now","why":"w","action":"a"},["no-Files-line"])["overridden_from"]')"

check "override keeps the original reasoning in why" 'true' \
  "$(run '' '"Original triage read: w" in t.enforce_flags({"id":"ASK-1","category":"do-now","why":"w","action":"a"},["no-Files-line"])["why"]')"

# Must NOT fire otherwise, or every issue collapses to needs-scope and the pass
# is worthless.
check "do-now with clean flags is untouched" '"do-now"' \
  "$(run '' 't.enforce_flags({"id":"ASK-1","category":"do-now","why":"w","action":"a"},["never-commented-on"])["category"]')"

check "non-do-now verdicts are never rewritten" '"not-planned"' \
  "$(run '' 't.enforce_flags({"id":"ASK-1","category":"not-planned","why":"superseded","action":"none"},["no-Files-line"])["category"]')"

check "enforce_flags does not mutate its input" '"do-now"' \
  "$(run '' '(lambda v: (t.enforce_flags(v,["no-Files-line"]), v["category"])[1])({"id":"ASK-1","category":"do-now","why":"w","action":"a"})')"

echo "== disk_evidence: facts, not guesses =="

check "an out-of-repo path is not called MISSING" '"out-of-repo"' \
  "$(run '' 't.disk_evidence({"description":"see `~/Library/LaunchAgents/com.x.plist`"})[0]["state"]')"

check "a real repo path reads exists" '"exists"' \
  "$(run '' 't.disk_evidence({"description":"see `q-system/.q-system/scripts/linear-triage.py`"})[0]["state"]')"

check "a bogus repo path reads MISSING" '"MISSING"' \
  "$(run '' 't.disk_evidence({"description":"see `q-system/nope-does-not-exist.py`"})[0]["state"]')"

echo "== structural_flags =="

check "missing Files: line is flagged" 'true' \
  "$(run '' '"no-Files-line" in t.structural_flags({"description":"## Definition of Ready\nstuff","comments":{"nodes":[{"id":"c"}]}},[])')"

check "machine-filed issues carry their producer" 'true' \
  "$(run '' 'any(f.startswith("machine-filed-by:job-migration") for f in t.structural_flags({"description":"<!-- kipi-key: job-migration/x -->","comments":{"nodes":[{"id":"c"}]}},[]))')"

echo "== idempotency: a second pass must not stack comments =="

check "finds its own marker in existing comments" '"c9"' \
  "$(run '' 't.existing_verdict_comment({"comments":{"nodes":[{"id":"c1","body":"unrelated"},{"id":"c9","body":t.MARKER+"\nold verdict"}]}})')"

check "returns None when it has never commented" 'null' \
  "$(run '' 't.existing_verdict_comment({"comments":{"nodes":[{"id":"c1","body":"unrelated"}]}})')"

check "an override is visible in the comment body" 'true' \
  "$(run '' '"Downgraded from" in t.comment_body({"id":"A","category":"needs-scope","why":"w","action":"a","overridden_from":"do-now"})')"

echo
echo "passed $PASS, failed $FAIL"
[ "$FAIL" -eq 0 ]
