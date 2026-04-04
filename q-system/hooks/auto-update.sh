#!/bin/bash
set -euo pipefail

# Auto-update hook - checks for and pulls skeleton updates on session start.
# Runs as part of SessionStart hook in instances.
# Only pulls if: (1) git repo, (2) has q-system subtree, (3) remote has new commits.
# Exit 0 always (never blocks session start).

PROJ_DIR="${CLAUDE_PROJECT_DIR:-.}"
# Auto-detect: subtree instances have q-system/q-system/, skeleton has q-system/
if [ -d "$PROJ_DIR/q-system/q-system/canonical" ]; then
  SENTINEL_DIR="$PROJ_DIR/q-system/q-system/output"
else
  SENTINEL_DIR="$PROJ_DIR/q-system/output"
fi
TODAY=$(date '+%Y-%m-%d')
SENTINEL="$SENTINEL_DIR/.update-check-$TODAY"

# Only check once per day
if [ -f "$SENTINEL" ]; then
  exit 0
fi

mkdir -p "$SENTINEL_DIR"

# Must be a git repo with q-system subtree
if [ ! -d "$PROJ_DIR/.git" ] || [ ! -d "$PROJ_DIR/q-system" ]; then
  exit 0
fi

cd "$PROJ_DIR"

# Check if remote has updates (timeout after 5 seconds)
REMOTE="https://github.com/assafkip/kipi-system.git"
REMOTE_HEAD=$(timeout 5 git ls-remote "$REMOTE" HEAD 2>/dev/null | cut -f1 || true)

if [ -z "$REMOTE_HEAD" ]; then
  # Can't reach remote, skip silently
  touch "$SENTINEL"
  exit 0
fi

# Check if we already have this commit
if git cat-file -e "$REMOTE_HEAD" 2>/dev/null; then
  # Already up to date
  touch "$SENTINEL"
  exit 0
fi

# Check for clean working tree before attempting pull
if ! git diff --quiet 2>/dev/null || ! git diff --cached --quiet 2>/dev/null; then
  # Dirty tree - skip silently (don't pollute session start with noise)
  touch "$SENTINEL"
  exit 0
fi

# Updates available - pull subtree
echo "=== Kipi Update Available ==="
echo "Pulling latest skeleton into q-system/..."

if git subtree pull --prefix=q-system "$REMOTE" main --squash -m "chore: auto-update kipi skeleton $(date '+%Y-%m-%d')" 2>&1; then
  echo "Updated successfully."
else
  echo "Update failed. Run 'kipi update' manually."
fi

touch "$SENTINEL"
exit 0
