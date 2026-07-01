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

command -v claude >/dev/null 2>&1 || { echo "$(TS) no claude CLI -> skip" >> "$LOG"; exit 0; }

SUMMARY="$(cd "$SKEL" && python3 "$DISTILL" 2>>"$LOG")"
echo "$(TS) $SUMMARY" >> "$LOG"

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
bash "$NOTIFY" "$MSG"
echo "$(TS) slacked: $MSG" >> "$LOG"
