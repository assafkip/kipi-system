#!/usr/bin/env bash
# REPRO B: when the worktree is absent, a gate-30 rebase round hands the agent a
# tree force-RESET to origin/main -- i.e. containing ZERO of the approved PR's
# commits -- and the new conflict prompt tells it to `git push --force-with-lease
# origin <branch>`.
#
# linear-worker.sh:343  git worktree add -q -B "$BRANCH" "$TREE" origin/main
#   -B resets an EXISTING branch to origin/main. Pre-PR that only ever happened
#   on a REQUEST CHANGES rework (no force-push instruction). This PR is what
#   routes an APPROVED PR through that same line and then hands the agent an
#   explicit force-push command.
set -uo pipefail
REPO="/Users/assafkipnis/projects/kipi-system/.pr25rev/repo"
WORKER="$REPO/q-system/.q-system/scripts/linear-worker.sh"
REAL_PY="$(command -v python3)"; REAL_GIT="$(command -v git)"

W2="$REPO/../reset-$$"; mkdir -p "$W2/home"
G() { git -c user.email=t@t.t -c user.name=t "$@"; }
git init -q --bare "$W2/origin"
git init -q "$W2/skel"
G -C "$W2/skel" commit -q --allow-empty -m "base commit"
git -C "$W2/skel" branch -M main
git -C "$W2/skel" remote add origin "$W2/origin"
git -C "$W2/skel" push -q -u origin main

# The approved PR: two commits on sana/ask-aaa, pushed to origin.
git -C "$W2/skel" checkout -q -b sana/ask-aaa
echo "the approved feature" > "$W2/skel/feature.txt"
G -C "$W2/skel" add -A; G -C "$W2/skel" commit -q -m "feat: the approved work (ASK-AAA)"
git -C "$W2/skel" push -q -u origin sana/ask-aaa
APPROVED_SHA="$(git -C "$W2/skel" rev-parse sana/ask-aaa)"
git -C "$W2/skel" checkout -q main
# main moved underneath it -- this is what made the PR DIRTY.
echo "conflicting change" > "$W2/skel/feature.txt"
G -C "$W2/skel" add -A; G -C "$W2/skel" commit -q -m "main moved"
git -C "$W2/skel" push -q origin main

echo "--- approved PR head        : $APPROVED_SHA  ($(git -C "$W2/skel" log -1 --pretty=%s sana/ask-aaa))"
echo "--- origin/main             : $(git -C "$W2/skel" rev-parse origin/main)"

STUB="$W2/bin"; mkdir -p "$STUB"
cat > "$STUB/python3" <<EOF
#!/usr/bin/env bash
case "\${1:-}" in
  -)  cat >/dev/null
      printf '{"ready":[{"id":"ASK-AAA","title":"t","project":"p"}],"total_open":1}\n'
      exit 0 ;;
  *linear-sync.py) exit 0 ;;
esac
exec "$REAL_PY" "\$@"
EOF
# The dispatched agent: record the tree it was handed, then stop.
cat > "$STUB/claude" <<EOF
#!/usr/bin/env bash
cat > "$W2/prompt.txt"
exit 0
EOF
cat > "$W2/notify.sh" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
cat > "$STUB/gh" <<'EOF'
#!/usr/bin/env bash
case "$*" in
  "pr list"*)                             echo 777 ;;
  "pr view 777 --json mergeStateStatus"*) echo DIRTY ;;
esac
exit 0
EOF
chmod +x "$STUB/python3" "$STUB/claude" "$STUB/gh" "$W2/notify.sh"
export PATH="$STUB:$PATH"

S="$W2/state"; mkdir -p "$S/pr-reviews"
printf '{"verdict":"APPROVE WITH NITS","pr":777}\n' > "$S/pr-reviews/pr-777.verdict.json"
# NO worktree at $S/worktrees/ask-aaa -- the branch exists, the tree does not.
# (fresh machine / cleaned ~/.config/kipi / tree deleted by hand)

( cd "$W2/skel" && HOME="$W2/home" KIPI_SKEL="$W2/skel" KIPI_STATE_DIR="$S" \
    KIPI_NOTIFY="$W2/notify.sh" bash "$WORKER" --apply --issue ASK-AAA --limit 1 ) \
  > "$W2/run.out" 2>&1
grep -iE "dispatching|skip" "$W2/run.out" | sed 's/^/    /'

TREE="$S/worktrees/ask-aaa"
echo "--- the worktree the rebase agent was handed: $TREE"
echo "    HEAD sha  : $(git -C "$TREE" rev-parse HEAD)"
echo "    branch    : $(git -C "$TREE" rev-parse --abbrev-ref HEAD)"
echo "    log       : $(git -C "$TREE" log --oneline -3 | tr '\n' ' | ')"
echo "    approved commit still reachable from HEAD? $(git -C "$TREE" merge-base --is-ancestor "$APPROVED_SHA" HEAD 2>/dev/null && echo YES || echo NO)"
echo "    feature.txt content: $(cat "$TREE/feature.txt" 2>/dev/null)"
echo "--- the push command the prompt gave that agent:"
grep -n "force-with-lease" "$W2/prompt.txt" | sed 's/^/    /'
echo "--- W2=$W2"
