#!/usr/bin/env bash
# Rollback across updater failure phases. Pairs with issue fcu-rollback-matrix.
#
# The updater can die at any phase (preservation, sync, settings, plugins,
# commit) and each phase leaves a DIFFERENT amount of the instance rewritten:
# nothing at all, files in the worktree, files staged, or a finished commit. A
# rollback that guesses -- reverts the newest sync-looking commit, or restores
# everything the commit touched -- either misses the damage or buries founder
# work that landed after the update. So rollback is receipt-driven: it restores
# ONLY the paths the receipt lists, and refuses outright when one of those paths
# has been edited since the update.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
RB="$ROOT/kipi-rollback.sh"

# The script under test runs bare git commands that need a committer identity.
# CI runners have none (scar: test-kipi-rollback.sh, 2026-07-23).
export GIT_AUTHOR_NAME=test GIT_AUTHOR_EMAIL=t@t.t
export GIT_COMMITTER_NAME=test GIT_COMMITTER_EMAIL=t@t.t

fail() { echo "FAIL: $1" >&2; exit 1; }
G() { git -c user.email=t@t.t -c user.name=test -c commit.gpgsign=false "$@"; }

WORK="$(mktemp -d)"
trap 'rm -r -- "$WORK"' EXIT

# Exact content, not a substring: a file holding the expected marker PLUS wrong
# content would sail through a grep.
exact() {
  local path="$1" want="$2" why="$3"
  [ -f "$path" ] || fail "$why: $path is missing"
  [ "$(cat "$path")" = "$want" ] ||
    fail "$why: $path holds $(cat "$path") not $want"
}

# HEAD + full status + every file's hash and mode. One value that answers
# "did the rollback change anything at all?"
state_digest() {
  python3 - "$1" <<'PY'
import hashlib
import os
import pathlib
import subprocess
import sys

root = pathlib.Path(sys.argv[1])
digest = hashlib.sha256()
for command in (["rev-parse", "HEAD"], ["status", "--porcelain", "--untracked-files=all"]):
    result = subprocess.run(["git", "-C", str(root)] + command, capture_output=True)
    digest.update(result.stdout)
for current, directories, files in os.walk(root):
    directories[:] = sorted(name for name in directories if name != ".git")
    for name in sorted(files):
        candidate = pathlib.Path(current, name)
        digest.update(str(candidate.relative_to(root)).encode() + b"\0")
        digest.update(f"{candidate.stat().st_mode & 0o7777:04o}".encode() + b"\0")
        digest.update(candidate.read_bytes() + b"\0")
print(digest.hexdigest())
PY
}

mk_instance() {
  local dir="$1"
  mkdir -p "$dir"
  (
    cd "$dir"
    G init -q -b main
    mkdir -p q-system/my-project q-system/canonical
    printf 'skeleton-v1\n' > q-system/CLAUDE.md
    printf 'retired\n' > q-system/legacy.md
    printf 'state-v1\n' > q-system/my-project/current-state.md
    printf 'dec-v1\n' > q-system/canonical/decisions.md
    G add -A
    G commit -qm baseline
  )
}

write_synced_files() {
  local dir="$1"
  printf 'skeleton-v2\n' > "$dir/q-system/CLAUDE.md"
  printf 'brand new\n' > "$dir/q-system/added.md"
  rm -f "$dir/q-system/legacy.md"
}

apply_sync() {
  local dir="$1"
  write_synced_files "$dir"
  (
    cd "$dir"
    G add -A
    G commit -qm "chore: sync q-system from skeleton 2026-07-25"
  )
}

mk_registry() {
  python3 -c "
import json, sys
json.dump({'instances': [{'name': sys.argv[2], 'path': sys.argv[3],
                          'type': 'subtree', 'subtree_prefix': 'q-system'}]},
          open(sys.argv[1], 'w'))
" "$1" "$2" "$3"
}

# receipt, instance, before-head, after-head, status, phase, eligible, kind
write_receipt() {
  python3 - "$@" <<'PY'
import hashlib
import json
import pathlib
import sys

(receipt_path, instance, before_head, after_head,
 status, phase, eligible, kind) = sys.argv[1:9]
root = pathlib.Path(instance)


def frozen(value):
    return hashlib.sha256(value.encode()).hexdigest()


if kind.startswith("mode-change"):
    # mode-change-bad claims a pre-update 0755 that git never recorded, while
    # still matching the on-disk mode so it gets past the drift check.
    modes = ("0755", "0644") if kind == "mode-change-bad" else ("0644", "0755")
    changes = {
        "q-system/CLAUDE.md": {
            "operation": "mode-change",
            "content_sha256": frozen("skeleton-v1\n"),
            "before_mode": modes[0],
            "after_mode": modes[1],
        }
    }
else:
    changes = {
        "q-system/CLAUDE.md": {
            "operation": "update",
            "before_sha256": frozen("skeleton-v1\n"),
            "after_sha256": frozen("skeleton-v2\n"),
        },
        "q-system/added.md": {
            "operation": "create",
            "before_sha256": None,
            "after_sha256": frozen("brand new\n"),
        },
        "q-system/legacy.md": {
            "operation": "delete",
            "before_sha256": frozen("retired\n"),
            "after_sha256": None,
        },
    }

if eligible == "true":
    rollback = {
        "eligible": True,
        "target_receipt_id": None,
        "required_head": after_head,
        "required_worktree_sha256": frozen(after_head),
        "refusal_reason": None,
        "recovery_artifact": {
            "kind": "snapshot",
            "path": "/tmp/kipi-rollback-fixture.tar",
            "sha256": frozen("snapshot"),
        },
    }
else:
    rollback = {
        "eligible": False,
        "target_receipt_id": None,
        "required_head": None,
        "required_worktree_sha256": None,
        "refusal_reason": f"updater stopped in the {phase} phase with status {status}",
        "recovery_artifact": None,
    }

receipt = {
    "schema_version": 1,
    "receipt_id": "ur-" + hashlib.sha256(receipt_path.encode()).hexdigest()[:16],
    "producer": "updater",
    "instance": {"name": "fixture", "path": str(root.resolve()), "type": "subtree"},
    "mode": "apply",
    "phase": phase,
    "status": status,
    "created_at": "2026-07-25T12:00:00Z",
    "before": {"head": before_head, "worktree_sha256": frozen(before_head)},
    "after": {"head": after_head, "worktree_sha256": frozen(after_head)},
    "changes": changes if status != "skipped" else {},
    "rollback": rollback,
}
path = pathlib.Path(receipt_path)
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
}

# name, partial-state, status, phase, eligible[, kind] -> echoes the case dir.
# The partial state is what the updater ACTUALLY left behind when it died in
# that phase, so each row models a different instance shape.
prepare_case() {
  local case_name="$1" partial="$2" status="$3" phase="$4" eligible="$5"
  local kind="${6:-standard}"
  local dir="$WORK/$case_name"
  mk_instance "$dir/instance"
  local before_head after_head
  before_head="$(git -C "$dir/instance" rev-parse HEAD)"
  after_head="$before_head"
  case "$partial" in
    none) ;;
    applied)
      apply_sync "$dir/instance"
      after_head="$(git -C "$dir/instance" rev-parse HEAD)"
      ;;
    worktree)
      write_synced_files "$dir/instance"
      ;;
    staged)
      write_synced_files "$dir/instance"
      ( cd "$dir/instance" && G add -A )
      ;;
    *) fail "unknown partial state: $partial" ;;
  esac
  mk_registry "$dir/registry.json" fixture "$dir/instance"
  write_receipt "$dir/receipts/receipt.json" "$dir/instance" \
    "$before_head" "$after_head" "$status" "$phase" "$eligible" "$kind"
  echo "$dir"
}

run_rollback() {
  local dir="$1"
  set +e
  KIPI_REGISTRY="$dir/registry.json" KIPI_UPDATER_RECEIPT_DIR="$dir/receipts" \
    bash "$RB" fixture > "$dir/output.log" 2>&1
  local rc=$?
  set -e
  echo "$rc"
}

assert_synced_state() {
  local dir="$1" why="$2"
  exact "$dir/instance/q-system/CLAUDE.md" 'skeleton-v2' "$why"
  exact "$dir/instance/q-system/added.md" 'brand new' "$why"
  [ ! -f "$dir/instance/q-system/legacy.md" ] || fail "$why: legacy.md was restored"
}

assert_rolled_back() {
  local dir="$1" why="$2"
  exact "$dir/instance/q-system/CLAUDE.md" 'skeleton-v1' "$why"
  [ ! -f "$dir/instance/q-system/added.md" ] || fail "$why: added.md was not removed"
  exact "$dir/instance/q-system/legacy.md" 'retired' "$why"
}

assert_owned_state_untouched() {
  local dir="$1" why="$2"
  exact "$dir/instance/q-system/my-project/current-state.md" 'state-v1' "$why"
  exact "$dir/instance/q-system/canonical/decisions.md" 'dec-v1' "$why"
}

echo "Phase-injection matrix (each phase leaves its own partial state):"
while IFS='|' read -r case_name partial status phase marker; do
  [ -z "$case_name" ] && continue
  DIR="$(prepare_case "$case_name" "$partial" "$status" "$phase" false)"
  BEFORE_DIGEST="$(state_digest "$DIR/instance")"
  RC="$(run_rollback "$DIR")"
  [ "$RC" -ne 0 ] || fail "$case_name: partial $phase update returned success"
  grep -q "$marker" "$DIR/output.log" ||
    fail "$case_name: expected refusal '$marker', got: $(cat "$DIR/output.log")"
  [ "$(state_digest "$DIR/instance")" = "$BEFORE_DIGEST" ] ||
    fail "$case_name: refused rollback still changed the instance"
  echo "  refused: $phase / $status / left-as $partial"
done <<'MATRIX'
phase-preservation|none|failed|preservation|preservation phase
phase-sync|worktree|failed|sync|REFUSED (dirty working tree
phase-settings|worktree|failed|settings|REFUSED (dirty working tree
phase-plugins|worktree|failed|plugins|REFUSED (dirty working tree
phase-commit|staged|failed|commit|REFUSED (dirty working tree
phase-started|applied|started|sync|sync phase
phase-refused|applied|refused|preservation|preservation phase
MATRIX

echo "Completed update rolls back exactly the receipt-listed paths:"
DIR="$(prepare_case complete applied complete complete true)"
printf 'later founder work\n' > "$DIR/instance/q-system/my-project/notes.md"
( cd "$DIR/instance" && G add -A && G commit -qm "founder work after the update" )
[ "$(run_rollback "$DIR")" = "0" ] || {
  cat "$DIR/output.log" >&2
  fail "eligible rollback failed"
}
assert_rolled_back "$DIR" complete
assert_owned_state_untouched "$DIR" complete
exact "$DIR/instance/q-system/my-project/notes.md" 'later founder work' complete
[ -z "$(git -C "$DIR/instance" status --porcelain)" ] ||
  fail "complete: rollback left the instance dirty"
echo "  rolled back 3 receipt-listed paths, later founder commit intact"

echo "Later edit to a receipt-listed path refuses:"
for edited in q-system/CLAUDE.md q-system/added.md; do
  DIR="$(prepare_case "edited-$(basename "$edited")" applied complete complete true)"
  printf 'founder edited this after the update\n' > "$DIR/instance/$edited"
  ( cd "$DIR/instance" && G add -A && G commit -qm "founder edit on an updater path" )
  BEFORE_DIGEST="$(state_digest "$DIR/instance")"
  RC="$(run_rollback "$DIR")"
  [ "$RC" -ne 0 ] || fail "later edit to $edited returned success"
  grep -q "REFUSED" "$DIR/output.log" || fail "later edit to $edited was not refused"
  grep -q "$edited" "$DIR/output.log" || fail "later-edit refusal did not name $edited"
  [ "$(state_digest "$DIR/instance")" = "$BEFORE_DIGEST" ] ||
    fail "later-edit refusal still changed the instance"
  echo "  refused: later edit to $edited"
done

echo "A deleted path restored by the founder refuses:"
DIR="$(prepare_case edited-legacy applied complete complete true)"
printf 'founder brought this back\n' > "$DIR/instance/q-system/legacy.md"
( cd "$DIR/instance" && G add -A && G commit -qm "founder restored a deleted path" )
BEFORE_DIGEST="$(state_digest "$DIR/instance")"
RC="$(run_rollback "$DIR")"
[ "$RC" -ne 0 ] || fail "restored deleted path returned success"
grep -q 'q-system/legacy.md' "$DIR/output.log" ||
  fail "refusal did not name the restored deleted path"
[ "$(state_digest "$DIR/instance")" = "$BEFORE_DIGEST" ] ||
  fail "refusal still changed the instance"
echo "  refused: founder restored q-system/legacy.md"

echo "An UNTRACKED file at a receipt-listed path refuses:"
DIR="$(prepare_case untracked applied complete complete true)"
(
  cd "$DIR/instance"
  G rm -q --cached q-system/added.md
  G commit -qm "founder untracked a synced path"
)
BEFORE_DIGEST="$(state_digest "$DIR/instance")"
RC="$(run_rollback "$DIR")"
[ "$RC" -ne 0 ] || fail "untracked listed path returned success"
grep -q 'uncommitted state' "$DIR/output.log" ||
  fail "untracked listed path was not refused: $(cat "$DIR/output.log")"
exact "$DIR/instance/q-system/added.md" 'brand new' untracked
[ "$(state_digest "$DIR/instance")" = "$BEFORE_DIGEST" ] ||
  fail "untracked refusal still changed the instance"
echo "  refused: q-system/added.md is untracked"

echo "Dirty working tree refuses before anything is read:"
DIR="$(prepare_case dirty applied complete complete true)"
printf 'uncommitted\n' >> "$DIR/instance/q-system/my-project/current-state.md"
RC="$(run_rollback "$DIR")"
[ "$RC" -ne 0 ] || fail "dirty tree refusal still exited 0"
grep -q 'REFUSED (dirty working tree' "$DIR/output.log" ||
  fail "dirty tree was not refused"
assert_synced_state "$DIR" dirty
echo "  refused: dirty working tree"

echo "A damaged receipt store refuses instead of falling back to an older one:"
DIR="$(prepare_case damaged applied complete complete true)"
printf 'not json at all\n' > "$DIR/receipts/zz-newer.json"
BEFORE_DIGEST="$(state_digest "$DIR/instance")"
RC="$(run_rollback "$DIR")"
[ "$RC" -ne 0 ] || fail "damaged receipt store returned success"
grep -q 'receipt store is damaged' "$DIR/output.log" ||
  fail "damaged receipt store was not refused: $(cat "$DIR/output.log")"
[ "$(state_digest "$DIR/instance")" = "$BEFORE_DIGEST" ] ||
  fail "damaged receipt store still changed the instance"
echo "  refused: unreadable receipt in the store"

echo "File modes are part of the restore, not just content:"
MODE_DIR="$WORK/mode-exec"
mk_instance "$MODE_DIR/instance"
( cd "$MODE_DIR/instance" && chmod +x q-system/CLAUDE.md && G add -A &&
  G commit -qm "executable baseline" )
MODE_BEFORE="$(git -C "$MODE_DIR/instance" rev-parse HEAD)"
apply_sync "$MODE_DIR/instance"
chmod -x "$MODE_DIR/instance/q-system/CLAUDE.md"
( cd "$MODE_DIR/instance" && G add -A && G commit -qm "sync dropped the exec bit" )
MODE_AFTER="$(git -C "$MODE_DIR/instance" rev-parse HEAD)"
mk_registry "$MODE_DIR/registry.json" fixture "$MODE_DIR/instance"
write_receipt "$MODE_DIR/receipts/receipt.json" "$MODE_DIR/instance" \
  "$MODE_BEFORE" "$MODE_AFTER" complete complete true standard
[ "$(run_rollback "$MODE_DIR")" = "0" ] || {
  cat "$MODE_DIR/output.log" >&2
  fail "mode-restoring rollback failed"
}
[ -x "$MODE_DIR/instance/q-system/CLAUDE.md" ] ||
  fail "rollback restored content but not the executable bit"
echo "  restored the executable bit from the pre-update commit"

echo "A founder permission change survives the rollback:"
PERM_DIR="$WORK/perm"
mk_instance "$PERM_DIR/instance"
PERM_BEFORE="$(git -C "$PERM_DIR/instance" rev-parse HEAD)"
apply_sync "$PERM_DIR/instance"
PERM_AFTER="$(git -C "$PERM_DIR/instance" rev-parse HEAD)"
chmod 0600 "$PERM_DIR/instance/q-system/CLAUDE.md"
mk_registry "$PERM_DIR/registry.json" fixture "$PERM_DIR/instance"
write_receipt "$PERM_DIR/receipts/receipt.json" "$PERM_DIR/instance" \
  "$PERM_BEFORE" "$PERM_AFTER" complete complete true standard
[ "$(run_rollback "$PERM_DIR")" = "0" ] || {
  cat "$PERM_DIR/output.log" >&2
  fail "rollback over a founder permission change failed"
}
assert_rolled_back "$PERM_DIR" perm
PERM_NOW="$(python3 -c "
import os, sys
print(f'{os.stat(sys.argv[1]).st_mode & 0o777:04o}')
" "$PERM_DIR/instance/q-system/CLAUDE.md")"
[ "$PERM_NOW" = "0600" ] ||
  fail "rollback buried the founder permission change (mode is $PERM_NOW, want 0600)"
echo "  restored content, kept the founder 0600 permission"

echo "A mode-change receipt is checked against git before it is applied:"
MC_DIR="$WORK/mode-change"
mk_instance "$MC_DIR/instance"
MC_BEFORE="$(git -C "$MC_DIR/instance" rev-parse HEAD)"
( cd "$MC_DIR/instance" && chmod +x q-system/CLAUDE.md && G add -A &&
  G commit -qm "chore: sync q-system from skeleton 2026-07-25" )
MC_AFTER="$(git -C "$MC_DIR/instance" rev-parse HEAD)"
mk_registry "$MC_DIR/registry.json" fixture "$MC_DIR/instance"
write_receipt "$MC_DIR/receipts/receipt.json" "$MC_DIR/instance" \
  "$MC_BEFORE" "$MC_AFTER" complete complete true mode-change
[ "$(run_rollback "$MC_DIR")" = "0" ] || {
  cat "$MC_DIR/output.log" >&2
  fail "mode-change rollback failed"
}
[ ! -x "$MC_DIR/instance/q-system/CLAUDE.md" ] ||
  fail "mode-change rollback did not restore the pre-update mode"
exact "$MC_DIR/instance/q-system/CLAUDE.md" 'skeleton-v1' mode-change
echo "  restored the pre-update mode"

echo "A mode-change receipt git disagrees with is refused:"
MCB_DIR="$WORK/mode-change-bad"
mk_instance "$MCB_DIR/instance"
MCB_BEFORE="$(git -C "$MCB_DIR/instance" rev-parse HEAD)"
printf 'skeleton-v1\n' > "$MCB_DIR/instance/q-system/notes.md"
( cd "$MCB_DIR/instance" && G add -A && G commit -qm "no mode change at all" )
MCB_AFTER="$(git -C "$MCB_DIR/instance" rev-parse HEAD)"
mk_registry "$MCB_DIR/registry.json" fixture "$MCB_DIR/instance"
# The receipt claims CLAUDE.md was 0755 before the update; git says 0644. The
# on-disk 0644 matches the receipt's after_mode, so this gets past drift and
# has to be caught by checking the receipt against git.
write_receipt "$MCB_DIR/receipts/receipt.json" "$MCB_DIR/instance" \
  "$MCB_BEFORE" "$MCB_AFTER" complete complete true mode-change-bad
BEFORE_DIGEST="$(state_digest "$MCB_DIR/instance")"
RC="$(run_rollback "$MCB_DIR")"
[ "$RC" -ne 0 ] || fail "a mode-change receipt git disagrees with returned success"
grep -q 'disagrees with' "$MCB_DIR/output.log" ||
  fail "inconsistent mode-change was not refused: $(cat "$MCB_DIR/output.log")"
[ "$(state_digest "$MCB_DIR/instance")" = "$BEFORE_DIGEST" ] ||
  fail "inconsistent mode-change refusal still changed the instance"
echo "  refused: receipt mode disagrees with git"

echo "A rejected commit unwinds every restored path:"
DIR="$(prepare_case unwind applied complete complete true)"
printf '#!/usr/bin/env bash\nexit 1\n' > "$DIR/instance/.git/hooks/pre-commit"
chmod +x "$DIR/instance/.git/hooks/pre-commit"
BEFORE_DIGEST="$(state_digest "$DIR/instance")"
RC="$(run_rollback "$DIR")"
[ "$RC" -ne 0 ] || fail "a rejected rollback commit returned success"
grep -q 'instance left as it was' "$DIR/output.log" ||
  fail "rejected commit did not report an unwind: $(cat "$DIR/output.log")"
assert_synced_state "$DIR" unwind
[ -z "$(git -C "$DIR/instance" status --porcelain)" ] ||
  fail "rejected commit left the instance dirty (index or worktree not unwound)"
[ "$(state_digest "$DIR/instance")" = "$BEFORE_DIGEST" ] ||
  fail "rejected commit left the instance changed"
echo "  unwound the worktree and the index"

echo "No receipt keeps the legacy sync-commit revert:"
DIR="$(prepare_case no-receipt applied complete complete true)"
rm -f "$DIR/receipts/receipt.json"
[ "$(run_rollback "$DIR")" = "0" ] || {
  cat "$DIR/output.log" >&2
  fail "legacy revert path regressed"
}
assert_rolled_back "$DIR" no-receipt
assert_owned_state_untouched "$DIR" no-receipt
echo "  legacy revert path intact"

if [ "${1:-}" = "--assert-later-edit-refusal" ]; then
  echo "PASS: rollback refuses over every later edit to a receipt-listed path"
else
  echo "PASS: rollback restores only receipt-listed changes across every failure phase"
fi
