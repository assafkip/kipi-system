#!/bin/bash
# Daily autonomous cross-instance learning heartbeat (launchd-fired).
#   distill new learnings -> publish clean lessons -> propagate to the fleet -> Slack the founder.
# Founder model 2026-06-30: fully autonomous, every learning shared, client data scrubbed (fail-closed
# in lessons_scrub.py). Silent when nothing new; Slacks only on a real change or a failure.
# Disable: launchctl unload ~/Library/LaunchAgents/com.kipi.lessons-daily.plist
#
# Seams (env, production defaults unchanged; tests point them at temp files and stubs):
#   KIPI_CLAUDE_BIN       the CLI whose presence is checked (default: claude)
#   KIPI_DISTILL_CMD      the distiller command (default: python3 lessons-distill.py)
#   KIPI_PERSIST_CMD      the commit step (default: git add + commit in the skeleton)
#   KIPI_PROPAGATE_CMD    the fan-out (default: bash kipi-update.sh)
#   KIPI_NOTIFY_CMD       the alert sink (default: slack-notify.sh, which files Sana's ticket)
#   KIPI_LESSONS_LOG, KIPI_STREAK_FILE, KIPI_ESCALATIONS_FILE   paths
#
# THE STREAK (issue lr-propagation-streak-escalation, plan 3b). Measured
# 2026-09-01: propagate FAILED on six consecutive logged runs, five weeks, six
# identical alarms filed to Sana's queue, no action. An alarm that reads the
# same on night 1 and night 40 is the defect. Now a streak counter persists
# across runs; at STREAK_ESCALATE and above the log line and the alert carry
# the streak length, and ONE row is appended to an escalations ledger per
# escalating run: the logged automated action the detect-act-learn triad was
# missing. Success resets the streak.
set -uo pipefail
# Unattended fetch and push: a credential prompt must fail, never hang the job.
export GIT_TERMINAL_PROMPT=0

SKEL="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"   # scripts -> .q-system -> q-system -> repo root
NOTIFY="$SKEL/q-system/.q-system/scripts/slack-notify.sh"
DISTILL="$SKEL/q-system/.q-system/scripts/lessons-distill.py"
LOG="${KIPI_LESSONS_LOG:-$SKEL/q-system/output/lessons-daily.log}"
STREAK_FILE="${KIPI_STREAK_FILE:-$SKEL/q-system/output/lessons-propagation-streak.json}"
ESCALATIONS="${KIPI_ESCALATIONS_FILE:-$SKEL/q-system/output/lessons-propagation-escalations.jsonl}"
STREAK_ESCALATE="${KIPI_STREAK_ESCALATE:-3}"
TS() { date '+%Y-%m-%dT%H:%M:%S%z'; }
mkdir -p "$(dirname "$LOG")"

notify() { if [ -n "${KIPI_NOTIFY_CMD:-}" ]; then bash -c "$KIPI_NOTIFY_CMD" "_" "$1"; else bash "$NOTIFY" "$1" 2>/dev/null; fi; }

# The exit code IS this job's wire to Linear (ASK-182). fleet-health-daily.py's
# `launchd-failing` detector keys on a non-zero LastExitStatus, so a run that
# reports 0 after a bad night is invisible to the board no matter what it Slacked.
# Observed 2026-07-27: the 06:00 run logged "propagate FAILED", Slacked it, and
# `launchctl list` still said LastExitStatus = 0. Pinned by
# test/test-lessons-daily-exit.sh.
#
# A LESSONS FAILURE NEVER SKIPS THE FLEET UPDATE (ASK-2736). This job is the
# fleet's only unattended caller of kipi-update.sh, and the fan-out sat behind a
# `fail` that exited on the spot. Review rounds 3 and 4 of PR #551 each found
# more of them (the unmerged-branch guard, then fetch, worktree add, ls-remote
# and the merged check): one broken gh login would have stopped every weekly
# fleet update while the alert talked only about lessons. Same class twice, so
# the shape changed instead of a fifth site patch: the lessons half is one
# function, a failure in it records the reason and returns, and the fan-out
# after it always runs. The run still exits 1 and its one alert names both
# halves. Pinned by test/test-lessons-daily-publish.sh case 13.
LESSONS_FAIL=""
lessons_fail() { LESSONS_FAIL="$*"; echo "$(TS) FAILURE: $*" >> "$LOG"; }

# Founder decision 2026-08-01: pin the distiller's model; unpinned it rides the
# interactive default (Fable on 2026-08-01) and burns quota unattended.
export ANTHROPIC_MODEL="claude-opus-5"

# ARM NEWLY COMMITTED LAUNCHD JOBS (ASK-1130), and do it BEFORE the early exits
# below. This job is the fleet's only unattended caller of kipi-update.sh, and that
# call sits behind `if [ "$PUB" -gt 0 ]`, so with the arming living only inside the
# updater a merged plist waited for the next day a lesson happened to publish. The
# "armed with no human command" claim was therefore true on publish days and false
# on quiet ones. A quiet week is quiet for lessons, not a reason for a merged job to
# stay inert.
#
# install-plist.sh --missing carries every guard itself -- worktree refusal,
# registry-skeleton refusal, already-installed, retired sidecar, declared disabled --
# so this call can arm nothing the updater's own call would not have armed. That is
# why the skeleton check lives in the mode and not only in arm_new_jobs.
# Non-fatal on purpose: a launchd problem does not stop lessons work.
if ARM_OUT="$(bash "$SKEL/q-system/.q-system/scripts/install-plist.sh" --missing 2>&1)"; then
  echo "$(TS) jobs: $(printf '%s' "$ARM_OUT" | sed -n 's/^install-jobs: //p' | tail -1)" >> "$LOG"
else
  echo "$(TS) jobs: arming FAILED (non-fatal)" >> "$LOG"
  printf '%s\n' "$ARM_OUT" >> "$LOG"
fi

# WHERE LESSONS ARE WRITTEN, COMMITTED AND SENT (ASK-2736).
#
# THE SCAR. This job used to write and commit lessons in the checkout it runs
# from. From 2026-09-07 to 2026-10-19 that checkout sat on a feature branch, so
# six weekly runs committed 29 lessons onto it, three of those commits never
# left the machine, and kipi-update.sh refused every fan-out because the
# checkout was not at origin/main. The alert only ever said "propagate FAILED".
#
# So with an origin, no lesson is written or committed in this checkout (its one
# change is a fast-forward of main before the fan-out, see sync_skel_to_main):
# the run opens a fresh worktree at origin/main, distills into it, commits there through the
# repo's hooks, pushes a branch, opens a PR to main, arms auto-merge and runs the
# fleet reviewer. Lessons reach main through review or the run fails loudly and
# keeps the worktree. Main is protected (enforce_admins), so a PR is the only way.
#
# With no origin there is nothing to strand against: the run commits in place,
# and says so. Same DISARMED convention as kipi-update.sh's branch check.
# KIPI_PERSIST_CMD replaces the whole persist-and-publish step, so a run with
# that seam never opens a worktree or asks GitHub anything. The suites that set
# it run this script in place, inside a real checkout with a real origin.
#
# FIXTURE GUARD, same rule as alert-to-linear.py's: under pytest, PR mode needs
# a test-owned KIPI_LESSONS_WT_ROOT. Without one, a suite running this script in
# place fetched, opened worktrees under the live state dir, asked GitHub, and
# reached the real kipi-update.sh (PR #551 round 2: test_lessons_daily_streak,
# stopped only by the updater's own not-on-main preflight).
FIXTURE_RUN=""
[ -n "${PYTEST_CURRENT_TEST:-}" ] && [ -z "${KIPI_LESSONS_WT_ROOT:-}" ] && FIXTURE_RUN=1
WT_ROOT="${KIPI_LESSONS_WT_ROOT:-$HOME/.local/state/kipi/lessons}"
PUBLISH_MODE=local
LREPO="$SKEL"
KEEP_WT=0
cleanup_wt() {
  [ "$PUBLISH_MODE" = pr ] && [ -d "$LREPO" ] || return 0
  if [ "$KEEP_WT" = 1 ]; then
    echo "$(TS) lessons worktree KEPT at $LREPO" >> "$LOG"
  # --force because KEEP_WT=0 already means nothing in here is worth keeping:
  # the lessons are pushed, or nothing was committed and the ledger rows go with
  # the lessons. The reviewer runs claude inside this worktree and its
  # SessionStart hook rewrites the tracked q-system/memory/.sycophancy-monthly-stamp,
  # so a plain remove refused every clean publish and leaked one registered
  # worktree a week while the run exited 0 (PR #551 round 4).
  elif ! git -C "$SKEL" worktree remove --force "$LREPO" >> "$LOG" 2>&1; then
    echo "$(TS) lessons worktree left at $LREPO (not clean, see above)" >> "$LOG"
  fi
}
# The mode is decided before anything in the lessons half can fail. Decided
# inside it, a failure ahead of the decision (no claude CLI) left the run in
# local mode, where publishing nothing means no fan-out at all.
if [ -z "${KIPI_PERSIST_CMD:-}" ] && [ -z "$FIXTURE_RUN" ] \
   && git -C "$SKEL" remote get-url origin >/dev/null 2>&1; then
  PUBLISH_MODE=pr
  LREPO="$WT_ROOT/wt-$(date +%Y%m%d-%H%M%S)-$$"
else
  echo "$(TS) lessons publish: DISARMED (no origin remote; committing in place)" >> "$LOG"
fi
export LESSONS_DIR="$LREPO/q-system/lessons"
PUB=0; HELD=0; TITLES=""
field() { printf '%s' "$SUMMARY" | python3 -c "import json,sys;d=json.load(sys.stdin);print($1)" 2>/dev/null; }

# THE LESSONS HALF: distill, commit, publish. Every failure in it is
# lessons_fail + return, never exit (see lessons_fail above). The one exit left
# is local mode's quiet night, which has no fan-out to skip.
lessons_half() {
  # The plist pins PATH to include ~/.local/bin, so a missing binary here is a
  # broken machine, not a normal night. Skipping silently would make this job dark
  # with a clean exit status -- the one state the four bars forbid.
  command -v "${KIPI_CLAUDE_BIN:-claude}" >/dev/null 2>&1 \
    || { lessons_fail "no claude CLI on PATH -> nothing distilled"; return 1; }

  if [ "$PUBLISH_MODE" = pr ]; then
    mkdir -p "$WT_ROOT"
    git -C "$SKEL" fetch -q origin main >> "$LOG" 2>&1 \
      || { lessons_fail "could not fetch origin/main; nothing distilled"; return 1; }
    git -C "$SKEL" worktree add -q --detach "$LREPO" origin/main >> "$LOG" 2>&1 \
      || { lessons_fail "could not open a worktree at origin/main; nothing distilled"; return 1; }
    trap cleanup_wt EXIT
    # The lessons commit's [no-issue:] bypass row must land in the skeleton's
    # countable ledger, not in this worktree, which is deleted on a clean publish
    # (review of PR #551, round 3). linear-issue-ref-check.py reads this override.
    export LINEAR_BYPASS_LEDGER="${LINEAR_BYPASS_LEDGER:-$SKEL/q-system/output/linear-bypass.jsonl}"
    # ONE LESSONS BRANCH IN FLIGHT. The ledger travels with the lessons, so a run
    # distilling from a main that lacks an earlier run's unmerged rows publishes
    # the same sources twice. Any auto/lessons-* branch on origin with no MERGED
    # PR counts: an open PR, and also a branch whose PR never opened. Checking
    # open PRs alone missed that second case (PR #551 review round 1). The repo
    # keeps merged branches (delete_branch_on_merge is off), so "merged" is asked
    # of GitHub rather than read from the branch list. The alert is how a stuck
    # lessons PR or an orphan branch reaches the board.
    # The listing is captured on its own line so its exit status is checked. Piped
    # straight into the loop, a failed ls-remote produced no refs and read as "no
    # pending branches", so a network blip let the run distill past the guard
    # (codex, PR #551 round 2). Unknown is not empty.
    REMOTE_BR="$(git -C "$SKEL" ls-remote --heads origin 'refs/heads/auto/lessons-*' 2>>"$LOG")" \
      || { lessons_fail "could not list lessons branches on origin; nothing distilled"; return 1; }
    PENDING_BR=""
    REFS="$(printf '%s\n' "$REMOTE_BR" | awk 'NF {sub("refs/heads/", "", $2); print $2}')"
    # ONE CALL FOR EVERY BRANCH. Asking per branch grew by one call a week, since
    # merged branches are never deleted, and any one failing cost that week's
    # distilling (PR #551 round 4: 53 calls in one run after a year). GitHub's
    # head: qualifier is a prefix match (measured 2026-10-23). 1000 is the search
    # API's own result cap; a merged branch past it reads as unmerged, which
    # holds distilling and names the branch, the loud direction.
    if [ -n "$REFS" ]; then
      MERGED_BR="$(cd "$LREPO" && gh pr list --state merged --search "head:auto/lessons-" \
                   --limit 1000 --json headRefName --jq '.[].headRefName' 2>>"$LOG")" \
        || { lessons_fail "could not ask GitHub which lessons branches merged; nothing distilled"; return 1; }
      for ref in $REFS; do
        printf '%s\n' "$MERGED_BR" | grep -qxF -- "$ref" || PENDING_BR="$PENDING_BR $ref"
      done
    fi
    # The guard holds back DISTILLING, not the fan-out. A stuck lessons PR is
    # named in the alert and the run exits 1, but main still goes to the fleet
    # (review of PR #551, round 3).
    if [ -n "$PENDING_BR" ]; then
      HOLD="lessons branch(es) not merged yet:$PENDING_BR. Not distilling until they merge (or the same sources publish twice). Merge its PR, open one, or delete the branch."
      echo "$(TS) $HOLD" >> "$LOG"
    fi
  fi

  if [ -n "${HOLD:-}" ]; then
    SUMMARY='{"scanned": 0, "published": [], "held": [], "skipped": "a lessons branch is not merged"}'
  elif [ -n "${KIPI_DISTILL_CMD:-}" ]; then
    SUMMARY="$(bash -c "$KIPI_DISTILL_CMD" 2>>"$LOG")" \
      || { lessons_fail "lessons-distill.py exited non-zero"; return 1; }
  else
    SUMMARY="$(cd "$SKEL" && python3 "$DISTILL" --lessons-dir "$LESSONS_DIR" \
      --ledger "$LREPO/lesson-candidates/.processed.json" 2>>"$LOG")" \
      || { lessons_fail "lessons-distill.py exited non-zero"; return 1; }
  fi
  echo "$(TS) $SUMMARY" >> "$LOG"

  # A dead distiller emits no JSON, every count below parses as 0, and the run
  # reads as a quiet night. A zero result must prove it is empty, not broken.
  printf '%s' "$SUMMARY" | python3 -c "import json,sys; json.load(sys.stdin)" 2>/dev/null \
    || { lessons_fail "lessons-distill.py emitted no parseable JSON summary"; return 1; }

  PUB=$(field "len(d.get('published',[]))");  PUB=${PUB:-0}
  HELD=$(field "len(d.get('held',[]))");      HELD=${HELD:-0}
  TITLES=$(field "'; '.join(d.get('published',[])[:5])")

  if [ "$PUB" = "0" ] && [ "$HELD" = "0" ]; then
    echo "$(TS) nothing new" >> "$LOG"
    # PR mode still fans out: last week's lessons reached main through a PR after
    # that run's fan-out, so this weekly update is what carries them to the fleet
    # (PR #551 review round 1). It stays silent unless the fan-out fails.
    [ "$PUBLISH_MODE" = pr ] || exit 0
    QUIET=1
  fi

  # Persist new lessons + ledger in the skeleton, then fan to the fleet.
  if [ -n "${KIPI_PERSIST_CMD:-}" ]; then
    bash -c "$KIPI_PERSIST_CMD" || true
  else
    # ASK-2290: this commit used to pass --no-verify and send all output to
    # /dev/null, so no repo gate ever saw a daily lesson commit, and the
    # linear-issue-ref gate would have refused its message every night. It now
    # goes through the hooks. The message carries its own [no-issue: reason], so
    # the Linear gate passes it legitimately and counts it in the bypass ledger.
    # A refused commit is a failed run, same wire as a failed propagation
    # (ASK-182, lines above): the alert says so and the job exits 1, so Linear
    # sees it. The job is WEEKLY (plist Weekday 1), so a silent refusal would
    # leave a week of lessons uncommitted with nobody told (PR review, ASK-2290).
    # "Nothing staged" is not a failure: held lessons are gitignored (ASK-2278),
    # so a held-only run legitimately has nothing to commit.
    # Pinned by test/test-lessons-daily-commit-hooks.sh.
    COMMIT_MSG="chore(lessons): auto-learn $(date +%Y-%m-%d), ${PUB} published, ${HELD} held [no-issue: automated daily lesson persist]"
    LPATHS=()
    for p in q-system/lessons lesson-candidates; do [ -e "$LREPO/$p" ] && LPATHS+=("$p"); done
    if [ "${#LPATHS[@]}" -eq 0 ]; then
      echo "$(TS) lessons commit: no lesson paths exist, nothing to persist" >> "$LOG"
    elif ! ( cd "$LREPO" && git add -- "${LPATHS[@]}" ) >> "$LOG" 2>&1; then
      PERSIST="FAILED"
    elif ( cd "$LREPO" && git diff --cached --quiet -- "${LPATHS[@]}" ); then
      echo "$(TS) lessons commit: nothing staged" >> "$LOG"
    elif ! ( cd "$LREPO" || exit 1
             CPATHS=()
             for p in "${LPATHS[@]}"; do
               if [ -n "$(git diff --cached --name-only -- "$p")" ]; then CPATHS+=("$p"); fi
             done
             git commit --no-gpg-sign -m "$COMMIT_MSG" -- "${CPATHS[@]}" ) >> "$LOG" 2>&1; then
      # The pathspec keeps foreign staged files out of the lesson commit. A
      # path git knows nothing about (an empty lesson-candidates/) is a fatal
      # pathspec error, so only paths with STAGED changes are named; the
      # diff --cached test above guarantees at least one (and, unlike ls-files,
      # it sees a staged deletion), so CPATHS is never empty under set -u.
      PERSIST="FAILED"
    else
      COMMITTED=1
    fi
    if [ "${PERSIST:-}" = "FAILED" ]; then
      # Unstage what this job staged. Left in the index, q-system/lessons is the
      # exact state kipi-update.sh aborts on ("q-system/ is staged but not
      # committed"), which would jam every fleet update until someone resets it,
      # and the next commit would silently absorb it (PR 487 review round 3).
      # Path-limited reset: the working tree, and so the lessons, are untouched.
      ( cd "$LREPO" && git reset -q -- "${LPATHS[@]}" ) >> "$LOG" 2>&1 \
        || echo "$(TS) WARNING: could not unstage ${LPATHS[*]}; kipi-update.sh will abort until reset" >> "$LOG"
      echo "$(TS) lessons commit did not land (hook refusal or git error; output above). Lessons unstaged, still on disk." >> "$LOG"
    fi
  fi

  # PUBLISH: the commit leaves this machine before anything else happens (ASK-2736).
  # Every failure keeps the worktree and names it, so nothing is lost and nothing
  # is silent. The reviewer verdict is not a publish failure: an armed PR waits for
  # it, and the open-PR check above alerts next run if it is still waiting.
  [ "$PUBLISH_MODE" = pr ] && [ "${PERSIST:-}" = "FAILED" ] && KEEP_WT=1
  if [ "$PUBLISH_MODE" = pr ] && [ "${COMMITTED:-0}" = 1 ]; then
    KEEP_WT=1
    BR="auto/lessons-$(date +%Y%m%d)-$(git -C "$LREPO" rev-parse --short HEAD)"
    PR_BODY="Automated weekly lessons from lessons-daily.sh: ${PUB} published, ${HELD} held. Titles: ${TITLES:-none}"
    # THE PUSH GUARD (review of PR #551, round 4). This repo is public and a push is
    # permanent. On 2026-10-04 a Stop hook committed a non-lesson file onto the
    # cloud routine's lessons branch after its staged-set check, and it reached
    # PR #515. lessons-push-guard.py reads every commit on the branch, so this
    # path runs it before its push too.
    if ! python3 "$SKEL/q-system/.q-system/scripts/lessons-push-guard.py" \
           --repo "$LREPO" --base origin/main >> "$LOG" 2>&1; then
      PUBLISH="FAILED (lessons-push-guard refused the branch, see log; nothing pushed)"
    elif ! git -C "$LREPO" push -q origin "HEAD:refs/heads/$BR" >> "$LOG" 2>&1; then
      PUBLISH="FAILED (push of $BR refused)"
    elif ! PR_URL="$(cd "$LREPO" && gh pr create --base main --head "$BR" \
           --title "$COMMIT_MSG" --body "$PR_BODY" 2>>"$LOG")"; then
      PUBLISH="FAILED (branch $BR pushed, PR not opened)"
    elif ! ( cd "$LREPO" && gh pr merge "$PR_URL" --auto --squash ) >> "$LOG" 2>&1; then
      PUBLISH="FAILED ($PR_URL opened, auto-merge not armed)"
    else
      export PR_NUMBER="${PR_URL##*/}"
      if [ -n "${KIPI_REVIEW_CMD:-}" ]; then REVIEW="bash -c \"\$KIPI_REVIEW_CMD\""; else
        REVIEW="bash \"$LREPO/q-system/.q-system/scripts/pr-review-agent.sh\" \"$PR_NUMBER\" --post"; fi
      ( cd "$LREPO" && eval "$REVIEW" ) >> "$LOG" 2>&1 \
        || echo "$(TS) reviewer did not finish cleanly on $PR_URL; the armed PR waits for a verdict" >> "$LOG"
      echo "$(TS) lessons published: $PR_URL (branch $BR, auto-merge armed)" >> "$LOG"
      KEEP_WT=0
    fi
    [ -n "${PUBLISH:-}" ] && echo "$(TS) lessons publish $PUBLISH; lessons are in $LREPO" >> "$LOG"
  fi
}
lessons_half

# A refused commit may be a content gate (gitleaks, client-name guard) saying
# these lessons must not ship. Mirroring or fanning them out anyway would ship
# exactly what the gate stopped, so both are skipped (PR 487 review round 2).
# PR mode is the exception for the fan-out only: the refused lessons sit in the
# worktree and the fan-out ships the checkout's main, which never saw them, so
# skipping it would only freeze the fleet (ASK-2736). The mirror reads the
# worktree, so it is still skipped.

# Mirror the corpus to the founder's Notion lessons database (founder 2026-09-02:
# "the process needs to constantly write to Notion"). Off without credentials;
# a Notion outage is logged and never fails the lessons job.
if [ -n "${KIPI_NOTION_SYNC_CMD:-}" ]; then NOTION_SYNC="bash -c \"$KIPI_NOTION_SYNC_CMD\""; else NOTION_SYNC="python3 \"$SKEL/q-system/.q-system/scripts/lessons_notion_sync.py\" --lessons-dir \"$LESSONS_DIR\""; fi
if [ "${PERSIST:-}" = "FAILED" ]; then
  echo "$(TS) notion sync skipped: lessons commit did not land" >> "$LOG"
elif [ -n "$LESSONS_FAIL" ]; then
  echo "$(TS) notion sync skipped: the lessons half failed" >> "$LOG"
elif [ "${QUIET:-0}" = 1 ]; then
  echo "$(TS) notion sync skipped: nothing new" >> "$LOG"
elif eval "$NOTION_SYNC" >> "$LOG" 2>&1; then :; else
  echo "$(TS) notion sync failed (non-fatal, see above)" >> "$LOG"
fi

# BRING THE CHECKOUT TO MAIN BEFORE THE FAN-OUT (codex, PR #551 round 2).
# kipi-update.sh fans out from the checkout it runs in and refuses unless that
# checkout is ON main and AT origin/main (kipi-update.sh, "skeleton is not on" /
# "not AT origin"). Nothing else moves this checkout, and main moves several
# times a day, so a checkout switched to main is behind it within hours and the
# weekly fan-out refused anyway. This is the "pull before propagating" the
# updater asks a human for, done only where it cannot lose work:
#   on main with no local commits -> fast-forward (--ff-only refuses if a dirty
#     file is in the way, and then the updater refuses and the alert says so);
#   any other branch, or local commits -> left alone. Switching branches under
#     whoever is working in this checkout is not this job's call; the run fails
#     and the alert names the branch.
# A detached worktree at origin/main is NOT an alternative: the updater refuses
# a detached HEAD by the same check.
sync_skel_to_main() {
  local br
  br="$(git -C "$SKEL" symbolic-ref --short -q HEAD 2>/dev/null || true)"
  if [ "$br" != main ]; then
    echo "$(TS) skeleton checkout is on ${br:-a detached HEAD}, not main: left alone" >> "$LOG"
    return 0
  fi
  if ! git -C "$SKEL" fetch -q origin main >> "$LOG" 2>&1; then
    echo "$(TS) could not fetch origin/main before the fan-out" >> "$LOG"
    return 0
  fi
  if ! git -C "$SKEL" merge-base --is-ancestor HEAD origin/main 2>>"$LOG"; then
    echo "$(TS) skeleton main has commits origin/main lacks: left alone" >> "$LOG"
    return 0
  fi
  git -C "$SKEL" merge --ff-only -q origin/main >> "$LOG" 2>&1 \
    || echo "$(TS) fast-forward of skeleton main refused (see above)" >> "$LOG"
}

# --- streak bookkeeping: lessons_streak.py is the ONLY writer of the streak file
# and the escalations ledger (atomic replace under one lock; Codex finding-9).
STREAK_PY="$SKEL/q-system/.q-system/scripts/lessons_streak.py"
streak() { python3 "$STREAK_PY" --file "$STREAK_FILE" --ledger "$ESCALATIONS" "$@"; }

# Rule (finding-10): only a real propagation attempt bumps the streak. In local
# mode a run that publishes nothing neither resets nor increments it; that is the
# branch below ("no propagation (nothing published)") and the "nothing new" exit
# above. In PR mode every run attempts the fan-out, so every run moves it.
if [ "${PERSIST:-}" = "FAILED" ] && [ "$PUBLISH_MODE" != pr ]; then
  PROP="no propagation (lessons commit did not land)"
elif [ "$PUB" -gt 0 ] || [ "$PUBLISH_MODE" = pr ]; then  # PR mode fans out main every run (ASK-2736)
  [ "$PUBLISH_MODE" = pr ] && sync_skel_to_main
  if [ -n "${KIPI_PROPAGATE_CMD:-}" ]; then
    if bash -c "$KIPI_PROPAGATE_CMD" >> "$LOG" 2>&1; then PROP="propagated to fleet"; else PROP="propagate FAILED"; fi
  else
    if ( cd "$SKEL" && bash kipi-update.sh >> "$LOG" 2>&1 ); then PROP="propagated to fleet"; else PROP="propagate FAILED"; fi
  fi
else
  PROP="no propagation (nothing published)"
fi

# bump prints "<new>\t<previous>" from ONE locked operation; a separate read
# before the reset would let a concurrent failure land in between (Codex).
# A bump that FAILS is not "below the threshold" (PR #294 review round 7): an
# empty STREAK used to fall through the -ge test and skip the escalation with
# no line anywhere. Unknown escalates, with streak -1 in the ledger row so the
# count is never invented, and the founder's line says the bump broke.
if [ "$PROP" = "propagate FAILED" ]; then
  BUMP_OUT="$(streak bump --outcome fail 2>>"$LOG")"; BUMP_RC=$?
  IFS=$'\t' read -r STREAK _PREV <<< "$BUMP_OUT"
  case "$STREAK" in
    ''|*[!0-9]*)
      echo "$(TS) STREAK BUMP FAILED rc=$BUMP_RC (output: '${BUMP_OUT}'); escalating with the count unknown" >> "$LOG"
      streak append-escalation --streak -1 --threshold "$STREAK_ESCALATE" >/dev/null 2>>"$LOG" \
        || echo "$(TS) ESCALATION ROW FAILED too: $ESCALATIONS" >> "$LOG"
      PROP="propagate FAILED (streak UNKNOWN: bump failed rc=$BUMP_RC; escalated)"
      ;;
    *)
      if [ "$STREAK" -ge "$STREAK_ESCALATE" ]; then
        streak append-escalation --streak "$STREAK" --threshold "$STREAK_ESCALATE" >/dev/null
        PROP="propagate FAILED ($(streak summary))"
        echo "$(TS) ESCALATION streak=$STREAK (threshold $STREAK_ESCALATE): recorded in $ESCALATIONS" >> "$LOG"
      fi
      ;;
  esac
elif [ "$PROP" = "propagated to fleet" ]; then
  IFS=$'\t' read -r _NEW PREV_STREAK <<< "$(streak bump --outcome ok 2>>"$LOG")"
  case "$PREV_STREAK" in
    ''|*[!0-9]*) echo "$(TS) STREAK BUMP FAILED on the ok path (output: '${_NEW:-}'); the streak file needs a look" >> "$LOG" ;;
    *) [ "$PREV_STREAK" -gt 0 ] && echo "$(TS) streak reset after $PREV_STREAK failure(s)" >> "$LOG" ;;
  esac
fi

# In PR mode the fan-out ships MAIN, and this run's lessons are not on main yet.
# Saying "propagated to fleet" beside "they reach the fleet after it merges" was
# one alert contradicting itself (PR #551 review round 1), so the words say
# what actually went out.
PROP_TXT="$PROP"
[ "$PUBLISH_MODE" = pr ] && [ "$PROP" = "propagated to fleet" ] && PROP_TXT="fleet updated from main"
MSG="Fleet learning ($(date +%Y-%m-%d)): ${PUB} new lesson(s), ${PROP_TXT}"
[ "$PUB" -gt 0 ] && [ -n "${TITLES:-}" ] && MSG="$MSG — ${TITLES}"
[ "$HELD" -gt 0 ] && MSG="$MSG · ${HELD} held for review (possible client data, see lesson-candidates/)"
case "$PROP" in "propagate FAILED"*) MSG="$MSG · propagation FAILED, see log" ;; esac
[ "${PERSIST:-}" = "FAILED" ] && MSG="$MSG · lessons commit FAILED (hook refusal or git error), not persisted, see log"
[ "$PUBLISH_MODE" = pr ] && [ "${PERSIST:-}" = "FAILED" ] && MSG="$MSG · lessons left in $LREPO"
[ -n "${PR_URL:-}" ] && [ -z "${PUBLISH:-}" ] && MSG="$MSG · this run's lessons are in $PR_URL, not in that update; they go out with the first weekly update after it merges"
[ -n "${PUBLISH:-}" ] && MSG="$MSG · lessons publish $PUBLISH, lessons are in $LREPO"
# The reason the alert never gave for six weeks (ASK-2736): name the branch.
case "$PROP" in "propagate FAILED"*)
  SKEL_BRANCH="$(git -C "$SKEL" symbolic-ref --short -q HEAD 2>/dev/null || echo detached)"
  [ "$SKEL_BRANCH" != "main" ] && MSG="$MSG · the skeleton checkout is on $SKEL_BRANCH, not main" ;;
esac
[ -n "${HOLD:-}" ] && MSG="$MSG · $HOLD"
[ -n "$LESSONS_FAIL" ] && MSG="$MSG · lessons FAILED: $LESSONS_FAIL"
# Silent when nothing new and the weekly update went out: the header contract.
# A held run is never silent: nothing was distilled and someone has to act.
if [ "${QUIET:-0}" = 1 ] && [ "$PROP" = "propagated to fleet" ] && [ -z "${HOLD:-}" ]; then
  echo "$(TS) quiet week: fleet updated from main, nothing new, not slacked" >> "$LOG"
else
  notify "$MSG"
  echo "$(TS) slacked: $MSG" >> "$LOG"
fi

# Lessons that published but never reached the fleet are a half-done run: the
# Slack line above says so, and this makes launchd (and therefore Linear) agree.
# Held lessons are NOT a failure -- the scrub gate holding client data is the gate
# working, and paging on it would train the founder to ignore the channel.
case "$PROP" in
  "propagate FAILED"*) echo "$(TS) propagation failed -> exit 1" >> "$LOG"; exit 1 ;;
esac
if [ "${PERSIST:-}" = "FAILED" ]; then echo "$(TS) lessons commit failed -> exit 1" >> "$LOG"; exit 1; fi
if [ -n "${PUBLISH:-}" ]; then echo "$(TS) lessons publish failed -> exit 1" >> "$LOG"; exit 1; fi
if [ -n "${HOLD:-}" ]; then echo "$(TS) distilling held by an unmerged lessons branch -> exit 1" >> "$LOG"; exit 1; fi
if [ -n "$LESSONS_FAIL" ]; then echo "$(TS) lessons half failed -> exit 1" >> "$LOG"; exit 1; fi
exit 0
