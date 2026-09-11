#!/usr/bin/env bash
# PR #265 codex major: the fallback tree search accepted a DESCENDANT worktree.
#
# `merge-base --is-ancestor "$HEAD_SHA" HEAD` is true for every descendant, so a
# worktree past the PR head satisfied it. The reviewer then read FILES from newer
# code while the verdict carried the captured older sha: findings citing lines
# the PR does not contain, with the provenance saying otherwise.
#
# This drives the SELECTION PREDICATE directly rather than a whole review, so it
# needs no network and no model call. The predicate is the whole defect.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
AGENT="$ROOT/q-system/.q-system/scripts/pr-review-agent.sh"
PASS=0; FAILED=0
ok()  { echo "  ok   $1"; PASS=$((PASS+1)); }
bad() { echo "  FAIL $1"; FAILED=$((FAILED+1)); }

TMP="$(mktemp -d)"
trap 'chmod -R u+w "$TMP" 2>/dev/null; command rm -rf "$TMP"' EXIT

REPO="$TMP/repo"; mkdir -p "$REPO"; cd "$REPO"
git init -q .
git config user.email t@t; git config user.name t
echo pr-head > f.txt; git add f.txt; git commit -qm "the PR head"
HEAD_SHA="$(git rev-parse HEAD)"
echo newer > f.txt; git add f.txt; git commit -qm "one commit LATER"
LATER="$(git rev-parse HEAD)"

AT="$TMP/at"; DESC="$TMP/desc"
git -C "$REPO" worktree add --detach "$AT"   "$HEAD_SHA" >/dev/null 2>&1
git -C "$REPO" worktree add --detach "$DESC" "$LATER"    >/dev/null 2>&1

# The predicate as the script now writes it, lifted from the source so this test
# cannot drift from the code it pins.
if grep -q 'rev-parse HEAD 2>/dev/null)" = "$HEAD_SHA"' "$AGENT"; then
  ok "the fallback selects on exact HEAD equality"
else
  bad "the fallback no longer compares HEAD to HEAD_SHA exactly"
fi
if grep -q 'merge-base --is-ancestor "\$HEAD_SHA" HEAD 2>/dev/null; then' "$AGENT"; then
  bad "an ancestor-based selection is still present; a descendant tree can be picked"
else
  ok "no ancestor-based tree selection remains"
fi

# And the behaviour itself, so this is not only a grep.
exact() { [ "$(git -C "$1" rev-parse HEAD 2>/dev/null)" = "$HEAD_SHA" ]; }
ancestral() { git -C "$1" merge-base --is-ancestor "$HEAD_SHA" HEAD 2>/dev/null; }

exact "$AT"      && ok "exact match accepts the tree AT the sha" \
                 || bad "exact match rejected the tree at the sha"
exact "$DESC"    && bad "exact match accepted a DESCENDANT tree" \
                 || ok "exact match rejects the descendant tree"
# The old predicate is shown accepting it, which is the defect, stated as a fact.
ancestral "$DESC" && ok "the OLD predicate accepted that descendant (the defect)" \
                  || bad "the descendant fixture is wrong; it is not a descendant"

echo ""
if [ "$FAILED" -gt 0 ]; then echo "FAILED: $FAILED"; exit 1; fi
echo "PASS: $PASS checks green"
