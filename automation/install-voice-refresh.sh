#!/usr/bin/env bash
# install-voice-refresh.sh — render + load the monthly voice-refresh launchd job.
# PRD prd-voice-refresh-monthly-2026-07-04, issue voice-refresh-schedule.
# Reuses the lessons-daily launchd + launchd-health prior art (no second style).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PLIST_SRC="$ROOT/automation/com.kipi.voice-refresh.plist"
DEST="$HOME/Library/LaunchAgents/com.kipi.voice-refresh.plist"

# Render the __ROOT__ placeholder to the real repo path.
sed "s#__ROOT__#$ROOT#g" "$PLIST_SRC" > "$DEST"

launchctl unload "$DEST" 2>/dev/null || true
launchctl load "$DEST"

# Register with the launchd-health watchdog so a silently-dead nudge pings the
# founder (the income-scanner scar). Best-effort: no-op if the watchdog is absent.
HEALTH="$ROOT/q-system/.q-system/scripts/launchd-health-register.sh"
if [ -x "$HEALTH" ]; then
  bash "$HEALTH" com.kipi.voice-refresh || true
fi

echo "installed com.kipi.voice-refresh (launchd, monthly, launchd-health-registered)"
