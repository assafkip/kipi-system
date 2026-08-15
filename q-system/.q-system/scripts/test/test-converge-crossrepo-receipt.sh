#!/usr/bin/env bash
# Pairs with receipt_tree() in converge.sh (ASK-821).
#
# THE DEFECT: receipt_tree searched $SKEL -- the skeleton, and post-ASK-447 the
# PINNED kipi-system checkout -- for a worktree on the issue branch. But
# linear-worker.sh cuts that branch in the repo the work is FOR. So for every
# cross-repo issue the search was guaranteed to miss, the receipt was skipped,
# and the PR went green and sat with nothing proving it was reviewed.
#
# Measured on the first real cross-repo run, 2026-08-15T00:21:54Z, ASK-144 in a
# non-home dispatch repo. It was unreachable before that: dispatch was capped at
# 1 and bound to the home repo, so no cross-repo run had ever completed.
#
# NO INSTANCE IS NAMED HERE, DELIBERATELY. This file ships to every instance and
# validate-separation Gate 1.2 sweeps skeleton files for live instance names. The
# founder flagged this exact trap before I started and I walked into it anyway:
# the first cut named the repo in both this file and converge.sh, and CI refused
# the PR. A text check cannot tell a rule from a mention of one.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONVERGE="$HERE/../converge.sh"
[ -f "$CONVERGE" ] || { echo "FATAL: no converge.sh at $CONVERGE" >&2; exit 1; }

PASS=0; FAIL=0
ok()  { echo "  PASS: $*"; PASS=$((PASS+1)); }
bad() { echo "  FAIL: $*"; FAIL=$((FAIL+1)); }
# THE TEMP DIR IS VALIDATED BEFORE IT IS EVER RESOLVED, AND THE CLEANUP REFUSES
# ANYTHING THAT IS NOT A TEMP DIR (codex blocker, PR #181).
#
# The first cut was  WORK="$(cd "$(mktemp -d)" && pwd -P)"  which is a repo
# shredder waiting for a bad day. In bash, cd with an empty operand SUCCEEDS as a
# no-op. So if mktemp ever failed -- full disk, TMPDIR pointing somewhere
# unwritable -- the substitution collapsed to a cd that went nowhere followed by
# pwd -P, WORK became the CURRENT DIRECTORY (this checkout), and the EXIT trap
# recursively deleted the founder's working tree along with any uncommitted work.
#
# So: capture, prove it is a real temp directory, and only then resolve it. The
# cleanup re-checks at DELETION TIME rather than trusting the assignment, because
# a guard that runs only once cannot protect against anything that reassigns WORK
# later.
WORK="$(mktemp -d)" || { echo "FATAL: mktemp failed" >&2; exit 1; }
case "$WORK" in
  /tmp/*|/private/tmp/*|/var/folders/*|/private/var/folders/*) : ;;
  *) echo "FATAL: mktemp returned an unexpected path: '$WORK'" >&2; exit 1 ;;
esac
[ -d "$WORK" ] || { echo "FATAL: mktemp path is not a directory: '$WORK'" >&2; exit 1; }
# PHYSICAL path. On macOS /var is a symlink to /private/var, so mktemp hands back
# /var/... while `git worktree list` reports the RESOLVED /private/var/...
# Comparing the two made a correct fix read as a failure on the first run.
WORK="$(cd "$WORK" && pwd -P)" || { echo "FATAL: could not resolve temp dir" >&2; exit 1; }

cleanup() {
  # Re-checked HERE, because this is the line that actually deletes.
  case "${WORK:-}" in
    /tmp/*|/private/tmp/*|/var/folders/*|/private/var/folders/*)
      [ -d "$WORK" ] && /bin/rm -rf -- "$WORK" ;;
    *) echo "cleanup refused: WORK is not a temp dir ('${WORK:-unset}')" >&2 ;;
  esac
}
trap cleanup EXIT

# Two throwaway repos: a stand-in skeleton and a stand-in target. The branch
# exists ONLY in the target, which is the whole point.
mk() {
  git init -q -b main "$1"
  ( cd "$1" && git config user.email t@e.com && git config user.name t \
    && echo x > f && git add f && git commit -qm init )
}
mk "$WORK/skel"; mk "$WORK/target"
git -C "$WORK/target" branch sana/ask-999
git -C "$WORK/target" worktree add -q "$WORK/tree999" sana/ask-999

# receipt_tree cut from the shipped file, so this exercises real code rather than
# a restatement that could pass forever while converge.sh drifted.
FN="$WORK/fn.sh"
sed -n '/^receipt_tree() {/,/^}$/p' "$CONVERGE" > "$FN"
grep -q 'worktree list' "$FN" \
  || { echo "FATAL: could not extract receipt_tree from $CONVERGE" >&2; exit 1; }

echo "== the branch lives in the TARGET repo, not the skeleton =="
FOUND="$(SKEL="$WORK/skel" TARGET_REPO="$WORK/target" bash -c ". '$FN'; receipt_tree sana/ask-999")"
[ "$FOUND" = "$WORK/tree999" ] \
  && ok "receipt_tree finds the worktree in the target repo" \
  || bad "receipt_tree did not find the target's worktree (got: '${FOUND:-empty}')"

echo "== NEGATIVE: the old \$SKEL behaviour must FAIL this =="
# Rebuild the pre-fix line and prove it returns nothing. Without this, the case
# above cannot tell a real fix from a test that would have passed either way.
sed 's|git -C "$TARGET_REPO" worktree list|git -C "$SKEL" worktree list|' "$FN" > "$WORK/fn-old.sh"
grep -q 'git -C "$SKEL" worktree list' "$WORK/fn-old.sh" \
  || bad "the mutant was not applied, so this negative proves nothing"
OLD="$(SKEL="$WORK/skel" TARGET_REPO="$WORK/target" bash -c ". '$WORK/fn-old.sh'; receipt_tree sana/ask-999")"
[ -z "$OLD" ] \
  && ok "the old \$SKEL lookup returns nothing -- this is the shipped defect" \
  || bad "the old lookup also found it, so the fix changed nothing (got: '$OLD')"

echo "== same-repo still works (TARGET_REPO defaults to SKEL) =="
# Guarding the fix against being its own bug: the home-repo path is the common
# case and must be untouched.
git -C "$WORK/skel" branch sana/ask-100
git -C "$WORK/skel" worktree add -q "$WORK/tree100" sana/ask-100
HOME_FOUND="$(SKEL="$WORK/skel" TARGET_REPO="$WORK/skel" bash -c ". '$FN'; receipt_tree sana/ask-100")"
[ "$HOME_FOUND" = "$WORK/tree100" ] \
  && ok "the home-repo path is unchanged" \
  || bad "the fix broke same-repo receipts (got: '${HOME_FOUND:-empty}')"

echo
echo "-------- $PASS passed, $FAIL failed --------"
[ "$FAIL" -eq 0 ] || exit 1
echo "PASS: converge-crossrepo-receipt"
