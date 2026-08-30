#!/usr/bin/env bash
# PR #265 codex major: an EARLY bail out of review_worktree left the stale
# pr/<N> ref in place, so assert_pr_ref_not_stale hard-refused every later round
# with no self-heal. A guard whose only recovery is a human is an outage with a
# good error message.
#
# The existing suite covers the LATE bail (update-ref fails). This covers the
# four earlier ones, and it goes red against the pre-fix script -- verified by
# reverting `_wt_bail "$wt"` back to a bare `return 1` and watching both cases
# fail.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
AGENT="$ROOT/q-system/.q-system/scripts/pr-review-agent.sh"
PASS=0; FAILED=0
ok()  { echo "  ok   $1"; PASS=$((PASS+1)); }
bad() { echo "  FAIL $1"; FAILED=$((FAILED+1)); }

TMP="$(mktemp -d)"
trap 'chmod -R u+w "$TMP" 2>/dev/null; command rm -rf "$TMP"' EXIT

REPO="$TMP/repo"
mkdir -p "$REPO"; cd "$REPO"
git init -q .
git config user.email t@t; git config user.name t
echo round1 > f.txt; git add f.txt; git commit -qm one
SHA1="$(git rev-parse HEAD)"
echo round2 > f.txt; git add f.txt; git commit -qm two
SHA2="$(git rev-parse HEAD)"

# Source the agent's function definitions without running a review.
SKEL="$ROOT"; REVIEW_REPO="$REPO"; REVIEW_SLUG="t_repo"; PR=97
eval "$(sed -n '/^_wt_bail() {/,/^}/p' "$AGENT")"
eval "$(sed -n '/^_wt_bail() {/,/^}/p' "$AGENT")"
eval "$(sed -n '/^acquire_wt_lock() {/,/^}/p' "$AGENT")"
eval "$(sed -n '/^release_wt_lock() {/,/^}/p' "$AGENT")"
eval "$(sed -n '/^review_worktree() {/,/^  printf/p' "$AGENT"; echo '}')"
# EVERY EXTRACTION MUST HAVE DEFINED SOMETHING. These suites lift functions out
# of the agent by NAME, so a rename or a new dependency makes the extraction
# silently empty and every case then fails for a reason unrelated to what it
# asserts -- which is exactly what happened when review_worktree grew a call to
# acquire_wt_lock. Fail loudly on the extraction instead.
for _fn in review_worktree acquire_wt_lock release_wt_lock _wt_bail; do
  if ! declare -f "$_fn" >/dev/null 2>&1; then
    echo "FAIL: could not extract $_fn from $AGENT (renamed, or its shape changed)" >&2
    exit 1
  fi
done


WT="$TMP/wt"
git -C "$REPO" worktree add --detach "$WT" "$SHA1" >/dev/null 2>&1
git -C "$WT" update-ref "refs/remotes/pr/$PR" "$SHA1"
review_tree_path() { echo "$WT"; }

STALE="$(git -C "$WT" rev-parse "refs/remotes/pr/$PR")"
[ "$STALE" = "$SHA1" ] && ok "setup: a round-1 ref exists" \
                       || bad "setup: the ref was not written"

# EARLY BAIL: make the checkout fail, which is the second of the four and the
# one a real run hits (a tree left mid-rebase, a lock, a full disk).
git() {
  if [ "${3:-}" = "checkout" ]; then return 1; fi
  command git "$@"
}
review_worktree "$SHA2" >/dev/null 2>&1
RC=$?
unset -f git

[ "$RC" -ne 0 ] && ok "an early bail returns nonzero" \
                || bad "an early bail returns nonzero (got $RC)"

# THE POINT: the stale ref must be gone, so the next round self-heals instead of
# hitting a fatal refusal forever.
if command git -C "$WT" rev-parse "refs/remotes/pr/$PR" >/dev/null 2>&1; then
  LEFT="$(command git -C "$WT" rev-parse --short=8 "refs/remotes/pr/$PR")"
  bad "an early bail leaves the ref stale (still at $LEFT), wedging every later round"
else
  ok "an early bail clears the stale ref, so the next round self-heals"
fi

# THE EARLIEST BAIL OF ALL: mkdir (PR #265 codex major, round 2). When mkdir
# fails there is no review tree to clear the ref THROUGH, so a fix that only
# cleared $wt left the previous round's ref exactly where it was. This is the
# case neither suite covered, and it is the one a real run hits on a full disk.
git -C "$WT" update-ref "refs/remotes/pr/$PR" "$SHA1"
mkdir() { return 1; }
review_tree_path() { echo "$TMP/never-created/wt"; }
review_worktree "$SHA2" >/dev/null 2>&1
RC=$?
unset -f mkdir
review_tree_path() { echo "$WT"; }

[ "$RC" -ne 0 ] && ok "a mkdir bail returns nonzero" \
                || bad "a mkdir bail returns nonzero (got $RC)"

if command git -C "$REPO" rev-parse "refs/remotes/pr/$PR" >/dev/null 2>&1; then
  LEFT="$(command git -C "$REPO" rev-parse --short=8 "refs/remotes/pr/$PR")"
  bad "a mkdir bail leaves the ref in REVIEW_REPO (still at $LEFT)"
else
  ok "a mkdir bail clears the ref through REVIEW_REPO too"
fi

# THE CALL SITE IS THE WIRING (PR #265 codex minor). The stale-ref suite stayed
# fully green when the only call to assert_pr_ref_not_stale was deleted: it
# exercised the guard as a function and never asserted that anything invokes it.
# A guard nothing calls is the defect class this whole PR is about.
#
# READ THIS NARROWLY. It pins that an executable (non-comment) call exists on the
# path that materialises the review tree. It does NOT prove the call is reached
# at runtime, and no grep can: that needs the caller driven end to end, which
# means a real PR and a real network round trip. Presence is the half a test can
# hold, and saying so beats implying the other half.
CALLS="$(grep -c '^[^#]*assert_pr_ref_not_stale "' "$AGENT" || true)"
[ "${CALLS:-0}" -ge 1 ] && ok "assert_pr_ref_not_stale is actually called ($CALLS site(s))" \
                        || bad "assert_pr_ref_not_stale is defined but never called"

echo ""
if [ "$FAILED" -gt 0 ]; then echo "FAILED: $FAILED"; exit 1; fi
echo "PASS: $PASS checks green"
