#!/usr/bin/env bash
# The q-system sync must REFUSE when --delete would remove instance-owned data.
#
# Pairs with kipi-update-deletion-guard.py (sp-737ce1ae, sp-10cf4f76).
#
# The positive cases drive REAL rsync dry runs against real fixture trees --
# the itemized output is produced by rsync, not hand-written, because a
# hand-written fixture would test my idea of rsync's format rather than rsync's.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
GUARD="$ROOT/kipi-update-deletion-guard.py"
UPDATER="$ROOT/kipi-update.sh"
PASS=0; FAIL=0
ok()   { echo "PASS: $1"; PASS=$((PASS+1)); }
bad()  { echo "FAIL: $1" >&2; FAIL=$((FAIL+1)); }
check(){ if [ "$2" = "$3" ]; then ok "$1"; else bad "$1 (want rc=$3, got rc=$2)"; fi; }

WORK="$(mktemp -d)"
trap 'python3 -c "import shutil,sys;shutil.rmtree(sys.argv[1],ignore_errors=True)" "$WORK"' EXIT

# Same anchored excludes kipi-update.sh builds.
OWNED=(my-project canonical memory output research .q-system/data .q-system/agent-pipeline/bus)
excludes() { local s; for s in "${OWNED[@]}"; do printf -- '--exclude=/%s/\n' "$s"; done; }

skeleton() { mkdir -p "$1/q-system/canonical" "$1/q-system/methodology"
  echo tmpl > "$1/q-system/canonical/decisions.md"
  echo shared > "$1/q-system/methodology/modes.md"; }
instance() { mkdir -p "$1/canonical" "$1/my-project" "$1/memory"
  echo REAL > "$1/canonical/decisions.md"
  echo REAL > "$1/my-project/current-state.md"
  echo REAL > "$1/memory/last-handoff.md"; }

dry() { rsync -ain --delete "$1" "$2" $(excludes) 2>/dev/null; }

# --- 1. the reproduced defect: prefix empty, data under q-system/ -----------
A="$WORK/a"; mkdir -p "$A/arch" "$A/inst"
skeleton "$A/arch"; instance "$A/inst/q-system"
dry "$A/arch/q-system/" "$A/inst/" | python3 "$GUARD" 2>/dev/null
check "prefix-empty + data under q-system/ is REFUSED" "$?" "2"

# --- 2. the correct layout must still sync ---------------------------------
B="$WORK/b"; mkdir -p "$B/arch" "$B/inst"
skeleton "$B/arch"; instance "$B/inst/q-system"
dry "$B/arch/q-system/" "$B/inst/q-system/" | python3 "$GUARD" 2>/dev/null
check "matching prefix is ALLOWED (negative-fire)" "$?" "0"

# Without this the guard could be satisfied by refusing everything, which
# would break every instance in the fleet rather than protect it.

# --- 3. a skeleton-owned deletion is not instance-owned --------------------
C="$WORK/c"; mkdir -p "$C/arch" "$C/inst/q-system/methodology"
skeleton "$C/arch"
echo stale > "$C/inst/q-system/methodology/removed-by-skeleton.md"
dry "$C/arch/q-system/" "$C/inst/q-system/" | python3 "$GUARD" 2>/dev/null
check "deleting a skeleton-owned file is ALLOWED" "$?" "0"

# --- 4. tracked instance-only file inside an owned subtree (sp-10cf4f76) ---
D="$WORK/d"; mkdir -p "$D/arch" "$D/inst"
skeleton "$D/arch"; instance "$D/inst/q-system"
mkdir -p "$D/inst/q-system/my-project/scripts"
echo 'income scanner' > "$D/inst/q-system/my-project/scripts/scan.py"
dry "$D/arch/q-system/" "$D/inst/" | python3 "$GUARD" 2>/dev/null
check "instance-only script under an owned subtree is REFUSED" "$?" "2"

# --- 5. anchored on q-system/, at any PREFIX depth -------------------------
# Was "matched at ANY depth". That over-corrected: `.q-system/agent-pipeline/
# templates/deck/output/` is a REAL skeleton-owned directory, so a skeleton
# deletion under it refused the sync for the whole fleet (Codex, PR #111).
# A guard that halts every unattended update gets switched off.
printf '*deleting   instances/foo/q-system/memory/last-handoff.md\n' | python3 "$GUARD" 2>/dev/null
check "owned subtree under q-system/ at any PREFIX depth is REFUSED" "$?" "2"
printf '*deleting   memory/last-handoff.md\n' | python3 "$GUARD" 2>/dev/null
check "owned subtree at the transfer ROOT is REFUSED" "$?" "2"
printf '*deleting   q-system/.q-system/agent-pipeline/templates/deck/output/x.html\n' | python3 "$GUARD" 2>/dev/null
check "REAL skeleton-owned nested output/ is ALLOWED (no false fleet block)" "$?" "0"
printf '*deleting   a/b/c/memory/last-handoff.md\n' | python3 "$GUARD" 2>/dev/null
check "an owned NAME not under q-system/ is skeleton content, allowed" "$?" "0"
printf '*deleting   q-system/methodology/modes.md\n' | python3 "$GUARD" 2>/dev/null
check "unowned path at depth is allowed" "$?" "0"
printf '*deleting   memoryless/notes.md\n' | python3 "$GUARD" 2>/dev/null
check "substring of an owned name is NOT a match" "$?" "0"

# --- 5b. bypasses found by attacking THIS guard ----------------------------
# Every one of these passed before hardening. Kept as regressions because they
# are the shapes a reader would not think to check.
printf '*deleting   q-system/My-Project/x.md\n' | python3 "$GUARD" 2>/dev/null
check "case variant is caught (macOS FS is case-insensitive)" "$?" "2"
printf '*deleting   Q-SYSTEM/MEMORY/x.md\n' | python3 "$GUARD" 2>/dev/null
check "fully-uppercased owned path is caught" "$?" "2"
printf 'deleting   q-system/my-project/x.md\n' | python3 "$GUARD" 2>/dev/null
check "bare 'deleting' (no asterisk) is caught" "$?" "2"

# --- 6. empty input --------------------------------------------------------
printf '' | python3 "$GUARD" 2>/dev/null
check "no deletions planned is allowed" "$?" "0"

# --- 7. the two owned-subtree lists must not drift -------------------------
# The guard duplicates INSTANCE_OWNED_SUBTREES so it stays standalone-runnable.
# Duplication is only safe while something reads both.
GUARD_LIST=$(python3 -c "
import re,sys
src=open('$GUARD').read()
blk=re.search(r'INSTANCE_OWNED = \(([^)]*)\)', src).group(1)
print(' '.join(sorted(re.findall(r'\"([^\"]+)\"', blk))))")
SH_LIST=$(python3 -c "
import re
src=open('$UPDATER').read()
blk=re.search(r'INSTANCE_OWNED_SUBTREES=\(([^)]*)\)', src).group(1)
names=[l.strip() for l in blk.splitlines() if l.strip() and not l.strip().startswith('#')]
print(' '.join(sorted(names)))")
if [ "$GUARD_LIST" = "$SH_LIST" ]; then ok "owned-subtree lists agree"
else bad "owned-subtree lists DRIFTED: guard=[$GUARD_LIST] updater=[$SH_LIST]"; fi

# --- 8. the guard is actually WIRED into the updater -----------------------
if grep -q "kipi-update-deletion-guard.py" "$UPDATER"; then
  ok "guard is invoked by kipi-update.sh"
else
  bad "guard exists but kipi-update.sh never calls it (a gate nothing runs)"
fi

# --- 9. END TO END: the real updater refuses and the data survives ---------
# Everything above tests the guard in isolation plus a grep proving it is
# called. Neither proves the updater actually refuses, which is the claim that
# matters: this is a P0 data-loss bug, so the receipt has to be "the founder's
# files are still on disk after a real run".
G() { git -c user.email=t@t.t -c user.name=test -c commit.gpgsign=false "$@"; }
E="$WORK/e2e"; SKE="$E/skel"; INS="$E/inst"
mkdir -p "$SKE/q-system/canonical" "$SKE/q-system/.q-system/scripts" "$SKE/q-system/.q-system/state"
cp "$UPDATER" "$SKE/kipi-update.sh"
cp "$ROOT/kipi-update-preserve-scan.py" "$SKE/kipi-update-preserve-scan.py"
cp "$GUARD" "$SKE/kipi-update-deletion-guard.py"
cp "$ROOT/q-system/.q-system/scripts/propagation-leak-gate.py" "$SKE/q-system/.q-system/scripts/"
cp "$ROOT/q-system/.q-system/scripts/containment-targets.py" "$SKE/q-system/.q-system/scripts/"
cp "$ROOT/validate-separation.py" "$SKE/validate-separation.py"
cat > "$SKE/q-system/.q-system/state/propagation-leak-baseline.json" <<'BJ'
{"schema_version":1,"blocking_classes":["case_proof_gap","client_identity","dated_interaction","pricing","relationship","source_identity","sourced_interaction"],"classifier_sha256":null,"entries":[]}
BJ
printf 'skeleton template\n' > "$SKE/q-system/canonical/decisions.md"
( cd "$SKE" && G init -q && G add -A -f && G commit -qm skel )

# A REACHABLE fixture. An earlier draft used subtree_prefix null, and that
# instance is refused earlier ("UNDECLARED NON-PROPAGATING") before any rsync,
# so the data survived for a reason that had nothing to do with this guard --
# the test passed with the guard deleted. Verified by mutation.
#
# This shape reaches the rsync: a non-null prefix ("app") that passes the
# propagation check, with the instance still nesting its real data under
# app/q-system/. The anchored excludes point at app/, the data is one level
# below, and the deletions itemize as q-system/my-project/... .
mkdir -p "$INS/app/q-system/my-project" "$INS/app/q-system/memory"
printf 'REAL FOUNDER STATE\n' > "$INS/app/q-system/my-project/current-state.md"
printf 'REAL HANDOFF\n'      > "$INS/app/q-system/memory/last-handoff.md"
( cd "$INS" && G init -q && G add -A && G commit -qm inst )
printf '{"instances":[{"name":"nested","path":"%s","subtree_prefix":"app","type":"subtree"}]}\n' \
  "$INS" > "$SKE/instance-registry.json"

bash "$SKE/kipi-update.sh" >/dev/null 2>&1 || true

if [ -f "$INS/app/q-system/my-project/current-state.md" ] \
   && [ -f "$INS/app/q-system/memory/last-handoff.md" ] \
   && grep -q "REAL FOUNDER STATE" "$INS/app/q-system/my-project/current-state.md"; then
  ok "END-TO-END: real kipi update left instance-owned data intact"
else
  bad "END-TO-END: a real kipi update DESTROYED instance-owned data"
fi

echo
echo "passed=$PASS failed=$FAIL"
[ "$FAIL" -eq 0 ] || exit 1
