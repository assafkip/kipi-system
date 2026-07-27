#!/usr/bin/env bash
# Continuation of repro B: does the prompt's exact push command destroy the
# approved commits on the remote branch?
set -uo pipefail
W2="$(ls -d /Users/assafkipnis/projects/kipi-system/.pr25rev/reset-* | head -1)"
T="$W2/state/worktrees/ask-aaa"
APPROVED="$(git -C "$W2/origin" rev-parse sana/ask-aaa)"
echo "remote sana/ask-aaa BEFORE : $APPROVED  ($(git -C "$W2/origin" log -1 --pretty=%s sana/ask-aaa))"
echo "--- the agent runs the prompt's commands, verbatim, in the tree it was handed:"
git -C "$T" fetch -q origin
git -C "$T" rebase origin/main 2>&1 | sed 's/^/    rebase: /'
git -C "$T" push --force-with-lease origin sana/ask-aaa 2>&1 | sed 's/^/    push  : /'
AFTER="$(git -C "$W2/origin" rev-parse sana/ask-aaa)"
echo "remote sana/ask-aaa AFTER  : $AFTER  ($(git -C "$W2/origin" log -1 --pretty=%s sana/ask-aaa))"
if git -C "$W2/origin" merge-base --is-ancestor "$APPROVED" sana/ask-aaa 2>/dev/null; then
  echo "RESULT: approved commit STILL on the remote branch"
else
  echo "RESULT: the approved commit is GONE from the remote branch (PR diff destroyed)"
fi
