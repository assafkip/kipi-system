#!/usr/bin/env bash
# skeleton-provenance.sh: is this checkout AT the configured skeleton remote's branch?
#
# Usage: skeleton-provenance.sh <checkout-dir> <remote-url> <branch>
# Exit 0 and print "provenance: OK <sha>" when HEAD equals the tip of <branch> at
# <remote-url>. Exit 1 with an ABORT block otherwise (unreachable remote, unresolvable
# refs, or drift in either direction).
#
# WHY IT IS ITS OWN SCRIPT (GitHub issue #2, PR A, review round 1). kipi-update.sh fanned
# the skeleton to every instance only after proving the working tree matched what was
# reviewed. That proof fetched `origin`, the checkout's own remote name, while every other
# site in the updater had just learned to read KIPI_SKELETON_REMOTE. A fork with the
# override set was still being compared against whatever `origin` happened to be, so the
# override was displayed and then ignored at the one step that gates the fan-out. Fetching
# the configured URL and comparing against FETCH_HEAD closes that; putting it here lets a
# test drive it with two bare repositories instead of the whole updater.
#
# Fail closed when the comparison cannot be made. GIT_TERMINAL_PROMPT=0 so an unreachable
# remote errors out rather than hanging on credentials. Fanning to every instance from an
# unproven source is worse than not fanning at all.
set -euo pipefail
export GIT_TERMINAL_PROMPT=0

DIR="${1:?checkout dir}"
REMOTE="${2:?remote url}"
BRANCH="${3:?branch}"

if ! git -C "$DIR" fetch "$REMOTE" "$BRANCH" --quiet 2>/dev/null; then
  echo ""
  echo "ABORT: could not fetch $BRANCH from $REMOTE."
  echo "Without it there is no way to prove this working tree matches what was"
  echo "reviewed. Fix connectivity, or propagate later; do not fan the fleet"
  echo "from an unverified source."
  exit 1
fi
LOCAL_SHA="$(git -C "$DIR" rev-parse HEAD 2>/dev/null || true)"
REMOTE_SHA="$(git -C "$DIR" rev-parse FETCH_HEAD 2>/dev/null || true)"
if [ -z "$LOCAL_SHA" ] || [ -z "$REMOTE_SHA" ]; then
  echo ""
  echo "ABORT: could not resolve HEAD or $REMOTE $BRANCH to a commit."
  exit 1
fi
if [ "$LOCAL_SHA" != "$REMOTE_SHA" ]; then
  DRIFT="$(git -C "$DIR" rev-list --left-right --count "HEAD...FETCH_HEAD" 2>/dev/null || printf '? ?')"
  echo ""
  echo "ABORT: the skeleton is on $BRANCH but not AT $BRANCH of $REMOTE."
  echo "  local:  $LOCAL_SHA"
  echo "  remote: $REMOTE_SHA"
  echo "  ahead/behind: $DRIFT"
  echo "Ahead means bytes nobody reviewed; behind means bytes that were"
  echo "superseded. Either way the fleet would get something other than"
  echo "$BRANCH. Push or pull before propagating."
  exit 1
fi
echo "provenance: OK $LOCAL_SHA"
