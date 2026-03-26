#!/bin/bash
set -euo pipefail

# kipi-push-upstream.sh - Push generic improvements from an instance back to the skeleton
# Usage: Run from an instance directory that has a q-system/ subtree
#   ./kipi-push-upstream.sh

SKELETON_REMOTE="https://github.com/assafkip/kipi-system.git"
SKELETON_BRANCH="main"
PREFIX="q-system"

# Safety check: are we in a git repo?
if [ ! -d .git ]; then
  echo "ERROR: Not in a git repo. Run from the instance root."
  exit 1
fi

# Safety check: does the subtree prefix exist?
if [ ! -d "$PREFIX" ]; then
  echo "ERROR: $PREFIX/ directory not found. Is this a kipi instance?"
  exit 1
fi

# Safety check: warn if instance-specific content might be in the subtree
echo "=== Pre-push safety check ==="
INSTANCE_CONTENT=$(grep -ril "KTLYST\|ktlyst\|CISO\|re-breach\|Assaf\|/Users/" "$PREFIX/" 2>/dev/null | grep -v ".git/" | head -5)
if [ -n "$INSTANCE_CONTENT" ]; then
  echo "WARNING: Instance-specific content found in $PREFIX/:"
  echo "$INSTANCE_CONTENT"
  echo ""
  echo "Pushing instance content to the skeleton will break other instances."
  echo "Remove instance-specific content first, then re-run."
  exit 1
fi

echo "  No instance-specific content detected in $PREFIX/"
echo ""
echo "=== Pushing to skeleton ==="
echo "  Remote: $SKELETON_REMOTE"
echo "  Branch: $SKELETON_BRANCH"
echo "  Prefix: $PREFIX"
echo ""

git subtree push --prefix="$PREFIX" "$SKELETON_REMOTE" "$SKELETON_BRANCH"

echo ""
echo "=== Done ==="
echo "Changes pushed to skeleton. Run kipi-update.sh to propagate to other instances."
