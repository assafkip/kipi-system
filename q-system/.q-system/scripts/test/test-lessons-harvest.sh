#!/bin/bash
# Reproducer for lessons-harvest.py. Builds fake instances + RCAs + injected cause-tags and asserts:
#  - two UNRELATED instances sharing a cause-type  -> a candidate
#  - a ktlyst PAIR sharing a cause-type (same cluster) -> NO candidate
#  - a singleton cause-type                        -> NO candidate
#  - candidates land in the repo-root candidates dir, NOT under q-system/ (so they never fan)
#  - --dry writes nothing
# Run: bash q-system/.q-system/scripts/test/test-lessons-harvest.sh
set -euo pipefail

HARVEST="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/lessons-harvest.py"
T="$(mktemp -d)"
CAND="$T/lesson-candidates"

mk_rca() {  # $1=instance dir  $2=rca filename  $3=title
  mkdir -p "$1/q-system/output/rca"
  printf '# %s\n\n## Structural root cause\n\nsome structural cause text.\n' "$3" > "$1/q-system/output/rca/$2"
}

# Mirror the real layout: instances live under a `projects/` parent (-> solo clusters), except
# ktlyst-named ones (-> the ktlyst cluster by name). Two UNRELATED consulting instances share A.
mk_rca "$T/projects/acme-consulting" "rca-a.md" "acme clobber"
mk_rca "$T/projects/beta-labs"       "rca-b.md" "beta clobber"
# A ktlyst PAIR (same cluster by name) -> share cause-type B
mk_rca "$T/projects/ktlyst-strategy" "rca-c.md" "ktlyst strat"
mk_rca "$T/projects/ktlyst-website"  "rca-d.md" "ktlyst web"
# A singleton -> cause-type C
mk_rca "$T/projects/gamma-co"        "rca-e.md" "gamma solo"

# Build registry + injected tags with exact absolute RCA paths.
python3 - "$T" > "$T/tags.json" <<'PY'
import json, sys
T = sys.argv[1]
names = ["acme-consulting", "beta-labs", "ktlyst-strategy", "ktlyst-website", "gamma-co"]
reg = {"instances": [{"name": n, "path": f"{T}/projects/{n}"} for n in names]}
open(f"{T}/registry.json", "w").write(json.dumps(reg))
rca = {n: f"{T}/projects/{n}/q-system/output/rca" for n in names}
tags = {
    f"{rca['acme-consulting']}/rca-a.md": "two-writers-shared-resource",
    f"{rca['beta-labs']}/rca-b.md":       "two-writers-shared-resource",
    f"{rca['ktlyst-strategy']}/rca-c.md": "sync-delete-clobber",
    f"{rca['ktlyst-website']}/rca-d.md":  "sync-delete-clobber",
    f"{rca['gamma-co']}/rca-e.md":        "path-doubling",
}
print(json.dumps(tags))
PY

OUT="$(python3 "$HARVEST" --registry "$T/registry.json" --tags-file "$T/tags.json" --candidates-dir "$CAND")"
echo "--- harvester output ---"; echo "$OUT"

fail=0
echo "=== assertions ==="
echo "$OUT" | grep -q "CANDIDATE: two-writers-shared-resource" && echo "  PASS unrelated pair -> candidate" || { echo "  FAIL no candidate for unrelated pair"; fail=1; }
echo "$OUT" | grep -q "sync-delete-clobber"  && { echo "  FAIL ktlyst pair wrongly a candidate"; fail=1; } || echo "  PASS ktlyst pair -> no candidate"
echo "$OUT" | grep -q "path-doubling"        && { echo "  FAIL singleton wrongly a candidate"; fail=1; } || echo "  PASS singleton -> no candidate"
[ -f "$CAND/two-writers-shared-resource.md" ] && echo "  PASS candidate file written" || { echo "  FAIL candidate file missing"; fail=1; }
[ -f "$CAND/sync-delete-clobber.md" ] && { echo "  FAIL related-pair file written"; fail=1; } || echo "  PASS no file for related pair"

# candidates dir must be OUTSIDE q-system/ (default location), so kipi update never fans it
if python3 - "$HARVEST" <<'PY'
import importlib.util, sys
spec = importlib.util.spec_from_file_location("lh", sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
sys.exit(1 if "/q-system/" in str(m.CANDIDATES_DIR) else 0)
PY
then echo "  PASS default candidates dir is outside q-system (not fanned)"; else echo "  FAIL default candidates dir is inside q-system (would fan)"; fail=1; fi

# --dry writes nothing
DRYT="$(mktemp -d)"
python3 "$HARVEST" --registry "$T/registry.json" --tags-file "$T/tags.json" --candidates-dir "$DRYT/c" --dry >/dev/null
[ -d "$DRYT/c" ] && { echo "  FAIL --dry wrote files"; fail=1; } || echo "  PASS --dry wrote nothing"

[ "$fail" = 0 ] && echo "ALL PASS" || { echo "SOME FAILED"; exit 1; }
