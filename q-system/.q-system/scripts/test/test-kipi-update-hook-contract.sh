#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
UPDATER="$ROOT/kipi-update.sh"

fail() {
  echo "FAIL: $1" >&2
  exit 1
}

git_test() {
  git -c user.email=test@example.com -c user.name=test \
    -c commit.gpgsign=false "$@"
}

make_fixture() {
  local root="$1"
  local skeleton="$root/skeleton"
  local instance="$root/instance"

  mkdir -p "$skeleton/q-system/.q-system/scripts" \
    "$skeleton/.claude/agents" "$skeleton/plugins/core" \
    "$instance/q-system" "$instance/.claude"
  cp "$UPDATER" "$skeleton/kipi-update.sh"
  cp "$ROOT/kipi-update-preserve-scan.py" \
    "$skeleton/kipi-update-preserve-scan.py"
cp "$ROOT/kipi-update-deletion-guard.py" \
  "$skeleton/kipi-update-deletion-guard.py"
cp "$ROOT/kipi-update-deletion-guard.py" \
  "$skeleton/kipi-update-deletion-guard.py"
  cp "$ROOT/kipi-settings-merge.py" "$skeleton/kipi-settings-merge.py"
  cp "$ROOT/settings-template.json" "$skeleton/settings-template.json"
  # A valid skeleton ships the propagation leak gate: kipi-update.sh is
  # fail-closed on it, so a fixture without it aborts before any sync.
  mkdir -p "$skeleton/q-system/.q-system/scripts" "$skeleton/q-system/.q-system/state"
  cp "$ROOT/q-system/.q-system/scripts/propagation-leak-gate.py" \
     "$skeleton/q-system/.q-system/scripts/propagation-leak-gate.py"
  cp "$ROOT/q-system/.q-system/scripts/containment-targets.py" \
     "$skeleton/q-system/.q-system/scripts/containment-targets.py"
  cp "$ROOT/validate-separation.py" "$skeleton/validate-separation.py"
  # NOT the repo's committed baseline: that one is ARMED and its permits
  # describe THIS repo's content, so loading it against a synthetic skeleton
  # refuses ("a permit cannot exceed what was reviewed"). A fixture gets its
  # own unarmed baseline.
  cat > "$skeleton/q-system/.q-system/state/propagation-leak-baseline.json" <<'BASELINE_JSON'
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
  printf 'new skeleton content\n' > "$skeleton/q-system/tracked.md"
  printf 'new path from skeleton\n' > "$skeleton/q-system/new.md"
  printf '%s\n' \
    'import os' \
    'with open(os.environ["CAPABILITY_LOG"], "a", encoding="utf-8") as stream:' \
    '    stream.write("capability ran\n")' \
    > "$skeleton/q-system/.q-system/scripts/capability-gate.py"
  printf 'generic agent\n' > "$skeleton/.claude/agents/generic.md"
  printf 'plugin runtime\n' > "$skeleton/plugins/core/runtime.py"
  (
    cd "$skeleton"
    git_test init -q -b main
    git_test add -A
    git_test commit -qm skeleton
  )
  printf \
    '{"instances":[{"name":"fixture","path":"%s","subtree_prefix":"q-system","type":"subtree"}]}\n' \
    "$instance" > "$skeleton/instance-registry.json"

  printf 'old instance content\n' > "$instance/q-system/tracked.md"
  printf '{}\n' > "$instance/.claude/settings.json"
  printf 'founder work\n' > "$instance/unrelated.md"
  (
    cd "$instance"
    git_test init -q -b main
    git_test add -A
    git_test commit -qm instance
  )
  write_hook_set "$instance/.git/hooks" "hook ran"
}

# The fixture hooks deliberately depend on their own identity: each sources a
# SIBLING resolved from `dirname "$0"` and reports `basename "$0"`. A guard that
# runs the instance hook through a renamed symlink breaks both, which is exactly
# how an active hook silently loses authority over the updater commit.
write_hook_set() {
  local hook_dir="$1"
  local marker="$2"

  mkdir -p "$hook_dir"
  printf '%s\n' \
    'hook_record() {' \
    '  printf "'"$marker"' %s\n" "$1" >> "$HOOK_LOG"' \
    '}' \
    > "$hook_dir/hook-common.sh"
  printf '%s\n' \
    '#!/usr/bin/env bash' \
    'sibling="$(dirname "$0")/hook-common.sh"' \
    'if [ ! -f "$sibling" ]; then' \
    '  printf "sibling missing %s\n" "$(basename "$0")" >> "$HOOK_LOG"' \
    '  exit 1' \
    'fi' \
    '. "$sibling"' \
    'hook_record "$(basename "$0")"' \
    'hook_count="$(grep -c "^'"$marker"' pre-commit$" "$HOOK_LOG" || true)"' \
    'if [ "${HOOK_STAGE_EXTRA:-0}" = "1" ]; then git add -- "$HOOK_EXTRA_PATH"; fi' \
    'if [ "${HOOK_FAIL:-0}" != "0" ]; then exit 1; fi' \
    'if [ "${HOOK_FAIL_ON:-0}" != "0" ] && [ "$hook_count" = "$HOOK_FAIL_ON" ]; then exit 1; fi' \
    > "$hook_dir/pre-commit"
  local message_hook
  for message_hook in prepare-commit-msg commit-msg; do
    printf '%s\n' \
      '#!/usr/bin/env bash' \
      'sibling="$(dirname "$0")/hook-common.sh"' \
      'if [ ! -f "$sibling" ]; then' \
      '  printf "sibling missing %s\n" "$(basename "$0")" >> "$HOOK_LOG"' \
      '  exit 1' \
      'fi' \
      '. "$sibling"' \
      'hook_record "$(basename "$0")"' \
      'if [ -z "${1:-}" ] || [ ! -f "$1" ]; then' \
      '  printf "missing message file %s\n" "$(basename "$0")" >> "$HOOK_LOG"' \
      '  exit 1' \
      'fi' \
      > "$hook_dir/$message_hook"
  done
  chmod +x "$hook_dir/pre-commit" "$hook_dir/prepare-commit-msg" \
    "$hook_dir/commit-msg"
}

count_hook_runs() {
  local log="$1"
  local hook_name="$2"
  if [ ! -e "$log" ]; then
    echo 0
    return
  fi
  grep -c "^hook ran $hook_name\$" "$log" || true
}

WORK="$(mktemp -d)"
trap 'rm -r -- "$WORK"' EXIT

SUCCESS="$WORK/success"
make_fixture "$SUCCESS"
mkdir -p "$SUCCESS/instance/q-system/local" \
  "$SUCCESS/instance/.claude/local" \
  "$SUCCESS/instance/plugins/instance-only"
printf 'q work\n' > "$SUCCESS/instance/q-system/local/untracked.md"
printf 'claude work\n' > "$SUCCESS/instance/.claude/local/untracked.md"
printf 'plugin work\n' > "$SUCCESS/instance/plugins/instance-only/run.py"
HOOK_LOG="$SUCCESS/hook.log" CAPABILITY_LOG="$SUCCESS/capability.log" \
  bash "$SUCCESS/skeleton/kipi-update.sh" >"$SUCCESS/output.log" 2>&1 || {
    cat "$SUCCESS/output.log" >&2
    fail "clean updater run failed"
  }
[ -s "$SUCCESS/hook.log" ] || fail "active pre-commit hook did not run"
[ "$(count_hook_runs "$SUCCESS/hook.log" pre-commit)" = "2" ] ||
  fail "both updater commits did not run the active hook"
grep -q 'sibling missing' "$SUCCESS/hook.log" &&
  fail "active hook could not resolve its sibling from dirname \$0"
grep -q 'missing message file' "$SUCCESS/hook.log" &&
  fail "message hooks did not receive their commit-message file argument"
[ "$(count_hook_runs "$SUCCESS/hook.log" prepare-commit-msg)" = "2" ] ||
  fail "prepare-commit-msg did not run for both updater commits"
[ "$(count_hook_runs "$SUCCESS/hook.log" commit-msg)" = "2" ] ||
  fail "commit-msg did not run for both updater commits"
[ -s "$SUCCESS/capability.log" ] ||
  fail "capability phase did not run after successful commits"
git -C "$SUCCESS/instance" log -1 --format=%s |
  grep -q '^chore: sync .claude config + plugins' ||
  fail "clean updater run did not create the config commit"
for relative in \
  q-system/local/untracked.md \
  .claude/local/untracked.md \
  plugins/instance-only/run.py; do
  git -C "$SUCCESS/instance" ls-files --error-unmatch "$relative" \
    >/dev/null 2>&1 &&
    fail "updater committed untracked WIP: $relative"
  [ -f "$SUCCESS/instance/$relative" ] ||
    fail "updater removed untracked WIP: $relative"
done

BLOCKED="$WORK/blocked"
make_fixture "$BLOCKED"
BLOCKED_HEAD="$(git -C "$BLOCKED/instance" rev-parse HEAD)"
set +e
HOOK_LOG="$BLOCKED/hook.log" HOOK_FAIL=1 \
  CAPABILITY_LOG="$BLOCKED/capability.log" \
  bash "$BLOCKED/skeleton/kipi-update.sh" \
  >"$BLOCKED/output.log" 2>&1
BLOCKED_RC=$?
set -e
[ "$BLOCKED_RC" -ne 0 ] || fail "hook failure returned success"
[ -s "$BLOCKED/hook.log" ] || fail "failing hook did not run"
[ "$(git -C "$BLOCKED/instance" rev-parse HEAD)" = "$BLOCKED_HEAD" ] ||
  fail "updater committed after hook failure"
grep -q 'could not commit q-system sync' "$BLOCKED/output.log" ||
  fail "hook failure did not abort the updater commit"
[ ! -e "$BLOCKED/capability.log" ] ||
  fail "capability phase ran after hook rejection"
[ ! -e "$BLOCKED/instance/.claude/agents/generic.md" ] ||
  fail "config phase ran after hook rejection"

CONFIG_BLOCKED="$WORK/config-blocked"
make_fixture "$CONFIG_BLOCKED"
CONFIG_BEFORE="$(git -C "$CONFIG_BLOCKED/instance" rev-parse HEAD)"
set +e
HOOK_LOG="$CONFIG_BLOCKED/hook.log" HOOK_FAIL_ON=2 \
  CAPABILITY_LOG="$CONFIG_BLOCKED/capability.log" \
  bash "$CONFIG_BLOCKED/skeleton/kipi-update.sh" \
  >"$CONFIG_BLOCKED/output.log" 2>&1
CONFIG_RC=$?
set -e
[ "$CONFIG_RC" -ne 0 ] || fail "second-commit hook failure returned success"
[ "$(git -C "$CONFIG_BLOCKED/instance" rev-parse HEAD)" != "$CONFIG_BEFORE" ] ||
  fail "first updater commit did not complete before second-hook fixture"
git -C "$CONFIG_BLOCKED/instance" log -1 --format=%s |
  grep -q '^chore: sync q-system from skeleton' ||
  fail "second-hook failure did not stop at the config commit"
[ ! -e "$CONFIG_BLOCKED/capability.log" ] ||
  fail "capability phase ran after config hook rejection"

DIRTY="$WORK/dirty"
make_fixture "$DIRTY"
DIRTY_HEAD="$(git -C "$DIRTY/instance" rev-parse HEAD)"
printf 'founder work in progress\n' > "$DIRTY/instance/unrelated.md"
set +e
HOOK_LOG="$DIRTY/hook.log" CAPABILITY_LOG="$DIRTY/capability.log" \
  bash "$DIRTY/skeleton/kipi-update.sh" >"$DIRTY/output.log" 2>&1
DIRTY_RC=$?
set -e
[ "$DIRTY_RC" -ne 0 ] || fail "dirty instance returned success"
[ "$(git -C "$DIRTY/instance" rev-parse HEAD)" = "$DIRTY_HEAD" ] ||
  fail "updater committed unrelated work in progress"
grep -q 'founder work in progress' "$DIRTY/instance/unrelated.md" ||
  fail "updater changed unrelated work in progress"
[ ! -e "$DIRTY/hook.log" ] ||
  fail "updater reached a commit hook after dirty-tree refusal"
grep -q 'dirty working tree' "$DIRTY/output.log" ||
  fail "dirty-tree refusal was not explicit"

STAGED="$WORK/staged"
make_fixture "$STAGED"
STAGED_HEAD="$(git -C "$STAGED/instance" rev-parse HEAD)"
printf 'staged founder work\n' > "$STAGED/instance/unrelated.md"
git -C "$STAGED/instance" add unrelated.md
set +e
HOOK_LOG="$STAGED/hook.log" CAPABILITY_LOG="$STAGED/capability.log" \
  bash "$STAGED/skeleton/kipi-update.sh" >"$STAGED/output.log" 2>&1
STAGED_RC=$?
set -e
[ "$STAGED_RC" -ne 0 ] || fail "staged WIP returned success"
[ "$(git -C "$STAGED/instance" rev-parse HEAD)" = "$STAGED_HEAD" ] ||
  fail "updater committed staged WIP"

MUTATING="$WORK/mutating"
make_fixture "$MUTATING"
MUTATING_HEAD="$(git -C "$MUTATING/instance" rev-parse HEAD)"
printf 'hook-added founder work\n' > "$MUTATING/instance/hook-extra.md"
set +e
HOOK_LOG="$MUTATING/hook.log" HOOK_STAGE_EXTRA=1 \
  HOOK_EXTRA_PATH=hook-extra.md CAPABILITY_LOG="$MUTATING/capability.log" \
  bash "$MUTATING/skeleton/kipi-update.sh" >"$MUTATING/output.log" 2>&1
MUTATING_RC=$?
set -e
[ "$MUTATING_RC" -ne 0 ] || fail "hook-expanded commit returned success"
[ "$(git -C "$MUTATING/instance" rev-parse HEAD)" = "$MUTATING_HEAD" ] ||
  fail "hook added unrelated WIP to updater commit"
git -C "$MUTATING/instance" ls-files --error-unmatch hook-extra.md \
  >/dev/null 2>&1 &&
  fail "hook-added WIP remained staged after rejection"

Q_COLLISION="$WORK/q-collision"
make_fixture "$Q_COLLISION"
printf 'untracked founder version\n' > "$Q_COLLISION/instance/q-system/new.md"
set +e
HOOK_LOG="$Q_COLLISION/hook.log" \
  CAPABILITY_LOG="$Q_COLLISION/capability.log" \
  bash "$Q_COLLISION/skeleton/kipi-update.sh" \
  >"$Q_COLLISION/output.log" 2>&1
Q_COLLISION_RC=$?
set -e
[ "$Q_COLLISION_RC" -ne 0 ] || fail "q-system collision returned success"
grep -q 'untracked founder version' "$Q_COLLISION/instance/q-system/new.md" ||
  fail "q-system collision overwrote untracked WIP"
# Assert the collision-specific diagnostic, not just a nonzero exit: any
# unrelated updater failure would otherwise satisfy this case.
grep -q 'untracked WIP collides with skeleton path: q-system/new.md' \
  "$Q_COLLISION/output.log" ||
  fail "q-system collision did not name the colliding path"
[ ! -e "$Q_COLLISION/hook.log" ] ||
  fail "q-system collision reached a commit hook"
[ ! -e "$Q_COLLISION/capability.log" ] ||
  fail "capability phase ran after q-system collision"

CONFIG_COLLISION="$WORK/config-collision"
make_fixture "$CONFIG_COLLISION"
mkdir -p "$CONFIG_COLLISION/instance/.claude/agents"
printf 'untracked founder agent\n' \
  > "$CONFIG_COLLISION/instance/.claude/agents/generic.md"
set +e
HOOK_LOG="$CONFIG_COLLISION/hook.log" \
  CAPABILITY_LOG="$CONFIG_COLLISION/capability.log" \
  bash "$CONFIG_COLLISION/skeleton/kipi-update.sh" \
  >"$CONFIG_COLLISION/output.log" 2>&1
CONFIG_COLLISION_RC=$?
set -e
[ "$CONFIG_COLLISION_RC" -ne 0 ] ||
  fail "managed config collision returned success"
grep -q 'untracked founder agent' \
  "$CONFIG_COLLISION/instance/.claude/agents/generic.md" ||
  fail "config collision overwrote untracked WIP"
grep -q 'untracked WIP collides with managed config: .claude/agents/generic.md' \
  "$CONFIG_COLLISION/output.log" ||
  fail "config collision did not name the colliding path"
[ "$(count_hook_runs "$CONFIG_COLLISION/hook.log" pre-commit)" = "1" ] ||
  fail "config collision did not stop after the q-system commit"
[ ! -e "$CONFIG_COLLISION/capability.log" ] ||
  fail "capability phase ran after config collision"

# core.hooksPath moves hook authority off .git/hooks. Both a relative and an
# absolute configured path must still be found, still run with their own
# identity, and still be able to reject the updater commit.
for hooks_scope in relative absolute; do
  CONFIGURED="$WORK/hooks-$hooks_scope"
  make_fixture "$CONFIGURED"
  if [ "$hooks_scope" = "relative" ]; then
    CONFIGURED_VALUE=".githooks"
    CONFIGURED_DIR="$CONFIGURED/instance/.githooks"
  else
    CONFIGURED_VALUE="$CONFIGURED/external-hooks"
    CONFIGURED_DIR="$CONFIGURED/external-hooks"
  fi
  write_hook_set "$CONFIGURED_DIR" "configured hook ran"
  git -C "$CONFIGURED/instance" config core.hooksPath "$CONFIGURED_VALUE"
  CONFIGURED_HEAD="$(git -C "$CONFIGURED/instance" rev-parse HEAD)"
  set +e
  HOOK_LOG="$CONFIGURED/hook.log" HOOK_FAIL=1 \
    CAPABILITY_LOG="$CONFIGURED/capability.log" \
    bash "$CONFIGURED/skeleton/kipi-update.sh" \
    >"$CONFIGURED/output.log" 2>&1
  CONFIGURED_RC=$?
  set -e
  [ "$CONFIGURED_RC" -ne 0 ] ||
    fail "$hooks_scope core.hooksPath rejection returned success"
  grep -q '^configured hook ran pre-commit$' "$CONFIGURED/hook.log" ||
    fail "$hooks_scope core.hooksPath hook did not run with its own identity"
  grep -q 'sibling missing' "$CONFIGURED/hook.log" &&
    fail "$hooks_scope core.hooksPath hook lost its sibling directory"
  grep -q '^hook ran ' "$CONFIGURED/hook.log" &&
    fail "$hooks_scope core.hooksPath was ignored in favour of .git/hooks"
  [ "$(git -C "$CONFIGURED/instance" rev-parse HEAD)" = "$CONFIGURED_HEAD" ] ||
    fail "$hooks_scope core.hooksPath rejection still produced a commit"
  grep -q 'could not commit q-system sync' "$CONFIGURED/output.log" ||
    fail "$hooks_scope core.hooksPath rejection did not abort the updater"
done

# A direct-clone dry run rebases and merges inside the disposable model. Those
# git operations fire pre-rebase / post-rewrite / post-merge / post-checkout from
# the COPIED .git, so hook isolation has to cover the whole modeled iteration,
# not only the commit.
CLONE_DRY="$WORK/clone-dry"
make_fixture "$CLONE_DRY"
git_test clone -q "$CLONE_DRY/skeleton" "$CLONE_DRY/clone"
printf 'skeleton moved ahead\n' > "$CLONE_DRY/skeleton/q-system/tracked.md"
(
  cd "$CLONE_DRY/skeleton"
  git_test add -A
  git_test commit -qm advance
)
printf 'local clone work\n' > "$CLONE_DRY/clone/local.md"
(
  cd "$CLONE_DRY/clone"
  git_test add -A
  git_test commit -qm local
)
for pull_hook in pre-rebase post-rewrite post-merge post-checkout pre-commit \
    prepare-commit-msg commit-msg; do
  printf '%s\n' \
    '#!/usr/bin/env bash' \
    'printf "pull hook ran %s\n" "$(basename "$0")" >> "$PULL_HOOK_LOG"' \
    > "$CLONE_DRY/clone/.git/hooks/$pull_hook"
  chmod +x "$CLONE_DRY/clone/.git/hooks/$pull_hook"
done
printf \
  '{"instances":[{"name":"clone","path":"%s","subtree_prefix":"q-system","type":"direct-clone"}]}\n' \
  "$CLONE_DRY/clone" > "$CLONE_DRY/skeleton/instance-registry.json"
CLONE_HEAD="$(git -C "$CLONE_DRY/clone" rev-parse HEAD)"
CLONE_STATUS="$(git -C "$CLONE_DRY/clone" status --porcelain)"
PULL_HOOK_LOG="$CLONE_DRY/pull-hook.log" HOOK_LOG="$CLONE_DRY/hook.log" \
  CAPABILITY_LOG="$CLONE_DRY/capability.log" \
  bash "$CLONE_DRY/skeleton/kipi-update.sh" --dry-run \
  >"$CLONE_DRY/output.log" 2>&1 || {
    cat "$CLONE_DRY/output.log" >&2
    fail "direct-clone dry run failed"
  }
[ ! -e "$CLONE_DRY/pull-hook.log" ] ||
  fail "dry run executed production pull hooks: $(cat "$CLONE_DRY/pull-hook.log")"
[ "$(git -C "$CLONE_DRY/clone" rev-parse HEAD)" = "$CLONE_HEAD" ] ||
  fail "dry run advanced production HEAD"
[ "$(git -C "$CLONE_DRY/clone" status --porcelain)" = "$CLONE_STATUS" ] ||
  fail "dry run changed the production worktree"
[ ! -e "$CLONE_DRY/capability.log" ] ||
  fail "dry run ran the capability phase"

DRY="$WORK/dry"
make_fixture "$DRY"
DRY_HEAD="$(git -C "$DRY/instance" rev-parse HEAD)"
HOOK_LOG="$DRY/hook.log" HOOK_FAIL=1 GIT_CONFIG_COUNT=1 \
  GIT_CONFIG_KEY_0=core.hooksPath \
  GIT_CONFIG_VALUE_0="$DRY/instance/.git/hooks" \
  CAPABILITY_LOG="$DRY/capability.log" \
  bash "$DRY/skeleton/kipi-update.sh" --dry-run >/dev/null 2>&1 ||
  fail "isolated dry run failed because a production hook executed"
[ ! -e "$DRY/hook.log" ] ||
  fail "dry run executed a production hook with external side effects"
[ "$(git -C "$DRY/instance" rev-parse HEAD)" = "$DRY_HEAD" ] ||
  fail "dry run changed production HEAD"

if [ "${1:-}" = "--reject-no-verify" ]; then
  echo "PASS: both updater commits dynamically reject failing active hooks"
else
  echo "PASS: updater runs hooks, aborts on hook failure, and never commits unrelated WIP"
fi
