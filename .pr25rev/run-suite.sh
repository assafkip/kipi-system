#!/usr/bin/env bash
# Run the PR-25 severity-floor suite from the PR's own worktree, with TMPDIR
# pointed at a sandbox-writable scratch dir.
REPO="/Users/assafkipnis/projects/kipi-system"
TREE="${1:-/Users/assafkipnis/.config/kipi/worktrees/ask-212}"
export TMPDIR="$REPO/.pr25rev/tmp/"
mkdir -p "$TMPDIR"
bash "$TREE/q-system/.q-system/scripts/test/test-severity-floor.sh"
echo "SUITE RC=$?"
