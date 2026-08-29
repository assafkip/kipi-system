#!/bin/bash
# Run kipi-dispatch.sh from a checkout DEDICATED to it and pinned to origin/main.
#
# THE OUTAGE THIS ENDS (measured 2026-08-06)
# ------------------------------------------
# com.kipi.dispatch sets KIPI_REPO to the shared checkout at
# ~/projects/kipi-system. Interactive agent sessions work in that same checkout,
# so it spends most of its life parked on a feature branch. kipi-dispatch.sh's
# stale_check() then correctly refuses to dispatch:
#
#   2026-08-06T22:24:47Z STALE: origin/main holds 12 commit(s) this checkout
#     lacks (HEAD ba584d2, origin/main 7aa9cdd). Dispatching would run
#     superseded control code and auto-merge the result.
#
# Every 900s tick from 2026-08-05T23:53Z onward aborted there: 1351 minutes of
# total dispatch outage, one page, because the page suppressor mutes a persisting
# condition for 24h (sp-64b8872b). The guard was right every single time. What was
# wrong was pointing it at a checkout that humans park.
#
# WHY A WORKTREE AND NOT A CLONE
# ------------------------------
# `.prd-os/spillover.jsonl` is gitignored (.gitignore:36) and lives physically in
# the shared checkout's working tree. prd_runner resolves it through
# git-common-dir, so every worktree of this repo reaches ONE ledger. A separate
# clone has its own .git, so it would silently fork the spillover ledger into two
# files and the no-orphan-findings gate would go green on half the record.
# A worktree fixes the staleness without splitting any state.
#
# This is safe because the worker never moves TARGET_REPO's HEAD: linear-worker.sh
# cuts every issue tree with `worktree add -B` into $STATE_DIR/worktrees/
# (linear-worker.sh:1064,1092). A dedicated checkout therefore just stays on main.
#
# THIS DOES NOT WEAKEN THE STALE GUARD, AND MUST NOT
# --------------------------------------------------
# The guard exists so dispatch never runs superseded control code. This wrapper
# removes the CAUSE (a parked checkout) and leaves the guard to catch the case
# where removal failed. So the advance below is `checkout --detach origin/main`,
# which REFUSES on a dirty or diverged tree, and never `reset --hard` / `-f` /
# `clean`. If the pinned checkout cannot be advanced, we still exec dispatch and
# let stale_check() refuse on its own terms. A wrapper that forced the tree green
# would clear the symptom and reintroduce exactly the risk the guard was written
# for. test_dispatch_pinned.sh holds that line.
set -uo pipefail

REPO_MAIN="${KIPI_REPO_MAIN:-$HOME/projects/kipi-system}"

# THE CHECKOUT'S DIRECTORY NAME IS LOAD-BEARING, AND NAMING IT "dispatch-checkout"
# SILENTLY KILLED HOME-REPO DISPATCH (ASK-829).
#
# linear-worker.sh resolves which Linear project an issue belongs to like this:
#     KIPI_LINEAR_PROJECT  ->  registry lookup by path  ->  basename $TARGET_REPO
# The pinned checkout is not in instance-registry.json, so resolution fell all the
# way through to basename, which was "dispatch-checkout" -- a name matching no
# Linear project. Every home-repo issue was filtered out:
#
#   MISCONFIG: repo identity 'dispatch-checkout' matches NO Linear project
#   MISCONFIG: every issue would be filtered out, so this run picked nothing
#              for a config reason, not an empty board.
#
# Measured 2026-08-15: 25 ready issues unpickable, while the DISPATCH log said
# only "nothing ready ()" -- indistinguishable from an empty board, because the
# MISCONFIG lines land in linear-worker.log, a different file. Cross-repo was
# unaffected: it passes --repo and resolves through the registry, so only the
# home repo was dead and the fleet looked half-alive.
#
# So the name is DERIVED from the repo's own identity rather than invented. The
# origin URL is the one thing that always knows what this repository is; the
# containing directory does not (KIPI_REPO_MAIN is itself a worktree here, named
# dispatch-main). A machine-local env override would have worked too and is what
# unblocked it on the night; it is not the fix, because a fresh install or a
# re-render of the plist silently reintroduces the filtering.
_repo_ident() {
  local url base
  url="$(git -C "$REPO_MAIN" remote get-url origin 2>/dev/null)" || return 1
  [ -n "$url" ] || return 1
  base="${url##*/}"; base="${base%.git}"
  [ -n "$base" ] || return 1
  printf '%s' "$base"
}
_IDENT="$(_repo_ident || true)"
# Fall back to the old literal ONLY if the remote cannot be read. That is worse
# than useless for project resolution, so it is announced rather than silent.
if [ -z "$_IDENT" ]; then
  _IDENT="dispatch-checkout"
fi
PINNED="${KIPI_DISPATCH_CHECKOUT:-$HOME/.local/state/kipi/dispatch/$_IDENT}"
LOG="${KIPI_DISPATCH_LOG:-$HOME/.config/kipi/dispatch.log}"

say() { printf '%s %s\n' "$(date -u +%FT%TZ)" "pinned: $*" >>"$LOG" 2>/dev/null || true; }

# A SILENT exit 0 IS THE FAILURE MODE THIS FILE EXISTS TO END (codex major, r1).
# Every refusal below returns 0 so launchd records a clean run -- which is right,
# because a nonzero exit would make launchd throttle a job that is behaving
# correctly. But a clean launchd record plus a line in a log nobody reads is
# exactly the shape of the 22.5h outage above: dispatch stopped, and the only
# evidence was a file. So a refusal RAISES AN ALERT, and the log line stops being
# the only copy.
#
# WHERE THAT ALERT ACTUALLY GOES (corrected, sp-d9212e22). An earlier version of
# this comment -- mine -- said it "reaches the founder's phone". It does not.
# slack-notify.sh keeps its name for ~30 callers but its header is explicit:
# "THE FLEET ALERT PATH. Files a Linear ticket for Sana. Pages nobody." Nothing
# in it sends to Slack. That is the founder's stated routing, not a degradation:
# things needing attention go to Sana. Saying "pages the founder" in a comment
# would set the wrong expectation about who is watching at 3am.
NOTIFY="${KIPI_NOTIFY:-$REPO_MAIN/q-system/.q-system/scripts/slack-notify.sh}"

# AND IT PAGES ONCE, NOT 96 TIMES A DAY (codex major, PR #122 r2).
#
# These refusals are PERSISTENT by nature: a checkout that cannot be created at
# 09:00 still cannot be created at 09:15. Paging every 900s tick is 96 identical
# Slack lines a day, which does not inform the operator, it trains them to swipe
# the alert away. An alert nobody reads is the same outcome as no alert, reached
# more expensively -- so the dedupe is part of the fix, not a polish pass on it.
#
# 24h, matching the suppressor kipi-dispatch.sh already applies to its own
# persisting conditions, so the two do not disagree about how loud a stuck state
# should be.
#
# DELIBERATELY SIMPLER THAN kipi-dispatch.sh's page_once. That one carries a
# lock because several dispatchers can evaluate one key at once. This runs as a
# single launchd job that exec's within seconds, so there is no second writer to
# race; a lock here would be machinery defending against a caller that does not
# exist. What it keeps is the part that matters: an orphaned marker must age out
# rather than mute the key forever.
PAGE_TTL="${KIPI_DISPATCH_PAGE_TTL:-86400}"
page() {
  local key="$1" msg="$2" mark now last
  mark="$(dirname "$LOG")/pinned-paged-$key"
  now="$(date -u +%s)"
  if [ -f "$mark" ]; then
    last="$(cat "$mark" 2>/dev/null || echo 0)"
    case "$last" in ''|*[!0-9]*) last=0 ;; esac
    # Still inside the window: log it, stay quiet. The log always has every
    # occurrence; only the phone is rate-limited.
    if [ $((now - last)) -lt "$PAGE_TTL" ]; then
      say "page suppressed ($key): already sent $(( (now - last) / 60 ))m ago"
      return 0
    fi
  fi
  # ONLY A DELIVERED PAGE BURNS THE WINDOW (codex major, PR #122 r3).
  #
  # Round 2 stamped the marker after the send ATTEMPT and the comment claimed
  # that protected a down notifier. It did not: "after the attempt" is not "on
  # success", so a Slack outage wrote a 24h mute and the dispatch outage went
  # unreported for a day after the notifier came back. That is the same
  # comment-says-one-thing-code-does-another shape this session already fixed in
  # the fleet drift detector, rebuilt here by the fix for the previous finding.
  #
  # So the exit status decides. A notifier that is absent or fails leaves NO
  # marker, and the next tick 900s later tries again. The cost of getting this
  # wrong is asymmetric: an extra page is noise, a swallowed page is the silent
  # outage the whole file exists to end.
  if [ ! -f "$NOTIFY" ]; then
    say "page NOT sent ($key): no notifier at $NOTIFY -- not recording a dedupe window"
    return 0
  fi
  if bash "$NOTIFY" "$msg" >/dev/null 2>&1; then
    printf '%s' "$now" > "$mark" 2>/dev/null || true
  else
    say "page FAILED to send ($key): leaving the window open so the next tick retries"
  fi
}

# A recovery clears the markers, so the NEXT time this breaks it pages
# immediately instead of inheriting a stale 24h window from the last outage.
clear_page_marks() { rm -f "$(dirname "$LOG")"/pinned-paged-* 2>/dev/null || true; }

# Fetch in the MAIN checkout: the worktree shares its object store, so one fetch
# updates origin/main for both. A failure here is not fatal -- stale_check() runs
# its own fetch and has a documented fail-open path for offline.
git -C "$REPO_MAIN" fetch --quiet origin main 2>/dev/null || say "fetch failed, continuing"

if [ ! -e "$PINNED/.git" ]; then
  mkdir -p "$(dirname "$PINNED")" 2>/dev/null || true
  if ! git -C "$REPO_MAIN" worktree add --detach "$PINNED" origin/main >>"$LOG" 2>&1; then
    say "could not create the pinned checkout at $PINNED -- NOT falling back to the shared checkout"
    # Deliberately not exec'ing dispatch against $REPO_MAIN here. Falling back to
    # the parked checkout is what this change exists to stop, and a fallback would
    # make the outage silent again instead of loud.
    page create-failed "kipi dispatch: STOPPED. The pinned checkout at $PINNED could not be created, and dispatch will not fall back to the shared checkout. No issues are being worked. Do: run \`git -C $REPO_MAIN worktree add --detach $PINNED origin/main\` and read the error."
    exit 0
  fi
  say "created pinned checkout at $PINNED"
fi

# REFUSES rather than forces. See the header.
if ! git -C "$PINNED" checkout --detach --quiet origin/main 2>>"$LOG"; then
  say "could not advance $PINNED to origin/main (dirty or diverged); dispatch's stale guard will refuse"
fi

if [ ! -f "$PINNED/kipi-dispatch.sh" ]; then
  say "no kipi-dispatch.sh in $PINNED -- refusing"
  page no-dispatch "kipi dispatch: STOPPED. $PINNED exists but holds no kipi-dispatch.sh, so there is nothing to run. No issues are being worked. Do: inspect that checkout, or remove it and let the next tick rebuild it."
  exit 0
fi

# Everything the wrapper is responsible for succeeded. Clear the suppressors so a
# FUTURE break pages at once rather than inheriting this outage's 24h window.
clear_page_marks

exec env KIPI_REPO="$PINNED" bash "$PINNED/kipi-dispatch.sh" "$@"
