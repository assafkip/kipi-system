#!/usr/bin/env bash
# Pairs with q-system/.q-system/scripts/lane-watchdog.py (ASK-3932).
#
# SCAR 2026-11-06: a supervised multi-lane run lost 11.5 hours. A lane agent
# ended its turn waiting on its own background CI watcher. CI finished red at
# 23:00 PST, the watcher never woke the agent, and the orchestrator session only
# wakes on agent notifications, so nothing moved until 10:11 the next morning.
# The watchdog is the waker that depends on no agent. These checks replay that
# shape and pin the negative self-test next to it, so a threshold that can never
# fire cannot pass for a working gate.
#
# Every `gh` read is served by a stub on PATH: no network, no live PR.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SCRIPTS="$(cd "$HERE/.." && pwd)"
WATCHDOG="$SCRIPTS/lane-watchdog.py"
LANE_MARK="$SCRIPTS/lane-mark.py"
FAILS=0
PASSES=0

check() { # name expected_exit actual_exit
  if [ "$2" = "$3" ]; then
    PASSES=$((PASSES + 1)); echo "  ok: $1 (exit $3)"
  else
    FAILS=$((FAILS + 1)); echo "  FAIL: $1 -- want exit $2, got exit $3"
  fi
}

check_has() { # name haystack needle
  case "$2" in
    *"$3"*) PASSES=$((PASSES + 1)); echo "  ok: $1" ;;
    *) FAILS=$((FAILS + 1)); echo "  FAIL: $1 -- $3 not in output:"; printf '%s\n' "$2" | sed 's/^/        /' ;;
  esac
}

check_lacks() { # name haystack needle
  case "$2" in
    *"$3"*) FAILS=$((FAILS + 1)); echo "  FAIL: $1 -- $3 unexpectedly in output:"; printf '%s\n' "$2" | sed 's/^/        /' ;;
    *) PASSES=$((PASSES + 1)); echo "  ok: $1" ;;
  esac
}

if [ ! -x "$WATCHDOG" ]; then
  echo "FAIL: $WATCHDOG is missing or not executable -- nothing wakes a stalled lane"
  exit 1
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"; kill $(jobs -p) 2>/dev/null || true' EXIT

# --- the gh stub -----------------------------------------------------------
# Reads its answers from $TMP/gh-env so each case can reshape the PR without
# rewriting the stub.
mkdir -p "$TMP/bin"
cat > "$TMP/bin/gh" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
. "$GH_STUB_ENV"
[ "${GH_FAIL:-0}" = "1" ] && exit 1
case "${2:-}" in
  view)   printf '%s\n' "{\"state\":\"OPEN\",\"updatedAt\":\"$GH_UPDATED_AT\"}" ;;
  checks) printf '%s\n' "$GH_CHECKS" ;;
  *)      exit 1 ;;
esac
STUB
chmod +x "$TMP/bin/gh"
export PATH="$TMP/bin:$PATH"
export GH_STUB_ENV="$TMP/gh-env"
export WATCHDOG_REVIEWS="$TMP/reviews"   # no stray review files from the real dir
mkdir -p "$TMP/reviews"

iso_ago() { python3 -c "import sys,datetime as dt;print((dt.datetime.now(dt.timezone.utc)-dt.timedelta(minutes=int(sys.argv[1]))).strftime('%Y-%m-%dT%H:%M:%SZ'))" "$1"; }

write_gh_env() { # updated_minutes_ago  checks_json  [fail]
  {
    echo "GH_UPDATED_AT=$(iso_ago "$1")"
    echo "GH_CHECKS='$2'"
    echo "GH_FAIL=${3:-0}"
  } > "$GH_STUB_ENV"
}

# A worktree whose newest file is old: the lane wrote nothing recently.
WT_OLD="$TMP/wt-old"; mkdir -p "$WT_OLD"; : > "$WT_OLD/f"
touch -t 202601010000 "$WT_OLD/f"
WT_FRESH="$TMP/wt-fresh"; mkdir -p "$WT_FRESH"; : > "$WT_FRESH/f"

state() { # path  lines...
  local p="$1"; shift; printf '%s\n' "$@" > "$p"
}

# A lane's quiet clock starts when the watchdog first SAW the lane, kept per lane
# in a sidecar. A case that wants a stall therefore needs a lane that has existed
# for a while -- which is what the 2026-11-06 lane was: hours old, signals stale.
# seed_seen writes that production state; without it a brand-new lane is MOVING
# by design (three lanes read STALL 0 minutes after launch on 2026-11-07).
SEEN_PATH=""
seed_seen() { # minutes_ago  label...
  local mins="$1"; shift
  SEEN_PATH="$TMP/seen-$RANDOM.json"
  python3 - "$SEEN_PATH" "$mins" "$@" <<'PY'
import json, sys, time
path, mins, labels = sys.argv[1], float(sys.argv[2]), sys.argv[3:]
json.dump({l: time.time() - mins * 60 for l in labels}, open(path, "w"))
PY
}

run_wd() { # state_file  extra args...  -> prints output, sets RC
  local sf="$1"; shift
  local seen="${SEEN_PATH:-$TMP/seen-$RANDOM.json}"
  set +e
  OUT="$(WATCHDOG_SEEN="$seen" python3 "$WATCHDOG" --state "$sf" "$@" 2>&1)"
  RC=$?
  set -e
  SEEN_PATH=""
}

echo "== 1. the 2026-11-06 shape: checks done 30m ago, nothing in flight =="
# Required check PASSED 30 minutes ago, PR untouched for 60, no process, no file
# change. This is exactly the lane that sat for 11.5 hours.
write_gh_env 60 '[{"bucket":"pass","completedAt":"'"$(iso_ago 30)"'"}]'
state "$TMP/s1" "lane-a 621 $WT_OLD"
seed_seen 120 lane-a
run_wd "$TMP/s1" --once --stall-min 20
check "stalled lane exits 3" 3 "$RC"
check_has "the stall names the lane" "$OUT" "STALL lane-a"
check_has "the stall names the quiet minutes" "$OUT" "quiet 30m"

echo "== 2. negative self-test: the same fixture, a threshold it cannot cross =="
seed_seen 120 lane-a
run_wd "$TMP/s1" --once --stall-min 100000
check "huge threshold does not stall" 0 "$RC"
check_has "it reports the lane as moving" "$OUT" "MOVING lane-a"
check_lacks "and never says STALL" "$OUT" "STALL"

echo "== 3. a required check still pending is ACTIVE =="
write_gh_env 60 '[{"bucket":"pending","completedAt":null}]'
run_wd "$TMP/s1" --once --stall-min 20
check "pending check exits 0" 0 "$RC"
check_has "it reports pending" "$OUT" "pending=1"

echo "== 4. a live process naming the worktree is ACTIVE =="
write_gh_env 60 '[{"bucket":"pass","completedAt":"'"$(iso_ago 30)"'"}]'
python3 -c "import sys,time; time.sleep(25)" "$WT_OLD" &
PROC_PID=$!
sleep 1
run_wd "$TMP/s1" --once --stall-min 20
check "live worktree process exits 0" 0 "$RC"
check_has "it names the worktree process" "$OUT" "worktree-proc"
kill "$PROC_PID" 2>/dev/null || true
wait "$PROC_PID" 2>/dev/null || true

echo "== 5. a freshly written worktree is MOVING =="
touch "$WT_FRESH/f"
state "$TMP/s5" "lane-b 621 $WT_FRESH"
run_wd "$TMP/s5" --once --stall-min 20
check "fresh file exits 0" 0 "$RC"
check_has "it reports moving" "$OUT" "MOVING lane-b"

echo "== 6. an unreadable gh fails toward ACTIVE, never pages =="
write_gh_env 60 '[]' 1
state "$TMP/s6" "lane-c 621 $WT_OLD"
run_wd "$TMP/s6" --once --stall-min 20
check "gh failure exits 0" 0 "$RC"
check_has "it says it is not judging" "$OUT" "not judging"

echo "== 7. a malformed state line exits 2 =="
write_gh_env 60 '[]'
state "$TMP/s7" "lane-d 621"
run_wd "$TMP/s7" --once --stall-min 20
check "bad state line exits 2" 2 "$RC"
check_has "it prints the bad line" "$OUT" "bad state line"

echo "== 8. a missing state file exits 2 =="
run_wd "$TMP/does-not-exist" --once
check "missing state file exits 2" 2 "$RC"

echo "== 9. loop mode returns at once on a stall, it does not wait out the poll =="
write_gh_env 60 '[{"bucket":"pass","completedAt":"'"$(iso_ago 30)"'"}]'
START=$(date +%s)
seed_seen 120 lane-a
run_wd "$TMP/s1" --stall-min 20 --poll-s 600 --heartbeat-min 600
ELAPSED=$(( $(date +%s) - START ))
check "loop mode exits 3 on the stall" 3 "$RC"
if [ "$ELAPSED" -lt 60 ]; then
  PASSES=$((PASSES + 1)); echo "  ok: it returned in ${ELAPSED}s, not after the 600s poll"
else
  FAILS=$((FAILS + 1)); echo "  FAIL: loop mode took ${ELAPSED}s; it waited out the poll"
fi

echo "== 10. a lane just added is never stalled on its first poll =="
# Found 2026-11-07: three lanes read STALL 0 minutes after launch because their
# worktree and PR carried day-old signals. The first-seen floor is per lane, so
# adding lane-f cannot reset lane-a's clock.
SEEN="$TMP/seen-shared.json"
state "$TMP/s10" "lane-a 621 $WT_OLD"
set +e
OUT="$(WATCHDOG_SEEN="$SEEN" python3 "$WATCHDOG" --state "$TMP/s10" --once --stall-min 20 2>&1)"; RC=$?
set -e
check "a brand-new lane exits 0" 0 "$RC"
check_has "its clock starts at first sight" "$OUT" "MOVING lane-a"
# Age the floor for lane-a only, then add a second lane. lane-a must stall.
python3 - "$SEEN" <<'PY'
import json, sys, time
p = sys.argv[1]
d = json.load(open(p))
for k in d:
    d[k] = time.time() - 3600
json.dump(d, open(p, "w"))
PY
state "$TMP/s10" "lane-a 621 $WT_OLD" "lane-f - $WT_FRESH"
set +e
OUT="$(WATCHDOG_SEEN="$SEEN" python3 "$WATCHDOG" --state "$TMP/s10" --once --stall-min 20 2>&1)"; RC=$?
set -e
check "an aged lane still stalls when a new lane joins" 3 "$RC"
check_has "the aged lane is the one named" "$OUT" "STALL lane-a"
check_has "the new lane is not stalled" "$OUT" "MOVING lane-f"

echo "== 11. an empty state file says so and does not page =="
: > "$TMP/s11"
run_wd "$TMP/s11" --once
check "empty state file exits 0" 0 "$RC"
check_has "it says there are no lanes" "$OUT" "NO-LANES"

echo "== 12. lane-mark.py is the one writer of the state file =="
LANES="$TMP/lanes"
export KIPI_LANES_DIR="$LANES"
python3 "$LANE_MARK" start ASK-9001 --agent test-lane --pr 621 --worktree "$WT_OLD" >/dev/null
STATE_FILE="$LANES/lanes.state"
if [ -f "$STATE_FILE" ]; then
  PASSES=$((PASSES + 1)); echo "  ok: lane-mark start wrote $STATE_FILE"
else
  FAILS=$((FAILS + 1)); echo "  FAIL: lane-mark start wrote no state file"
fi
check_has "the line carries label, pr and worktree" "$(cat "$STATE_FILE")" "ASK-9001 621 $WT_OLD"
# The watchdog reads what lane-mark wrote, with no hand-written state file.
write_gh_env 60 '[{"bucket":"pass","completedAt":"'"$(iso_ago 30)"'"}]'
seed_seen 120 ASK-9001
run_wd "$STATE_FILE" --once --stall-min 20
check "the watchdog stalls on the marker-derived lane" 3 "$RC"
check_has "it names the ticket as the lane" "$OUT" "STALL ASK-9001"
# A second lane joins, then the first ends: one writer, both edits.
python3 "$LANE_MARK" start ASK-9002 --agent test-lane --worktree "$WT_FRESH" >/dev/null
check_has "both live lanes are in the file" "$(cat "$STATE_FILE")" "ASK-9002 - $WT_FRESH"
python3 "$LANE_MARK" end ASK-9001 >/dev/null
check_lacks "an ended lane leaves the file" "$(cat "$STATE_FILE")" "ASK-9001"
check_has "the surviving lane stays" "$(cat "$STATE_FILE")" "ASK-9002"
# An expired marker is not a live lane.
python3 - "$LANES" <<'PY'
import json, os, sys
from datetime import datetime, timedelta, timezone
p = os.path.join(sys.argv[1], "ASK-9002.json")
d = json.load(open(p))
d["until"] = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
json.dump(d, open(p, "w"))
PY
python3 "$LANE_MARK" start ASK-9003 --agent test-lane --worktree "$WT_FRESH" >/dev/null
check_lacks "an expired lane is not in the file" "$(cat "$STATE_FILE")" "ASK-9002"
check_has "the fresh lane is" "$(cat "$STATE_FILE")" "ASK-9003"

echo "== 13. kipi lane arms the loop (the orchestrator start path) =="
KIPI="$(cd "$SCRIPTS/../../.." && pwd)/kipi"
if [ -x "$KIPI" ]; then
  set +e
  OUT="$(KIPI_LANES_DIR="$LANES" "$KIPI" lane watch --once --stall-min 100000 2>&1)"; RC=$?
  set -e
  check "kipi lane watch runs the watchdog" 0 "$RC"
  check_has "it read the marker-derived state" "$OUT" "ASK-9003"
  set +e
  OUT="$(KIPI_LANES_DIR="$LANES" "$KIPI" lane 2>&1)"; RC=$?
  set -e
  check "kipi lane with no subcommand exits 1" 1 "$RC"
else
  FAILS=$((FAILS + 1)); echo "  FAIL: $KIPI not found -- the orchestrator start path is unwired"
fi

echo ""
echo "lane-watchdog: $PASSES passed, $FAILS failed"
[ "$FAILS" -eq 0 ] || exit 1
