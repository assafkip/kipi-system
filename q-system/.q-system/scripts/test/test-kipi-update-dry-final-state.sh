#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
WORK="$(mktemp -d)"
SKELETON="$WORK/skeleton"
INSTANCE_MAIN="$WORK/instance-main"
INSTANCE="$WORK/instance"
ATTACHED_MAIN="$WORK/attached-main"
ATTACHED_INSTANCE="$WORK/attached-instance"
DIRECT_ORIGIN="$WORK/direct-origin.git"
DIRECT_SEED="$WORK/direct-seed"
DIRECT_INSTANCE="$WORK/direct-instance"
TEST_TMP="$WORK/tmp"

cleanup() {
  rm -r -- "$WORK"
}
trap cleanup EXIT

if [ "$#" -gt 1 ] ||
    { [ "$#" -eq 1 ] && [ "$1" != "--assert-byte-equivalent" ]; }; then
  echo "usage: $0 [--assert-byte-equivalent]" >&2
  exit 2
fi

fail() {
  echo "FAIL: $1" >&2
  exit 1
}

git_test() {
  git -c user.email=test@example.com -c user.name=test \
    -c commit.gpgsign=false "$@"
}

worktree_digest() {
  python3 - "$1" <<'PY'
import hashlib
import os
import pathlib
import stat
import sys

root = pathlib.Path(sys.argv[1])
digest = hashlib.sha256()
for current, directories, files in os.walk(root, followlinks=False):
    directories[:] = sorted(name for name in directories if name != ".git")
    for name in sorted(directories + files):
        candidate = pathlib.Path(current, name)
        if candidate == root / ".git":
            continue
        relative = candidate.relative_to(root).as_posix()
        metadata = candidate.lstat()
        digest.update(relative.encode("utf-8", "surrogateescape") + b"\0")
        digest.update(f"{stat.S_IFMT(metadata.st_mode):o}:{stat.S_IMODE(metadata.st_mode):o}".encode() + b"\0")
        if stat.S_ISLNK(metadata.st_mode):
            digest.update(os.readlink(candidate).encode("utf-8", "surrogateescape"))
        elif stat.S_ISREG(metadata.st_mode):
            with candidate.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
        digest.update(b"\0")
print(digest.hexdigest())
PY
}

modeled_diff() {
  local output="$1"
  local instance_name="$2"
  printf '%s\n' "$output" |
    awk -v instance_name="$instance_name" '
      $0 ~ "MODELED_FINAL_DIFF_BEGIN " instance_name "$" {
        capture = 1
        next
      }
      $0 ~ "MODELED_FINAL_DIFF_END " instance_name "$" && capture {
        exit
      }
      capture { print }
    ' |
    sort
}

modeled_value() {
  local output="$1"
  local key="$2"
  local instance_name="$3"
  printf '%s\n' "$output" |
    awk -v key="$key" -v instance_name="$instance_name" '
      $1 == key && $2 == instance_name { print $3; exit }
    '
}

mkdir -p \
  "$SKELETON/q-system" \
  "$SKELETON/q-system/.q-system/scripts" \
  "$SKELETON/.claude/agents" \
  "$SKELETON/.claude/rules" \
  "$SKELETON/.claude/output-styles" \
  "$SKELETON/plugins/demo" \
  "$INSTANCE_MAIN/q-system/canonical" \
  "$INSTANCE_MAIN/.claude" \
  "$INSTANCE_MAIN/plugins/demo" \
  "$TEST_TMP"

cp "$ROOT/kipi-update.sh" "$SKELETON/kipi-update.sh"
cp "$ROOT/kipi-update-preserve-scan.py" \
  "$SKELETON/kipi-update-preserve-scan.py"
cp "$ROOT/kipi-update-deletion-guard.py" \
  "$SKELETON/kipi-update-deletion-guard.py"
cp "$ROOT/kipi-update-deletion-guard.py" \
  "$SKELETON/kipi-update-deletion-guard.py"
cp "$ROOT/kipi-settings-merge.py" "$SKELETON/kipi-settings-merge.py"
# A valid skeleton ships the propagation leak gate: kipi-update.sh is
# fail-closed on it, so a fixture without it aborts before any sync.
mkdir -p "$SKELETON/q-system/.q-system/scripts" "$SKELETON/q-system/.q-system/state"
cp "$ROOT/q-system/.q-system/scripts/propagation-leak-gate.py" \
   "$SKELETON/q-system/.q-system/scripts/propagation-leak-gate.py"
cp "$ROOT/q-system/.q-system/scripts/containment-targets.py" \
   "$SKELETON/q-system/.q-system/scripts/containment-targets.py"
cp "$ROOT/validate-separation.py" "$SKELETON/validate-separation.py"
# NOT the repo's committed baseline: that one is ARMED and its permits
# describe THIS repo's content, so loading it against a synthetic skeleton
# refuses ("a permit cannot exceed what was reviewed"). A fixture gets its
# own unarmed baseline.
cat > "$SKELETON/q-system/.q-system/state/propagation-leak-baseline.json" <<'BASELINE_JSON'
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

printf 'skeleton version two content\n' > "$SKELETON/q-system/tracked.md"
printf 'raise SystemExit(0)\n' \
  > "$SKELETON/q-system/.q-system/scripts/capability-gate.py"
printf 'agent v2\n' > "$SKELETON/.claude/agents/example.md"
printf 'rule v2\n' > "$SKELETON/.claude/rules/example.md"
printf 'style v2\n' > "$SKELETON/.claude/output-styles/example.md"
printf 'plugin version two content\n' > "$SKELETON/plugins/demo/content.txt"
printf '{"permissions":{"allow":["Read"]},"hooks":{}}\n' \
  > "$SKELETON/settings-template.json"

(
  cd "$SKELETON"
  git_test init -q
  git_test add q-system
  git_test commit -qm skeleton
)
printf \
  '{"instances":[{"name":"fixture","path":"%s","subtree_prefix":"q-system","type":"subtree"},{"name":"attached","path":"%s","subtree_prefix":"q-system","type":"subtree"},{"name":"direct","path":"%s","subtree_prefix":"q-system","type":"direct-clone"}]}\n' \
  "$INSTANCE" "$ATTACHED_INSTANCE" "$DIRECT_INSTANCE" \
  > "$SKELETON/instance-registry.json"

printf 'old\n' > "$INSTANCE_MAIN/q-system/tracked.md"
printf 'private canonical\n' > "$INSTANCE_MAIN/q-system/canonical/private.md"
printf 'q-system/ignored-state.txt\n' > "$INSTANCE_MAIN/.gitignore"
printf '{"permissions":{"allow":["Write"]},"hooks":{}}\n' \
  > "$INSTANCE_MAIN/.claude/settings.json"
printf 'old\n' > "$INSTANCE_MAIN/plugins/demo/content.txt"
(
  cd "$INSTANCE_MAIN"
  git_test init -q
  git_test add -A
  git_test commit -qm instance
  git_test worktree add -q --detach "$INSTANCE"
)
(
  cd "$INSTANCE"
  git_test commit --allow-empty -qm detached-unadvertised
)
printf 'untracked instance bytes\n' > "$INSTANCE/q-system/untracked-state.txt"
printf 'ignored instance bytes\n' > "$INSTANCE/q-system/ignored-state.txt"

git clone -q "$INSTANCE_MAIN" "$ATTACHED_MAIN"
(
  cd "$ATTACHED_MAIN"
  git config extensions.worktreeConfig true
  git_test worktree add -q -b attached-fixture "$ATTACHED_INSTANCE"
)
git -C "$ATTACHED_INSTANCE" config --worktree \
  core.worktree "$ATTACHED_INSTANCE"

git init -q --bare "$DIRECT_ORIGIN"
git --git-dir="$DIRECT_ORIGIN" symbolic-ref HEAD refs/heads/main
git clone -q "$DIRECT_ORIGIN" "$DIRECT_SEED" 2>/dev/null
(
  cd "$DIRECT_SEED"
  mkdir -p q-system/.q-system/scripts
  printf 'old direct content\n' > direct.txt
  printf 'raise SystemExit(0)\n' \
    > q-system/.q-system/scripts/capability-gate.py
  git_test add -A
  git_test commit -qm direct-old
  git push -q origin HEAD:main
)
git clone -q "$DIRECT_ORIGIN" "$DIRECT_INSTANCE"
(
  cd "$DIRECT_INSTANCE"
  git remote set-url origin ../direct-origin.git
)
(
  cd "$DIRECT_SEED"
  printf 'new direct content\n' > direct.txt
  git_test add direct.txt
  git_test commit -qm direct-new
  git push -q origin HEAD:main
)

BEFORE_HEAD="$(git -C "$INSTANCE" rev-parse HEAD)"
BEFORE_STATUS="$(git -C "$INSTANCE" status --porcelain=v1)"
BEFORE_STATE="$(worktree_digest "$INSTANCE")"
BEFORE_GITDIR="$(git -C "$INSTANCE" rev-parse --git-dir)"
BEFORE_INDEX_HASH="$(shasum -a 256 "$BEFORE_GITDIR/index" | awk '{print $1}')"
ATTACHED_BEFORE_HEAD="$(git -C "$ATTACHED_INSTANCE" rev-parse HEAD)"
ATTACHED_BEFORE_STATE="$(worktree_digest "$ATTACHED_INSTANCE")"
ATTACHED_BEFORE_REFS="$(git -C "$ATTACHED_INSTANCE" show-ref | sort)"
DIRECT_BEFORE_HEAD="$(git -C "$DIRECT_INSTANCE" rev-parse HEAD)"
DIRECT_BEFORE_STATUS="$(git -C "$DIRECT_INSTANCE" status --porcelain=v1)"
DIRECT_BEFORE_STATE="$(worktree_digest "$DIRECT_INSTANCE")"
DIRECT_BEFORE_REFS="$(git -C "$DIRECT_INSTANCE" show-ref | sort)"
DRY_OUTPUT="$(TMPDIR="$TEST_TMP" bash "$SKELETON/kipi-update.sh" --dry-run)"

[ "$(git -C "$INSTANCE" rev-parse HEAD)" = "$BEFORE_HEAD" ] ||
  fail "dry run changed instance HEAD"
[ "$(git -C "$INSTANCE" status --porcelain=v1)" = "$BEFORE_STATUS" ] ||
  fail "dry run changed instance worktree"
[ "$(worktree_digest "$INSTANCE")" = "$BEFORE_STATE" ] ||
  fail "dry run changed linked-worktree files, modes, or symlinks"
[ "$(shasum -a 256 "$BEFORE_GITDIR/index" | awk '{print $1}')" = \
    "$BEFORE_INDEX_HASH" ] ||
  fail "dry run changed linked-worktree index"
[ "$(git -C "$ATTACHED_INSTANCE" rev-parse HEAD)" = \
    "$ATTACHED_BEFORE_HEAD" ] ||
  fail "dry run changed attached-worktree HEAD"
[ "$(worktree_digest "$ATTACHED_INSTANCE")" = \
    "$ATTACHED_BEFORE_STATE" ] ||
  fail "dry run changed attached-worktree state"
[ "$(git -C "$ATTACHED_INSTANCE" show-ref | sort)" = \
    "$ATTACHED_BEFORE_REFS" ] ||
  fail "dry run changed attached-worktree refs"
[ "$(git -C "$DIRECT_INSTANCE" rev-parse HEAD)" = "$DIRECT_BEFORE_HEAD" ] ||
  fail "dry run changed direct-clone HEAD"
[ "$(git -C "$DIRECT_INSTANCE" status --porcelain=v1)" = \
    "$DIRECT_BEFORE_STATUS" ] ||
  fail "dry run changed direct-clone worktree"
[ "$(worktree_digest "$DIRECT_INSTANCE")" = "$DIRECT_BEFORE_STATE" ] ||
  fail "dry run changed direct-clone files, modes, or symlinks"
[ "$(git -C "$DIRECT_INSTANCE" show-ref | sort)" = "$DIRECT_BEFORE_REFS" ] ||
  fail "dry run changed direct-clone refs"
[ -z "$(find "$TEST_TMP" -mindepth 1 -print -quit)" ] ||
  fail "dry run leaked a temporary model"

DRY_DIFF="$(modeled_diff "$DRY_OUTPUT" fixture)"
[ -n "$DRY_DIFF" ] || fail "dry run emitted no modeled final diff"
DRY_TREE="$(modeled_value "$DRY_OUTPUT" MODELED_FINAL_TREE fixture)"
[ -n "$DRY_TREE" ] || fail "dry run emitted no modeled final tree"
DRY_STATE="$(
  modeled_value "$DRY_OUTPUT" MODELED_FINAL_STATE_SHA256 fixture
)"
[ -n "$DRY_STATE" ] || fail "dry run emitted no modeled final state digest"
DIRECT_DRY_DIFF="$(modeled_diff "$DRY_OUTPUT" direct)"
[ -n "$DIRECT_DRY_DIFF" ] ||
  fail "dry run emitted no direct-clone modeled diff"
DIRECT_DRY_TREE="$(
  modeled_value "$DRY_OUTPUT" MODELED_FINAL_TREE direct
)"
[ -n "$DIRECT_DRY_TREE" ] ||
  fail "dry run emitted no direct-clone modeled tree"
DIRECT_DRY_STATE="$(
  modeled_value "$DRY_OUTPUT" MODELED_FINAL_STATE_SHA256 direct
)"
[ -n "$DIRECT_DRY_STATE" ] ||
  fail "dry run emitted no direct-clone modeled state digest"
ATTACHED_DRY_DIFF="$(modeled_diff "$DRY_OUTPUT" attached)"
[ -n "$ATTACHED_DRY_DIFF" ] ||
  fail "dry run emitted no attached-worktree modeled diff"
ATTACHED_DRY_TREE="$(
  modeled_value "$DRY_OUTPUT" MODELED_FINAL_TREE attached
)"
ATTACHED_DRY_STATE="$(
  modeled_value "$DRY_OUTPUT" MODELED_FINAL_STATE_SHA256 attached
)"
[ -n "$ATTACHED_DRY_TREE" ] && [ -n "$ATTACHED_DRY_STATE" ] ||
  fail "dry run omitted attached-worktree final-state receipts"

bash "$SKELETON/kipi-update.sh" >/dev/null
REAL_DIFF="$(
  git -C "$INSTANCE" diff --name-status "$BEFORE_HEAD" HEAD |
    sort
)"
DIRECT_REAL_DIFF="$(
  git -C "$DIRECT_INSTANCE" diff --name-status \
    "$DIRECT_BEFORE_HEAD" HEAD |
    sort
)"
ATTACHED_REAL_DIFF="$(
  git -C "$ATTACHED_INSTANCE" diff --name-status \
    "$ATTACHED_BEFORE_HEAD" HEAD |
    sort
)"

[ "$DRY_DIFF" = "$REAL_DIFF" ] || {
  echo "DRY:" >&2
  echo "$DRY_DIFF" >&2
  echo "REAL:" >&2
  echo "$REAL_DIFF" >&2
  fail "modeled dry-run diff differs from real final commit diff"
}
[ "$DRY_TREE" = "$(git -C "$INSTANCE" rev-parse 'HEAD^{tree}')" ] ||
  fail "modeled tracked bytes, modes, or symlink targets differ from real state"
[ "$DRY_STATE" = "$(worktree_digest "$INSTANCE")" ] ||
  fail "modeled complete worktree differs from real subtree state"
[ "$DIRECT_DRY_DIFF" = "$DIRECT_REAL_DIFF" ] || {
  echo "DIRECT DRY:" >&2
  echo "$DIRECT_DRY_DIFF" >&2
  echo "DIRECT REAL:" >&2
  echo "$DIRECT_REAL_DIFF" >&2
  fail "modeled direct-clone diff differs from real final diff"
}
[ "$DIRECT_DRY_TREE" = \
    "$(git -C "$DIRECT_INSTANCE" rev-parse 'HEAD^{tree}')" ] ||
  fail "modeled direct-clone tree differs from real final tree"
[ "$DIRECT_DRY_STATE" = "$(worktree_digest "$DIRECT_INSTANCE")" ] ||
  fail "modeled complete worktree differs from real direct-clone state"
[ "$ATTACHED_DRY_DIFF" = "$ATTACHED_REAL_DIFF" ] ||
  fail "modeled attached-worktree diff differs from real final diff"
[ "$ATTACHED_DRY_TREE" = \
    "$(git -C "$ATTACHED_INSTANCE" rev-parse 'HEAD^{tree}')" ] ||
  fail "modeled attached-worktree tree differs from real final tree"
[ "$ATTACHED_DRY_STATE" = "$(worktree_digest "$ATTACHED_INSTANCE")" ] ||
  fail "modeled attached-worktree state differs from real final state"
[ "$(cat "$DIRECT_INSTANCE/direct.txt")" = "new direct content" ] ||
  fail "real run did not apply the direct-clone update"
grep -q "private canonical" "$INSTANCE/q-system/canonical/private.md" ||
  fail "real run did not preserve canonical state"
for expected in \
  ".claude/agents/example.md" \
  ".claude/rules/example.md" \
  ".claude/output-styles/example.md" \
  ".claude/settings.json" \
  "plugins/demo/content.txt" \
  "q-system/tracked.md"; do
  echo "$REAL_DIFF" | grep -q "$expected" ||
    fail "final diff omitted $expected"
done

(
  cd "$DIRECT_INSTANCE"
  git_test checkout -qb pending-merge
  printf 'temporary merge state\n' > transient.txt
  git_test add transient.txt
  git_test commit -qm pending-side
  git_test checkout -q main
  git_test merge --no-commit --no-ff pending-merge >/dev/null 2>&1
)
DIRECT_MERGE_HEAD_BEFORE="$(
  shasum -a 256 "$DIRECT_INSTANCE/.git/MERGE_HEAD" |
    awk '{print $1}'
)"
if TMPDIR="$TEST_TMP" bash "$SKELETON/kipi-update.sh" --dry-run \
    >/dev/null 2>&1; then
  fail "dry run modeled an active merge instead of failing closed"
fi
[ "$(
    shasum -a 256 "$DIRECT_INSTANCE/.git/MERGE_HEAD" |
      awk '{print $1}'
  )" = "$DIRECT_MERGE_HEAD_BEFORE" ] ||
  fail "dry run changed direct-clone merge state"
git -C "$DIRECT_INSTANCE" merge --abort

ln -s "../outside" "$INSTANCE/unsafe-external-link"
UNSAFE_HEAD="$(git -C "$INSTANCE" rev-parse HEAD)"
if TMPDIR="$TEST_TMP" bash "$SKELETON/kipi-update.sh" --dry-run \
    >/dev/null 2>&1; then
  fail "dry run accepted a symlink that escapes the disposable model"
fi
[ "$(git -C "$INSTANCE" rev-parse HEAD)" = "$UNSAFE_HEAD" ] ||
  fail "unsafe-symlink rejection changed production HEAD"
unlink "$INSTANCE/unsafe-external-link"

mkdir -p "$INSTANCE/untracked-target"
printf 'production-only bytes\n' > "$INSTANCE/untracked-target/value.txt"
ln -s "$INSTANCE/untracked-target" "$INSTANCE/.claude/absolute-inside"
INSIDE_TARGET_BEFORE="$(
  shasum -a 256 "$INSTANCE/untracked-target/value.txt" |
    awk '{print $1}'
)"
if TMPDIR="$TEST_TMP" bash "$SKELETON/kipi-update.sh" --dry-run \
    >/dev/null 2>&1; then
  fail "dry run accepted an internal absolute symlink back to production"
fi
[ "$(
    shasum -a 256 "$INSTANCE/untracked-target/value.txt" |
      awk '{print $1}'
  )" = "$INSIDE_TARGET_BEFORE" ] ||
  fail "dry run wrote through an internal absolute symlink"
unlink "$INSTANCE/.claude/absolute-inside"

printf 'raise SystemExit(1)\n' > "$SKELETON/kipi-settings-merge.py"
FAIL_CLOSED_HEAD="$(git -C "$INSTANCE" rev-parse HEAD)"
if TMPDIR="$TEST_TMP" bash "$SKELETON/kipi-update.sh" --dry-run \
    >/dev/null 2>&1; then
  fail "dry run reported success after a modeled settings failure"
fi
[ "$(git -C "$INSTANCE" rev-parse HEAD)" = "$FAIL_CLOSED_HEAD" ] ||
  fail "failed dry run changed production HEAD"
[ -z "$(find "$TEST_TMP" -mindepth 1 -print -quit)" ] ||
  fail "failed dry run leaked a temporary model"

echo "PASS: dry run is isolated, fail closed, and byte-equivalent to real state"
