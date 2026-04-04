#!/bin/bash
set -euo pipefail

# Git health check - runs on SessionStart
# Detects zombie rebases, in-progress merges, and local/remote divergence
# Always exits 0 (never blocks session start)

PROJ_DIR="${CLAUDE_PROJECT_DIR:-.}"
GIT_DIR="$PROJ_DIR/.git"
WARNINGS=""

# Check for zombie rebase
if [ -d "$GIT_DIR/rebase-merge" ] || [ -d "$GIT_DIR/rebase-apply" ]; then
  WARNINGS="${WARNINGS}--- WARNING: Git rebase in progress ---\nA previous rebase was not completed. Run 'git rebase --abort' to clean up.\n\n"
fi

# Check for in-progress merge
if [ -f "$GIT_DIR/MERGE_HEAD" ]; then
  WARNINGS="${WARNINGS}--- WARNING: Git merge in progress ---\nA previous merge was not completed. Run 'git merge --abort' to clean up.\n\n"
fi

# Check for in-progress cherry-pick
if [ -f "$GIT_DIR/CHERRY_PICK_HEAD" ]; then
  WARNINGS="${WARNINGS}--- WARNING: Git cherry-pick in progress ---\nA previous cherry-pick was not completed. Run 'git cherry-pick --abort' to clean up.\n\n"
fi

# Fetch and check for divergence (quiet, best-effort)
if git -C "$PROJ_DIR" fetch origin --quiet 2>/dev/null; then
  LOCAL_AHEAD=$(git -C "$PROJ_DIR" rev-list --count origin/main..HEAD 2>/dev/null || echo "0")
  REMOTE_AHEAD=$(git -C "$PROJ_DIR" rev-list --count HEAD..origin/main 2>/dev/null || echo "0")

  if [ "$LOCAL_AHEAD" -gt 0 ] && [ "$REMOTE_AHEAD" -gt 0 ]; then
    WARNINGS="${WARNINGS}--- WARNING: Local and remote have diverged ---\nLocal has ${LOCAL_AHEAD} commit(s) not on remote. Remote has ${REMOTE_AHEAD} commit(s) not on local.\nRun 'git merge origin/main' to reconcile.\n\n"
  elif [ "$LOCAL_AHEAD" -gt 0 ]; then
    echo "--- Git: ${LOCAL_AHEAD} unpushed commit(s) ---"
  elif [ "$REMOTE_AHEAD" -gt 0 ]; then
    echo "--- Pulling ${REMOTE_AHEAD} new commit(s) from remote ---"
    git -C "$PROJ_DIR" pull --ff-only 2>/dev/null || \
      WARNINGS="${WARNINGS}--- WARNING: Cannot fast-forward from remote ---\nRun 'git pull' manually to update.\n\n"
  fi
fi

# Output warnings if any
if [ -n "$WARNINGS" ]; then
  echo -e "$WARNINGS"
fi

exit 0
