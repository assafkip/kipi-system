#!/bin/bash
# Bring a checkout up to origin/<branch> UNATTENDED, or refuse with a reason.
# ASK-294. Called by kipi-dispatch.sh's stale_check.
#
# WHY THIS EXISTS. 15 of the 48 founder pings in the measured 24h window were one
# line repeated: "kipi dispatch: refused to run -- origin/main has N commit(s)
# this checkout lacks. Do: cd <repo> && git merge --ff-only origin/main". It named
# the founder as the actor and handed him a shell command for something the loop
# can do itself. That is a defect in the producer, not a wording problem.
#
# WHY IT IS NOT JUST `git merge --ff-only`. An automatic ff-merge was built into
# kipi-dispatch.sh on 2026-08-02 and REMOVED the same night after three review
# rounds, each finding a NEW way for it to lose data (ASK-284 carries the record):
#   r1  a fast-forward SILENTLY OVERWRITES ignored files. Measured on this
#       checkout: an untracked-not-ignored collision ABORTS the merge, but an
#       IGNORED one fast-forwards with exit 0 and leaves no reflog to recover
#       from -- and `ls-files --others --exclude-standard` cannot even enumerate
#       that class (3982 such files here).
#   r2  the backup added to fix r1 continued the merge when a copy FAILED.
# Three rounds each finding a new instance of one class is a statement about the
# surface, not about care taken.
#
# WHAT CHANGES THE ANSWER. Those rounds tried to make an UNBOUNDED write safe --
# protect the whole working tree against anything a merge might touch. It is not
# unbounded. `git diff --name-only HEAD origin/<branch>` is the EXACT, finite set
# of paths the fast-forward will write. The precondition only has to hold over
# that set, and every member of it is individually checkable. So this script
# never copies, never backs up, never writes outside .git: it PROVES the merge
# cannot clobber anything, or it declines and says which path stopped it.
#
# Exit codes (kipi-dispatch.sh depends on these):
#   0  the checkout is current -- either already current, or fast-forwarded here.
#      Nothing to tell the founder. This is the quiet path and the common one.
#   1  refused. stdout carries one line naming WHY and WHICH path. The caller
#      decides whether that is a founder decision.
#   2  no answer (fetch failed, not a git repo, unreadable state). Fail OPEN --
#      offline is not proof of staleness, and wedging the loop on a network blip
#      is worse than running one cycle behind.
set -uo pipefail

REPO="${1:-$PWD}"
BRANCH="${2:-main}"
REMOTE="${3:-origin}"

cd "$REPO" 2>/dev/null || { echo "no-answer: not a directory: $REPO"; exit 2; }
git rev-parse --git-dir >/dev/null 2>&1 || { echo "no-answer: not a git repo: $REPO"; exit 2; }

LOCAL="$(git rev-parse HEAD 2>/dev/null)" || { echo "no-answer: cannot read HEAD"; exit 2; }
REMOTE_REF="$REMOTE/$BRANCH"
UPSTREAM="$(git rev-parse "$REMOTE_REF" 2>/dev/null)" || { echo "no-answer: cannot read $REMOTE_REF"; exit 2; }

# Already current, or ahead-only. An agent commits locally before it opens a PR,
# so "ahead" must keep running or the loop wedges on its own work.
[ "$LOCAL" = "$UPSTREAM" ] && { echo "current: already at $REMOTE_REF"; exit 0; }
BEHIND="$(git rev-list --count "$LOCAL..$UPSTREAM" 2>/dev/null)" || { echo "no-answer: rev-list failed"; exit 2; }
case "$BEHIND" in ''|*[!0-9]*) echo "no-answer: unparseable behind-count"; exit 2 ;; esac
[ "$BEHIND" -gt 0 ] || { echo "current: nothing to pull from $REMOTE_REF"; exit 0; }

# --- precondition 1: it must be a TRUE fast-forward --------------------------
# A diverged tree needs a real merge, which can conflict and can rewrite history.
# That is an irreversible git op and the founder owns it. This is the one branch
# of this script that is allowed to reach his phone.
if ! git merge-base --is-ancestor "$LOCAL" "$UPSTREAM" 2>/dev/null; then
  AHEAD="$(git rev-list --count "$UPSTREAM..$LOCAL" 2>/dev/null || echo '?')"
  echo "diverged: HEAD has $AHEAD commit(s) $REMOTE_REF lacks and is $BEHIND behind; a real merge is needed, not a fast-forward"
  exit 1
fi

# --- precondition 2: nothing the merge writes may already be at risk ---------
# THE BOUNDED SET. Not "is the tree clean" (it never is -- this repo carries
# review-scratch dirs and 3982 ignored files) but "is any path this merge TOUCHES
# unsafe to overwrite". Two ways a path can be unsafe, and r1's scar is the first:
#   a) it exists on disk but git does not track it -> ignored or untracked. A
#      fast-forward overwrites the ignored case silently, with no reflog. This is
#      the exact class that killed the previous attempt, and it is cheap to test
#      once you only ask about the paths being written.
#   b) it is tracked but locally modified -> the fast-forward would either abort
#      or bury uncommitted work.
COLLISIONS=""
while IFS= read -r path; do
  [ -n "$path" ] || continue
  if [ -e "$path" ] && ! git ls-files --error-unmatch -- "$path" >/dev/null 2>&1; then
    COLLISIONS="$COLLISIONS $path(untracked-or-ignored)"
    continue
  fi
  if ! git diff --quiet HEAD -- "$path" 2>/dev/null; then
    COLLISIONS="$COLLISIONS $path(locally-modified)"
  fi
done <<EOF
$(git diff --name-only "$LOCAL" "$UPSTREAM" 2>/dev/null)
EOF

if [ -n "$COLLISIONS" ]; then
  # Deliberately NOT "back it up and merge anyway": r2 removed the previous
  # attempt because its backup silently continued when a copy failed. Refusing is
  # the only branch with no write surface at all.
  set -- $COLLISIONS
  echo "collision: $# path(s) the fast-forward would overwrite are untracked, ignored, or locally modified:${COLLISIONS}"
  exit 1
fi

# --- the merge ---------------------------------------------------------------
# --ff-only is belt-and-braces: precondition 1 already proved it, and if git
# disagrees with us we take git's answer and refuse rather than force anything.
if MERGE_OUT="$(git merge --ff-only "$UPSTREAM" 2>&1)"; then
  echo "merged: fast-forwarded $BEHIND commit(s) to ${UPSTREAM:0:7} with no collisions"
  exit 0
fi
echo "refused: git declined the fast-forward despite the preconditions: $(printf '%s' "$MERGE_OUT" | head -2 | tr '\n' ' ')"
exit 1
