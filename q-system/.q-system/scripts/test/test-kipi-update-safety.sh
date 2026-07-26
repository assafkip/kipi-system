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

# --- an interrupted sync must be recoverable by re-running ------------------
# A run that dies after the rsync but before the commit leaves its own output
# in the instance as UNTRACKED files. The collision guard then reads them as
# work in progress and refuses forever, so one interrupted sync bricks that
# instance until a human deletes files by hand. Observed on a real run
# 2026-07-25: 40 residue files, every one byte-identical to the skeleton.
# Identical content is not WIP; it is this sync's own half-finished work.
WORK5="$(mktemp -d)"; SK5="$WORK5/skel"; I5="$WORK5/inst"
mkdir -p "$SK5/q-system/.q-system/scripts" "$SK5/q-system/.q-system/state" "$I5/q-system"
cp "$SCRIPT" "$SK5/kipi-update.sh"
cp "$ROOT/kipi-update-preserve-scan.py" "$SK5/kipi-update-preserve-scan.py"
cp "$ROOT/q-system/.q-system/scripts/propagation-leak-gate.py" \
   "$SK5/q-system/.q-system/scripts/propagation-leak-gate.py"
cp "$ROOT/q-system/.q-system/scripts/containment-targets.py" \
   "$SK5/q-system/.q-system/scripts/containment-targets.py"
cp "$ROOT/validate-separation.py" "$SK5/validate-separation.py"
cat > "$SK5/q-system/.q-system/state/propagation-leak-baseline.json" <<'BJ'
{"schema_version":1,"blocking_classes":["case_proof_gap","client_identity","dated_interaction","pricing","relationship","source_identity","sourced_interaction"],"classifier_sha256":null,"entries":[]}
BJ
printf 'skeleton v2\n' > "$SK5/q-system/tracked.md"
printf 'new skeleton file\n' > "$SK5/q-system/newthing.md"
( cd "$SK5" && G init -q && G add -A -f && G commit -qm skel )
printf '{"instances":[{"name":"r","path":"%s","subtree_prefix":"q-system","type":"subtree"}]}\n' \
  "$I5" > "$SK5/instance-registry.json"
printf 'old\n' > "$I5/q-system/tracked.md"
( cd "$I5" && G init -q && G add -A && G commit -qm inst )
# residue from an interrupted run: identical to the skeleton, untracked
printf 'new skeleton file\n' > "$I5/q-system/newthing.md"
# and a genuine untracked instance file that DOES differ -- must still block
printf 'MY OWN WORK\n' > "$I5/q-system/tracked.md.local"

OUT5="$(bash "$SK5/kipi-update.sh" 2>&1 || true)"
if echo "$OUT5" | grep -q "collides with skeleton path: q-system/newthing.md"; then
  fail "identical sync residue was read as untracked WIP: $OUT5"
fi
grep -q "skeleton v2" "$I5/q-system/tracked.md" || fail "re-run did not converge: $OUT5"
grep -q "MY OWN WORK" "$I5/q-system/tracked.md.local" || fail "a real untracked instance file was destroyed"
echo "PASS: an interrupted sync re-runs cleanly; genuine untracked work is still protected"


# --- a virtualenv's file symlinks must not block dry-run modeling -----------
# Measured 2026-07-25 on ASK_AI_consultant: the dry-run symlink guard walks the
# WHOLE instance and refuses on any symlink whose target resolves outside it.
# Every instance with kipi-mcp installed carries a 98MB
# plugins/kipi-core/kipi-mcp/.venv whose bin/ holds exactly that shape --
# `python -> /abs/path/to/python3.12` and a relative `python3 -> python` that
# inherits the escape through the chain. That refusal blocked the fleet for a
# reason unrelated to update safety.
#
# The boundary that actually matters: rsync and git REPLACE a file symlink,
# they never write through it, so an escaping FILE symlink cannot mutate
# anything outside the model. An escaping DIRECTORY symlink is a real path
# prefix a write can descend into, and must still refuse. Both are asserted
# below, and case A asserts the outside target is byte-identical afterwards --
# proof of no escape, not just proof the guard went quiet.
WORK6="$(mktemp -d)"; SK6="$WORK6/skel"; I6="$WORK6/inst"; OUT6DIR="$WORK6/outside"
mkdir -p "$SK6/q-system/.q-system/scripts" "$SK6/q-system/.q-system/state" \
         "$I6/q-system" "$I6/plugins/kipi-core/kipi-mcp/.venv/bin" "$OUT6DIR"
cp "$SCRIPT" "$SK6/kipi-update.sh"
cp "$ROOT/kipi-update-preserve-scan.py" "$SK6/kipi-update-preserve-scan.py"
cp "$ROOT/q-system/.q-system/scripts/propagation-leak-gate.py" \
   "$SK6/q-system/.q-system/scripts/propagation-leak-gate.py"
cp "$ROOT/q-system/.q-system/scripts/containment-targets.py" \
   "$SK6/q-system/.q-system/scripts/containment-targets.py"
cp "$ROOT/validate-separation.py" "$SK6/validate-separation.py"
cat > "$SK6/q-system/.q-system/state/propagation-leak-baseline.json" <<'BJ'
{"schema_version":1,"blocking_classes":["case_proof_gap","client_identity","dated_interaction","pricing","relationship","source_identity","sourced_interaction"],"classifier_sha256":null,"entries":[]}
BJ
printf 'skeleton v2\n' > "$SK6/q-system/tracked.md"
( cd "$SK6" && G init -q && G add -A -f && G commit -qm skel )
printf '{"instances":[{"name":"venvinst","path":"%s","subtree_prefix":"q-system","type":"subtree"}]}\n' \
  "$I6" > "$SK6/instance-registry.json"
printf 'old\n' > "$I6/q-system/tracked.md"
( cd "$I6" && G init -q && G add -A && G commit -qm inst )

# the real venv shape, byte for byte
printf 'REAL INTERPRETER\n' > "$OUT6DIR/python3.12"
ln -s "$OUT6DIR/python3.12" "$I6/plugins/kipi-core/kipi-mcp/.venv/bin/python"
( cd "$I6/plugins/kipi-core/kipi-mcp/.venv/bin" && ln -s python python3 )
OUT6="$(bash "$SK6/kipi-update.sh" --dry-run --only venvinst 2>&1 || true)"
echo "$OUT6" | grep -q "unsafe symlink" && \
  fail "a virtualenv's file symlinks blocked dry-run modeling: $OUT6"
echo "$OUT6" | grep -q "unsafe absolute symlink" && \
  fail "a virtualenv's absolute file symlink blocked dry-run modeling: $OUT6"
echo "$OUT6" | grep -qE "Changes vs skeleton|Up to date|final state" || \
  fail "--dry-run produced no model for an instance with a venv: $OUT6"
grep -q "REAL INTERPRETER" "$OUT6DIR/python3.12" || \
  fail "the dry run wrote THROUGH a file symlink and mutated a file outside the instance"

# case B: an escaping DANGLING symlink must refuse. Nothing exists to replace,
# so a mkdir -p or a redirect under it materialises the path outside the model.
ln -s "$OUT6DIR/never-created" "$I6/q-system/escapedangling"
OUT6B="$(bash "$SK6/kipi-update.sh" --dry-run --only venvinst 2>&1 || true)"
echo "$OUT6B" | grep -q "unsafe dangling symlink" || \
  fail "an escaping DANGLING symlink was modeled instead of refused: $OUT6B"
rm "$I6/q-system/escapedangling"

# case C: an escaping DIRECTORY symlink is a live write path and must refuse
mkdir -p "$OUT6DIR/realdir"
ln -s "$OUT6DIR/realdir" "$I6/q-system/escapedir"
OUT6C="$(bash "$SK6/kipi-update.sh" --dry-run --only venvinst 2>&1 || true)"
echo "$OUT6C" | grep -q "unsafe directory symlink" || \
  fail "an escaping DIRECTORY symlink was modeled instead of refused: $OUT6C"
echo "PASS: a venv's file symlinks model fine; escaping dangling and directory symlinks refuse"

# --- the dry-run model must not copy nested repositories --------------------
# The model is built with `rsync -a --delete --exclude=.git` of the WHOLE
# instance tree. Measured 2026-07-25: ASK_AI_consultant is
# /Users/assafkipnis/projects/consulting, which is the PARENT of ten other
# registered instances -- 21GB, of which this sync can write to about 100MB.
# The copy ran the data volume down to 605MB free before it was killed.
#
# A directory holding its own .git below the root is a separate repository.
# The updater never descends into one (it writes to the subtree prefix,
# .claude/ and plugins/), and in the fleet it is another registered instance
# with its own entry and its own update run. Copying it is pure waste and a
# disk hazard, so the model skips it and says so.
WORK7="$(mktemp -d)"; SK7="$WORK7/skel"; I7="$WORK7/inst"
mkdir -p "$SK7/q-system/.q-system/scripts" "$SK7/q-system/.q-system/state" \
         "$I7/q-system" "$I7/projects/nested/q-system"
cp "$SCRIPT" "$SK7/kipi-update.sh"
cp "$ROOT/kipi-update-preserve-scan.py" "$SK7/kipi-update-preserve-scan.py"
cp "$ROOT/q-system/.q-system/scripts/propagation-leak-gate.py" \
   "$SK7/q-system/.q-system/scripts/propagation-leak-gate.py"
cp "$ROOT/q-system/.q-system/scripts/containment-targets.py" \
   "$SK7/q-system/.q-system/scripts/containment-targets.py"
cp "$ROOT/validate-separation.py" "$SK7/validate-separation.py"
cat > "$SK7/q-system/.q-system/state/propagation-leak-baseline.json" <<'BJ'
{"schema_version":1,"blocking_classes":["case_proof_gap","client_identity","dated_interaction","pricing","relationship","source_identity","sourced_interaction"],"classifier_sha256":null,"entries":[]}
BJ
printf 'skeleton v2\n' > "$SK7/q-system/tracked.md"
( cd "$SK7" && G init -q && G add -A -f && G commit -qm skel )
printf '{"instances":[{"name":"parentinst","path":"%s","subtree_prefix":"q-system","type":"subtree"}]}\n' \
  "$I7" > "$SK7/instance-registry.json"
printf 'old\n' > "$I7/q-system/tracked.md"
( cd "$I7" && G init -q && G add -A && G commit -qm inst )
# a separate repository living under the parent, exactly like the fleet's
# consulting/projects/<instance> layout
printf 'NESTED INSTANCE WORK\n' > "$I7/projects/nested/q-system/tracked.md"
( cd "$I7/projects/nested" && G init -q && G add -A && G commit -qm nested )
# The probe that makes this test about BEHAVIOUR and not about the log line:
# an unreadable directory inside the nested repo. rsync cannot copy it and
# exits non-zero, so a model that still descends into nested repos fails to
# build. Announcing the skip while copying anyway does not survive this.
mkdir -p "$I7/projects/nested/locked" && chmod 000 "$I7/projects/nested/locked"
trap 'chmod 755 "$I7/projects/nested/locked" 2>/dev/null || true' EXIT

OUT7="$(bash "$SK7/kipi-update.sh" --dry-run --only parentinst 2>&1 || true)"
echo "$OUT7" | grep -q "could not create disposable dry-run model" && \
  fail "the dry-run model descended into a nested repository and failed on it: $OUT7"
echo "$OUT7" | grep -q "nested repositor" || \
  fail "the dry-run model did not report skipping the nested repository: $OUT7"
echo "$OUT7" | grep -qE "Changes vs skeleton|Up to date|final state" || \
  fail "--dry-run produced no model once nested repos were skipped: $OUT7"
grep -q "NESTED INSTANCE WORK" "$I7/projects/nested/q-system/tracked.md" || \
  fail "the dry run mutated the nested repository"
[ -d "$I7/projects/nested/.git" ] || fail "the dry run destroyed the nested repository's git dir"
echo "PASS: the dry-run model skips nested repositories and still models the instance"

# --- the stager must not stage what the syncer never wrote ------------------
# The plugin sync loop iterates `$SCRIPT_DIR/plugins/*/`, a glob that only
# matches directories, so a skeleton plugin entry that is a DANGLING symlink is
# silently skipped and never materialises in the instance. stage_config_sync
# then enumerates the same tree with `-type l` included, so it hands git that
# path anyway and the instance answers `fatal: pathspec ... did not match any
# files`, failing the whole config sync.
#
# Measured 2026-07-25: the skeleton's plugins/memory-lifecycle points at
# /Users/assafkip/projects/memory-lifecycle -- an old username, long dead --
# so all_points_setup and Prodigy_Gold both failed here. Instances that had
# received the plugin back when the link resolved passed, which is why this
# looked instance-specific rather than skeleton-wide.
WORK8="$(mktemp -d)"; SK8="$WORK8/skel"; I8="$WORK8/inst"
mkdir -p "$SK8/q-system/.q-system/scripts" "$SK8/q-system/.q-system/state" \
         "$SK8/plugins/realplugin" "$SK8/.claude/rules" "$I8/q-system" "$I8/.claude"
cp "$SCRIPT" "$SK8/kipi-update.sh"
cp "$ROOT/kipi-update-preserve-scan.py" "$SK8/kipi-update-preserve-scan.py"
cp "$ROOT/q-system/.q-system/scripts/propagation-leak-gate.py" \
   "$SK8/q-system/.q-system/scripts/propagation-leak-gate.py"
cp "$ROOT/q-system/.q-system/scripts/containment-targets.py" \
   "$SK8/q-system/.q-system/scripts/containment-targets.py"
cp "$ROOT/validate-separation.py" "$SK8/validate-separation.py"
cat > "$SK8/q-system/.q-system/state/propagation-leak-baseline.json" <<'BJ'
{"schema_version":1,"blocking_classes":["case_proof_gap","client_identity","dated_interaction","pricing","relationship","source_identity","sourced_interaction"],"classifier_sha256":null,"entries":[]}
BJ
printf 'skeleton v2\n' > "$SK8/q-system/tracked.md"
printf 'real plugin content\n' > "$SK8/plugins/realplugin/content.txt"
printf 'example rule\n' > "$SK8/.claude/rules/example.md"
cp "$ROOT/settings-template.json" "$SK8/settings-template.json" 2>/dev/null || \
  printf '{}\n' > "$SK8/settings-template.json"
cp "$ROOT/kipi-settings-merge.py" "$SK8/kipi-settings-merge.py" 2>/dev/null || true
# the dead entry, exactly the shape of plugins/memory-lifecycle
ln -s "$WORK8/never-existed" "$SK8/plugins/ghost"
( cd "$SK8" && G init -q && G add -A -f && G commit -qm skel )
printf '{"instances":[{"name":"ghostinst","path":"%s","subtree_prefix":"q-system","type":"subtree"}]}\n' \
  "$I8" > "$SK8/instance-registry.json"
printf 'old\n' > "$I8/q-system/tracked.md"
printf '{}\n' > "$I8/.claude/settings.json"
( cd "$I8" && G init -q && G add -A && G commit -qm inst )

OUT8="$(bash "$SK8/kipi-update.sh" --dry-run --only ghostinst 2>&1 || true)"
echo "$OUT8" | grep -q "did not match any files" && \
  fail "the stager staged a plugin the syncer never wrote: $OUT8"
echo "$OUT8" | grep -q "config sync did not reach a complete committed state" && \
  fail "a dangling skeleton plugin failed the config sync: $OUT8"
echo "$OUT8" | grep -qE "Changes vs skeleton|Up to date|final state" || \
  fail "--dry-run produced no model with a dangling skeleton plugin: $OUT8"

# and the real plugin next to it must still reach the instance
REAL8="$(bash "$SK8/kipi-update.sh" --only ghostinst 2>&1 || true)"
grep -q "real plugin content" "$I8/plugins/realplugin/content.txt" 2>/dev/null || \
  fail "skipping the dangling plugin also skipped the real one next to it: $REAL8"
[ -e "$I8/plugins/ghost" ] && fail "a dangling skeleton plugin was materialised in the instance"
echo "PASS: a dangling skeleton plugin is skipped by BOTH the syncer and the stager"

# --- one instance-ignored skeleton file must not fail the config sync -------
# stage_config_sync hands git every file under the skeleton's plugins/. If the
# INSTANCE's .gitignore covers one of them, `git add` refuses with "paths are
# ignored by one of your .gitignore files" and the whole config sync fails --
# so a single stray file in the skeleton takes down every instance that ignores
# its extension.
#
# Measured 2026-07-25 on ASK_AI_consultant: the skeleton TRACKS
# plugins/prd-os/scripts/export-fable-mirror.sh.remediation.bak (a backup
# committed by accident) and the instance's .gitignore line 62 is `*.bak`.
# The right behaviour is to skip what the instance cannot track, not to abort:
# an ignored file was never going to be committed there anyway.
WORK9="$(mktemp -d)"; SK9="$WORK9/skel"; I9="$WORK9/inst"
mkdir -p "$SK9/q-system/.q-system/scripts" "$SK9/q-system/.q-system/state" \
         "$SK9/plugins/realplugin" "$SK9/.claude/rules" "$I9/q-system" "$I9/.claude"
cp "$SCRIPT" "$SK9/kipi-update.sh"
cp "$ROOT/kipi-update-preserve-scan.py" "$SK9/kipi-update-preserve-scan.py"
cp "$ROOT/q-system/.q-system/scripts/propagation-leak-gate.py" \
   "$SK9/q-system/.q-system/scripts/propagation-leak-gate.py"
cp "$ROOT/q-system/.q-system/scripts/containment-targets.py" \
   "$SK9/q-system/.q-system/scripts/containment-targets.py"
cp "$ROOT/validate-separation.py" "$SK9/validate-separation.py"
cat > "$SK9/q-system/.q-system/state/propagation-leak-baseline.json" <<'BJ'
{"schema_version":1,"blocking_classes":["case_proof_gap","client_identity","dated_interaction","pricing","relationship","source_identity","sourced_interaction"],"classifier_sha256":null,"entries":[]}
BJ
printf 'skeleton v2\n' > "$SK9/q-system/tracked.md"
printf 'real plugin content\n' > "$SK9/plugins/realplugin/content.txt"
printf 'a backup committed by accident\n' > "$SK9/plugins/realplugin/thing.sh.remediation.bak"
printf 'example rule\n' > "$SK9/.claude/rules/example.md"
cp "$ROOT/settings-template.json" "$SK9/settings-template.json" 2>/dev/null || printf '{}\n' > "$SK9/settings-template.json"
cp "$ROOT/kipi-settings-merge.py" "$SK9/kipi-settings-merge.py" 2>/dev/null || true
( cd "$SK9" && G init -q && G add -A -f && G commit -qm skel )
printf '{"instances":[{"name":"ignoreinst","path":"%s","subtree_prefix":"q-system","type":"subtree"}]}\n' \
  "$I9" > "$SK9/instance-registry.json"
printf 'old\n' > "$I9/q-system/tracked.md"
printf '{}\n' > "$I9/.claude/settings.json"
printf '*.bak\n' > "$I9/.gitignore"
( cd "$I9" && G init -q && G add -A && G commit -qm inst )

OUT9="$(bash "$SK9/kipi-update.sh" --dry-run --only ignoreinst 2>&1 || true)"
echo "$OUT9" | grep -q "ignored by one of your .gitignore" && \
  fail "an instance-ignored skeleton file aborted the config sync: $OUT9"
echo "$OUT9" | grep -q "config sync did not reach a complete committed state" && \
  fail "one ignored file failed the whole config sync: $OUT9"
echo "$OUT9" | grep -qE "Changes vs skeleton|Up to date|final state" || \
  fail "--dry-run produced no model with an instance-ignored skeleton file: $OUT9"

REAL9="$(bash "$SK9/kipi-update.sh" --only ignoreinst 2>&1 || true)"
grep -q "real plugin content" "$I9/plugins/realplugin/content.txt" 2>/dev/null || \
  fail "skipping the ignored file also skipped the trackable plugin content: $REAL9"
[ -z "$(git -C "$I9" status --porcelain)" ] || \
  fail "the ignored file left the instance dirty: $(git -C "$I9" status --porcelain)"
echo "PASS: an instance-ignored skeleton file is skipped, not fatal, and leaves a clean tree"

# --- a TRACKED nested repo (submodule) must stay in the model ---------------
# The nested-repo exclusion above is right for a separate project living under
# a parent path, and wrong for a SUBMODULE. A submodule is a gitlink in the
# parent's index (mode 160000), so dropping it from the model makes git report
# it DELETED, the dirty-tree guard refuses, and the instance never updates.
#
# Scar 2026-07-25: introduced by the exclusion in commit cbd405a and caught on
# Alice, which carries three submodules under q-investigate/tools/. cole-gtm's
# nested instances are UNTRACKED, which is why the same exclusion is correct
# there. Tracked-ness is the line, not nested-ness.
WORK10="$(mktemp -d)"; SK10="$WORK10/skel"; I10="$WORK10/inst"
mkdir -p "$SK10/q-system/.q-system/scripts" "$SK10/q-system/.q-system/state" \
         "$I10/q-system" "$I10/tools/submod" "$I10/projects/separate/q-system"
cp "$SCRIPT" "$SK10/kipi-update.sh"
cp "$ROOT/kipi-update-preserve-scan.py" "$SK10/kipi-update-preserve-scan.py"
cp "$ROOT/q-system/.q-system/scripts/propagation-leak-gate.py" \
   "$SK10/q-system/.q-system/scripts/propagation-leak-gate.py"
cp "$ROOT/q-system/.q-system/scripts/containment-targets.py" \
   "$SK10/q-system/.q-system/scripts/containment-targets.py"
cp "$ROOT/validate-separation.py" "$SK10/validate-separation.py"
cat > "$SK10/q-system/.q-system/state/propagation-leak-baseline.json" <<'BJ'
{"schema_version":1,"blocking_classes":["case_proof_gap","client_identity","dated_interaction","pricing","relationship","source_identity","sourced_interaction"],"classifier_sha256":null,"entries":[]}
BJ
printf 'skeleton v2\n' > "$SK10/q-system/tracked.md"
( cd "$SK10" && G init -q && G add -A -f && G commit -qm skel )
printf '{"instances":[{"name":"submodinst","path":"%s","subtree_prefix":"q-system","type":"subtree"}]}\n' \
  "$I10" > "$SK10/instance-registry.json"
printf 'old\n' > "$I10/q-system/tracked.md"
# the SUBMODULE: its own repo, then added to the parent index as a gitlink
printf 'submodule content\n' > "$I10/tools/submod/file.txt"
( cd "$I10/tools/submod" && G init -q && G add -A && G commit -qm sub )
# the SEPARATE project: its own repo, never added to the parent index
printf 'separate project\n' > "$I10/projects/separate/q-system/tracked.md"
( cd "$I10/projects/separate" && G init -q && G add -A && G commit -qm sep )
( cd "$I10" && G init -q && G add q-system tools/submod && G commit -qm inst )
G -C "$I10" ls-files -s -- tools/submod | grep -q '^160000' || \
  fail "fixture is wrong: tools/submod is not a gitlink"

OUT10="$(bash "$SK10/kipi-update.sh" --dry-run --only submodinst 2>&1 || true)"
echo "$OUT10" | grep -q "dirty working tree" && \
  fail "a TRACKED submodule was excluded from the model and read as deleted: $OUT10"
echo "$OUT10" | grep -qE "Changes vs skeleton|Up to date|final state" || \
  fail "--dry-run produced no model for an instance with a submodule: $OUT10"
echo "$OUT10" | grep -q "skipped 1 nested repositories" || \
  fail "the UNTRACKED separate project should still be skipped, exactly one: $OUT10"
echo "PASS: a tracked submodule stays in the model; an untracked nested project is still skipped"

# --- the symlink guard must skip what the model will not copy ---------------
# The guard walks the WHOLE instance and refuses on a dangling symlink, but the
# model excludes untracked nested repositories, so a broken link inside one can
# never reach the model and cannot leak a write. Refusing on it means one dead
# link in a nested project blocks the PARENT instance forever.
#
# Scar 2026-07-25: gtm-partner is /Users/assafkipnis/projects/cole-gtm, parent
# of five registered instances. personal-brand's canonical files are broken
# links into the dissolved ktlyst-hub, and that refused cole-gtm's dry run --
# an instance blocked by rot in a DIFFERENT repo that this sync never touches.
WORK11="$(mktemp -d)"; SK11="$WORK11/skel"; I11="$WORK11/inst"
mkdir -p "$SK11/q-system/.q-system/scripts" "$SK11/q-system/.q-system/state" \
         "$I11/q-system" "$I11/projects/child/q-system"
cp "$SCRIPT" "$SK11/kipi-update.sh"
cp "$ROOT/kipi-update-preserve-scan.py" "$SK11/kipi-update-preserve-scan.py"
cp "$ROOT/q-system/.q-system/scripts/propagation-leak-gate.py" \
   "$SK11/q-system/.q-system/scripts/propagation-leak-gate.py"
cp "$ROOT/q-system/.q-system/scripts/containment-targets.py" \
   "$SK11/q-system/.q-system/scripts/containment-targets.py"
cp "$ROOT/validate-separation.py" "$SK11/validate-separation.py"
cat > "$SK11/q-system/.q-system/state/propagation-leak-baseline.json" <<'BJ'
{"schema_version":1,"blocking_classes":["case_proof_gap","client_identity","dated_interaction","pricing","relationship","source_identity","sourced_interaction"],"classifier_sha256":null,"entries":[]}
BJ
printf 'skeleton v2\n' > "$SK11/q-system/tracked.md"
( cd "$SK11" && G init -q && G add -A -f && G commit -qm skel )
printf '{"instances":[{"name":"parent11","path":"%s","subtree_prefix":"q-system","type":"subtree"}]}\n' \
  "$I11" > "$SK11/instance-registry.json"
printf 'old\n' > "$I11/q-system/tracked.md"
printf 'child content\n' > "$I11/projects/child/q-system/tracked.md"
( cd "$I11/projects/child" && G init -q && G add -A && G commit -qm child )
( cd "$I11" && G init -q && G add q-system && G commit -qm inst )
# the dead link lives INSIDE the untracked nested repo, which the model skips
ln -s "$WORK11/gone" "$I11/projects/child/q-system/deadlink.md"

OUT11="$(bash "$SK11/kipi-update.sh" --dry-run --only parent11 2>&1 || true)"
echo "$OUT11" | grep -q "unsafe" && \
  fail "a dead link inside a skipped nested repo blocked the parent: $OUT11"
echo "$OUT11" | grep -qE "Changes vs skeleton|Up to date|final state" || \
  fail "--dry-run produced no model for a parent with a broken link in a child: $OUT11"

# and a dead link in the instance's OWN tree must still refuse
ln -s "$WORK11/gone" "$I11/q-system/deadlink.md"
OUT11B="$(bash "$SK11/kipi-update.sh" --dry-run --only parent11 2>&1 || true)"
echo "$OUT11B" | grep -q "unsafe dangling symlink" || \
  fail "a dead link in the instance's own tree was modeled instead of refused: $OUT11B"
echo "PASS: the symlink guard skips paths the model excludes, still refuses in the instance's own tree"

# --- the model rsync and the symlink walk do NOT skip the same set ----------
# The two are built from one scan (model_skip_scan) but are DIFFERENT
# projections of it, and .git is the whole reason. The rsync exclusion carries
# .git, because the model receives .git by `cp -a` on the has-a-.git branch
# instead. The walk's projection does NOT carry it, because a dangling link
# under the instance's own .git/ must still refuse.
#
# Nothing pinned that asymmetry before: `grep -n 'ln -s'` across all 8 updater
# suites planted no link under .git/. So a future "one list for both" cleanup
# would silently delete this refusal and no test would notice. That is exactly
# the collapse this fixture exists to block.
WORK12="$(mktemp -d)"; SK12="$WORK12/skel"; I12="$WORK12/inst"
mkdir -p "$SK12/q-system/.q-system/scripts" "$SK12/q-system/.q-system/state" \
         "$I12/q-system"
cp "$SCRIPT" "$SK12/kipi-update.sh"
cp "$ROOT/kipi-update-preserve-scan.py" "$SK12/kipi-update-preserve-scan.py"
cp "$ROOT/q-system/.q-system/scripts/propagation-leak-gate.py" \
   "$SK12/q-system/.q-system/scripts/propagation-leak-gate.py"
cp "$ROOT/q-system/.q-system/scripts/containment-targets.py" \
   "$SK12/q-system/.q-system/scripts/containment-targets.py"
cp "$ROOT/validate-separation.py" "$SK12/validate-separation.py"
cat > "$SK12/q-system/.q-system/state/propagation-leak-baseline.json" <<'BJ'
{"schema_version":1,"blocking_classes":["case_proof_gap","client_identity","dated_interaction","pricing","relationship","source_identity","sourced_interaction"],"classifier_sha256":null,"entries":[]}
BJ
printf 'skeleton v2\n' > "$SK12/q-system/tracked.md"
( cd "$SK12" && G init -q && G add -A -f && G commit -qm skel )
printf '{"instances":[{"name":"gitlink","path":"%s","subtree_prefix":"q-system","type":"subtree"}]}\n' \
  "$I12" > "$SK12/instance-registry.json"
printf 'old\n' > "$I12/q-system/tracked.md"
( cd "$I12" && G init -q && G add -A && G commit -qm inst )

# control: the same instance models fine with no link at all
OUT12A="$(bash "$SK12/kipi-update.sh" --dry-run --only gitlink 2>&1 || true)"
echo "$OUT12A" | grep -qE "Changes vs skeleton|Up to date|final state" || \
  fail "control instance did not model: $OUT12A"

# the walk must still see, and refuse on, the instance's OWN .git
ln -s "$WORK12/never-existed" "$I12/.git/dead-link"
OUT12B="$(bash "$SK12/kipi-update.sh" --dry-run --only gitlink 2>&1 || true)"
echo "$OUT12B" | grep -q "unsafe dangling symlink" || \
  fail "a dangling symlink under the instance's own .git/ was modeled instead of refused -- the walk's projection has wrongly inherited the rsync's .git exclusion: $OUT12B"
echo "PASS: the walk still vets the instance's own .git/ while the rsync projection excludes it"

# --- a failed run must leave the instance updatable -------------------------
# 24 places give up on an instance. None of them recorded its state first, so a
# failure after the first write left debris that the dirty-tree guard then read
# as founder work -- and EVERY later run refused. One failure took the instance
# out of the fleet until a human deleted files by hand.
#
# Scars: sp-5f2d2a63 (a failed staging left 43 files staged) and sp-e244e821 (a
# failed sync left tracked skeleton files modified). Both fall out of the SAME
# failure, so one fixture covers both: the instance's own pre-commit hook
# rejects the updater's commit, which guarded_commit invokes by design, so
# nothing about the script under test is patched to produce it.
#
# The assertion is on the instance's STATE, not on a log line: run 1 must fail
# and leave `git status --porcelain` empty, and run 2 must then get through.
WORK13="$(mktemp -d)"; SK13="$WORK13/skel"; I13="$WORK13/inst"
mkdir -p "$SK13/q-system/.q-system/scripts" "$SK13/q-system/.q-system/state" \
         "$I13/q-system"
cp "$SCRIPT" "$SK13/kipi-update.sh"
cp "$ROOT/kipi-update-preserve-scan.py" "$SK13/kipi-update-preserve-scan.py"
cp "$ROOT/q-system/.q-system/scripts/propagation-leak-gate.py" \
   "$SK13/q-system/.q-system/scripts/propagation-leak-gate.py"
cp "$ROOT/q-system/.q-system/scripts/containment-targets.py" \
   "$SK13/q-system/.q-system/scripts/containment-targets.py"
cp "$ROOT/validate-separation.py" "$SK13/validate-separation.py"
cat > "$SK13/q-system/.q-system/state/propagation-leak-baseline.json" <<'BJ'
{"schema_version":1,"blocking_classes":["case_proof_gap","client_identity","dated_interaction","pricing","relationship","source_identity","sourced_interaction"],"classifier_sha256":null,"entries":[]}
BJ
printf 'skeleton content v2\n' > "$SK13/q-system/tracked.md"
( cd "$SK13" && G init -q && G add -A -f && G commit -qm skel )
printf '{"instances":[{"name":"stuck","path":"%s","subtree_prefix":"q-system","type":"subtree"}]}\n' \
  "$I13" > "$SK13/instance-registry.json"
printf 'skeleton content v1 (old)\n' > "$I13/q-system/tracked.md"
( cd "$I13" && G init -q && G add -A && G commit -qm inst )
mkdir -p "$I13/.git/hooks"
# The hook also WRITES while the run is in flight, into two instance-owned
# subtrees. Hooks that emit a report or a cache are ordinary, and so are the
# instance's own launchd jobs, so "nothing else writes during a sync" is not a
# property this script may assume. Restore must never delete these: they are
# untracked, so git holds no copy, and the preservation snapshot only covers
# what existed before the rsync. Deleting them would be silent and permanent.
mkdir -p "$I13/q-system/memory" "$I13/q-system/output"
cat > "$I13/.git/hooks/pre-commit" <<'HOOK13'
#!/usr/bin/env bash
printf 'written mid-run\n' > "$(git rev-parse --show-toplevel)/q-system/memory/new-note.md"
printf 'written mid-run\n' > "$(git rev-parse --show-toplevel)/q-system/output/loop-log.md"
echo "instance pre-commit refuses" >&2
exit 1
HOOK13
chmod +x "$I13/.git/hooks/pre-commit"

bash "$SK13/kipi-update.sh" --only stuck >/dev/null 2>&1 || true
# The condition that actually strands an instance is the dirty-tree guard's own:
# staged entries or modified tracked files. Untracked files are deliberately NOT
# part of it -- the guard ignores them, and the assertions below require two of
# them to have survived.
if ! G -C "$I13" diff --cached --quiet || ! G -C "$I13" diff --quiet; then
  fail "a failed run left tracked/staged debris; every later run will refuse at the dirty-tree guard: $(G -C "$I13" status --porcelain | tr '\n' ' ')"
fi
[ -f "$I13/q-system/memory/new-note.md" ] || \
  fail "restore DELETED an instance-owned file written during the run: q-system/memory/new-note.md"
[ -f "$I13/q-system/output/loop-log.md" ] || \
  fail "restore DELETED an instance-owned file written during the run: q-system/output/loop-log.md"

# hook removed, so the ONLY thing that could still block run 2 is run 1's debris
rm -f "$I13/.git/hooks/pre-commit"
OUT13="$(bash "$SK13/kipi-update.sh" --only stuck 2>&1 || true)"
echo "$OUT13" | grep -q "dirty working tree" && \
  fail "run 2 refused at the dirty-tree guard -- the instance is stuck: $OUT13"
grep -q "skeleton content v2" "$I13/q-system/tracked.md" || \
  fail "run 2 did not converge after run 1 failed: $OUT13"
echo "PASS: a failed run leaves the instance clean and a later run still converges"

# --- a founder's own in-progress rebase must survive a failed run -----------
# restore_instance aborts a rebase THIS run started. Deciding which rebases are
# "ours" by assuming the zombie-rebase cleanup already handled the founder's is
# wrong, and the wrong version destroyed real work.
#
# The cleanup tests "$path/.git/rebase-merge" as a DIRECTORY. In a linked
# worktree .git is a FILE, so that test is ENOTDIR and the cleanup silently
# does nothing -- while `rebase -i` paused at `edit` leaves a CLEAN index and
# worktree, so the dirty-tree guard passes and the run proceeds with the
# founder's rebase still open. Aborting it discarded their work AND rewound the
# sync commit the same run had just landed.
#
# The instance here is a linked worktree for exactly that reason.
WORK14="$(mktemp -d)"; SK14="$WORK14/skel"; HOST14="$WORK14/host"; I14="$WORK14/wt"
mkdir -p "$SK14/q-system/.q-system/scripts" "$SK14/q-system/.q-system/state" "$HOST14"
cp "$SCRIPT" "$SK14/kipi-update.sh"
cp "$ROOT/kipi-update-preserve-scan.py" "$SK14/kipi-update-preserve-scan.py"
cp "$ROOT/q-system/.q-system/scripts/propagation-leak-gate.py" \
   "$SK14/q-system/.q-system/scripts/propagation-leak-gate.py"
cp "$ROOT/q-system/.q-system/scripts/containment-targets.py" \
   "$SK14/q-system/.q-system/scripts/containment-targets.py"
cp "$ROOT/validate-separation.py" "$SK14/validate-separation.py"
cat > "$SK14/q-system/.q-system/state/propagation-leak-baseline.json" <<'BJ'
{"schema_version":1,"blocking_classes":["case_proof_gap","client_identity","dated_interaction","pricing","relationship","source_identity","sourced_interaction"],"classifier_sha256":null,"entries":[]}
BJ
printf 'skeleton content v2\n' > "$SK14/q-system/tracked.md"
( cd "$SK14" && G init -q && G add -A -f && G commit -qm skel )

# host repo, then the instance as a LINKED WORKTREE of it
( cd "$HOST14" && G init -q && mkdir -p q-system &&
  printf 'old\n' > q-system/tracked.md && G add -A && G commit -qm c1 &&
  printf 'old2\n' > q-system/tracked.md && G add -A && G commit -qm c2 &&
  G branch work && G worktree add -q "$I14" work ) >/dev/null 2>&1
printf '{"instances":[{"name":"wt","path":"%s","subtree_prefix":"q-system","type":"subtree"}]}\n' \
  "$I14" > "$SK14/instance-registry.json"
[ -f "$I14/.git" ] || fail "fixture is wrong: the instance's .git is not a FILE (not a linked worktree)"

# the founder's own rebase, paused at `edit`, leaving a clean tree
( cd "$I14" && GIT_SEQUENCE_EDITOR="sed -i.bak -e '1s/^pick/edit/'" \
  G -c core.editor=true rebase -i HEAD~1 ) >/dev/null 2>&1 || true
instance_rebase_dir() { G -C "$I14" rev-parse --path-format=absolute --git-path rebase-merge 2>/dev/null; }
[ -d "$(instance_rebase_dir)" ] || fail "fixture is wrong: no rebase is in flight in the worktree"
WORKTIP_BEFORE="$(G -C "$I14" rev-parse HEAD)"

# make the run fail after it has written and committed
mkdir -p "$I14/.git-hooks-x"
G -C "$I14" config core.hooksPath "$I14/.git-hooks-x"
printf '#!/usr/bin/env bash\nexit 1\n' > "$I14/.git-hooks-x/pre-commit"
chmod +x "$I14/.git-hooks-x/pre-commit"

bash "$SK14/kipi-update.sh" --only wt >/dev/null 2>&1 || true

[ -d "$(instance_rebase_dir)" ] || \
  fail "a failed run ABORTED the founder's own in-progress rebase (linked worktree); their work is gone"
echo "PASS: a founder's in-progress rebase survives a failed run in a linked worktree"

# --- identical residue under .claude/ is this sync's own output -------------
# The q-system collision guard already excuses an untracked file byte-identical
# to what the skeleton is about to write: that is this sync's half-finished
# work from a run that died after writing and before committing. Treating it as
# founder WIP is how sp-5f2d2a63 bricked an instance -- every later run refused
# and the only recovery was deleting files by hand.
#
# The .claude/ + plugins/ guard did not have that carve-out (sp-72bd8029), so
# the same interrupted run bricked the config sync instead. Both halves are
# asserted here: identical residue proceeds, and content that DIFFERS is still
# refused, because the carve-out must not become a hole that eats real work.
WORK15="$(mktemp -d)"; SK15="$WORK15/skel"; I15="$WORK15/inst"
mkdir -p "$SK15/q-system/.q-system/scripts" "$SK15/q-system/.q-system/state" \
         "$SK15/.claude/rules" "$I15/q-system" "$I15/.claude/rules"
cp "$SCRIPT" "$SK15/kipi-update.sh"
cp "$ROOT/kipi-update-preserve-scan.py" "$SK15/kipi-update-preserve-scan.py"
cp "$ROOT/q-system/.q-system/scripts/propagation-leak-gate.py" \
   "$SK15/q-system/.q-system/scripts/propagation-leak-gate.py"
cp "$ROOT/q-system/.q-system/scripts/containment-targets.py" \
   "$SK15/q-system/.q-system/scripts/containment-targets.py"
cp "$ROOT/validate-separation.py" "$SK15/validate-separation.py"
cp "$ROOT/settings-template.json" "$SK15/settings-template.json" 2>/dev/null || \
  printf '{}\n' > "$SK15/settings-template.json"
cp "$ROOT/kipi-settings-merge.py" "$SK15/kipi-settings-merge.py" 2>/dev/null || true
cat > "$SK15/q-system/.q-system/state/propagation-leak-baseline.json" <<'BJ'
{"schema_version":1,"blocking_classes":["case_proof_gap","client_identity","dated_interaction","pricing","relationship","source_identity","sourced_interaction"],"classifier_sha256":null,"entries":[]}
BJ
printf 'skeleton v2\n' > "$SK15/q-system/tracked.md"
printf 'rule content from the skeleton\n' > "$SK15/.claude/rules/shared.md"
( cd "$SK15" && G init -q && G add -A -f && G commit -qm skel )
printf '{"instances":[{"name":"resid","path":"%s","subtree_prefix":"q-system","type":"subtree"}]}\n' \
  "$I15" > "$SK15/instance-registry.json"
printf 'old\n' > "$I15/q-system/tracked.md"
printf '{}\n' > "$I15/.claude/settings.json"
( cd "$I15" && G init -q && G add -A && G commit -qm inst )

# Order matters: the DIFFERING case runs first, while the file is still
# untracked. A successful sync commits it, after which overwriting it is
# tracked-modified and trips the dirty-tree guard instead -- a different guard
# and not what this fixture is about.
printf 'MY OWN UNFINISHED WORK\n' > "$I15/.claude/rules/shared.md"
OUT15B="$(bash "$SK15/kipi-update.sh" --only resid 2>&1 || true)"
echo "$OUT15B" | grep -q "untracked WIP collides with managed config" || \
  fail "genuine untracked founder work under .claude/ was NOT protected: $OUT15B"

# That run refused before writing, so the file is still untracked. Replace it
# with this sync's own output -- byte-identical to what the skeleton writes --
# and the same run must now get through.
cp "$SK15/.claude/rules/shared.md" "$I15/.claude/rules/shared.md"
OUT15="$(bash "$SK15/kipi-update.sh" --only resid 2>&1 || true)"
echo "$OUT15" | grep -q "untracked WIP collides with managed config" && \
  fail "identical config residue was read as founder WIP; an interrupted sync bricks the config path forever: $OUT15"
echo "$OUT15" | grep -q "Config synced" || \
  fail "the config sync did not complete over its own identical residue: $OUT15"

# And a DOT-named directory under plugins/ is not a plugin. `managed_plugin_names`
# globs plugins/*/ which never matches one, so the stager and the copy loop both
# ignore it -- nothing is ever rsynced there. A second, independent [ -d ] test
# used to disagree and call it managed, so the guard refused the whole sync over
# an untracked file in a directory the sync cannot touch (sp-7ff28101).
mkdir -p "$SK15/plugins/.hidden" "$I15/plugins/.hidden"
printf 'hidden\n' > "$SK15/plugins/.hidden/h.md"
( cd "$SK15" && G add -A -f && G commit -qm dotdir ) >/dev/null 2>&1
printf 'incidental\n' > "$I15/plugins/.hidden/wip.md"
OUT15C="$(bash "$SK15/kipi-update.sh" --only resid 2>&1 || true)"
echo "$OUT15C" | grep -q "untracked WIP collides with managed config: plugins/.hidden" && \
  fail "refused over a dot-named plugin dir the sync never writes: $OUT15C"
echo "PASS: differing config content is protected; identical residue and dot-named dirs are not"
