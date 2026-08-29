#!/usr/bin/env bash
# review_worktree must refresh refs/remotes/pr/<N>, not only HEAD (sp-690ba60b).
#
# WHY THIS EXISTS. The reviewer reuses one detached worktree per PR across
# rounds, re-detaching rather than removing. HEAD moved; refs/remotes/pr/<N> did
# not. The reviewer's reproducers read the PR through that ref
# (`git show pr/<N>:<file>`), so from round 2 onward it probed the code as it
# was in round 1 and re-raised findings the author had already fixed.
#
# Measured 2026-08-29: pr/253 sat at the pre-fix sha while the PR head had
# moved, and that round's verdict was issued without the fix in view. On
# ASK-353 the same staleness cost two whole rounds of re-raised findings before
# anyone looked at the ref instead of at the code.
#
# A gate reading the wrong input is worse than a gate that fails: it returns a
# confident verdict about a file that is not there.
#
# Isolation: builds its own repo in a tmpdir, sources only the one function
# under test, posts nothing, touches no network and no real review tree.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENT="${REVIEW_AGENT_SCRIPT:-$HERE/../pr-review-agent.sh}"
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  ok   $1"; }
bad() { FAIL=$((FAIL+1)); echo "  FAIL $1"; }

TMP="$(mktemp -d)"
cleanup() { [ -n "${TMP:-}" ] && chmod -R u+w "$TMP" 2>/dev/null; /bin/rm -rf -- "$TMP"; }
trap cleanup EXIT

REPO="$TMP/repo"; mkdir -p "$REPO"
git -C "$REPO" init -q
git -C "$REPO" config user.email t@t; git -C "$REPO" config user.name t
echo round1 > "$REPO/f.txt"; git -C "$REPO" add -A; git -C "$REPO" commit -qm r1
SHA1="$(git -C "$REPO" rev-parse HEAD)"
echo round2 > "$REPO/f.txt"; git -C "$REPO" add -A; git -C "$REPO" commit -qm r2
SHA2="$(git -C "$REPO" rev-parse HEAD)"

# Round 1 leaves the tree and the ref together, which is the state the real
# flow is in when a second round starts.
WT="$TMP/wt"
git -C "$REPO" worktree add --detach "$WT" "$SHA1" >/dev/null 2>&1
git -C "$WT" update-ref refs/remotes/pr/99 "$SHA1"

# Drive round 2 through the real function, pulled out of the agent by name so
# this test cannot drift from the implementation it claims to pin.
PR=99
REVIEW_REPO="$REPO"; REVIEW_SLUG="t/t"
eval "$(sed -n '/^review_worktree() {/,/^}/p' "$AGENT")"
review_tree_path() { echo "$WT"; }
review_worktree "$SHA2" >/dev/null 2>&1

HEADAT="$(git -C "$WT" rev-parse HEAD 2>/dev/null)"
REFAT="$(git -C "$WT" rev-parse refs/remotes/pr/99 2>/dev/null)"

[ "$HEADAT" = "$SHA2" ] && ok "round 2 moves HEAD to the new sha" \
                        || bad "round 2 moves HEAD to the new sha"

# THE POINT. This is the half that was broken.
[ "$REFAT" = "$SHA2" ] && ok "round 2 also moves refs/remotes/pr/<N>" \
                       || bad "round 2 also moves refs/remotes/pr/<N> (got ${REFAT:0:8}, want ${SHA2:0:8})"

# And the thing the reviewer would actually READ through that ref. Asserting the
# CONTENT, not just the sha: the sha check alone would still pass if some later
# change pointed the ref at the right commit in the wrong repository.
SEEN="$(git -C "$WT" show refs/remotes/pr/99:f.txt 2>/dev/null)"
[ "$SEEN" = "round2" ] && ok "reading the PR through pr/<N> sees round-2 content" \
                       || bad "reading the PR through pr/<N> sees stale content (got '$SEEN')"

# WHEN THE REF CANNOT BE MADE CORRECT, IT MUST NOT SURVIVE STALE.
# (Codex major on PR #265, which is this change reviewing itself.) The caller
# wraps review_worktree in `|| true` and degrades to the live tree, so simply
# returning 1 left the ref stale and the review running anyway -- the exact
# state this function exists to prevent, reached through its own error path.
#
# Failure is injected with a `git` shim rather than by breaking the repo on
# disk: a read-only refs dir would also break the DELETE, so the test would pass
# while proving nothing. The shim fails update-ref and leaves `update-ref -d`
# working, which is precisely the split the fix depends on.
WT2="$TMP/wt2"
git -C "$REPO" worktree add --detach "$WT2" "$SHA1" >/dev/null 2>&1
git -C "$WT2" update-ref refs/remotes/pr/98 "$SHA1"

git() {
  if [ "${3:-}" = "update-ref" ] && [ "${4:-}" != "-d" ]; then return 1; fi
  command git "$@"
}
PR=98
review_tree_path() { echo "$WT2"; }
review_worktree "$SHA2" >/dev/null 2>&1
RC=$?
unset -f git

[ "$RC" -ne 0 ] && ok "a failed ref update returns nonzero" \
                || bad "a failed ref update returns nonzero (got $RC)"

# THE POINT: gone, not stale.
if command git -C "$WT2" rev-parse refs/remotes/pr/98 >/dev/null 2>&1; then
  LEFT="$(command git -C "$WT2" rev-parse --short=8 refs/remotes/pr/98)"
  bad "a ref that could not be updated is deleted, not left stale (still at $LEFT)"
else
  ok "a ref that could not be updated is deleted, not left stale"
fi

# And what a reproducer would get: an error, never round-1 content.
OUT="$(command git -C "$WT2" show refs/remotes/pr/98:f.txt 2>/dev/null)"
[ "$OUT" != "round1" ] && ok "a reproducer cannot read stale content through the dead ref" \
                       || bad "a reproducer still reads stale content (got '$OUT')"

echo
if [ "$FAIL" -eq 0 ]; then echo "PASS: $PASS checks green"; exit 0; fi
echo "FAILED: $FAIL"; exit 1
