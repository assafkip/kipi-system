#!/bin/bash
# kipi-job-pinned.sh -- run one launchd job from ITS OWN checkout, advanced to origin/main (ASK-3966).
#
# Usage (written by install-plist.sh, never by hand):
#   /bin/bash <pinned>/q-system/.q-system/scripts/kipi-job-pinned.sh <job argv...>
# where <pinned> is <HOME>/.local/state/kipi/jobs/<label>/<repo ident>, a worktree of the
# skeleton that install-plist.sh created detached at origin/main and LOCKED.
#
# WHY. Founder, 2026-11-08: "ensure everyitng runs on separate work trees so things done
# conflict". 14 com.kipi.* jobs ran their code from the shared checkout
# ~/projects/kipi-system, where a human works and the orchestrator fast-forwards. A
# fast-forward could land in the middle of a job's run, and the job ran whatever the
# human had half-edited. kipi-dispatch-pinned.sh (ASK-812) fixed this for dispatch alone
# on 2026-08-06 after a 22.5-hour outage; this is the same move for every other job.
#
# ONE CHECKOUT PER JOB, NOT ONE FOR ALL. A shared job checkout would bring the race
# back: job A advancing it while job B runs. Each job advances only its own tree, at
# the start of its own run, and nothing else ever moves it.
#
# IT REFUSES, NEVER FORCES (the rule kipi-dispatch-pinned.sh carries). The advance is
# `checkout --detach origin/main`, which refuses on a tree it cannot move cleanly, and
# never `reset --hard`, `-f` or `clean`. On a refusal the job still runs, on the head it
# has: a consistent old version beats no run, and the refusal is logged and filed once a
# day. A tree that is dirty is a bug in the job (it writes inside its checkout) and the
# filed ticket names it.
#
# THE WHOLE BODY IS ONE { } BLOCK, AND THAT IS LOAD-BEARING. This file lives inside the
# tree it advances, so the checkout below can rewrite it while it runs. bash reads a
# script as it executes it, so an edit landing mid-run would make it execute a mix of
# two versions. bash parses a compound command whole before running any of it, and the
# `exit` inside the block means nothing after it is ever read.
{
set -uo pipefail
TREE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
LABEL="$(basename "$(dirname "$TREE")")"
LOG="${KIPI_JOB_PIN_LOG:-$HOME/.config/kipi/job-pinned.log}"
NOTIFY="${KIPI_NOTIFY:-$TREE/q-system/.q-system/scripts/slack-notify.sh}"
PAGE_TTL="${KIPI_JOB_PIN_PAGE_TTL:-86400}"

say() { printf '%s %s: %s\n' "$(date -u +%FT%TZ)" "$LABEL" "$*" >>"$LOG" 2>/dev/null || true; }

# Once a day per label, and only a delivered alert burns the window: the two rules
# kipi-dispatch-pinned.sh learned in PR #122 rounds 2 and 3. slack-notify.sh files a
# Linear ticket for Sana and pages nobody.
page_once() {
  local mark now last
  mark="$(dirname "$LOG")/job-pinned-paged-$LABEL"
  now="$(date -u +%s)"
  last="$(cat "$mark" 2>/dev/null || echo 0)"
  case "$last" in ''|*[!0-9]*) last=0 ;; esac
  [ $((now - last)) -lt "$PAGE_TTL" ] && return 0
  [ -f "$NOTIFY" ] || return 0
  if bash "$NOTIFY" "$1" >/dev/null 2>&1; then
    printf '%s' "$now" > "$mark" 2>/dev/null || true
  fi
}

if [ $# -eq 0 ]; then
  say "no job command given; nothing to run"
  exit 2
fi

# A worktree shares the skeleton's object store, so this fetch also updates origin/main
# for every other worktree. Offline is not fatal: the job runs on the head it has.
git -C "$TREE" fetch --quiet origin main 2>/dev/null || say "fetch failed; running the head this checkout has"

before="$(git -C "$TREE" rev-parse --short HEAD 2>/dev/null || echo '?')"
if git -C "$TREE" checkout --detach --quiet origin/main 2>>"$LOG"; then
  after="$(git -C "$TREE" rev-parse --short HEAD 2>/dev/null || echo '?')"
  [ "$before" = "$after" ] || say "advanced $before -> $after"
  rm -f "$(dirname "$LOG")/job-pinned-paged-$LABEL" 2>/dev/null || true
else
  say "could not advance $TREE to origin/main (dirty or diverged); running $before"
  page_once "kipi job $LABEL: its pinned checkout $TREE could not advance to origin/main (dirty or diverged), so it is running old code ($before). A job must not write inside its checkout. Run \`git -C $TREE status\` to see what it wrote."
fi

cd "$TREE" || { say "cannot cd into $TREE"; exit 1; }
exec "$@"
exit $?
}
