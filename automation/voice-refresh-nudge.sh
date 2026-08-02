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
if [ -x "$NOTIFY" ]; then
  bash "$NOTIFY" "$MSG" --kind decision --class publish
else
  # slack-notify is a silent no-op when unconfigured; log so a dead nudge is visible.
  echo "[voice-refresh-nudge] slack-notify.sh not executable at $NOTIFY" >&2
fi
