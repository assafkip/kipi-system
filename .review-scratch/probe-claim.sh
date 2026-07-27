#!/usr/bin/env bash
# Minimal probe: what does linear-claim.py return when cwd is a worktree whose
# skeleton moved (re-clone / rename)? The PR routes the claim through exactly
# this cwd.
set -uo pipefail
CLAIM="/Users/assafkipnis/projects/kipi-system/q-system/.q-system/scripts/linear-claim.py"
W="$(mktemp -d)"
unset KIPI_LINEAR_CLAIMS KIPI_SESSION_ID CLAUDE_SESSION_ID 2>/dev/null || true

git init -q --bare "$W/origin"
git init -q "$W/skel"
git -C "$W/skel" -c user.email=t@t.t -c user.name=t commit -q --allow-empty -m init
git -C "$W/skel" branch -M main
git -C "$W/skel" remote add origin "$W/origin"
git -C "$W/skel" push -q -u origin main
mkdir -p "$W/state/worktrees"
git -C "$W/skel" worktree add -q -B sana/ask-aaa "$W/state/worktrees/ask-aaa" origin/main

TREE="$W/state/worktrees/ask-aaa"
echo "=== healthy worktree ==="
( cd "$TREE" && git rev-parse --show-toplevel )
( cd "$TREE" && python3 "$CLAIM" claim ASK-AAA --agent sana --session s1 ); echo "  claim exit=$?"
( cd "$TREE" && python3 "$CLAIM" release ASK-AAA --agent sana --session s1 ); echo "  release exit=$?"

echo
echo "=== now the skeleton is moved/re-cloned; the worktree dir survives ==="
mv "$W/skel" "$W/skel-moved"
echo "  dir still present: $([ -d "$TREE" ] && echo yes || echo no)"
echo "  .git file says:    $(cat "$TREE/.git")"
echo "  rev-parse output:"
( cd "$TREE" && git rev-parse --show-toplevel ) 2>&1 | sed 's/^/    /'
echo "  claim from inside it:"
( cd "$TREE" && python3 "$CLAIM" claim ASK-AAA --agent sana --session s2 ) 2>&1 | sed 's/^/    /'
( cd "$TREE" && python3 "$CLAIM" claim ASK-AAA --agent sana --session s2 ) >/dev/null 2>&1
echo "  >>> claim EXIT CODE = $?   (3 == EXIT_COLLISION, which linear-worker.sh maps to 'claimed by another session')"
echo "workdir: $W"
