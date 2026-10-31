#!/usr/bin/env bash
# voice-refresh-nudge.sh — monthly nudge that the voice refresh is due.
# PRD prd-voice-refresh-monthly-2026-07-04, issue voice-refresh-schedule.
#
# Routes the founder ping ONLY through slack-notify.sh (the single sanctioned
# channel). NEVER osascript: macOS desktop notifications are silently dropped
# from a launchd/background context (founder-notifications rule).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
NOTIFY="$ROOT/q-system/.q-system/scripts/slack-notify.sh"
MSG="Voice refresh due. Run /voice-refresh in a session to pull this month's Granola meetings and refresh your voice DNA."

# Never allowed to abort the script. slack-notify.sh has a documented non-zero
# exit contract for ORDINARY states -- 3 = no Linear API key configured, 4 =
# refused as a fixture run, 1 = send failed -- and under `set -e` any of those
# from the first send would kill the nudge before the staleness check below ever
# ran. The exit code is logged instead of swallowed, so a dead sink stays visible
# in voice-refresh-nudge.err.
send() {
  if [ ! -x "$NOTIFY" ]; then
    echo "[voice-refresh-nudge] slack-notify.sh not executable at $NOTIFY" >&2
    return 0
  fi
  local rc=0
  bash "$NOTIFY" "$1" || rc=$?
  [ "$rc" -eq 0 ] || echo "[voice-refresh-nudge] slack-notify exit $rc for: $1" >&2
  return 0
}

send "$MSG"

# ASK-3405: an unanswered personal block has to become visible on its own. The
# nudge was the only thing this loop ever emitted, and it only ever said "a
# refresh is due" -- a delta sitting unreviewed since 2026-10-22 produced no
# signal at all. --stale-check prints one line after 7 days, once per delta, and
# nothing otherwise. Guarded so a failing check can never swallow the line above.
STALE="$(python3 "$ROOT/automation/voice_refresh.py" --stale-check 2>/dev/null || true)"
if [ -n "$STALE" ]; then
  send "$STALE"
fi
