#!/bin/bash
# weekly-improve.sh -- the ONE registered trigger for the learning lane.
#
# Runs, in this order, each step logged with its exit code:
#   1. draft-vs-sent.py            the producer (pairs drafts with sent mail)
#   2. route-overrides-to-learn.py the learner (copy_edits -> skill-proposals inbox)
#   3. weekly-improve.py           the weekly pass (friction + inbox -> founder Slack)
#
# Why one script and one plist: every-stage-needs-its-own-trigger. The learner
# existed for four months with no registered starter (plan item 2a); the
# producer it depends on was an agent of a retired pipeline. Codex finding-9 on
# the PRD: three independently failing units need three logged steps, and a
# failing producer must NOT skip the pass (the founder still gets his message).
#
# The self-healing-retry contract: every attempt is logged (step, exit code,
# time) to q-system/output/weekly-improve.log, so run-step-audit sees steps,
# not silence. No retries here: each step bounds itself.
#
# EMPTY IS NOT A PROPOSAL (Codex finding-9 / plan 2a): after the learner runs,
# today's inbox file is checked; a file whose body is the learner's empty
# marker is logged as EMPTY and never counted as a proposal.
#
# Usage: weekly-improve.sh [--dry-run]     (--dry-run prints the order, runs nothing)
# Env:   KIPI_WEEKLY_LOG overrides the log path (tests use a temp file).
set -uo pipefail
SCRIPTS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
QROOT="$(cd "$SCRIPTS/../.." && pwd)"
LOG="${KIPI_WEEKLY_LOG:-$QROOT/output/weekly-improve.log}"
INBOX="${KIPI_PROPOSALS_INBOX:-$QROOT/output/skill-proposals/_inbox}"
EMPTY_MARKER="No edited engagement actions in the metrics database."
TS() { date '+%Y-%m-%dT%H:%M:%S%z'; }

STEPS=("draft-vs-sent.py" "route-overrides-to-learn.py" "weekly-improve.py")

if [ "${1:-}" = "--dry-run" ]; then
  for s in "${STEPS[@]}"; do echo "would run: $s"; done
  exit 0
fi

mkdir -p "$(dirname "$LOG")"
overall=0
for s in "${STEPS[@]}"; do
  echo "$(TS) START $s" >> "$LOG"
  python3 "$SCRIPTS/$s" >> "$LOG" 2>&1
  rc=$?
  echo "$(TS) END $s rc=$rc" >> "$LOG"
  if [ "$s" = "route-overrides-to-learn.py" ]; then
    today="$INBOX/engagement-$(date +%Y-%m-%d).md"
    if [ -f "$today" ] && grep -qF "$EMPTY_MARKER" "$today"; then
      echo "$(TS) EMPTY $today (learner wrote its empty marker; not a proposal)" >> "$LOG"
    elif [ -f "$today" ]; then
      echo "$(TS) PROPOSAL $today" >> "$LOG"
    fi
  fi
  # A producer or learner failure is logged and does NOT skip the pass; the
  # pass's own exit decides the run's exit because it is the deliverable.
  if [ "$s" = "weekly-improve.py" ]; then overall=$rc; fi
done
exit "$overall"
