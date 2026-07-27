#!/bin/bash
# ASK-184 recon: live state of com.kipi.openloops-heartbeat. Read-only.
set -uo pipefail
echo "=== launchctl list <label> ==="
launchctl list com.kipi.openloops-heartbeat 2>&1 | grep -E '"(LastExitStatus|PID|Label)"' || echo "(label not loaded)"
echo
echo "=== crontab duplicate? ==="
crontab -l 2>/dev/null | grep -i "open-loops" || echo "(no crontab reference -- launchd is the only scheduler)"
echo
echo "=== pause ledger entries ==="
grep -H "openloops" ~/.config/kipi/launchd-paused.txt ~/.config/kipi/cole-pause.state 2>/dev/null || echo "(not paused -- expected, it is live)"
echo
echo "=== stderr sink ==="
ls -la /tmp/kipi-openloops-heartbeat.err 2>&1
echo
echo "=== last 8 lines of the job log ==="
tail -8 /Users/assafkipnis/projects/kipi-system/q-system/output/open-loops-heartbeat.log 2>&1
echo
echo "=== last structured run-log ==="
cat /Users/assafkipnis/projects/kipi-system/q-system/output/heartbeat-run-last.json 2>&1
