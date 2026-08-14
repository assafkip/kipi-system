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
PINNED="${KIPI_DISPATCH_CHECKOUT:-$HOME/.local/state/kipi/dispatch-checkout}"
LOG="${KIPI_DISPATCH_LOG:-$HOME/.config/kipi/dispatch.log}"

say() { printf '%s %s\n' "$(date -u +%FT%TZ)" "pinned: $*" >>"$LOG" 2>/dev/null || true; }

# A SILENT exit 0 IS THE FAILURE MODE THIS FILE EXISTS TO END (codex major, r1).
# Every refusal below returns 0 so launchd records a clean run -- which is right,
# because a nonzero exit would make launchd throttle a job that is behaving
# correctly. But a clean launchd record plus a line in a log nobody reads is
# exactly the shape of the 22.5h outage above: dispatch stopped, and the only
# evidence was a file. So a refusal PAGES, and the log line stops being the only
# copy. Routed through slack-notify.sh because it is the one channel that reaches
# the founder's phone from a headless launchd context; osascript is silently
# dropped there (founder-notifications rule).
NOTIFY="${KIPI_NOTIFY:-$REPO_MAIN/q-system/.q-system/scripts/slack-notify.sh}"
page() { [ -f "$NOTIFY" ] && bash "$NOTIFY" "$1" >/dev/null 2>&1 || true; }

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
    page "kipi dispatch: STOPPED. The pinned checkout at $PINNED could not be created, and dispatch will not fall back to the shared checkout. No issues are being worked. Do: run \`git -C $REPO_MAIN worktree add --detach $PINNED origin/main\` and read the error."
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
  page "kipi dispatch: STOPPED. $PINNED exists but holds no kipi-dispatch.sh, so there is nothing to run. No issues are being worked. Do: inspect that checkout, or remove it and let the next tick rebuild it."
  exit 0
fi

exec env KIPI_REPO="$PINNED" bash "$PINNED/kipi-dispatch.sh" "$@"
