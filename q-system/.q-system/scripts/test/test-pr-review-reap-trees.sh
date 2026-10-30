#!/bin/bash
# ASK-3506: pr-review-agent.sh removes the review trees of merged or closed PRs
# at the start of a run and never touches an open PR's tree, the PR under review,
# a tree with a live lock holder, or a tree whose PR state cannot be read.
# Scar: 2026-10-30, 22 merged-PR trees (12 GB) filled the disk to 313 MiB free.
# Drives the REAL function, sliced out of pr-review-agent.sh, in a throwaway repo
# with a fake HOME and a stub gh. Nothing here names a real path or repo.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENT="$HERE/../pr-review-agent.sh"
LIB="$HERE/../repo-slug-lib.sh"
T="$(mktemp -d)"
fail=0
check() { if eval "$2"; then echo "PASS $1"; else echo "FAIL $1"; fail=1; fi; }

awk '/^reap_finished_review_trees\(\)/{f=1} f{print} f&&/^}$/{exit}' "$AGENT" > "$T/reap.sh"
awk '/^_wt_rows\(\)/{on=1} on{print} on&&/^}$/{exit}' "$AGENT" > "$T/rows.sh"
check "slices hold the function and _wt_rows" \
  'grep -q "^reap_finished_review_trees()" "$T/reap.sh" && grep -q "^_wt_rows()" "$T/rows.sh"'

mkdir -p "$T/bin" "$T/home/.config/kipi/review-trees" "$T/repo"
git -C "$T/repo" init -q
git -C "$T/repo" -c user.name=t -c user.email=t@example.invalid commit -q --allow-empty -m init
RT="$T/home/.config/kipi/review-trees"
# Keys come from the real path builder, so the fixture cannot drift from it.
source "$LIB"
SLUG="acme/widgets"
tree() { git -C "$T/repo" worktree add -q --detach "$(review_tree_path "$T/home/.config/kipi" "$SLUG" "$1")" HEAD; }
path_of() { review_tree_path "$T/home/.config/kipi" "$SLUG" "$1"; }
tree 11   # merged
tree 12   # closed
tree 13   # open: the negative control
tree 14   # the PR under review
tree 15   # merged but a live run holds its lock
tree 16   # state unreadable (gh fails)
tree 17   # merged but DIRTY: an untracked file (ASK-3508 negative control)
tree 18   # merged but a live process stands in it (ASK-3508 negative control)
tree 19   # merged and clean and idle: positive control for the new checks
git -C "$T/repo" worktree add -q --detach "$RT/other_repo__pr-11" HEAD   # another repo's key
git -C "$T/repo" worktree add -q --detach "$T/bystander" HEAD           # not a review tree
printf 'unsaved' > "$(path_of 17)/untracked.txt"
(cd "$(path_of 18)" && exec sleep 300) & CWDPROC=$!
sleep 300 & LIVE=$!
printf '%s' "$LIVE" > "$(path_of 15).lock"

cat > "$T/bin/gh" <<'EOF'
#!/bin/bash
n="$3"
case "$n" in
  11|15|17|18|19|99) echo MERGED ;; 12) echo CLOSED ;; 13|14) echo OPEN ;; *) exit 1 ;;
esac
EOF
chmod +x "$T/bin/gh"
for tool in bash env git cat awk cut grep rm kill printf tr sed dirname lsof; do ln -sf "$(command -v "$tool")" "$T/bin/$tool"; done

cat > "$T/drive.sh" <<EOF
REVIEW_REPO="$T/repo"; REVIEW_SLUG="$SLUG"; PR=14; KIPI_GH_REPO_ARGS=""
source "$LIB"
source "$T/rows.sh"
source "$T/reap.sh"
reap_finished_review_trees
EOF
HOME="$T/home" PATH="$T/bin" "$T/bin/bash" "$T/drive.sh" > "$T/out" 2>"$T/err"
echo "drive rc=$?"; cat "$T/out"

check "merged PR tree is removed (red before the fix: nothing removed it)" '[ ! -e "$(path_of 11)" ]'
check "closed PR tree is removed" '[ ! -e "$(path_of 12)" ]'
check "removed trees are unregistered from the repo" \
  '! git -C "$T/repo" worktree list | grep -q "__pr-11\$"'
check "NEGATIVE CONTROL: an open PR tree stays" '[ -d "$(path_of 13)" ]'
check "the PR under review keeps its tree" '[ -d "$(path_of 14)" ]'
check "a merged PR with a live lock holder keeps its tree" '[ -d "$(path_of 15)" ]'
check "an unreadable PR state keeps the tree" '[ -d "$(path_of 16)" ]'
check "another repo's key is never touched" '[ -d "$RT/other_repo__pr-11" ]'
check "a non-review worktree is never touched" '[ -d "$T/bystander" ]'
check "ASK-3508 a merged tree with an untracked file stays" '[ -f "$(path_of 17)/untracked.txt" ]'
check "ASK-3508 the dirty skip is named" 'grep -q "skip: PR 17 tree has uncommitted" "$T/out"'
check "ASK-3508 a merged tree that is a live process cwd stays" '[ -d "$(path_of 18)" ]'
check "ASK-3508 the live-cwd skip is named" 'grep -q "skip: PR 18 tree is the cwd" "$T/out"'
check "ASK-3508 a clean idle merged tree is still removed" '[ ! -e "$(path_of 19)" ]'
check "one cleanup line is printed" '[ "$(grep -c "review-tree cleanup:" "$T/out")" = 1 ]'
check "the line counts 3 removed" 'grep -q "removed 3 finished" "$T/out"'

kill "$LIVE" "$CWDPROC" 2>/dev/null
exit "$fail"
