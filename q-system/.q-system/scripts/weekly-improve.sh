#!/bin/bash
# weekly-improve.sh -- the ONE registered trigger for the learning lane.
#
# Runs one step, logged with its exit code:
#   1. weekly-improve.py           the weekly pass (friction + inbox -> founder Slack)
#
# RETIRED 2026-10-30 (ASK-3402): draft-vs-sent.py (the producer) and
# route-overrides-to-learn.py (the learner) were removed. Neither had a caller
# for its input: the drafts ledger and copy_edits had 0 rows, so the only run
# (2026-10-26) reported "nothing this week" while starved. The consulting voice
# loop already learns from what he actually sent.
#
# STARVATION ALARM (ASK-3402): after the pass, its input count goes to
# loop_starvation.py, which files ONE ticket for Sana after 3 consecutive
# zero-input runs. The pass exits 0 when starved, so no failure detector would
# ever see it. This file does not name the notifier; the helper owns it
# (test_runner_never_references_the_fleet_alert_notifier).
#
# Why one script and one plist: every-stage-needs-its-own-trigger.
#
# The self-healing-retry contract: every attempt is logged (step, exit code,
# time) to q-system/output/weekly-improve.log, so run-step-audit sees steps,
# not silence. No retries here: each step bounds itself.
#
# Usage: weekly-improve.sh [--dry-run]     (--dry-run prints the order, runs nothing)
# Env:   KIPI_WEEKLY_LOG overrides the log path (tests use a temp file).
set -uo pipefail
SCRIPTS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
QROOT="$(cd "$SCRIPTS/../.." && pwd)"
LOG="${KIPI_WEEKLY_LOG:-$QROOT/output/weekly-improve.log}"
TS() { date '+%Y-%m-%dT%H:%M:%S%z'; }

STEPS=("weekly-improve.py")

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
  # The pass's own exit decides the run's exit because it is the deliverable.
  if [ "$s" = "weekly-improve.py" ]; then
    overall=$rc
    # Count AFTER the pass, from the same readers. A failed count records
    # nothing rather than a false zero: an unreadable input is not starvation.
    n="$(python3 "$SCRIPTS/weekly-improve.py" --count-inputs 2>>"$LOG")" \
      && python3 "$SCRIPTS/loop_starvation.py" record weekly-improve "$n" >> "$LOG" 2>&1
  fi
done
exit "$overall"
