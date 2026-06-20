#!/bin/bash
set -euo pipefail

# Auto-update hook - checks for skeleton updates on session start and NUDGES the
# founder to run `kipi update` (it never auto-pulls; that path was dangerous).
# Runs as part of SessionStart hook in instances.
# Only NUDGES (never pulls -- run kipi update for the actual sync) if: (1) git repo,
# (2) has q-system subtree, (3) remote has new commits.
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
REMOTE="${KIPI_SKELETON_REMOTE:-https://github.com/assafkip/kipi-system.git}"
# Portable timeout: macOS has no `timeout` (it is `gtimeout` from coreutils, or absent).
# Without this the ls-remote silently failed on macOS and the nudge never fired.
if command -v timeout >/dev/null 2>&1; then _TO="timeout 5"
elif command -v gtimeout >/dev/null 2>&1; then _TO="gtimeout 5"
else _TO=""; fi
REMOTE_HEAD=$($_TO git ls-remote "$REMOTE" HEAD 2>/dev/null | cut -f1 || true)

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

# Updates available -- NUDGE ONLY. Never auto-pull from a SessionStart hook:
# the old git-subtree auto-pull here used the wrong prefix on real subtree instances
# and ran silently. `kipi update` is the single safe, tested propagation path.
echo "=== Kipi skeleton update available ==="
echo "    Run: kipi update"

touch "$SENTINEL"
exit 0
