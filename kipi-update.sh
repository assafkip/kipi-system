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

  if [ "$itype" = "direct-clone" ]; then
    echo "  Direct clone - use 'git pull' in $path"
    if [ "$DRY_RUN" != "--dry-run" ]; then
      cd "$path"
      if git pull --ff-only origin main 2>&1; then
        echo "  OK"
        PASS=$((PASS + 1))
      else
        echo "  WARN: pull failed (may need manual merge)"
        FAIL=$((FAIL + 1))
      fi
    else
      echo "  (dry run - skipped)"
      PASS=$((PASS + 1))
    fi
  else
    echo "  Subtree pull into $prefix/"
    if [ "$DRY_RUN" != "--dry-run" ]; then
      cd "$path"
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
