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
