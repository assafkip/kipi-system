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

PASS=0
FAIL=0
SKIP=0

while IFS='|' read -r name path prefix itype; do
  echo "--- $name ($itype) ---"

  if [ ! -d "$path" ]; then
    echo "  SKIP: path $path does not exist"
    SKIP=$((SKIP + 1))
    echo ""
    continue
  fi

  if [ "$DRY_RUN" != "--dry-run" ]; then
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
      git add -u 2>/dev/null || true
      git commit --no-verify --no-gpg-sign -m "chore: auto-commit before kipi update" </dev/null 2>/dev/null || true
    fi
  fi

  if [ "$itype" = "direct-clone" ]; then
    echo "  Direct clone - pulling from origin..."
    if [ "$DRY_RUN" != "--dry-run" ]; then
      git fetch origin "$SKELETON_BRANCH" --quiet 2>/dev/null || true
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
    else
      cd "$path"
      git fetch origin "$SKELETON_BRANCH" --quiet 2>/dev/null || true
      BEHIND=$(git rev-list --count HEAD..origin/"$SKELETON_BRANCH" 2>/dev/null) || BEHIND="?"
      echo "  $BEHIND commits behind origin/$SKELETON_BRANCH"
      if [ "$BEHIND" != "0" ] && [ "$BEHIND" != "?" ]; then
        git log --oneline -5 HEAD..origin/"$SKELETON_BRANCH" 2>/dev/null | while read -r line; do echo "    $line"; done || true
      fi
      PASS=$((PASS + 1))
    fi
  else
    # Archive + rsync: fast, reliable, no history walking
    echo "  Syncing $prefix/ from skeleton..."
    if [ "$DRY_RUN" != "--dry-run" ]; then
      ARCHIVE_TMP=$(mktemp -d)
      if git -C "$SCRIPT_DIR" archive --format=tar HEAD -- q-system/ 2>/dev/null | tar -x -C "$ARCHIVE_TMP" 2>/dev/null; then
        # Snapshot untracked instance files before the destructive --delete.
        # `git ls-files --others` lists untracked files INCLUDING gitignored ones
        # (so it covers q-system/sources/ etc. that `git stash -u` would miss).
        # Lives inside ARCHIVE_TMP so the existing rm -rf cleans it -- no stash stack,
        # no extra cleanup, collision-safe.
        SNAP="$ARCHIVE_TMP/.snap"; mkdir -p "$SNAP/f"
        ( cd "$path" && git ls-files -z --others -- "$prefix/" \
            ":(exclude)$prefix/my-project/" ":(exclude)$prefix/canonical/" \
            ":(exclude)$prefix/memory/" ":(exclude)$prefix/output/" \
            ":(exclude)$prefix/.q-system/agent-pipeline/bus/" 2>/dev/null ) > "$SNAP/list" || true
        ( cd "$path" && while IFS= read -r -d '' uf; do
            mkdir -p "$SNAP/f/$(dirname "$uf")" && cp -a "$uf" "$SNAP/f/$uf" 2>/dev/null || true
          done < "$SNAP/list" )
        rsync -a --delete "$ARCHIVE_TMP/q-system/" "$path/$prefix/" \
          --exclude="my-project/" \
          --exclude="canonical/" \
          --exclude="memory/" \
          --exclude="output/" \
          --exclude=".q-system/agent-pipeline/bus/" 2>/dev/null
        # Restore any untracked file the rsync --delete removed (skeleton doesn't manage it).
        ( cd "$path" && while IFS= read -r -d '' uf; do
            if ! { [ -e "$uf" ] || [ -L "$uf" ]; } && { [ -e "$SNAP/f/$uf" ] || [ -L "$SNAP/f/$uf" ]; }; then
              mkdir -p "$(dirname "$uf")" && cp -a "$SNAP/f/$uf" "$uf" && echo "  restored untracked: $uf"
            fi
          done < "$SNAP/list" )
        rm -rf "$ARCHIVE_TMP"
        cd "$path"
        git add "$prefix/" 2>/dev/null || true
        CHANGES=$(git diff --cached --name-only 2>/dev/null | wc -l | tr -d ' ')
        if [ "$CHANGES" != "0" ]; then
          git commit --no-verify --no-gpg-sign -m "chore: sync q-system from skeleton $(date +%Y-%m-%d)" </dev/null 2>/dev/null || true
          echo "  OK ($CHANGES files updated)"
        else
          echo "  OK (already up to date)"
        fi
        PASS=$((PASS + 1))
      else
        rm -rf "$ARCHIVE_TMP"
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
          --exclude="my-project/" --exclude="canonical/" --exclude="memory/" \
          --exclude="output/" --exclude=".q-system/agent-pipeline/bus/" 2>/dev/null)
        if [ -n "$CHANGED" ]; then
          echo "  Changes vs skeleton (run without --dry to apply):"
          echo "$CHANGED" | sed 's/^/    /'
        else
          echo "  Up to date"
        fi
        rm -rf "$DRY_TMP"
      else
        rm -rf "$DRY_TMP"
        echo "  WARN: archive export failed (dry)"
      fi
      PASS=$((PASS + 1))
    fi
  fi

  # Sync settings, agents, rules, output styles, and plugins
  if [ "$DRY_RUN" != "--dry-run" ] && [ -d "$path/.claude" ]; then
    echo "  Syncing .claude/ config..."

    # Rebuild settings.json from template (preserves instance customizations)
    if [ -f "$path/.claude/settings.json" ]; then
      python3 -c "
import json, sys

template = json.load(open('$SCRIPT_DIR/settings-template.json'))
existing = json.load(open('$path/.claude/settings.json'))
merged = dict(template)

# Preserve instance MCP servers (all, including disabled _prefixed)
if 'mcpServers' in existing:
    merged['mcpServers'] = dict(template.get('mcpServers', {}))
    for k, v in existing['mcpServers'].items():
        merged['mcpServers'][k] = v

# Preserve instance-specific enabled plugins (additive merge)
if 'enabledPlugins' in existing:
    merged['enabledPlugins'] = dict(template.get('enabledPlugins', {}))
    merged['enabledPlugins'].update(existing['enabledPlugins'])

# Preserve instance-specific permission additions (merge allow lists)
if 'permissions' in existing and 'allow' in existing['permissions']:
    template_allow = set(template.get('permissions', {}).get('allow', []))
    instance_allow = set(existing['permissions']['allow'])
    merged['permissions']['allow'] = sorted(template_allow | instance_allow)

# Preserve instance tool configurations (additive merge)
if 'toolConfigurations' in existing:
    merged['toolConfigurations'] = dict(template.get('toolConfigurations', {}))
    merged['toolConfigurations'].update(existing['toolConfigurations'])

# Preserve instance model override if different from template
if existing.get('model') and existing.get('model') != template.get('model'):
    merged['model'] = existing['model']

# Preserve instance-added HOOKS (union template + instance per event+matcher, dedupe by
# command). Without this the merge dropped instance hooks every update -- the
# kipi-update-clobbers-instance-files failure that wiped skill-hook gating. Template hook
# updates still apply; instance-added lint/gate hooks survive.
if 'hooks' in existing or 'hooks' in template:
    merged_hooks = {}
    events = set(list(template.get('hooks', {})) + list(existing.get('hooks', {})))
    for event in events:
        groups = template.get('hooks', {}).get(event, []) + existing.get('hooks', {}).get(event, [])
        by_matcher = {}
        order = []
        for grp in groups:
            m = grp.get('matcher', '')
            if m not in by_matcher:
                by_matcher[m] = {'matcher': m, 'hooks': [], '_seen': set()}
                order.append(m)
            for h in grp.get('hooks', []):
                cmd = h.get('command', '')
                if cmd not in by_matcher[m]['_seen']:
                    by_matcher[m]['_seen'].add(cmd)
                    by_matcher[m]['hooks'].append(h)
        merged_hooks[event] = [{'matcher': by_matcher[m]['matcher'], 'hooks': by_matcher[m]['hooks']}
                               if by_matcher[m]['matcher'] else {'hooks': by_matcher[m]['hooks']}
                               for m in order]
    merged['hooks'] = merged_hooks

json.dump(merged, open('$path/.claude/settings.json', 'w'), indent=2)
print('    settings.json updated (MCP, plugins, permissions, tools, hooks preserved)')
" 2>/dev/null || echo "    WARN: settings.json sync failed"

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
    mkdir -p "$path/.claude/agents" "$path/.claude/output-styles" "$path/.claude/rules"
    cp "$SCRIPT_DIR"/.claude/agents/*.md "$path/.claude/agents/" 2>/dev/null || true
    cp "$SCRIPT_DIR"/.claude/output-styles/*.md "$path/.claude/output-styles/" 2>/dev/null || true
    cp "$SCRIPT_DIR"/.claude/rules/*.md "$path/.claude/rules/" 2>/dev/null || true

    # Sync plugins (copy contents, not directory, to avoid plugins/plugins/ nesting)
    if [ -d "$SCRIPT_DIR/plugins" ]; then
      mkdir -p "$path/plugins"
      for plugin_dir in "$SCRIPT_DIR"/plugins/*/; do
        if [ -d "$plugin_dir" ]; then
          plugin_name="$(basename "$plugin_dir")"
          rm -rf "$path/plugins/$plugin_name"
          cp -R "$plugin_dir" "$path/plugins/$plugin_name"
        fi
      done
    fi

    echo "  Config synced"
  fi
  echo ""
done < <(python3 -c "
import json
d = json.load(open('$REGISTRY'))
for i in d['instances']:
    if 'status' in i and i['status'].startswith('merged'):
        continue
    t = i.get('type', 'subtree')
    prefix = i.get('subtree_prefix', 'q-system')
    print(i['name'] + '|' + i['path'] + '|' + prefix + '|' + t)
")

echo "=== Summary ==="
echo "  Updated: $PASS"
echo "  Failed:  $FAIL"
echo "  Skipped: $SKIP"

[ "$FAIL" -eq 0 ] && exit 0 || exit 1
