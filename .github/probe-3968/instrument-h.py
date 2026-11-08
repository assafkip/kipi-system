"""TEMPORARY ASK-3968 probe. Instruments section H of test-worker-env-halt.sh
IN THE PROBE JOB'S CHECKOUT ONLY: before the race it appends the load average
and the busiest processes on the machine to $PROBE_SNAP, and after the race it
appends the winner count. Nothing about the race itself changes.

Usage: python3 instrument-h.py <test-file>
"""
import pathlib
import sys

p = pathlib.Path(sys.argv[1])
s = p.read_text()
before = 'CLAIM_PIDS=""\nfor _i in 1 2 3 4 5 6 7 8; do\n'
assert s.count(before) == 1, "race start not found exactly once"
snap = ('{ echo "--- H snapshot $(date -u +%T)"; cat /proc/loadavg; nproc; '
        'ps -eo pid,ppid,pgid,sid,pcpu,etimes,args --sort=-pcpu | head -20; } '
        '>> "${PROBE_SNAP:-/dev/null}" 2>&1\n')
s = s.replace(before, snap + before)
after = 'N_WIN="$(grep -c \'^win$\' "$CLAIM_WINNERS" 2>/dev/null)" || true\n'
assert s.count(after) == 1, "winner count not found exactly once"
s = s.replace(after, after + 'echo "N_WIN=${N_WIN:-0} at $(date -u +%T)" >> "${PROBE_SNAP:-/dev/null}"\n')
p.write_text(s)
print("instrumented", p)
