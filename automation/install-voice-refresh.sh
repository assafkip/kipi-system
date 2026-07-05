#!/usr/bin/env bash
# install-voice-refresh.sh — render + load the monthly voice-refresh launchd job.
# PRD prd-voice-refresh-monthly-2026-07-04, issue voice-refresh-schedule.
# Reuses the lessons-daily launchd + launchd-health prior art (no second style).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PLIST_SRC="$ROOT/automation/com.kipi.voice-refresh.plist"
DEST="$HOME/Library/LaunchAgents/com.kipi.voice-refresh.plist"

# Render the __ROOT__ placeholder to the real repo path. Use python (not sed) so
# a repo path containing #, &, or backslashes cannot corrupt the plist.
ROOT="$ROOT" PLIST_SRC="$PLIST_SRC" DEST="$DEST" python3 - <<'PY'
import os, xml.sax.saxutils as sx
root = sx.escape(os.environ["ROOT"])  # escape & < > so any repo path stays valid XML
src = open(os.environ["PLIST_SRC"]).read()
open(os.environ["DEST"], "w").write(src.replace("__ROOT__", root))
PY

launchctl unload "$DEST" 2>/dev/null || true
launchctl load "$DEST"

# Register with the launchd-health watchdog so a silently-dead nudge pings the
# founder (the income-scanner scar). Best-effort: no-op if the watchdog is absent.
HEALTH="$ROOT/q-system/.q-system/scripts/launchd-health-register.sh"
if [ -x "$HEALTH" ]; then
  bash "$HEALTH" com.kipi.voice-refresh || true
  HEALTH_MSG="launchd-health-registered"
else
  HEALTH_MSG="launchd-health watchdog absent (registration skipped)"
fi

echo "installed com.kipi.voice-refresh (launchd, monthly; $HEALTH_MSG)"
