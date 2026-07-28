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

# --- LIVENESS BEACON: page when the heartbeat COMES BACK ------------------
# Founder ask 2026-07-28: "I want to get a slack notification that the heartbeat
# restarted when it does."
#
# The signal is the TRANSITION (was gone -> is back), never the level. This runs
# every 900s, so paging per tick would be 96 pings a day -- the cry-wolf failure
# that trains someone to mute the channel and costs the real alerts their job.
#
# Placed BEFORE every early exit on purpose. Most ticks legitimately skip (cap
# reached, nothing ready), and a skip is still proof of life. Recording the beat
# only on a dispatch would make a healthy-but-idle loop look dead, and would fire
# a false "resumed" ping on the next dispatch.
#
# A gap larger than GAP_MINUTES means it was not running: reboot, a manual
# unload/load, a crash the launchd watchdog restarted, or the Mac asleep. All
# four are worth one line.
GAP_MINUTES="${KIPI_DISPATCH_GAP_MINUTES:-45}"   # 3 missed ticks at 900s
BEAT_FILE="$HOME/.config/kipi/dispatch-lastbeat"
NOW_EPOCH="$(date -u +%s)"
LAST_BEAT="$(cat "$BEAT_FILE" 2>/dev/null || echo "")"
case "$LAST_BEAT" in ''|*[!0-9]*) LAST_BEAT="" ;; esac

if [ -z "$LAST_BEAT" ]; then
  say "heartbeat: first beat on record"
  page "kipi heartbeat: STARTED. The Linear loop is live and will check for ready issues every 15 min (max ${KIPI_DISPATCH_DAILY_MAX:-4} issues/day). Nothing to do."
else
  GAP=$(( (NOW_EPOCH - LAST_BEAT) / 60 ))
  if [ "$GAP" -ge "$GAP_MINUTES" ]; then
    say "heartbeat: RESUMED after ${GAP}m without a beat"
    page "kipi heartbeat: RESUMED after ${GAP} min down (reboot, sleep, or a reload). The Linear loop is running again. Nothing to do -- this is the all-clear, not a fault."
  fi
fi
printf '%s' "$NOW_EPOCH" > "$BEAT_FILE"

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
# The budget day starts at RESET_HOUR LOCAL, not at midnight and not at UTC.
# Founder-set 2026-07-28, and the reasoning is safety, not tidiness:
#
#   UTC midnight     rolls at 17:00 local -- refills at teatime, leaving the loop
#                    idle through the whole working day it was meant to serve.
#   local midnight   refills the instant the founder falls asleep, handing a full
#                    budget to an unattended overnight run. Worst of the three.
#   local 07:00      overnight can only spend what is LEFT from yesterday, and a
#                    fresh budget arrives when someone is awake to watch it.
#
# Implemented by shifting the clock back RESET_HOUR hours and taking that date,
# so 03:00 Tuesday still belongs to Monday's budget. The file NAME carries the
# label, so the rollover needs no timer, no cron entry and no state machine: a
# new budget day is simply a new filename that reads 0.
RESET_HOUR="${KIPI_DISPATCH_RESET_HOUR:-7}"
# BSD date (macOS) uses -v; GNU date uses -d. Try both so this is not silently
# wrong on a Linux box, where a failed shift would fall back to today's date and
# quietly restore the midnight behaviour.
BUDGET_DAY="$(date -v-"${RESET_HOUR}"H +%Y-%m-%d 2>/dev/null \
              || date -d "-${RESET_HOUR} hours" +%Y-%m-%d 2>/dev/null)"
if [ -z "$BUDGET_DAY" ]; then
  say "FATAL: could not compute the budget day (neither BSD nor GNU date worked)"
  page "kipi dispatch: cannot compute its spend budget window, so it refused to dispatch rather than run uncapped. Do: check \`date -v-7H\` on this machine."
  exit 1
fi
COUNT_FILE="$HOME/.config/kipi/dispatch-count-$BUDGET_DAY"
DISPATCHED_TODAY="$(cat "$COUNT_FILE" 2>/dev/null || echo 0)"
case "$DISPATCHED_TODAY" in ''|*[!0-9]*) DISPATCHED_TODAY=0 ;; esac

if [ "$DISPATCHED_TODAY" -ge "$DAILY_MAX" ]; then
  # Say it once per day, not every 15 minutes -- a budget ceiling repeated 96
  # times is the cry-wolf failure, and this is not an error state anyway.
  if [ ! -f "$COUNT_FILE.paged" ]; then
    say "DAILY CAP: $DISPATCHED_TODAY/$DAILY_MAX issues dispatched for budget day $BUDGET_DAY, stopping until ${RESET_HOUR}:00 local"
    page "kipi dispatch: hit the daily cap of $DAILY_MAX issues (~$((DAILY_MAX * 6)) agent sessions). Not an error -- the loop is resting until ${RESET_HOUR}am, then it picks up again on its own. Do: nothing, or raise KIPI_DISPATCH_DAILY_MAX in com.kipi.dispatch.plist to go faster."
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

# THE CHILD NEEDS ITS OWN SESSION, AND THIS IS NOT A STYLE CHOICE.
#
# This was `nohup ... & disown`, which is correct in an interactive shell and
# WRONG under launchd. launchd reaps the job's whole process group when the main
# process exits; nohup only blocks SIGHUP, so the converge was killed the instant
# this script returned. Every launchd dispatch since the dispatcher was installed
# died that way, and the failure was invisible by construction: the log file is
# created by the redirect before the child dies, so it exists and is 0 bytes,
# `say "dispatched $NEXT"` still runs, and the budget counter is already spent.
# The loop reported four healthy dispatches of ASK-224 on 2026-07-28 and did no
# work at all -- it only spent the subscription.
#
# PROVEN, not reasoned about. A launchd job whose only act was
# `nohup bash -c "sleep 25; touch F" & disown; exit`:
#     under launchd   F never written  (child killed)
#     same script from an interactive shell   F written (child survived)
# and with the setsid form below, under launchd, F is written.
#
# macOS ships no setsid(1), so python3 is how setsid(2) gets called. A new
# session means a new process group with no controlling terminal, which is
# outside the group launchd tears down.
python3 - "$HOME/.config/kipi/converge-$NEXT.log" \
         ./kipi converge --issue "$NEXT" --max-rounds "$MAX_ROUNDS" <<'PY'
import subprocess, sys
log_path, argv = sys.argv[1], sys.argv[2:]
# Append, never truncate: a re-dispatch of the same issue must not erase the
# evidence of the previous run (the burst incident truncated a live log with >).
log = open(log_path, "ab", buffering=0)
subprocess.Popen(argv, stdout=log, stderr=log, start_new_session=True)
PY
RC=$?
if [ "$RC" -ne 0 ]; then
  # A launch that failed must NOT report success -- that is the same shape as
  # the bug above. The budget slot is already spent, so say so plainly.
  say "FAILED to launch converge for $NEXT (rc=$RC); the budget slot is spent"
  page "kipi dispatch: could not launch the converge run for $NEXT, so NO work is happening even though the loop looks alive. Do: run \`bash kipi-dispatch.sh\` by hand and read the error."
  exit 1
fi

# PROVE IT IS ALIVE BEFORE CLAIMING IT. The whole defect above was a dispatch
# that reported success into a void, so the report is now evidence-backed: the
# process either shows up in the table or the founder hears about it.
#
# NOT `pgrep -f "...$NEXT\b"`. \b is a GNU regex extension and BSD pgrep (macOS,
# where this actually runs under launchd) does not honour it, so that pattern
# never matches and a HEALTHY run gets reported as died -- a false alarm is how
# an alert earns itself muted. The boundary is done in grep, which does support
# it, against `pgrep -fl` output.
#
# NOR `pgrep -fl`. Its -l means two different things: on macOS it prints the full
# command line, on Linux (procps) it prints only the process NAME, so the issue
# id is simply not in the output there and a healthy run reads as died. That is
# not academic -- it failed exactly that way on CI.
#
# `ps -Ao args=` prints full command lines on both. The [c] bracket is the
# standard trick to stop this grep from matching ITSELF: the pattern matches the
# text "converge", while this process's own command line contains the literal
# "[c]onverge", which does not.
DISPATCH_OK=0
for _ in 1 2 3 4 5 6 7 8 9 10; do
  if ps -Ao args= 2>/dev/null \
       | grep -qE "[c]onverge\.sh --issue ${NEXT}([[:space:]]|\$)"; then
    DISPATCH_OK=1; break
  fi
  sleep 1
done
if [ "$DISPATCH_OK" -eq 1 ]; then
  say "dispatched $NEXT (confirmed running)"
else
  say "DISPATCH DIED: $NEXT was launched but no converge process is alive after 10s"
  page "kipi dispatch: $NEXT was launched but died immediately -- the loop is spending budget and doing no work. Do: check ~/.config/kipi/converge-$NEXT.log and whether launchd is reaping the child."
  exit 1
fi
exit 0
