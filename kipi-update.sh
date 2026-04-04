#!/bin/bash
set -euo pipefail

# kipi-update.sh - Pull latest kipi-system skeleton into all registered instances
# Usage: ./kipi-update.sh [--dry-run]

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

    # Auto-stash dirty working tree
    STASHED=false
    if ! git diff --quiet 2>/dev/null || ! git diff --cached --quiet 2>/dev/null; then
      echo "  Stashing uncommitted changes..."
      git stash push -m "kipi-update auto-stash $(date '+%Y-%m-%d %H:%M')" 2>&1 || true
      STASHED=true
    fi
    # Also commit untracked files that would block subtree
    UNTRACKED=$(git ls-files --others --exclude-standard 2>/dev/null | head -1)
    if [ -n "$UNTRACKED" ]; then
      echo "  Auto-committing untracked files..."
      git add -A 2>/dev/null || true
      git commit -m "chore: auto-commit before kipi update" 2>/dev/null || true
    fi
  fi

  if [ "$itype" = "direct-clone" ]; then
    echo "  Direct clone - pulling from origin..."
    if [ "$DRY_RUN" != "--dry-run" ]; then
      if git pull --ff-only origin main 2>&1; then
        echo "  OK"
        PASS=$((PASS + 1))
      else
        # Try merge if ff-only fails
        echo "  Fast-forward failed, trying merge..."
        if git merge origin/main --no-edit 2>&1; then
          echo "  OK (merged)"
          PASS=$((PASS + 1))
        else
          echo "  WARN: merge failed (needs manual resolve)"
          git merge --abort 2>/dev/null || true
          FAIL=$((FAIL + 1))
        fi
      fi
    else
      echo "  (dry run - skipped)"
      PASS=$((PASS + 1))
    fi
  else
    echo "  Subtree pull into $prefix/"
    if [ "$DRY_RUN" != "--dry-run" ]; then
      if git subtree pull --prefix="$prefix" "$SKELETON_REMOTE" "$SKELETON_BRANCH" --squash 2>&1; then
        echo "  OK"
        PASS=$((PASS + 1))
      else
        echo "  WARN: subtree pull failed (may need manual resolve)"
        FAIL=$((FAIL + 1))
      fi
    else
      echo "  (dry run - skipped)"
      PASS=$((PASS + 1))
    fi
  fi

  # Pop stash if we stashed
  if [ "$DRY_RUN" != "--dry-run" ] && [ "$STASHED" = true ]; then
    echo "  Restoring stashed changes..."
    git stash pop 2>&1 || echo "  WARN: stash pop had conflicts, check manually"
  fi

  # Sync settings, agents, rules, output styles, and plugins
  if [ "$DRY_RUN" != "--dry-run" ] && [ -d "$path/.claude" ]; then
    echo "  Syncing .claude/ config..."

    # Rebuild settings.json from template (preserves instance MCP servers)
    if [ -f "$path/.claude/settings.json" ]; then
      python3 -c "
import json, sys
template = json.load(open('$SCRIPT_DIR/settings-template.json'))
existing = json.load(open('$path/.claude/settings.json'))
# Preserve instance-specific MCP servers (user configured)
if 'mcpServers' in existing:
    for k, v in existing['mcpServers'].items():
        if not k.startswith('_'):
            template['mcpServers'][k] = v
# Merge: template wins for hooks, permissions, top-level; instance wins for MCP
json.dump(template, open('$path/.claude/settings.json', 'w'), indent=2)
print('    settings.json updated (MCP servers preserved)')
" 2>/dev/null || echo "    WARN: settings.json sync failed"

      # Fix paths for subtree instances
      if [ "$itype" = "subtree" ]; then
        sed -i '' 's|/q-system/hooks/|/q-system/q-system/hooks/|g' "$path/.claude/settings.json" 2>/dev/null || true
        sed -i '' 's|/q-system/.q-system/|/q-system/q-system/.q-system/|g' "$path/.claude/settings.json" 2>/dev/null || true
      fi
    fi

    # Sync agents, output styles, rules
    cp "$SCRIPT_DIR"/.claude/agents/*.md "$path/.claude/agents/" 2>/dev/null || true
    cp "$SCRIPT_DIR"/.claude/output-styles/*.md "$path/.claude/output-styles/" 2>/dev/null || true
    cp "$SCRIPT_DIR"/.claude/rules/*.md "$path/.claude/rules/" 2>/dev/null || true

    # Sync plugins
    cp -R "$SCRIPT_DIR/.claude-plugin" "$path/.claude-plugin" 2>/dev/null || true
    cp -R "$SCRIPT_DIR/plugins" "$path/plugins" 2>/dev/null || true

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
