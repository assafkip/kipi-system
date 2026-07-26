#!/usr/bin/env bash
# H2+H4: kipi update must not destroy untracked (incl. gitignored) instance files,
# and --dry must give a real itemized preview. Pairs with issue kipi-update-safety.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
SCRIPT="$ROOT/kipi-update.sh"
fail() { echo "FAIL: $1" >&2; exit 1; }
G() { git -c user.email=t@t.t -c user.name=test -c commit.gpgsign=false "$@"; }

WORK="$(mktemp -d)"; SK="$WORK/skel"; INST="$WORK/inst"

# skeleton: git repo with committed q-system/ + a copy of the script + a registry
mkdir -p "$SK/q-system"
cp "$SCRIPT" "$SK/kipi-update.sh"
cp "$ROOT/kipi-update-preserve-scan.py" "$SK/kipi-update-preserve-scan.py"
# A valid skeleton ships the propagation leak gate: kipi-update.sh is
# fail-closed on it, so a fixture without it aborts before any sync.
mkdir -p "$SK/q-system/.q-system/scripts" "$SK/q-system/.q-system/state"
cp "$ROOT/q-system/.q-system/scripts/propagation-leak-gate.py" \
   "$SK/q-system/.q-system/scripts/propagation-leak-gate.py"
cp "$ROOT/q-system/.q-system/scripts/containment-targets.py" \
   "$SK/q-system/.q-system/scripts/containment-targets.py"
cp "$ROOT/validate-separation.py" "$SK/validate-separation.py"
# NOT the repo's committed baseline: that one is ARMED and its permits
# describe THIS repo's content, so loading it against a synthetic skeleton
# refuses ("a permit cannot exceed what was reviewed"). A fixture gets its
# own unarmed baseline.
cat > "$SK/q-system/.q-system/state/propagation-leak-baseline.json" <<'BASELINE_JSON'
{
  "schema_version": 1,
  "blocking_classes": [
    "case_proof_gap",
    "client_identity",
    "dated_interaction",
    "pricing",
    "relationship",
    "source_identity",
    "sourced_interaction"
  ],
  "classifier_sha256": null,
  "entries": []
}
BASELINE_JSON
printf 'skeleton content v2\n' > "$SK/q-system/tracked.md"
( cd "$SK" && G init -q && G add -A && G commit -qm skel )
printf '{"instances":[{"name":"testinst","path":"%s","subtree_prefix":"q-system","type":"subtree"}]}\n' "$INST" > "$SK/instance-registry.json"

# instance: q-system/ with OLD tracked content + an UNTRACKED GITIGNORED file in a synced (non-excluded) dir
mkdir -p "$INST/q-system/sources"
printf 'skeleton content v1 (old)\n' > "$INST/q-system/tracked.md"
printf 'sources/*\n' > "$INST/q-system/.gitignore"
( cd "$INST" && G init -q && G add -A && G commit -qm inst )
printf 'PRIVATE UNTRACKED SOURCE\n' > "$INST/q-system/sources/secret.md"
mkdir -p "$INST/realdir" && printf 'x\n' > "$INST/realdir/x.md"
( cd "$INST/q-system" && ln -s ../realdir linkdir )  # untracked symlink-to-dir under the synced prefix

# 1. real run: the untracked gitignored file must SURVIVE the rsync --delete
bash "$SK/kipi-update.sh" >/dev/null 2>&1 || true
[ -f "$INST/q-system/sources/secret.md" ] || fail "untracked gitignored file DESTROYED by rsync --delete (snapshot/restore failed)"
grep -q "PRIVATE UNTRACKED SOURCE" "$INST/q-system/sources/secret.md" || fail "untracked content not preserved"
grep -q "skeleton content v2" "$INST/q-system/tracked.md" || fail "tracked file not synced from skeleton"
[ -L "$INST/q-system/linkdir" ] || fail "untracked symlink-to-dir DESTROYED by rsync --delete (cp -a fix)"

# 2. --dry-run: itemized preview, NOT the file-count heuristic
printf 'skeleton content v1 (old again)\n' > "$INST/q-system/tracked.md"
DRY="$(bash "$SK/kipi-update.sh" --dry-run 2>&1)" || true
echo "$DRY" | grep -q "skeleton files:" && fail "--dry still uses the file-count heuristic"
echo "$DRY" | grep -qE "Changes vs skeleton|Up to date" || fail "--dry produced no itemized preview: $DRY"

echo "PASS: untracked gitignored file survives the sync; --dry is an itemized preview (no file-count heuristic)"

# --- staged rollout: --only must touch exactly one instance -----------------
# A fleet update writes to every registered instance in one command. Without a
# way to target one, there is no way to verify a risky change on a single repo
# before the other 22, which is the only safe way to roll one out.
WORK3="$(mktemp -d)"; SK3="$WORK3/skel"; A3="$WORK3/a"; B3="$WORK3/b"
mkdir -p "$SK3/q-system" "$A3/q-system" "$B3/q-system"
cp "$SCRIPT" "$SK3/kipi-update.sh"
cp "$ROOT/kipi-update-preserve-scan.py" "$SK3/kipi-update-preserve-scan.py"
mkdir -p "$SK3/q-system/.q-system/scripts" "$SK3/q-system/.q-system/state"
cp "$ROOT/q-system/.q-system/scripts/propagation-leak-gate.py" \
   "$SK3/q-system/.q-system/scripts/propagation-leak-gate.py"
cp "$ROOT/q-system/.q-system/scripts/containment-targets.py" \
   "$SK3/q-system/.q-system/scripts/containment-targets.py"
cp "$ROOT/validate-separation.py" "$SK3/validate-separation.py"
cat > "$SK3/q-system/.q-system/state/propagation-leak-baseline.json" <<'BJ'
{"schema_version":1,"blocking_classes":["case_proof_gap","client_identity","dated_interaction","pricing","relationship","source_identity","sourced_interaction"],"classifier_sha256":null,"entries":[]}
BJ
printf 'skeleton v2\n' > "$SK3/q-system/tracked.md"
( cd "$SK3" && G init -q && G add -A -f && G commit -qm skel )
printf '{"instances":[{"name":"aaa","path":"%s","subtree_prefix":"q-system","type":"subtree"},{"name":"bbb","path":"%s","subtree_prefix":"q-system","type":"subtree"}]}\n' \
  "$A3" "$B3" > "$SK3/instance-registry.json"
for d in "$A3" "$B3"; do
  printf 'old\n' > "$d/q-system/tracked.md"
  ( cd "$d" && G init -q && G add -A && G commit -qm inst )
done
HB_BEFORE="$( cd "$B3" && G rev-parse HEAD )"

bash "$SK3/kipi-update.sh" --only aaa >/dev/null 2>&1 || true
grep -q "skeleton v2" "$A3/q-system/tracked.md" || fail "--only aaa did not update aaa"
HB_AFTER="$( cd "$B3" && G rev-parse HEAD )"
[ "$HB_BEFORE" = "$HB_AFTER" ] || fail "--only aaa also wrote to bbb"
grep -q "old" "$B3/q-system/tracked.md" || fail "--only aaa changed bbb's content"
echo "PASS: --only targets exactly one instance and leaves the rest untouched"

# --- instance-owned state under .q-system/data/ must survive a sync ---------
# The skeleton TRACKS q-system/.q-system/data/metrics.db, and every instance
# generates its own. Measured 2026-07-25 on a real run: the collision guard
# correctly refused rather than overwrite one instance's metrics with the
# skeleton's -- and it would have refused on all 23. A per-instance metrics
# database is instance-owned state, the same class as memory/ and output/,
# and belongs in the same exclusion set rather than blocking every update.
WORK4="$(mktemp -d)"; SK4="$WORK4/skel"; I4="$WORK4/inst"
mkdir -p "$SK4/q-system/.q-system/data" "$I4/q-system/.q-system/data"
cp "$SCRIPT" "$SK4/kipi-update.sh"
cp "$ROOT/kipi-update-preserve-scan.py" "$SK4/kipi-update-preserve-scan.py"
mkdir -p "$SK4/q-system/.q-system/scripts" "$SK4/q-system/.q-system/state"
cp "$ROOT/q-system/.q-system/scripts/propagation-leak-gate.py" \
   "$SK4/q-system/.q-system/scripts/propagation-leak-gate.py"
cp "$ROOT/q-system/.q-system/scripts/containment-targets.py" \
   "$SK4/q-system/.q-system/scripts/containment-targets.py"
cp "$ROOT/validate-separation.py" "$SK4/validate-separation.py"
cat > "$SK4/q-system/.q-system/state/propagation-leak-baseline.json" <<'BJ'
{"schema_version":1,"blocking_classes":["case_proof_gap","client_identity","dated_interaction","pricing","relationship","source_identity","sourced_interaction"],"classifier_sha256":null,"entries":[]}
BJ
printf 'skeleton v2\n' > "$SK4/q-system/tracked.md"
printf 'SKELETON METRICS\n' > "$SK4/q-system/.q-system/data/metrics.db"
( cd "$SK4" && G init -q && G add -A -f && G commit -qm skel )
printf '{"instances":[{"name":"m","path":"%s","subtree_prefix":"q-system","type":"subtree"}]}\n' \
  "$I4" > "$SK4/instance-registry.json"
printf 'old\n' > "$I4/q-system/tracked.md"
( cd "$I4" && G init -q && G add -A && G commit -qm inst )
printf 'INSTANCE OWN METRICS\n' > "$I4/q-system/.q-system/data/metrics.db"   # untracked, local

OUT4="$(bash "$SK4/kipi-update.sh" 2>&1 || true)"
if echo "$OUT4" | grep -q "untracked WIP collides with skeleton path"; then
  fail "instance-owned .q-system/data/ blocked the sync: $OUT4"
fi
grep -q "skeleton v2" "$I4/q-system/tracked.md" || fail "sync did not run: $OUT4"
grep -q "INSTANCE OWN METRICS" "$I4/q-system/.q-system/data/metrics.db" || \
  fail "the instance's own metrics.db was overwritten by the skeleton's"
echo "PASS: instance-owned .q-system/data/ neither blocks the sync nor is overwritten"

