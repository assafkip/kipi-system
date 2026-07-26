#!/bin/bash
set -euo pipefail
trap "" PIPE
# Never let GPG signing or a credential prompt hang the updater. Updater commits
# still run the instance's active hooks and fail closed when a hook rejects them.
export GIT_TERMINAL_PROMPT=0

# kipi-update.sh - Sync latest kipi-system skeleton into all registered instances
# Usage: ./kipi-update.sh [--dry-run]
#
# Uses git archive + rsync (not git subtree pull) for speed and reliability.
# Instance-specific directories (my-project/, canonical/, memory/, output/, bus/)
# are preserved. Everything else syncs from the skeleton.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REGISTRY="$SCRIPT_DIR/instance-registry.json"
SKELETON_REMOTE="https://github.com/assafkip/kipi-system.git"
SKELETON_BRANCH="main"
# Args in any order: --dry-run and/or --only <name>. Without --only there is no
# way to verify a risky change against ONE repo before the other 22, and a
# staged rollout is the only safe way to ship anything with this blast radius.
DRY_RUN=""
ONLY=""
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN="--dry-run"; shift ;;
    --only)
      ONLY="${2:-}"
      if [ -z "$ONLY" ]; then
        echo "ERROR: --only needs an instance name" >&2
        exit 1
      fi
      shift 2
      ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      echo "Usage: kipi-update.sh [--dry-run] [--only <instance-name>]" >&2
      exit 1
      ;;
  esac
done

if [ ! -f "$REGISTRY" ]; then
  echo "ERROR: instance-registry.json not found at $REGISTRY"
  exit 1
fi

# Instance-owned subtrees: the skeleton never overwrites these, because each
# instance authors its own. This list was duplicated across four sites (the
# q-system rsync, the dry-run preview rsync, the untracked-collision scan, and
# the staging list) and drifted the moment a sixth entry was added -- the sync
# wrote files it then refused to stage, leaving the instance dirty with no
# commit. One list, four consumers.
INSTANCE_OWNED_SUBTREES=(
  my-project
  canonical
  memory
  output
  .q-system/data
  .q-system/agent-pipeline/bus
)

rsync_owned_excludes() {
  local sub
  for sub in "${INSTANCE_OWNED_SUBTREES[@]}"; do printf -- '--exclude=/%s/\n' "$sub"; done
}

pathspec_owned_excludes() {
  local sub
  for sub in "${INSTANCE_OWNED_SUBTREES[@]}"; do printf -- ':(exclude)%s/%s/\n' "$1" "$sub"; done
}

is_instance_owned() {
  local relative="$1" sub
  for sub in "${INSTANCE_OWNED_SUBTREES[@]}"; do
    case "$relative" in "$sub"/*) return 0 ;; esac
  done
  return 1
}

echo "=== Kipi System Update ==="
echo "Remote: $SKELETON_REMOTE"
echo "Branch: $SKELETON_BRANCH"
[ "$DRY_RUN" = "--dry-run" ] && echo "MODE: DRY RUN (no changes)"
echo ""

# Preflight: refuse to propagate if an enforcement hook is wired in the skeleton's
# runtime .claude/settings.json but missing from settings-template.json -- it would
# ship its SCRIPT to the fleet while the SWITCH never propagates (instances rebuild
# settings from the template only). Scar 2026-06-30: 8 hooks ran dead in 18/18
# instances exactly this way (lessons-validator, wiring-check, +6).
SYNC_CHECK="$SCRIPT_DIR/q-system/.q-system/scripts/settings-template-sync-check.py"
if [ -f "$SYNC_CHECK" ]; then
  if ! CLAUDE_PROJECT_DIR="$SCRIPT_DIR" python3 "$SYNC_CHECK" --check; then
    echo ""
    echo "ABORT: .claude/settings.json and settings-template.json are out of sync (above)."
    echo "Add the stranded hook(s) to settings-template.json before propagating,"
    echo "or kipi update would ship dead enforcement to every instance."
    exit 1
  fi
fi

# Preflight: refuse to fan a leaked instance fact out to every instance.
#
# NOT wrapped in `[ -f "$LEAK_GATE" ]`, unlike the settings check directly
# above. That guard turns a DELETED script into a green run, which is the exact
# failure this gate exists to prevent, one level up: the gate's own absence
# must stop the fleet, not wave it through. A leak caught after the fan-out is
# a post-mortem -- 23 repos already hold the fact, each in a commit.
LEAK_GATE="$SCRIPT_DIR/q-system/.q-system/scripts/propagation-leak-gate.py"
if [ ! -f "$LEAK_GATE" ]; then
  echo ""
  echo "ABORT: propagation leak gate missing at $LEAK_GATE"
  echo "It is fail-closed on purpose. Restore it or revert; do not proceed"
  echo "with 23 instances unchecked."
  exit 1
fi
# The gate reads the INDEX; this sync copies HEAD via `git archive`. Staging a
# fix without committing it decouples the two and HEAD wins, so the gate clears
# bytes nobody is propagating while the leak ships. Worse, a `git rm --cached`
# file has NO index entry at all and is never even enumerated. Refuse the
# divergence rather than scan the wrong tree.
if ! git -C "$SCRIPT_DIR" diff --cached --quiet HEAD -- q-system/ 2>/dev/null; then
  echo ""
  echo "ABORT: q-system/ is staged but not committed."
  echo "The leak gate scans the index and this sync copies HEAD, so they must"
  echo "agree. Commit or reset q-system/ before propagating."
  exit 1
fi

# Proof of EXECUTION, not proof of existence. `[ ! -f ]` above only closes the
# deleted case: a zero-byte .py is a valid program that exits 0, so a truncated
# or comment-only gate would pass with no output at all -- quieter, and likelier
# (interrupted write, bad merge, full disk), than deletion. Require the gate to
# state its own verdict before its exit code is believed.
# `if` form, not a bare assignment: under `set -e` a failing command
# substitution kills the script AT the assignment, so the gate's own abort
# message would never print and the run would die silent.
if LEAK_OUT="$(python3 "$LEAK_GATE" --check --repo-root "$SCRIPT_DIR" 2>&1)"; then
  LEAK_RC=0
else
  LEAK_RC=$?
fi
printf '%s\n' "$LEAK_OUT"
if ! printf '%s' "$LEAK_OUT" | grep -q "^propagation leak gate: "; then
  echo ""
  echo "ABORT: the propagation leak gate did not report a verdict."
  echo "It exists but did not run as a gate. Restore it or revert; do not"
  echo "proceed with 23 instances unchecked."
  exit 1
fi
if [ "$LEAK_RC" -ne 0 ]; then
  echo ""
  echo "ABORT: a fact absent from the propagation baseline would be copied into"
  echo "every instance (named above). Remove it, replace it with a placeholder,"
  echo "or re-baseline explicitly after a human reads each new entry."
  exit 1
fi

PASS=0
FAIL=0
SKIP=0
GATE_FAIL=""
MODEL_RUN=0
DRY_MODEL_ROOT=""
ARCHIVE_TMP=""
DRY_TMP=""

cleanup_dry_model() {
  if [ "${MODEL_RUN:-0}" = "1" ] && [ -n "${DRY_MODEL_ROOT:-}" ]; then
    cd "$SCRIPT_DIR"
    rm -r -- "$DRY_MODEL_ROOT"
    DRY_MODEL_ROOT=""
    MODEL_RUN=0
    # The isolated hooksPath pointed into the model that just went away.
    unset GIT_CONFIG_COUNT GIT_CONFIG_KEY_0 GIT_CONFIG_VALUE_0
  fi
}

cleanup_updater_temps() {
  if [ -n "${ARCHIVE_TMP:-}" ] && [ -d "$ARCHIVE_TMP" ]; then
    rm -r -- "$ARCHIVE_TMP"
    ARCHIVE_TMP=""
  fi
  if [ -n "${DRY_TMP:-}" ] && [ -d "$DRY_TMP" ]; then
    rm -r -- "$DRY_TMP"
    DRY_TMP=""
  fi
  cleanup_dry_model
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

stage_q_system_sync() {
  local target="$1"
  local managed_prefix="$2"
  git -C "$target" add -u -- "$managed_prefix/" || return 1
  git -C "$SCRIPT_DIR" ls-tree -r --name-only -z HEAD -- q-system/ |
    python3 -c '
import os
import sys

prefix = sys.argv[1]
owned = sys.argv[2:]
for source in sys.stdin.buffer.read().split(b"\0"):
    if not source:
        continue
    relative = source.removeprefix(b"q-system/")
    # Skeleton paths under an instance-owned subtree are NOT synced, so adding
    # them stages a path that does not exist and the whole stage fails -- which
    # left the instance written-to but uncommitted.
    if any(relative.startswith(os.fsencode(o) + b"/") for o in owned):
        continue
    target = os.fsencode(prefix) + b"/" + relative
    sys.stdout.buffer.write(target + b"\0")
' "$managed_prefix" "${INSTANCE_OWNED_SUBTREES[@]}" |
    git -C "$target" add --pathspec-from-file=- --pathspec-file-nul
}

# Staging is not atomic: `git add -u` then a second add that can fail leaves the
# first one's work in the index. The updater then aborts, and EVERY later run
# aborts at the dirty-tree guard, because that guard reads `git diff --cached`.
# One interrupted run made an instance permanently un-updatable and a working
# tree checkout did not clear it, which made it easy to misdiagnose. Any staging
# failure unstages what it staged.
unstage_scope() {
  local target="$1"
  shift
  git -C "$target" reset -q -- "$@" 2>/dev/null || true
}

stage_config_sync() {
  local target="$1"
  local scope source relative plugin_top
  for scope in .claude plugins; do
    if [ -n "$(git -C "$target" ls-files -- "$scope/")" ]; then
      git -C "$target" add -u -- "$scope/" || return 1
    fi
  done
  if [ -f "$target/.claude/settings.json" ]; then
    git -C "$target" add -- .claude/settings.json || return 1
  fi
  for scope in agents rules output-styles; do
    if [ -d "$SCRIPT_DIR/.claude/$scope" ]; then
      while IFS= read -r -d '' source; do
        relative="${source#"$SCRIPT_DIR/"}"
        git -C "$target" add -- "$relative" || return 1
      done < <(
        find "$SCRIPT_DIR/.claude/$scope" -maxdepth 1 -type f \
          -name '*.md' -print0
      )
    fi
  done
  if [ -d "$SCRIPT_DIR/plugins" ]; then
    while IFS= read -r -d '' source; do
      relative="${source#"$SCRIPT_DIR/"}"
      # Stage only what the sync loop can actually write. That loop iterates
      # `$SCRIPT_DIR/plugins/*/`, a glob that matches directories and symlinks
      # to directories, so a skeleton entry that is a DANGLING symlink is
      # skipped there and never materialises in the instance. Handing git that
      # path here fails with `pathspec ... did not match any files` and takes
      # the whole config sync down with it.
      #
      # Scar 2026-07-25: plugins/memory-lifecycle points at
      # /Users/assafkip/projects/memory-lifecycle -- an old username, long
      # gone -- so all_points_setup and Prodigy_Gold both failed here while
      # instances that received the plugin back when the link resolved passed.
      # That asymmetry made a skeleton-wide defect look instance-specific.
      plugin_top="${relative#plugins/}"
      plugin_top="${plugin_top%%/*}"
      [ -d "$SCRIPT_DIR/plugins/$plugin_top" ] || continue
      git -C "$target" add -- "$relative" || return 1
    done < <(
      find "$SCRIPT_DIR/plugins" \
        \( -type d -name .git -o -type d -name __pycache__ \
           -o -type d -name .pytest_cache -o -type d -name .venv \) -prune -o \
        \( -type f ! -name '*.pyc' -o -type l \) -print0
    )
  fi
}

guarded_commit() {
  local target="$1"
  local message="$2"
  local guard_dir original_hooks configured hook index_path rc
  guard_dir="$(mktemp -d)"
  index_path="$(git -C "$target" rev-parse --git-path index)"
  cp "$index_path" "$guard_dir/index.before" || {
    rm -r -- "$guard_dir"
    return 1
  }
  git -C "$target" diff --cached --name-only -z > "$guard_dir/allowed"

  original_hooks=""
  if [ "$MODEL_RUN" != "1" ]; then
    configured="$(git -C "$target" config --path --get core.hooksPath || true)"
    if [ -n "$configured" ]; then
      case "$configured" in
        /*) original_hooks="$configured" ;;
        *) original_hooks="$target/$configured" ;;
      esac
    else
      original_hooks="$(
        git -C "$target" rev-parse --path-format=absolute --git-path hooks
      )"
    fi
  fi
  cat > "$guard_dir/hook-guard" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
hook_name="$(basename "$0")"
# Invoke the instance's hook by its REAL path. Running it through a renamed
# symlink (original-pre-commit) changed `basename "$0"` and pointed
# `dirname "$0"` at the guard dir, so dispatch-on-$0 hooks (lefthook, husky) and
# hooks that source a sibling (`. "$(dirname "$0")/common.sh"`) either
# misbehaved or hard-failed -- the active hook lost authority either way.
original="${GUARDED_ORIGINAL_HOOKS:-}"
if [ -n "$original" ] && [ -x "$original/$hook_name" ]; then
  "$original/$hook_name" "$@"
fi
case "$hook_name" in
  pre-commit|prepare-commit-msg|commit-msg)
    git diff --cached --name-only -z > "$GUARDED_HOOK_DIR/after"
    if ! cmp -s "$GUARDED_HOOK_DIR/allowed" "$GUARDED_HOOK_DIR/after"; then
      echo "ERROR: $hook_name changed the updater commit path set" >&2
      exit 1
    fi
    ;;
esac
SH
  chmod +x "$guard_dir/hook-guard"
  for hook in pre-commit prepare-commit-msg commit-msg post-commit post-rewrite; do
    ln -s hook-guard "$guard_dir/$hook" || {
      rm -r -- "$guard_dir"
      return 1
    }
  done

  set +e
  env -u GIT_CONFIG_PARAMETERS -u GIT_CONFIG_COUNT \
    GUARDED_HOOK_DIR="$guard_dir" \
    GUARDED_ORIGINAL_HOOKS="$original_hooks" \
    git -C "$target" -c core.hooksPath="$guard_dir" \
      commit --no-gpg-sign -m "$message" </dev/null
  rc=$?
  set -e
  if [ "$rc" -ne 0 ]; then
    cp "$guard_dir/index.before" "$index_path" || true
  fi
  rm -r -- "$guard_dir"
  return "$rc"
}

config_source_manages() {
  local relative="$1"
  case "$relative" in
    .claude/settings.json)
      return 0
      ;;
    .claude/agents/*.md|.claude/rules/*.md|.claude/output-styles/*.md)
      [ -f "$SCRIPT_DIR/$relative" ]
      return
      ;;
    plugins/*/*)
      # A build artifact is not work in progress. The plugins rsync runs with
      # --delete-excluded and its filters (/.git/, __pycache__/, *.pyc, .venv/)
      # exist precisely to clear these from the instance, so flagging them as a
      # collision refuses the sync over the thing the sync is for. Scar
      # 2026-07-25: this matched whenever the plugin DIRECTORY existed in the
      # skeleton, and the scan enumerates gitignored files, so a single
      # __pycache__ entry aborted the config sync on 23 of 23 instances -- and
      # with it .claude/, plugins/, and the 98MB .venv deletion.
      case "$relative" in
        */.git/*|*/__pycache__/*|*.pyc|*/.venv/*|*/.pytest_cache/*)
          return 1
          ;;
      esac
      # Anything else under a managed plugin dir IS a real collision: the rsync
      # is --delete, so it removes instance files the skeleton does not carry.
      local plugin_name="${relative#plugins/}"
      plugin_name="${plugin_name%%/*}"
      [ -d "$SCRIPT_DIR/plugins/$plugin_name" ]
      return
      ;;
  esac
  return 1
}

reject_untracked_config_collisions() {
  local target="$1"
  local relative
  while IFS= read -r -d '' relative; do
    if config_source_manages "$relative"; then
      echo "  ERROR: untracked WIP collides with managed config: $relative"
      return 1
    fi
  done < <(
    # UNTRACKED only, not --ignored. This guard exists to protect WORK from a
    # sync that would overwrite or --delete it. A file the instance itself
    # gitignores is, by its own declaration, not work; one real instance
    # returns 2569 ignored entries under these two dirs and the first of them
    # aborted the whole config block. Genuinely precious untracked state lives
    # under q-system/, which has its own snapshot-and-restore path.
    git -C "$target" ls-files -z --others --exclude-standard -- \
      .claude/ plugins/
  )
}

trap cleanup_updater_temps EXIT

while IFS='|' read -r name path prefix itype; do
  # Filter INSIDE the loop, not in the feed, so an --only name that matches
  # nothing is caught by the post-loop check rather than reading as an empty
  # registry.
  if [ -n "$ONLY" ] && [ "$name" != "$ONLY" ]; then
    continue
  fi
  echo "--- $name ($itype) ---"

  if [ ! -d "$path" ]; then
    echo "  SKIP: path $path does not exist"
    SKIP=$((SKIP + 1))
    echo ""
    continue
  fi

  # Standalone repos have no skeleton subtree; nothing to sync and the updater
  # must not auto-commit or rsync into them. (A null subtree_prefix used to
  # crash the registry parser below -- keep this guard before any mutation.)
  if [ "$itype" = "standalone" ] || [ -z "$prefix" ]; then
    echo "  SKIP: standalone (not skeleton-managed)"
    SKIP=$((SKIP + 1))
    echo ""
    continue
  fi

  MODEL_RUN=0
  DRY_MODEL_ROOT=""
  ORIGINAL_PATH="$path"
  ORIGINAL_HEAD=""
  if [ "$DRY_RUN" = "--dry-run" ]; then
    DRY_MODEL_ROOT="$(mktemp -d)"
    MODEL_RUN=1
    # Neutralize hooks for the WHOLE modeled iteration, not just the commit. A
    # direct-clone dry run runs fetch/pull/rebase/merge inside the model, which
    # fires pre-rebase, post-rewrite, post-merge and post-checkout out of the
    # COPIED .git (or an absolute core.hooksPath) -- production side effects
    # escaping a run that is supposed to change nothing. GIT_CONFIG_* env beats
    # local and worktree config, so it is the only scope the modeled repo cannot
    # override from inside; `git -c` still beats it, which is what keeps
    # guarded_commit authoritative.
    DRY_HOOKS_DIR="$DRY_MODEL_ROOT/no-hooks"
    if ! mkdir -p "$DRY_HOOKS_DIR"; then
      echo "  ERROR: could not create the isolated dry-run hooks directory"
      cleanup_dry_model
      FAIL=$((FAIL + 1))
      echo ""
      continue
    fi
    unset GIT_CONFIG_PARAMETERS
    case "${GIT_CONFIG_COUNT:-}" in
      ''|*[!0-9]*) ;;
      *)
        if [ "$GIT_CONFIG_COUNT" -le 4096 ]; then
          INHERITED_CONFIG=0
          while [ "$INHERITED_CONFIG" -lt "$GIT_CONFIG_COUNT" ]; do
            unset "GIT_CONFIG_KEY_$INHERITED_CONFIG" \
              "GIT_CONFIG_VALUE_$INHERITED_CONFIG"
            INHERITED_CONFIG=$((INHERITED_CONFIG + 1))
          done
        fi
        ;;
    esac
    export GIT_CONFIG_COUNT=1
    export GIT_CONFIG_KEY_0=core.hooksPath
    export GIT_CONFIG_VALUE_0="$DRY_HOOKS_DIR"
    ORIGINAL_HEAD="$(git -C "$path" rev-parse HEAD 2>/dev/null || true)"
    if [ -z "$ORIGINAL_HEAD" ]; then
      echo "  ERROR: could not resolve production HEAD for dry-run model"
      cleanup_dry_model
      FAIL=$((FAIL + 1))
      echo ""
      continue
    fi
    if ! python3 - "$path" <<'PY'
import os
import pathlib
import sys

# An escaping symlink is allowed ONLY when it resolves to an existing regular
# file. Such a link cannot leak a write: rsync and git replace the link itself
# rather than writing through it, which test-kipi-update-safety.sh asserts by
# checking the outside target is byte-identical after a dry run.
#
# Everything else that escapes is refused, for two different reasons:
#   - a DIRECTORY is a live path prefix a write can descend into
#   - a DANGLING target is worse, not better: nothing exists to replace, so a
#     mkdir -p or a redirect under it materialises the path OUTSIDE the model
#     (test-kipi-update-dry-final-state.sh plants exactly that shape)
#
# Scar 2026-07-25 (ASK_AI_consultant, fleet rollout): this walked the whole
# instance and refused on ANY escaping target, so every instance carrying a
# kipi-mcp virtualenv was unmodelable -- `.venv/bin/python -> /abs/python3.12`
# plus a relative `python3 -> python` that inherits the escape through the
# chain. That is the normal shape of every venv on disk and says nothing about
# update safety.
root = pathlib.Path(sys.argv[1]).resolve()
for current, directories, files in os.walk(root, followlinks=False):
    for name in directories + files:
        candidate = pathlib.Path(current, name)
        if not candidate.is_symlink():
            continue
        target = os.readlink(candidate)
        # is_file() follows the whole chain and is False for both a directory
        # and a dangling target, which is the line that matters. A link to a
        # real file is safe everywhere: rsync and git replace the link rather
        # than writing through it, so it cannot mutate what it points at.
        if candidate.is_file():
            continue
        # Not a file, so a write can descend into it or materialise it. It is
        # only safe if the whole chain is relative AND stays inside the
        # instance: relative hops follow the copy into the model, an absolute
        # hop keeps pointing at PRODUCTION even when it names a path inside
        # the instance -- which is the isolation break, not the escape.
        hop = candidate
        internal = True
        for _ in range(40):
            if not hop.is_symlink():
                break
            hop_target = os.readlink(hop)
            if os.path.isabs(hop_target):
                internal = False
                break
            hop = hop.parent / hop_target
            try:
                hop.resolve(strict=False).relative_to(root)
            except ValueError:
                internal = False
                break
        else:
            internal = False
        if internal:
            continue
        reason = "directory" if candidate.is_dir() else "dangling"
        print(f"unsafe {reason} symlink escapes the disposable model: {candidate.relative_to(root)} -> {target}", file=sys.stderr)
        raise SystemExit(1)
PY
    then
      echo "  ERROR: unsafe symlink prevents isolated dry-run modeling"
      cleanup_dry_model
      FAIL=$((FAIL + 1))
      echo ""
      continue
    fi
    SOURCE_GIT_DIR="$(
      git -C "$path" rev-parse --path-format=absolute --git-common-dir \
        2>/dev/null || true
    )"
    SOURCE_WORKTREE_GIT_DIR="$(
      git -C "$path" rev-parse --path-format=absolute --git-dir \
        2>/dev/null || true
    )"
    if [ -n "$SOURCE_WORKTREE_GIT_DIR" ] &&
        { [ -f "$SOURCE_WORKTREE_GIT_DIR/MERGE_HEAD" ] ||
          [ -d "$SOURCE_WORKTREE_GIT_DIR/rebase-merge" ] ||
          [ -d "$SOURCE_WORKTREE_GIT_DIR/rebase-apply" ]; }; then
      echo "  ERROR: active merge or rebase cannot be modeled safely"
      cleanup_dry_model
      FAIL=$((FAIL + 1))
      echo ""
      continue
    fi
    ORIGINAL_BRANCH="$(git -C "$path" symbolic-ref --short -q HEAD || true)"
    # Copy only what this sync can write into. A directory holding its own
    # .git below the root is a SEPARATE repository -- in the fleet, another
    # registered instance with its own entry and its own update run -- and the
    # sync never descends into one; it writes to the subtree prefix, .claude/
    # and plugins/. Scar 2026-07-25: ASK_AI_consultant is
    # /Users/assafkipnis/projects/consulting, the parent of ten nested
    # instances, so a faithful whole-tree model wanted 21GB of scratch for a
    # sync that touches about 100MB. It ran the data volume down to 605MB free
    # before it was killed.
    MODEL_EXCLUDES=(--exclude=".git")
    NESTED_COUNT=0
    while IFS= read -r nested_git; do
      nested_rel="${nested_git#"$path"/}"
      nested_rel="${nested_rel%/.git}"
      [ -n "$nested_rel" ] || continue
      [ "$nested_rel" != "$nested_git" ] || continue
      MODEL_EXCLUDES+=(--exclude="/$nested_rel/")
      NESTED_COUNT=$((NESTED_COUNT + 1))
    done < <(find "$path" -mindepth 2 -maxdepth 5 -name .git -print 2>/dev/null)
    if [ "$NESTED_COUNT" -gt 0 ]; then
      echo "  dry-run model: skipped $NESTED_COUNT nested repositories (separate repos, not synced)"
    fi
    MODEL_SETUP_FAILED=0
    if [ -d "$path/.git" ]; then
      if ! mkdir -p "$DRY_MODEL_ROOT/instance" ||
          ! rsync -a --delete "${MODEL_EXCLUDES[@]}" "$path/" \
            "$DRY_MODEL_ROOT/instance/" ||
          ! cp -a "$path/.git" "$DRY_MODEL_ROOT/instance/.git"; then
        MODEL_SETUP_FAILED=1
      fi
    else
      if [ -z "$SOURCE_GIT_DIR" ] ||
          [ -z "$SOURCE_WORKTREE_GIT_DIR" ] ||
          ! git init --quiet "$DRY_MODEL_ROOT/instance" ||
          ! git -C "$DRY_MODEL_ROOT/instance" fetch --quiet --no-tags \
            "$SOURCE_GIT_DIR" "$ORIGINAL_HEAD"; then
        MODEL_SETUP_FAILED=1
      elif [ -n "$ORIGINAL_BRANCH" ]; then
        git -C "$DRY_MODEL_ROOT/instance" checkout --quiet \
          -B "$ORIGINAL_BRANCH" "$ORIGINAL_HEAD" ||
          MODEL_SETUP_FAILED=1
      else
        git -C "$DRY_MODEL_ROOT/instance" checkout --quiet \
          --detach "$ORIGINAL_HEAD" ||
          MODEL_SETUP_FAILED=1
      fi
      if [ "$MODEL_SETUP_FAILED" = "0" ] &&
          { ! cp "$SOURCE_GIT_DIR/config" \
              "$DRY_MODEL_ROOT/instance/.git/config" ||
            ! git -C "$DRY_MODEL_ROOT/instance" config --local \
              core.bare false ||
            ! rsync -a --delete "${MODEL_EXCLUDES[@]}" "$path/" \
              "$DRY_MODEL_ROOT/instance/"; }; then
        MODEL_SETUP_FAILED=1
      fi
      if [ "$MODEL_SETUP_FAILED" = "0" ] &&
          [ -f "$SOURCE_WORKTREE_GIT_DIR/index" ] &&
          ! cp "$SOURCE_WORKTREE_GIT_DIR/index" \
            "$DRY_MODEL_ROOT/instance/.git/index"; then
        MODEL_SETUP_FAILED=1
      fi
      if [ "$MODEL_SETUP_FAILED" = "0" ] &&
          [ -f "$SOURCE_WORKTREE_GIT_DIR/config.worktree" ] &&
          ! cp "$SOURCE_WORKTREE_GIT_DIR/config.worktree" \
            "$DRY_MODEL_ROOT/instance/.git/config.worktree"; then
        MODEL_SETUP_FAILED=1
      fi
      if [ "$MODEL_SETUP_FAILED" = "0" ] &&
          [ -f "$SOURCE_WORKTREE_GIT_DIR/info/sparse-checkout" ]; then
        mkdir -p "$DRY_MODEL_ROOT/instance/.git/info"
        cp "$SOURCE_WORKTREE_GIT_DIR/info/sparse-checkout" \
          "$DRY_MODEL_ROOT/instance/.git/info/sparse-checkout" ||
          MODEL_SETUP_FAILED=1
      fi
    fi
    if [ "$MODEL_SETUP_FAILED" != "0" ]; then
      echo "  ERROR: could not create disposable dry-run model"
      cleanup_dry_model
      FAIL=$((FAIL + 1))
      echo ""
      continue
    fi
    if git -C "$DRY_MODEL_ROOT/instance" config --local \
        --get-all core.worktree >/dev/null 2>&1; then
      if ! git -C "$DRY_MODEL_ROOT/instance" config --local \
          --replace-all core.worktree "$DRY_MODEL_ROOT/instance"; then
        echo "  ERROR: could not isolate repository worktree config"
        cleanup_dry_model
        FAIL=$((FAIL + 1))
        echo ""
        continue
      fi
    fi
    if [ -f "$DRY_MODEL_ROOT/instance/.git/config.worktree" ] &&
        git -C "$DRY_MODEL_ROOT/instance" config --worktree \
          --get-all core.worktree >/dev/null 2>&1; then
      if ! git -C "$DRY_MODEL_ROOT/instance" config --worktree \
          --replace-all core.worktree "$DRY_MODEL_ROOT/instance"; then
        echo "  ERROR: could not isolate linked-worktree config"
        cleanup_dry_model
        FAIL=$((FAIL + 1))
        echo ""
        continue
      fi
    fi
    path="$DRY_MODEL_ROOT/instance"
    if [ "$itype" = "direct-clone" ]; then
      ORIGINAL_ORIGIN="$(git -C "$ORIGINAL_PATH" remote get-url origin 2>/dev/null || true)"
      case "$ORIGINAL_ORIGIN" in
        /*|*://*|*@*:*) ;;
        *)
          ORIGINAL_ORIGIN="$(
            python3 - "$ORIGINAL_PATH" "$ORIGINAL_ORIGIN" <<'PY'
import os
import sys
print(os.path.abspath(os.path.join(sys.argv[1], os.path.expanduser(sys.argv[2]))))
PY
          )"
          ;;
      esac
      if [ -z "$ORIGINAL_ORIGIN" ] ||
          ! git -C "$path" remote set-url origin "$ORIGINAL_ORIGIN"; then
        echo "  ERROR: could not configure isolated direct-clone origin"
        cleanup_dry_model
        FAIL=$((FAIL + 1))
        echo ""
        continue
      fi
    fi
  fi

  if [ "$DRY_RUN" != "--dry-run" ] || [ "$MODEL_RUN" = "1" ]; then
    cd "$path"

    # Clean up stale git lock files from crashed processes
    for lockfile in "$path/.git/HEAD.lock" "$path/.git/index.lock" "$path/.git/AUTO_MERGE.lock"; do
      if [ -f "$lockfile" ]; then
        echo "  Removing stale lock: $(basename "$lockfile")"
        rm -f "$lockfile"
      fi
    done

    # Abort any zombie rebase/merge/cherry-pick
    if [ -d "$path/.git/rebase-merge" ] || [ -d "$path/.git/rebase-apply" ]; then
      echo "  Aborting zombie rebase..."
      git rebase --abort 2>/dev/null || true
    fi
    if [ -f "$path/.git/MERGE_HEAD" ]; then
      echo "  Aborting zombie merge..."
      git merge --abort 2>/dev/null || true
    fi

    # Refuse tracked work in progress. The updater owns only its scoped sync
    # commits and must never package unrelated founder edits into an infra commit.
    if ! git diff --cached --quiet 2>/dev/null ||
        ! git diff --quiet 2>/dev/null; then
      if [ "$MODEL_RUN" = "1" ]; then
        echo "  Changes vs skeleton: blocked by dirty working tree"
      fi
      echo "  ERROR: dirty working tree; refusing to commit unrelated work"
      git status --short 2>/dev/null | sed 's/^/    /' || true
      cleanup_dry_model
      FAIL=$((FAIL + 1))
      echo ""
      continue
    fi
  fi

  if [ "$itype" = "direct-clone" ]; then
    echo "  Direct clone - pulling from origin..."
    if [ "$DRY_RUN" != "--dry-run" ] || [ "$MODEL_RUN" = "1" ]; then
      if ! git fetch origin "$SKELETON_BRANCH" --quiet 2>/dev/null; then
        echo "  ERROR: fetch failed"
        cleanup_dry_model
        FAIL=$((FAIL + 1))
        echo ""
        continue
      fi
      if git pull --rebase origin "$SKELETON_BRANCH" 2>&1; then
        echo "  OK"
        PASS=$((PASS + 1))
      else
        echo "  WARN: rebase failed, trying merge..."
        git rebase --abort 2>/dev/null || true
        if git merge origin/"$SKELETON_BRANCH" --no-edit 2>&1; then
          echo "  OK (merged)"
          PASS=$((PASS + 1))
        else
          echo "  WARN: merge failed (needs manual resolve)"
          git merge --abort 2>/dev/null || true
          FAIL=$((FAIL + 1))
        fi
      fi
    fi
  else
    # Archive + rsync: fast, reliable, no history walking
    echo "  Syncing $prefix/ from skeleton..."
    if [ "$DRY_RUN" != "--dry-run" ] || [ "$MODEL_RUN" = "1" ]; then
      ARCHIVE_TMP=$(mktemp -d)
      if git -C "$SCRIPT_DIR" archive --format=tar HEAD -- q-system/ 2>/dev/null | tar -x -C "$ARCHIVE_TMP" 2>/dev/null; then
        # Snapshot untracked instance files before the destructive --delete.
        # `git ls-files --others` lists untracked files INCLUDING gitignored ones
        # (so it covers q-system/sources/ etc. that `git stash -u` would miss).
        # Lives inside ARCHIVE_TMP so the existing rm -rf cleans it -- no stash stack,
        # no extra cleanup, collision-safe.
        SNAP="$ARCHIVE_TMP/.snap"; mkdir -p "$SNAP/f"
        # Excluded from preservation: bytecode junk (regenerable) and the forbidden
        # nested $prefix/q-system/ shadow tree (a stale skeleton copy from the old
        # `git subtree add` creation path -- folder-structure.md bans it; restoring
        # it made the shadow tree immortal across updates).
        if ! ( cd "$path" && git ls-files -z --others -- "$prefix/" \
            $(pathspec_owned_excludes "$prefix") \
            ":(exclude)$prefix/q-system/" \
            ":(exclude)*.pyc" ":(exclude)*__pycache__*" 2>/dev/null ) > "$SNAP/list"; then
          echo "  ERROR: preservation snapshot inventory failed; rsync not started"
          rm -r -- "$ARCHIVE_TMP"
          cleanup_dry_model
          FAIL=$((FAIL + 1))
          echo ""
          continue
        fi
        COLLISION=0
        while IFS= read -r -d '' uf; do
          relative="${uf#"$prefix/"}"
          if [ "$relative" = "$uf" ]; then
            continue
          fi
          source_path="$ARCHIVE_TMP/q-system/$relative"
          if [ -e "$source_path" ] || [ -L "$source_path" ]; then
            # Byte-identical is not work in progress: it is THIS sync's own
            # output from a run that died after the rsync and before the
            # commit. Treating it as WIP made one interrupted sync brick an
            # instance permanently -- every later run refused, and the only
            # recovery was deleting files by hand. Observed on a real run
            # 2026-07-25: 40 residue files, all identical to the skeleton.
            if [ -f "$source_path" ] && [ -f "$uf" ] && cmp -s "$uf" "$source_path"; then
              continue
            fi
            echo "  ERROR: untracked WIP collides with skeleton path: $uf"
            COLLISION=1
          fi
        done < "$SNAP/list"
        if [ "$COLLISION" != "0" ]; then
          rm -r -- "$ARCHIVE_TMP"
          ARCHIVE_TMP=""
          cleanup_dry_model
          FAIL=$((FAIL + 1))
          echo ""
          continue
        fi
        # Also preserve TRACKED instance-only files the --delete would remove. The
        # ls-files --others snapshot above only covers UNTRACKED files; a script the
        # instance COMMITTED inside the synced tree was deleted with no protection
        # (scar 2026-06-24: fractional-cxo income scanners died this way for 6 days).
        # The helper flags only files the skeleton NEVER tracked (genuinely instance-
        # added), so skeleton-intended deletions still propagate. It is a hard
        # precondition: missing or incomplete proof stops before rsync --delete.
        PRESERVE_SCAN="$SCRIPT_DIR/kipi-update-preserve-scan.py"
        if [ ! -f "$PRESERVE_SCAN" ]; then
          echo "  ERROR: preservation helper missing; rsync not started"
          rm -r -- "$ARCHIVE_TMP"
          cleanup_dry_model
          FAIL=$((FAIL + 1))
          echo ""
          continue
        fi
        if ! python3 "$PRESERVE_SCAN" --skeleton-archive "$ARCHIVE_TMP" \
            --instance "$path" --prefix "$prefix" --skeleton-git "$SCRIPT_DIR" \
            --receipt "$SNAP/preservation-receipt.json" \
            > "$SNAP/tracked" 2>"$SNAP/warn"; then
          [ -s "$SNAP/warn" ] && cat "$SNAP/warn"
          echo "  ERROR: preservation helper failed; rsync not started"
          rm -r -- "$ARCHIVE_TMP"
          cleanup_dry_model
          FAIL=$((FAIL + 1))
          echo ""
          continue
        fi
        if ! python3 - "$SNAP/preservation-receipt.json" "$SNAP/tracked" <<'PY'
import hashlib
import json
import pathlib
import sys

receipt_path = pathlib.Path(sys.argv[1])
output_path = pathlib.Path(sys.argv[2])
try:
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    output = output_path.read_bytes()
except (OSError, UnicodeError, json.JSONDecodeError):
    raise SystemExit(1)
expected_keys = {
    "candidate_count",
    "complete",
    "schema_version",
    "stdout_sha256",
}
if set(receipt) != expected_keys:
    raise SystemExit(1)
if receipt["schema_version"] != 1 or receipt["complete"] is not True:
    raise SystemExit(1)
if output and not output.endswith(b"\n"):
    raise SystemExit(1)
if receipt["candidate_count"] != len(output.splitlines()):
    raise SystemExit(1)
if receipt["stdout_sha256"] != hashlib.sha256(output).hexdigest():
    raise SystemExit(1)
PY
        then
          echo "  ERROR: preservation receipt incomplete or invalid; rsync not started"
          rm -r -- "$ARCHIVE_TMP"
          cleanup_dry_model
          FAIL=$((FAIL + 1))
          echo ""
          continue
        fi
        [ -s "$SNAP/warn" ] && cat "$SNAP/warn"
        if [ -s "$SNAP/tracked" ]; then
          while IFS= read -r tf; do [ -n "$tf" ] && printf '%s\0' "$tf"; done \
            < "$SNAP/tracked" >> "$SNAP/list"
        fi
        if ! ( cd "$path" && while IFS= read -r -d '' uf; do
            mkdir -p "$SNAP/f/$(dirname "$uf")" &&
              cp -a "$uf" "$SNAP/f/$uf" 2>/dev/null || exit 1
          done < "$SNAP/list" ); then
          echo "  ERROR: preservation snapshot copy failed; rsync not started"
          rm -r -- "$ARCHIVE_TMP"
          cleanup_dry_model
          FAIL=$((FAIL + 1))
          echo ""
          continue
        fi
        # Excludes are ANCHORED (leading /) to the transfer root. Unanchored
        # patterns also matched inside the nested q-system/q-system/ shadow copy
        # (protecting ITS memory/, canonical/, ...), so rsync could never delete
        # the shadow tree -- "not empty, cannot delete" on every update.
        if ! rsync -a --delete "$ARCHIVE_TMP/q-system/" "$path/$prefix/" \
            $(rsync_owned_excludes) 2>/dev/null; then
          echo "  ERROR: q-system sync failed"
          rm -r -- "$ARCHIVE_TMP"
          ARCHIVE_TMP=""
          cleanup_dry_model
          FAIL=$((FAIL + 1))
          echo ""
          continue
        fi
        # Restore any untracked file the rsync --delete removed (skeleton doesn't manage it).
        if ! ( cd "$path" && while IFS= read -r -d '' uf; do
            if ! { [ -e "$uf" ] || [ -L "$uf" ]; } && { [ -e "$SNAP/f/$uf" ] || [ -L "$SNAP/f/$uf" ]; }; then
              mkdir -p "$(dirname "$uf")" && cp -a "$SNAP/f/$uf" "$uf" && echo "  restored untracked: $uf"
            fi
          done < "$SNAP/list" ); then
          echo "  ERROR: preserved-file restore failed"
          rm -r -- "$ARCHIVE_TMP"
          ARCHIVE_TMP=""
          cleanup_dry_model
          FAIL=$((FAIL + 1))
          echo ""
          continue
        fi
        rm -r -- "$ARCHIVE_TMP"
        ARCHIVE_TMP=""
        cd "$path"
        if ! stage_q_system_sync "$path" "$prefix" 2>/dev/null; then
          unstage_scope "$path" "$prefix/"
          echo "  ERROR: could not stage q-system sync"
          cleanup_dry_model
          FAIL=$((FAIL + 1))
          echo ""
          continue
        fi
        CHANGES=$(git diff --cached --name-only 2>/dev/null | wc -l | tr -d ' ')
        if [ "$CHANGES" != "0" ]; then
          if ! guarded_commit "$path" \
              "chore: sync q-system from skeleton $(date +%Y-%m-%d)"; then
            echo "  ERROR: could not commit q-system sync"
            cleanup_dry_model
            FAIL=$((FAIL + 1))
            echo ""
            continue
          fi
          echo "  OK ($CHANGES files updated)"
        else
          echo "  OK (already up to date)"
        fi
        PASS=$((PASS + 1))
      else
        rm -r -- "$ARCHIVE_TMP"
        ARCHIVE_TMP=""
        echo "  WARN: archive export failed"
        FAIL=$((FAIL + 1))
      fi
    else
      cd "$path"
      # Real itemized preview: rsync -ain --delete from the SAME `git archive HEAD`
      # source AND the same excludes the real run uses, so --dry cannot drift from
      # what a real run would change/delete.
      DRY_TMP=$(mktemp -d)
      if git -C "$SCRIPT_DIR" archive --format=tar HEAD -- q-system/ 2>/dev/null | tar -x -C "$DRY_TMP" 2>/dev/null; then
        CHANGED=$(rsync -ain --delete "$DRY_TMP/q-system/" "$path/$prefix/" \
          $(rsync_owned_excludes) 2>/dev/null)
        if [ -n "$CHANGED" ]; then
          echo "  Changes vs skeleton (run without --dry to apply):"
          echo "$CHANGED" | sed 's/^/    /'
        else
          echo "  Up to date"
        fi
        rm -r -- "$DRY_TMP"
        DRY_TMP=""
      else
        rm -r -- "$DRY_TMP"
        DRY_TMP=""
        echo "  WARN: archive export failed (dry)"
      fi
      PASS=$((PASS + 1))
    fi
  fi

  # Sync settings, agents, rules, output styles, and plugins
  if { [ "$DRY_RUN" != "--dry-run" ] || [ "$MODEL_RUN" = "1" ]; } &&
      [ -d "$path/.claude" ]; then
    echo "  Syncing .claude/ config..."
    CONFIG_FAILED=0
    if ! reject_untracked_config_collisions "$path"; then
      cleanup_dry_model
      FAIL=$((FAIL + 1))
      echo ""
      continue
    fi

    # Rebuild settings.json from template (preserves instance customizations)
    if [ -f "$path/.claude/settings.json" ]; then
      # Merge lives in kipi-settings-merge.py (extracted 2026-07-02 so it is
      # testable: test-settings-merge.sh). Scar: the former inline heredoc
      # deduped hooks by exact command string, so a template command-form
      # change left BOTH forms in every instance — token-guard ran twice per
      # tool call and its counters doubled. The script dedupes by invoked
      # script basename; template form wins, instance-added hooks survive.
      if ! python3 "$SCRIPT_DIR/kipi-settings-merge.py" \
          "$SCRIPT_DIR/settings-template.json" \
          "$path/.claude/settings.json" 2>/dev/null; then
        echo "    ERROR: settings.json sync failed"
        CONFIG_FAILED=1
      fi

      # Path rewriting: previously this section doubled $CLAUDE_PROJECT_DIR/q-system/
      # to $CLAUDE_PROJECT_DIR/q-system/q-system/ for "subtree" instances. That logic
      # was wrong: the rsync above copies skeleton/q-system/* into instance/q-system/*,
      # so template paths like q-system/.q-system/scripts/X.py already point to the
      # correct file at instance/q-system/.q-system/scripts/X.py.
      # The doubled paths were silently no-ops via the `test -f ... || true` wrappers
      # in the hook commands, which is why this went undetected for a long time.
      # If you're reading this and considering re-adding sed rewriting, verify the
      # actual on-disk file structure of a subtree instance first.
    fi

    # Sync agents, output styles, rules
    if ! mkdir -p "$path/.claude/agents" "$path/.claude/output-styles" \
        "$path/.claude/rules"; then
      CONFIG_FAILED=1
    fi
    for config_kind in agents output-styles rules; do
      if compgen -G "$SCRIPT_DIR/.claude/$config_kind/*.md" >/dev/null &&
          ! cp "$SCRIPT_DIR"/.claude/"$config_kind"/*.md \
            "$path/.claude/$config_kind/" 2>/dev/null; then
        CONFIG_FAILED=1
      fi
    done

    # Sync plugins (copy contents, not directory, to avoid plugins/plugins/ nesting).
    # rsync instead of rm -rf + cp -R: --delete-excluded strips embedded .git dirs
    # and bytecode from the instance copy. A symlinked skeleton plugin (e.g.
    # memory-lifecycle -> standalone repo) used to materialize WITH its .git,
    # leaving every instance permanently dirty on plugins/<name> in git status.
    if [ -d "$SCRIPT_DIR/plugins" ]; then
      mkdir -p "$path/plugins"
      for plugin_dir in "$SCRIPT_DIR"/plugins/*/; do
        if [ -d "$plugin_dir" ]; then
          plugin_name="$(basename "$plugin_dir")"
          # .venv/ is a uv-built virtualenv, not source: uv writes a
          # `.gitignore` of `*` inside it, pyvenv.cfg pins it to ONE machine's
          # Python (home = /Users/<name>/... macos-aarch64), and nothing
          # launches it -- plugins/kipi-core/.mcp.json runs `uv run`, which
          # rebuilds it from the tracked uv.lock (measured: 52 packages, 37ms).
          # It was 107MB of the 112MB plugin tree, copied into 23 instances
          # where it could never work. --delete-excluded also clears the stale
          # copies already there. Pairs with test-kipi-update-build-artifacts.sh.
          if ! rsync -a --delete --delete-excluded \
              --exclude="/.git/" --exclude="__pycache__/" --exclude="*.pyc" \
              --exclude=".venv/" --exclude=".pytest_cache/" \
              "$plugin_dir" "$path/plugins/$plugin_name/" 2>/dev/null; then
            CONFIG_FAILED=1
          fi
        fi
      done
    fi

    # Commit the config sync. The updater used to commit only $prefix/, leaving
    # .claude/ and plugins/ permanently dirty in every instance repo.
    if git -C "$path" rev-parse --git-dir >/dev/null 2>&1; then
      if ! ( cd "$path" &&
        if git ls-files --error-unmatch plugins/memory-lifecycle \
            >/dev/null 2>&1; then
          git rm -r -q --cached plugins/memory-lifecycle
        fi &&
        { stage_config_sync "$path" || { unstage_scope "$path" .claude/ plugins/; false; }; } &&
        if ! git diff --cached --quiet 2>/dev/null; then
          guarded_commit "$path" \
            "chore: sync .claude config + plugins from skeleton $(date +%Y-%m-%d)"
        fi
      ); then
        CONFIG_FAILED=1
      fi
    else
      CONFIG_FAILED=1
    fi

    if [ "$CONFIG_FAILED" != "0" ]; then
      echo "  ERROR: config sync did not reach a complete committed state"
      cleanup_dry_model
      FAIL=$((FAIL + 1))
      echo ""
      continue
    fi

    echo "  Config synced"
  fi

  # Post-sync capability gate (structure/wiring/data diff, no test execution —
  # the FULL per-instance run is fleet-capability-verify.py's job). This is the
  # deterministic instance-side call site: a skeleton-only artifact or missing
  # declared file goes loud HERE, at the moment it ships, not months later
  # (finding-2, prd-silent-absence-capability-gate-2026-07-23). Failures are
  # collected, not fatal per-instance, so one red instance cannot block the
  # fix from reaching the other 23; the run still exits non-zero at the end.
  GATE_SCRIPT="$path/q-system/.q-system/scripts/capability-gate.py"
  if [ -z "${DRY_RUN:-}" ]; then
    if [ -f "$GATE_SCRIPT" ]; then
      if python3 "$GATE_SCRIPT" --repo-root "$path" --check-only >"/tmp/kipi-gate-$$.log" 2>&1; then
        echo "  capability gate: GREEN"
      else
        echo "  capability gate: RED"
        tail -8 "/tmp/kipi-gate-$$.log" | sed 's/^/    /'
        GATE_FAIL="$GATE_FAIL $name"
      fi
      rm -f "/tmp/kipi-gate-$$.log"
    else
      # Post-sync and STILL no gate script = the sync itself failed to deliver
      # the fix. Silent skip here would be the disease this gate treats.
      echo "  capability gate: MISSING after sync"
      GATE_FAIL="$GATE_FAIL $name(missing-gate)"
    fi
  fi
  if [ "$MODEL_RUN" = "1" ]; then
    MODELED_DIFF="$(git -C "$path" diff --name-status "$ORIGINAL_HEAD" HEAD --)"
    MODELED_TREE="$(git -C "$path" rev-parse 'HEAD^{tree}')"
    MODELED_STATE="$(worktree_digest "$path")"
    if [ -n "$MODELED_DIFF" ]; then
      echo "  Changes vs skeleton (modeled final state):"
    else
      echo "  Up to date"
    fi
    echo "  MODELED_FINAL_DIFF_BEGIN $name"
    if [ -n "$MODELED_DIFF" ]; then
      printf '%s\n' "$MODELED_DIFF"
    fi
    echo "  MODELED_FINAL_DIFF_END $name"
    echo "  MODELED_FINAL_TREE $name $MODELED_TREE"
    echo "  MODELED_FINAL_STATE_SHA256 $name $MODELED_STATE"
    cleanup_dry_model
    path="$ORIGINAL_PATH"
  fi
  echo ""
done < <(python3 -c "
import json
d = json.load(open('$REGISTRY'))
for i in d['instances']:
    if 'status' in i and i['status'].startswith('merged'):
        continue
    t = i.get('type', 'subtree')
    prefix = i.get('subtree_prefix') or ''
    print(i['name'] + '|' + i['path'] + '|' + prefix + '|' + t)
")

if [ -n "$ONLY" ] && [ "$((PASS+FAIL+SKIP))" -eq 0 ]; then
  echo "ERROR: no registered instance named '$ONLY'" >&2
  exit 1
fi

echo "=== Summary ==="
echo "  Updated: $PASS"
echo "  Failed:  $FAIL"
echo "  Skipped: $SKIP"
if [ -n "${GATE_FAIL:-}" ]; then
  echo "  CAPABILITY GATE RED in:$GATE_FAIL"
fi

[ "$FAIL" -eq 0 ] && [ -z "${GATE_FAIL:-}" ] && exit 0 || exit 1
