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
fail() { echo "$(TS) FAILURE: $*" >> "$LOG"; notify "lessons-daily: $*"; exit 1; }

# The plist pins PATH to include ~/.local/bin, so a missing binary here is a
# broken machine, not a normal night. Skipping silently would make this job dark
# with a clean exit status -- the one state the four bars forbid.
command -v "${KIPI_CLAUDE_BIN:-claude}" >/dev/null 2>&1 || fail "no claude CLI on PATH -> nothing distilled"

# Founder decision 2026-08-01: pin the distiller's model; unpinned it rides the
# interactive default (Fable on 2026-08-01) and burns quota unattended.
export ANTHROPIC_MODEL="claude-opus-5"

if [ -n "${KIPI_DISTILL_CMD:-}" ]; then
  SUMMARY="$(bash -c "$KIPI_DISTILL_CMD" 2>>"$LOG")" || fail "lessons-distill.py exited non-zero"
else
  SUMMARY="$(cd "$SKEL" && python3 "$DISTILL" 2>>"$LOG")" || fail "lessons-distill.py exited non-zero"
fi
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
if [ -n "${KIPI_PERSIST_CMD:-}" ]; then
  bash -c "$KIPI_PERSIST_CMD" || true
else
  ( cd "$SKEL" && git add q-system/lessons lesson-candidates 2>/dev/null \
    && git commit --no-verify --no-gpg-sign -m "chore(lessons): auto-learn $(date +%Y-%m-%d) — ${PUB} published, ${HELD} held" >/dev/null 2>&1 || true )
fi

# Mirror the corpus to the founder's Notion lessons database (founder 2026-09-02:
# "the process needs to constantly write to Notion"). Off without credentials;
# a Notion outage is logged and never fails the lessons job.
if [ -n "${KIPI_NOTION_SYNC_CMD:-}" ]; then NOTION_SYNC="bash -c \"$KIPI_NOTION_SYNC_CMD\""; else NOTION_SYNC="python3 \"$SKEL/q-system/.q-system/scripts/lessons_notion_sync.py\""; fi
if eval "$NOTION_SYNC" >> "$LOG" 2>&1; then :; else
  echo "$(TS) notion sync failed (non-fatal, see above)" >> "$LOG"
fi

# --- streak bookkeeping: lessons_streak.py is the ONLY writer of the streak file
# and the escalations ledger (atomic replace under one lock; Codex finding-9).
# Rule (finding-10): only a real propagation attempt bumps the streak. A run
# that publishes nothing neither resets nor increments it; that is the branch
# below ("no propagation (nothing published)") and the "nothing new" exit above.
STREAK_PY="$SKEL/q-system/.q-system/scripts/lessons_streak.py"
streak() { python3 "$STREAK_PY" --file "$STREAK_FILE" --ledger "$ESCALATIONS" "$@"; }

if [ "$PUB" -gt 0 ]; then
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

MSG="Fleet learning ($(date +%Y-%m-%d)): ${PUB} new lesson(s), ${PROP}"
[ "$PUB" -gt 0 ] && [ -n "${TITLES:-}" ] && MSG="$MSG — ${TITLES}"
[ "$HELD" -gt 0 ] && MSG="$MSG · ${HELD} held for review (possible client data, see lesson-candidates/)"
case "$PROP" in "propagate FAILED"*) MSG="$MSG · propagation FAILED, see log" ;; esac
notify "$MSG"
echo "$(TS) slacked: $MSG" >> "$LOG"

# Lessons that published but never reached the fleet are a half-done run: the
# Slack line above says so, and this makes launchd (and therefore Linear) agree.
# Held lessons are NOT a failure -- the scrub gate holding client data is the gate
# working, and paging on it would train the founder to ignore the channel.
case "$PROP" in
  "propagate FAILED"*) echo "$(TS) propagation failed -> exit 1" >> "$LOG"; exit 1 ;;
esac
exit 0
