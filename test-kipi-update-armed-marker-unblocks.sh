#!/bin/bash
# Pairs with kipi-update.sh SYSTEM_NEVER_COMMIT / the one-time untrack migration
# (ASK-797). Proves the FLEET-LEVEL effect, which the coverage test cannot see:
# the coverage test asserts the array names the path, this asserts that naming it
# actually unblocks an instance the guard was refusing.
#
# Synthetic fixture on purpose. The real evidence came from instances whose names
# are client names and this repo is public, so the fixture reproduces the SHAPE
# (a tracked, volatile, skeleton-gitignored state file inside the synced prefix)
# rather than copying a real repo.
#
# Red first: step 2 asserts the guard REFUSES before the migration runs. A test
# that only ever sees the fixed state cannot tell a fix from a no-op.
#
# The control is the point of step 5. Clearing the block must not be achieved by
# weakening the guard, so an ordinary founder edit inside the same synced prefix
# has to keep refusing after the migration has run.
set -u

FAILURES=0
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

note() { printf '%s\n' "$*"; }
fail() { note "  FAIL: $*"; FAILURES=$((FAILURES + 1)); }

ARMED="q-system/.q-system/.claude-integrity-armed"

# The dirty-tree guard, reproduced as kipi-update.sh runs it: two `git diff
# --quiet` calls over the synced prefix. Returns 0 when the instance would sync.
guard_passes() {
  local repo="$1"
  git -C "$repo" diff --cached --quiet -- "q-system/" 2>/dev/null &&
  git -C "$repo" diff --quiet -- "q-system/" 2>/dev/null
}

# --- fixture: an instance poisoned exactly the way the fleet was ---------------
REPO="$WORK/instance"
mkdir -p "$REPO/q-system/.q-system"
git -C "$REPO" init -q 2>/dev/null || git init -q "$REPO"
git -C "$REPO" config user.email t@example.com
git -C "$REPO" config user.name Test
printf 'founder content\n' > "$REPO/q-system/.q-system/some-founder-file.md"
# Step 1 of the loop: the updater commits the volatile marker as system state.
printf 'armed 2026-08-10T21:33:20Z -- claude-integrity-tripwire.py\n' > "$REPO/$ARMED"
git -C "$REPO" add -A
git -C "$REPO" commit -q -m "chore: commit system-written state before skeleton sync"

# Step 2 of the loop: the tripwire arms again and rewrites the timestamp. This is
# not contrived -- the file's whole content is a timestamp, so any later arm
# changes it.
printf 'armed 2026-08-14T20:13:59Z -- claude-integrity-tripwire.py\n' > "$REPO/$ARMED"

note "=== 1. fixture built: marker tracked, then rewritten by the tripwire ==="
if [ -z "$(git -C "$REPO" status --porcelain -- "$ARMED")" ]; then
  fail "fixture did not go dirty; the rest of this test would be vacuous"
fi

note ""
note "=== 2. RED: the guard refuses before the fix ==="
if guard_passes "$REPO"; then
  fail "the guard passed on a dirty tracked marker -- fixture does not reproduce"
else
  note "  ok: refused, which is the state 13 of 22 instances were stuck in"
fi

note ""
note "=== 3. apply the one-time untrack migration ==="
# The same three commands kipi-update.sh runs for a tracked SYSTEM_NEVER_COMMIT
# path: refuse if the index already holds staged work, `git rm --cached` (NEVER a
# worktree delete), then a pathspec-free commit whose staged set was asserted.
if [ -n "$(git -C "$REPO" diff --cached --name-only)" ]; then
  fail "fixture index was not clean; the real migration would decline here"
fi
git -C "$REPO" rm --cached --quiet -- "$ARMED"
STAGED="$(git -C "$REPO" diff --cached --name-only)"
if [ "$STAGED" != "$ARMED" ]; then
  fail "staged set was '$STAGED', expected exactly '$ARMED'"
fi
git -C "$REPO" commit -q -m "chore: untrack instance-local $ARMED"

note ""
note "=== 4. GREEN: the guard passes and the file is untouched on disk ==="
if guard_passes "$REPO"; then
  note "  ok: this instance would now receive an update"
else
  note "  remaining blockers:"
  git -C "$REPO" status --short | sed 's/^/    /'
  fail "still refusing after the migration"
fi
# The tripwire treats a missing baseline on an armed tree as a REMOVED backstop
# and then refuses every tool call, so deleting the marker would cause by hand
# the outage this repairs. Untracking must leave the bytes alone.
if [ ! -f "$REPO/$ARMED" ]; then
  fail "the marker was deleted from disk; untrack must never touch the worktree"
elif ! grep -q '2026-08-14T20:13:59Z' "$REPO/$ARMED"; then
  fail "the marker's content changed; the newest arm must survive untracking"
else
  note "  ok: marker still on disk with the tripwire's own latest timestamp"
fi

note ""
note "=== 5. CONTROL: a real founder edit in the same prefix still refuses ==="
printf 'founder content, edited\n' > "$REPO/q-system/.q-system/some-founder-file.md"
if guard_passes "$REPO"; then
  fail "the guard passed over a founder edit -- the fix weakened the guard"
else
  note "  ok: still refuses founder work, so step 4 was a targeted clear"
fi

note ""
if [ "$FAILURES" -eq 0 ]; then
  note "ALL PASS"
  exit 0
fi
note "$FAILURES check(s) FAILED"
exit 1
