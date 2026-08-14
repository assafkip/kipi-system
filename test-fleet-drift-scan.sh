#!/bin/bash
# Pairs with fleet-drift-scan.py (ASK-795 / sp-786f1c4b).
#
# The scan's whole value is telling LAG from DRIFT. A detector that flags every
# instance behind main gets switched off within a day; one that flags nothing is
# indistinguishable from one that works. So the two controls below are the test:
# an old-but-shipped blob must stay QUIET, and a never-shipped blob must FIRE.
#
# Scar this encodes: the ten instances that committed PR #142's unmerged bytes were
# found only by hand. Every automated check called them clean.
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCAN="$SCRIPT_DIR/fleet-drift-scan.py"
TMP="$(mktemp -d)"
trap 'rm -r -- "$TMP" 2>/dev/null || true' EXIT

FAILED=0
ok()   { printf '  ok   %s\n' "$1"; }
bad()  { printf '  FAIL %s\n' "$1"; FAILED=1; }

q() { git -C "$1" "${@:2}" >/dev/null 2>&1; }

# ---- build a fake skeleton with a real 3-revision history for one managed file ----
SKEL="$TMP/skeleton"
mkdir -p "$SKEL/plugins/demo/scripts"
q "$SKEL" init -q -b main || git -C "$SKEL" init -q
git -C "$SKEL" config user.email t@t; git -C "$SKEL" config user.name t

write_rev() { printf 'revision %s\n' "$1" > "$SKEL/plugins/demo/scripts/tool.py"; }

write_rev v1; q "$SKEL" add -A; q "$SKEL" commit -m v1
BLOB_V1="$(git -C "$SKEL" rev-parse HEAD:plugins/demo/scripts/tool.py)"
write_rev v2; q "$SKEL" add -A; q "$SKEL" commit -m v2
write_rev v3; q "$SKEL" add -A; q "$SKEL" commit -m v3
BLOB_V3="$(git -C "$SKEL" rev-parse HEAD:plugins/demo/scripts/tool.py)"

# A blob that exists ONLY on a feature branch -- the exact shape of 7f42be38.
q "$SKEL" checkout -q -b feature
printf 'revision from-an-unmerged-branch\n' > "$SKEL/plugins/demo/scripts/tool.py"
q "$SKEL" add -A; q "$SKEL" commit -m branch-only
BLOB_BRANCH="$(git -C "$SKEL" rev-parse HEAD:plugins/demo/scripts/tool.py)"
q "$SKEL" checkout -q main

# The scan reads origin/main. No network here: point that ref at local main.
git -C "$SKEL" update-ref refs/remotes/origin/main refs/heads/main

[ "$BLOB_V1" != "$BLOB_V3" ] && [ "$BLOB_BRANCH" != "$BLOB_V3" ] \
  && ok "fixture built distinct blobs" || bad "fixture blobs collided"

# ---- three instances, one per case ----
mk_instance() {  # name, content
  local dir="$TMP/$1"
  mkdir -p "$dir/plugins/demo/scripts"
  q "$dir" init -q -b main || git -C "$dir" init -q
  git -C "$dir" config user.email t@t; git -C "$dir" config user.name t
  printf '%s\n' "$2" > "$dir/plugins/demo/scripts/tool.py"
  q "$dir" add -A; q "$dir" commit -m seed
}
mk_instance current "revision v3"
mk_instance lagging "revision v1"
mk_instance drifted "revision from-an-unmerged-branch"

cat > "$SKEL/instance-registry.json" <<EOF
{"skeleton":{"path":"$SKEL"},"instances":[
 {"name":"current","path":"$TMP/current"},
 {"name":"lagging","path":"$TMP/lagging"},
 {"name":"drifted","path":"$TMP/drifted"}]}
EOF

run_scan() { python3 "$SCAN" --skeleton "$SKEL" --no-fetch "$@" 2>&1; }

OUT="$(run_scan)"; RC=$?

# CONTROL 1: the instance matching main exactly must not appear at all.
echo "$OUT" | grep -q 'current' \
  && bad "an up-to-date instance was reported" \
  || ok "up-to-date instance is silent"

# CONTROL 2 (the false-positive killer): an OLD blob main really shipped is LAG,
# never DRIFT. Get this wrong and the scan flags the whole fleet.
echo "$OUT" | grep -q 'DRIFT .*lagging' \
  && bad "a legitimately lagging instance was called DRIFT" \
  || ok "lagging instance is not DRIFT"

# CONTROL 3 (the true positive we must actually catch): branch-only bytes.
echo "$OUT" | grep -q 'DRIFT .*drifted' \
  && ok "branch-only blob is reported as DRIFT" \
  || bad "branch-only blob was NOT detected -- the detector is inert"

[ "$RC" -eq 1 ] && ok "exit 1 when drift exists" || bad "expected exit 1, got $RC"

# CONTROL 4: with the drifted instance excluded, the scan must go green. Proves the
# exit code tracks the finding rather than being hardcoded.
run_scan --only current --only lagging >/dev/null 2>&1
[ $? -eq 0 ] && ok "exit 0 when no drift in scope" || bad "expected exit 0"

# CONTROL 5: an unmerged branch must NOT launder a blob. If the scan ever searched
# all refs, the drifted instance would read clean -- that is the ASK-775 round-7
# boundary, and it is the single assumption this whole file defends.
echo "$OUT" | grep -q 'DRIFT .*drifted' \
  && ok "ship-ref scope excludes feature branches" \
  || bad "feature-branch blob was laundered as legitimate"

# CONTROL 6: excluded paths are not audited (a .pyc must never be a finding).
: > "$TMP/drifted/plugins/demo/scripts/junk.pyc"
q "$TMP/drifted" add -A -f; q "$TMP/drifted" commit -m pyc
run_scan | grep -q 'junk.pyc' \
  && bad "an excluded .pyc was audited" || ok "excluded paths are skipped"

echo ""
[ "$FAILED" -eq 0 ] && echo "test-fleet-drift-scan: PASS" || echo "test-fleet-drift-scan: FAIL"
exit "$FAILED"
