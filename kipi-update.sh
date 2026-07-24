#!/bin/bash
set -euo pipefail
trap "" PIPE
# Never let an instance's git hooks, GPG signing, or a credential prompt hang the
# updater. These are infra commits made by kipi, not content commits; instance
# pre-commit hooks (e.g. gitleaks on thousands of staged files) must not run here.
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
DRY_RUN="${1:-}"

if [ ! -f "$REGISTRY" ]; then
  echo "ERROR: instance-registry.json not found at $REGISTRY"
  exit 1
fi

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

trap cleanup_updater_temps EXIT

while IFS='|' read -r name path prefix itype; do
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

root = pathlib.Path(sys.argv[1]).resolve()
for current, directories, files in os.walk(root, followlinks=False):
    for name in directories + files:
        candidate = pathlib.Path(current, name)
        if not candidate.is_symlink():
            continue
        target = os.readlink(candidate)
        if os.path.isabs(target):
            print(f"unsafe absolute symlink: {candidate.relative_to(root)} -> {target}", file=sys.stderr)
            raise SystemExit(1)
        resolved = (candidate.parent / target).resolve(strict=False)
        try:
            resolved.relative_to(root)
        except ValueError:
            print(f"unsafe symlink escapes instance: {candidate.relative_to(root)} -> {os.readlink(candidate)}", file=sys.stderr)
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
    MODEL_SETUP_FAILED=0
    if [ -d "$path/.git" ]; then
      if ! mkdir -p "$DRY_MODEL_ROOT/instance" ||
          ! rsync -a --delete --exclude=".git" "$path/" \
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
            ! rsync -a --delete --exclude=".git" "$path/" \
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

    # Auto-commit tracked modified files so working tree is clean
    if ! git diff --quiet 2>/dev/null || ! git diff --cached --quiet 2>/dev/null; then
      echo "  Auto-committing modified tracked files..."
      if ! git add -u 2>/dev/null ||
          { ! git diff --cached --quiet 2>/dev/null &&
            ! git commit --no-verify --no-gpg-sign \
              -m "chore: auto-commit before kipi update" \
              </dev/null 2>/dev/null; }; then
        echo "  ERROR: could not auto-commit tracked changes"
        git status --short 2>/dev/null | sed 's/^/    /' || true
        cleanup_dry_model
        FAIL=$((FAIL + 1))
        echo ""
        continue
      fi
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
            ":(exclude)$prefix/my-project/" ":(exclude)$prefix/canonical/" \
            ":(exclude)$prefix/memory/" ":(exclude)$prefix/output/" \
            ":(exclude)$prefix/.q-system/agent-pipeline/bus/" \
            ":(exclude)$prefix/q-system/" \
            ":(exclude)*.pyc" ":(exclude)*__pycache__*" 2>/dev/null ) > "$SNAP/list"; then
          echo "  ERROR: preservation snapshot inventory failed; rsync not started"
          rm -r -- "$ARCHIVE_TMP"
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
            --exclude="/my-project/" \
            --exclude="/canonical/" \
            --exclude="/memory/" \
            --exclude="/output/" \
            --exclude="/.q-system/agent-pipeline/bus/" 2>/dev/null; then
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
        if ! git add "$prefix/" 2>/dev/null; then
          echo "  ERROR: could not stage q-system sync"
          cleanup_dry_model
          FAIL=$((FAIL + 1))
          echo ""
          continue
        fi
        CHANGES=$(git diff --cached --name-only 2>/dev/null | wc -l | tr -d ' ')
        if [ "$CHANGES" != "0" ]; then
          if ! git commit --no-verify --no-gpg-sign \
              -m "chore: sync q-system from skeleton $(date +%Y-%m-%d)" \
              </dev/null 2>/dev/null; then
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
          --exclude="/my-project/" --exclude="/canonical/" --exclude="/memory/" \
          --exclude="/output/" --exclude="/.q-system/agent-pipeline/bus/" 2>/dev/null)
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
          if ! rsync -a --delete --delete-excluded \
              --exclude="/.git/" --exclude="__pycache__/" --exclude="*.pyc" \
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
        git add .claude/ plugins/ &&
        if ! git diff --cached --quiet 2>/dev/null; then
          git commit --no-verify --no-gpg-sign \
            -m "chore: sync .claude config + plugins from skeleton $(date +%Y-%m-%d)" \
            </dev/null 2>/dev/null
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

echo "=== Summary ==="
echo "  Updated: $PASS"
echo "  Failed:  $FAIL"
echo "  Skipped: $SKIP"
if [ -n "${GATE_FAIL:-}" ]; then
  echo "  CAPABILITY GATE RED in:$GATE_FAIL"
fi

[ "$FAIL" -eq 0 ] && [ -z "${GATE_FAIL:-}" ] && exit 0 || exit 1
