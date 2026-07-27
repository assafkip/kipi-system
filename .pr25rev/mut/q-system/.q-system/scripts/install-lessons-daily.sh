#!/bin/bash
# Install/refresh the daily autonomous-learning launchd job from this committed script.
# Reproducible: clone -> run this -> the daily heartbeat is scheduled. Idempotent.
# Usage: bash q-system/.q-system/scripts/install-lessons-daily.sh
set -euo pipefail

HEARTBEAT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lessons-daily.sh"
LABEL="com.kipi.lessons-daily"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOGDIR="$(cd "$(dirname "$HEARTBEAT")/../.." && pwd)/output"
UID_="$(id -u)"
mkdir -p "$HOME/Library/LaunchAgents" "$LOGDIR"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array>
    <string>/bin/bash</string>
    <string>$HEARTBEAT</string>
  </array>
  <key>StartCalendarInterval</key><dict>
    <key>Hour</key><integer>6</integer>
    <key>Minute</key><integer>0</integer>
  </dict>
  <key>StandardOutPath</key><string>$LOGDIR/lessons-daily.out</string>
  <key>StandardErrorPath</key><string>$LOGDIR/lessons-daily.err</string>
</dict></plist>
EOF

launchctl bootout "gui/$UID_/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$UID_" "$PLIST"
echo "installed $LABEL -> $HEARTBEAT (daily 06:00)"
launchctl list | grep "$LABEL" || echo "  WARN: not loaded"
