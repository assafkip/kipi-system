#!/usr/bin/env bash
# PR #265 codex majors.
#
# 1. REVIEW_ROOT defaulted to $SKEL -- the tree this SCRIPT lives in. For an
#    external target (--target / KIPI_TARGET_REPO) that is a different repository,
#    and the WARN-and-proceed branch leaves the default in place, so the reviewer
#    read files out of the skeleton and stamped the verdict with another repo's
#    PR sha.
#
# 2. review_worktree re-detaches a SHARED path rather than making a fresh one, so
#    two concurrent reviews of the same repo+PR point at one mutable checkout:
#    run A reads while run B re-checkouts it. Neither can tell, and both stamp
#    their verdicts with the sha they think they read.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
AGENT="$ROOT/q-system/.q-system/scripts/pr-review-agent.sh"
PASS=0; FAILED=0
ok()  { echo "  ok   $1"; PASS=$((PASS+1)); }
bad() { echo "  FAIL $1"; FAILED=$((FAILED+1)); }

TMP="$(mktemp -d)"
trap 'chmod -R u+w "$TMP" 2>/dev/null; command rm -rf "$TMP"' EXIT

# --- 1. REVIEW_ROOT must follow the repo under review ------------------------
if grep -q '^REVIEW_ROOT="\$REVIEW_REPO"' "$AGENT"; then
  ok "REVIEW_ROOT defaults to the repo under review"
else
  bad "REVIEW_ROOT does not default to REVIEW_REPO; an external target reads the skeleton"
fi
if grep -q '^REVIEW_ROOT="\$SKEL"' "$AGENT"; then
  bad "REVIEW_ROOT still defaults to SKEL somewhere"
else
  ok "no SKEL default remains"
fi

# --- 2. the review tree is locked against concurrent runs --------------------
eval "$(sed -n '/^acquire_wt_lock() {/,/^}/p' "$AGENT")"
eval "$(sed -n '/^release_wt_lock() {/,/^}/p' "$AGENT")"
for _fn in acquire_wt_lock release_wt_lock; do
  declare -f "$_fn" >/dev/null 2>&1 || { echo "FAIL: could not extract $_fn" >&2; exit 1; }
done

WT="$TMP/tree"
acquire_wt_lock "$WT" && ok "the first run takes the tree lock" \
                      || bad "the first run could not take the tree lock"

# Re-entrant for THIS run: review_worktree is called more than once per review.
acquire_wt_lock "$WT" && ok "the same run re-enters its own lock" \
                      || bad "a run refused its own lock"

# A DIFFERENT, live holder must be refused. Written directly, with a pid that is
# alive (this shell's parent is not reliable in CI, so use a real sleeper).
sleep 60 &
LIVE=$!
printf '%s' "$LIVE" > "$WT.lock"
_wt_lock_path=""
if acquire_wt_lock "$WT"; then
  bad "a live concurrent holder was ignored; two runs share one mutable tree"
else
  ok "a live concurrent holder is refused"
fi
kill "$LIVE" 2>/dev/null; wait "$LIVE" 2>/dev/null

# A dead holder must be reclaimed, or an operator clears locks by hand and
# eventually clears one while a run is live.
printf '999999999' > "$WT.lock"
_wt_lock_path=""
acquire_wt_lock "$WT" && ok "a stale lock is reclaimed" \
                      || bad "a stale lock needs a human"

echo ""
if [ "$FAILED" -gt 0 ]; then echo "FAILED: $FAILED"; exit 1; fi
echo "PASS: $PASS checks green"
