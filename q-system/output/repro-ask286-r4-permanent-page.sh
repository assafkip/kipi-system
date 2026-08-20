#!/usr/bin/env bash
# Standalone PRE-FIX observation for ASK-286 codex round 4 major: page_once
# returns 0 ("caller, do your page") on exit 2 and exit 3, and the stuck call
# site's page is a PERMANENT Linear comment. So:
#
#   exit 3 (contended)  -> run A pages, run B claims and pages   = 2 comments
#   exit 2 (unwritable) -> nothing is ever claimed               = 1 comment
#                          per issue PER RUN, forever
#
# Not part of the suite -- cases 7-9 of test-claim-page-once-routing.sh are the
# committed versions. This file exists to observe RED before the fix lands.
set -uo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORKER="$REPO/q-system/.q-system/scripts/linear-worker.sh"
LEDGER_PY="$REPO/q-system/.q-system/scripts/attempts-ledger.py"
W="$(mktemp -d)"
trap 'rm -rf "$W"' EXIT

CLAIM_FN="$(awk '/^claim_page_once\(\)/{print; exit}' "$WORKER")"
PAGE_FN="$(sed -n '/^page_once() {/,/^}/p' "$WORKER")"
# Absent pre-fix; `eval ""` is a harmless no-op, so this file runs against both
# the unfixed and the fixed worker.
FAULT_FN="$(sed -n '/^ledger_fault() {/,/^}/p' "$WORKER")"
LEDGER_FAULT_ALERTED=0

LEDGER="$LEDGER_PY"
ATTEMPTS="$W/attempts.json"
NOTIFY="$W/notify.sh"
printf '#!/usr/bin/env bash\necho "SLACK: $*" >> "%s"\n' "$W/slack.log" > "$NOTIFY"
chmod +x "$NOTIFY"
say() { echo "$*" >&2; }
eval "$CLAIM_FN"
eval "$FAULT_FN"
eval "$PAGE_FN"

# The permanent sink: what the stuck call site does inside `if page_once`.
PERMANENT="$W/linear-comments.log"
: > "$PERMANENT"
attempt_page() {
  if page_once "$1" stuck_paged 2>/dev/null; then
    echo "PERMANENT LINEAR COMMENT on $1" >> "$PERMANENT"
  fi
}
# A real worker RUN is a fresh process, so its run-scoped state starts at 0.
# Modelling several runs inside one shell means resetting it by hand -- forget
# this and a later section inherits an earlier one's "already alerted".
new_run() { LEDGER_FAULT_ALERTED=0; }

echo "=== A. CONTENTION (exit 3): two runs, one real state ==="
echo '{}' > "$ATTEMPTS"
rm -f "$ATTEMPTS.lock"
# Run A meets a live holder -> exit 3, wrote nothing.
python3 - "$ATTEMPTS.lock" <<'PY' &
import fcntl, sys, time
fh = open(sys.argv[1], "a")
fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
time.sleep(60)
PY
HOLDER=$!
sleep 1
new_run; KIPI_ATTEMPTS_LOCK_TRIES=2 attempt_page ASK-CONTEND
kill "$HOLDER" 2>/dev/null || true
wait "$HOLDER" 2>/dev/null || true
# Run B (next worker cycle), lock free -> claims and pages.
new_run; attempt_page ASK-CONTEND
echo "permanent comments posted for ASK-CONTEND: $(grep -c 'ASK-CONTEND' "$PERMANENT")"

echo
echo "=== B. UNWRITABLE LEDGER (exit 2): five worker cycles ==="
: > "$PERMANENT"
: > "$W/slack.log"
for cycle in 1 2 3 4 5; do
  new_run
  LEDGER="$W/no-such-ledger.py" attempt_page ASK-BROKEN
done
echo "permanent comments posted for ASK-BROKEN over 5 cycles: $(grep -c 'ASK-BROKEN' "$PERMANENT")"
echo "slack fault alerts over those 5 cycles:                $(wc -l < "$W/slack.log" | tr -d ' ')"

echo
echo "=== C. ONE BROKEN LEDGER, A QUEUE OF 4 ISSUES, ONE RUN ==="
: > "$PERMANENT"
: > "$W/slack.log"
new_run   # ONE run; the four issues below are its queue, not four runs
for i in ASK-1 ASK-2 ASK-3 ASK-4; do
  LEDGER="$W/no-such-ledger.py" attempt_page "$i"
done
echo "permanent comments in ONE run: $(wc -l < "$PERMANENT" | tr -d ' ')"
echo "slack fault alerts in ONE run:  $(wc -l < "$W/slack.log" | tr -d ' ')"
