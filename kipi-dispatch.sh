#!/usr/bin/env bash
# The heartbeat that keeps the Linear loop running with NO terminal open.
#
# WHY THIS EXISTS
# ---------------
# Every converge run before 2026-07-28 was typed by a human into an interactive
# session. `kipi work` and `converge` had no scheduler, unlike every other kipi
# job. So the loop only ran while someone watched it, which is not autonomy --
# it is a person standing in for a cron job. The founder's requirement, verbatim:
# "I want to make sure that I can actually, at the end of this session, close
# this terminal."
#
# Lives at REPO ROOT, not under q-system/. Instance automation inside the synced
# subtree gets deleted by `kipi update`'s rsync --delete (RULE-2026-06-30-A, and
# the scar: income scanners went dark for 6 days that way).
#
# LOOP EXITS (loop-exits.md -- an autonomous loop owns 2, 4, 7 at minimum)
#   2 turn cap      MAX_CONCURRENT live converge runs, counted from the process
#                   table, not from a state file that can lie.
#   3 budget        one dispatch per heartbeat. The interval IS the rate limit.
#   4 wall clock    each converge carries --max-rounds; the reviewer is bounded
#                   at 2400s inside pr-review-agent.sh.
#   5 no progress   an issue moves to In Progress the moment the worker takes
#                   it, and ready() only returns backlog/unstarted -- so a
#                   dispatched issue excludes itself from the next heartbeat.
#   7 error thresh  the worker's own MAX_ATTEMPTS marks an issue stuck and
#                   stops picking it. This script does not second-guess that.
#   6 human interrupt  launchctl unload. Outside the loop, as it must be.
#
# WHAT PICKS THE WORK
# -------------------
# `kipi work` in DRY mode. Deliberately not a second Linear query: ready() lives
# in linear-worker.sh:197 (owner:sana, not owner:assaf, backlog/unstarted, has a
# DoR) and two readers of "ready" with drifting semantics is the exact defect
# class this repo keeps finding. One source of truth, asked politely.
set -uo pipefail

REPO="${KIPI_REPO:-/Users/assafkipnis/projects/kipi-system}"
LOG="$HOME/.config/kipi/dispatch.log"
MAX_CONCURRENT="${KIPI_DISPATCH_MAX:-2}"
MAX_ROUNDS="${KIPI_DISPATCH_ROUNDS:-3}"
NOTIFY="${KIPI_NOTIFY:-$REPO/q-system/.q-system/scripts/slack-notify.sh}"

mkdir -p "$(dirname "$LOG")"
say() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >> "$LOG"; }
page() { bash "$NOTIFY" "$1" >/dev/null 2>&1 || true; }

cd "$REPO" 2>/dev/null || {
  say "FATAL: repo not found at $REPO"
  page "kipi dispatch: repo not found at $REPO -- the Linear loop is DEAD. Do: check the path in com.kipi.dispatch.plist."
  exit 1
}

# `pgrep -c` exits 1 with no match, which under `set -e` would look like failure
# and under a bare assignment yields an empty string. Force a number.
live_converges() { pgrep -f "converge.sh --issue" 2>/dev/null | grep -c . || true; }

LIVE="$(live_converges)"; LIVE="${LIVE:-0}"
if [ "$LIVE" -ge "$MAX_CONCURRENT" ]; then
  say "skip: $LIVE converge run(s) live, cap $MAX_CONCURRENT"
  exit 0
fi

# --- DAILY BUDGET (loop-exits.md exit 3) ---------------------------------
# The concurrency cap bounds how many run AT ONCE. It does NOT bound how many
# run IN A DAY -- at ~1 issue/hour that is ~24 issues and ~144 `claude -p`
# sessions overnight, against a subscription with a real weekly ceiling.
# Measured 2026-07-28: one interactive night spawned 89 sessions and 44 reviewer
# runs. An unbounded heartbeat is a runaway-bill loop, which is exactly the
# thing loop-exits.md says an autonomous loop must not be.
#
# One issue costs up to MAX_ROUNDS x (1 agent + 1 reviewer) = 6 sessions.
# So DAILY_MAX is roughly "sessions per day / 6".
DAILY_MAX="${KIPI_DISPATCH_DAILY_MAX:-4}"
TODAY="$(date -u +%Y-%m-%d)"
COUNT_FILE="$HOME/.config/kipi/dispatch-count-$TODAY"
DISPATCHED_TODAY="$(cat "$COUNT_FILE" 2>/dev/null || echo 0)"
case "$DISPATCHED_TODAY" in ''|*[!0-9]*) DISPATCHED_TODAY=0 ;; esac

if [ "$DISPATCHED_TODAY" -ge "$DAILY_MAX" ]; then
  # Say it once per day, not every 15 minutes -- a budget ceiling repeated 96
  # times is the cry-wolf failure, and this is not an error state anyway.
  if [ ! -f "$COUNT_FILE.paged" ]; then
    say "DAILY CAP: $DISPATCHED_TODAY/$DAILY_MAX issues dispatched today, stopping until UTC midnight"
    page "kipi dispatch: hit the daily cap of $DAILY_MAX issues (~$((DAILY_MAX * 6)) agent sessions). Not an error -- the loop is resting until UTC midnight. Do: raise KIPI_DISPATCH_DAILY_MAX in com.kipi.dispatch.plist to go faster, or leave it."
    : > "$COUNT_FILE.paged"
  fi
  exit 0
fi

# gh is what every downstream step needs; failing here with a clear page beats
# dispatching an agent that dies opening its PR.
if ! command -v gh >/dev/null 2>&1; then
  say "FATAL: gh not on PATH ($PATH)"
  page "kipi dispatch: gh CLI not on PATH under launchd, so no PR can be opened. The Linear loop is stalled. Do: fix PATH in com.kipi.dispatch.plist."
  exit 1
fi

WORK_OUT="$(bash ./kipi work 2>&1)"
WORK_RC=$?

# An infra error (Linear down, auth expired) is environmental: it will not
# self-heal on the next heartbeat, so say so once rather than fail silently
# every 15 minutes forever. self-healing-retry.md rule 5.
if printf '%s' "$WORK_OUT" | grep -qi "infra_error\|authentication\|unauthorized"; then
  say "infra error from kipi work: $(printf '%s' "$WORK_OUT" | head -3 | tr '\n' ' ')"
  page "kipi dispatch: Linear is unreachable or auth expired, so NO issues can be picked up. The loop is stopped, not slow. Do: run \`bash kipi work\` by hand and check the Linear token."
  exit 1
fi

NEXT="$(printf '%s' "$WORK_OUT" | grep -oE '\[dry\] would work ASK-[0-9]+' | grep -oE 'ASK-[0-9]+' | head -1)"
if [ -z "$NEXT" ]; then
  say "nothing ready ($(printf '%s' "$WORK_OUT" | grep -oE '[0-9]+ ready issue' | head -1))"
  exit 0
fi

# Belt and braces against the race between dispatch and the In Progress
# transition: two converge runs on one issue would fight over one worktree.
if pgrep -f "converge.sh --issue $NEXT\b" >/dev/null 2>&1; then
  say "skip $NEXT: a converge run for it is already live"
  exit 0
fi

# Count BEFORE launching. Counting after would let a crash between the two
# hand out a free dispatch every heartbeat -- the budget must fail closed.
printf '%s' "$((DISPATCHED_TODAY + 1))" > "$COUNT_FILE"

say "dispatching $NEXT (live=$LIVE cap=$MAX_CONCURRENT rounds=$MAX_ROUNDS budget=$((DISPATCHED_TODAY + 1))/$DAILY_MAX)"
nohup ./kipi converge --issue "$NEXT" --max-rounds "$MAX_ROUNDS" \
  > "$HOME/.config/kipi/converge-$NEXT.log" 2>&1 &
disown

say "dispatched $NEXT"
exit 0
