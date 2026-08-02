#!/bin/bash
# Daily autonomous cross-instance learning heartbeat (launchd-fired).
#   distill new learnings -> publish clean lessons -> propagate to the fleet -> Slack the founder.
# Founder model 2026-06-30: fully autonomous, every learning shared, client data scrubbed (fail-closed
# in lessons_scrub.py). Silent when nothing new; Slacks only on a real change or a failure.
# Disable: launchctl unload ~/Library/LaunchAgents/com.kipi.lessons-daily.plist
set -uo pipefail

SKEL="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"   # scripts -> .q-system -> q-system -> repo root
NOTIFY="$SKEL/q-system/.q-system/scripts/slack-notify.sh"
DISTILL="$SKEL/q-system/.q-system/scripts/lessons-distill.py"
LOG="$SKEL/q-system/output/lessons-daily.log"
TS() { date '+%Y-%m-%dT%H:%M:%S%z'; }
mkdir -p "$(dirname "$LOG")"

# The exit code IS this job's wire to Linear (ASK-182). fleet-health-daily.py's
# `launchd-failing` detector keys on a non-zero LastExitStatus, so a run that
# reports 0 after a bad night is invisible to the board no matter what it Slacked.
# Observed 2026-07-27: the 06:00 run logged "propagate FAILED", Slacked it, and
# `launchctl list` still said LastExitStatus = 0. Pinned by
# test/test-lessons-daily-exit.sh.
fail() { echo "$(TS) FAILURE: $*" >> "$LOG"; KIPI_NOTIFY_KIND=receipt bash "$NOTIFY" "lessons-daily: $*" 2>/dev/null; exit 1; }

# The plist pins PATH to include ~/.local/bin, so a missing binary here is a
# broken machine, not a normal night. Skipping silently would make this job dark
# with a clean exit status -- the one state the four bars forbid.
command -v claude >/dev/null 2>&1 || fail "no claude CLI on PATH -> nothing distilled"

# Founder decision 2026-08-01: pin the distiller's model; unpinned it rides the
# interactive default (Fable on 2026-08-01) and burns quota unattended.
export ANTHROPIC_MODEL="claude-opus-5"

SUMMARY="$(cd "$SKEL" && python3 "$DISTILL" 2>>"$LOG")" || fail "lessons-distill.py exited non-zero"
echo "$(TS) $SUMMARY" >> "$LOG"

# A dead distiller emits no JSON, every count below parses as 0, and the run
# reads as a quiet night. A zero result must prove it is empty, not broken.
printf '%s' "$SUMMARY" | python3 -c "import json,sys; json.load(sys.stdin)" 2>/dev/null \
  || fail "lessons-distill.py emitted no parseable JSON summary"

field() { printf '%s' "$SUMMARY" | python3 -c "import json,sys;d=json.load(sys.stdin);print($1)" 2>/dev/null; }
PUB=$(field "len(d.get('published',[]))");  PUB=${PUB:-0}
HELD=$(field "len(d.get('held',[]))");      HELD=${HELD:-0}
TITLES=$(field "'; '.join(d.get('published',[])[:5])")

if [ "$PUB" = "0" ] && [ "$HELD" = "0" ]; then
  echo "$(TS) nothing new" >> "$LOG"; exit 0
fi

# Persist new lessons + ledger in the skeleton, then fan to the fleet.
( cd "$SKEL" && git add q-system/lessons lesson-candidates 2>/dev/null \
  && git commit --no-verify --no-gpg-sign -m "chore(lessons): auto-learn $(date +%Y-%m-%d) — ${PUB} published, ${HELD} held" >/dev/null 2>&1 || true )

if [ "$PUB" -gt 0 ]; then
  if ( cd "$SKEL" && bash kipi-update.sh >> "$LOG" 2>&1 ); then PROP="propagated to fleet"; else PROP="propagate FAILED"; fi
else
  PROP="no propagation (nothing published)"
fi

MSG="Fleet learning ($(date +%Y-%m-%d)): ${PUB} new lesson(s), ${PROP}"
[ "$PUB" -gt 0 ] && [ -n "${TITLES:-}" ] && MSG="$MSG — ${TITLES}"
[ "$HELD" -gt 0 ] && MSG="$MSG · ${HELD} held for review (possible client data, see lesson-candidates/)"
[ "$PROP" = "propagate FAILED" ] && MSG="$MSG · propagation FAILED, see log"
KIPI_NOTIFY_KIND=receipt bash "$NOTIFY" "$MSG"
echo "$(TS) slacked: $MSG" >> "$LOG"

# Lessons that published but never reached the fleet are a half-done run: the
# Slack line above says so, and this makes launchd (and therefore Linear) agree.
# Held lessons are NOT a failure -- the scrub gate holding client data is the gate
# working, and paging on it would train the founder to ignore the channel.
if [ "$PROP" = "propagate FAILED" ]; then
  echo "$(TS) propagation failed -> exit 1" >> "$LOG"
  exit 1
fi
exit 0
