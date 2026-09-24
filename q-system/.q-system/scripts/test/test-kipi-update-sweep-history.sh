#!/usr/bin/env bash
# ASK-776: every fleet sweep leaves one history row, and a fixture never writes the live one.
#
# kipi-update.sh printed "Updated/Failed/Skipped" to stdout and nothing else. On
# 2026-09-23 a read-only audit found 21 of 24 instances syncing and nothing had
# said so. The row this test pins is what fleet-health-daily.py's
# detect_sweep_degraded reads.
#
# Drives the REAL kipi-update.sh from a throwaway skeleton against a throwaway
# instance with one forced refusal (a founder edit to a tracked source file).
# HOME is a temp dir for every run, so no path here can reach the live history.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
fail() { echo "FAIL: $1" >&2; exit 1; }
G() { git -c user.email=t@t.t -c user.name=test -c commit.gpgsign=false "$@"; }

build() {
  local work="$1" sk="$work/skel" inst="$work/inst"
  mkdir -p "$sk/q-system/.q-system/scripts" "$sk/q-system/.q-system/state" \
           "$sk/q-system/hooks" "$sk/.claude/rules"
  for f in kipi-update.sh kipi-update-preserve-scan.py kipi-update-deletion-guard.py \
           kipi-update-gitignore-block.py validate-separation.py fleet-reach-audit.py; do
    cp "$ROOT/$f" "$sk/$f"
  done
  cp "$ROOT/.gitignore" "$sk/.gitignore"
  cp "$ROOT/q-system/.q-system/scripts/propagation-leak-gate.py" \
     "$sk/q-system/.q-system/scripts/propagation-leak-gate.py"
  cp "$ROOT/q-system/.q-system/scripts/containment-targets.py" \
     "$sk/q-system/.q-system/scripts/containment-targets.py"
  cp "$ROOT/q-system/hooks/auto-commit.py" "$sk/q-system/hooks/auto-commit.py"
  cat > "$sk/q-system/.q-system/state/propagation-leak-baseline.json" <<'JSON'
{
  "schema_version": 1,
  "blocking_classes": ["case_proof_gap", "client_identity", "dated_interaction",
                       "pricing", "relationship", "source_identity",
                       "sourced_interaction"],
  "classifier_sha256": null,
  "entries": []
}
JSON
  printf 'generic skeleton content\n' > "$sk/q-system/tracked.md"
  printf '# demo rule\n' > "$sk/.claude/rules/demo.md"
  ( cd "$sk" && G init -q -b main && G add -A -f && G commit -qm skel )
  printf '{"instances":[{"name":"testinst","path":"%s","subtree_prefix":"q-system","type":"subtree"}]}\n' \
    "$inst" > "$sk/instance-registry.json"
  mkdir -p "$inst/q-system/tools"
  printf 'instance state\n' > "$inst/q-system/tracked.md"
  printf 'def local():\n    return 1\n' > "$inst/q-system/tools/local_tool.py"
  ( cd "$inst" && G init -q -b main && G add -A -f && G commit -qm inst )
  # The forced failure: founder work in the sync scope, correctly refused.
  printf 'def local():\n    return 2\n' > "$inst/q-system/tools/local_tool.py"
}

rows() { [ -f "$1" ] && grep -c . "$1" || echo 0; }

# ------------------------------------------------------------------ property 1
work="$(mktemp -d)"; build "$work"; hist="$work/history.jsonl"
out="$(HOME="$work/home" KIPI_FLEET_SWEEP_HISTORY="$hist" bash "$work/skel/kipi-update.sh" 2>&1)" || true
case "$out" in *"refusing to commit unrelated work"*) ;; *) fail "the forced refusal did not happen: $out" ;; esac
[ "$(rows "$hist")" = "1" ] || fail "expected 1 history row, got $(rows "$hist")"
python3 - "$hist" <<'PY' || fail "history row wrong: $(cat "$hist")"
import json, sys
row = json.loads(open(sys.argv[1]).read().splitlines()[-1])
assert row["mode"] == "real", row
assert row["failed"] == 1 and row["updated"] == 0, row
assert row["failed_names"] == ["testinst"], row
assert row["only"] == "" and len(row["skeleton_sha"]) == 40, row
PY
echo "PASS: a real sweep appends one row naming the failed instance"

# ------------------------------------------------------------------ property 2
out="$(HOME="$work/home" KIPI_FLEET_SWEEP_HISTORY="$hist" bash "$work/skel/kipi-update.sh" --dry-run 2>&1)" || true
[ "$(rows "$hist")" = "2" ] || fail "a dry sweep did not append: $(rows "$hist") rows"
python3 -c "import json,sys; r=json.loads(open(sys.argv[1]).read().splitlines()[-1]); assert r['mode']=='dry', r" "$hist" \
  || fail "the dry row is not marked dry: $(tail -1 "$hist")"
echo "PASS: a dry sweep appends a row marked dry"

# ------------------------------------------------------------------ property 3
# No override: a skeleton under the temp dir is a fixture and writes nothing,
# not even to the (temp) HOME it was given.
out="$(env -u KIPI_FLEET_SWEEP_HISTORY HOME="$work/home" bash "$work/skel/kipi-update.sh" 2>&1)" || true
case "$out" in *"--- testinst"*) ;; *) fail "the default run never reached the instance: $out" ;; esac
[ ! -e "$work/home/.config/kipi/fleet-sweep-history.jsonl" ] \
  || fail "a fixture skeleton wrote the default history path"
echo "PASS: a skeleton in a temp dir never writes the default history"
# ------------------------------------------------------------------ property 4
# An UNDECLARED NON-PROPAGATING instance fails the run and must be NAMED in the
# row, or the regression signal can never fire for the one class where the name
# is the whole value (PR #439 review, major 2).
mkdir -p "$work/orphan"
python3 - "$work/skel/instance-registry.json" "$work/orphan" <<'PY'
import json, sys
path, orphan = sys.argv[1:3]
reg = json.load(open(path))
reg["instances"].append({"name": "orphan", "path": orphan})
json.dump(reg, open(path, "w"))
PY
out="$(HOME="$work/home" KIPI_FLEET_SWEEP_HISTORY="$hist" bash "$work/skel/kipi-update.sh" 2>&1)" || true
case "$out" in *"UNDECLARED NON-PROPAGATING"*) ;; *) fail "the undeclared instance was not reported: $out" ;; esac
python3 -c "import json,sys; r=json.loads(open(sys.argv[1]).read().splitlines()[-1]); assert 'orphan' in r['failed_names'], r" "$hist" \
  || fail "the undeclared failure is counted but not named: $(tail -1 "$hist")"
echo "PASS: an undeclared instance is named in the row"
echo "PASS: every sweep leaves a history row (ASK-776)"
