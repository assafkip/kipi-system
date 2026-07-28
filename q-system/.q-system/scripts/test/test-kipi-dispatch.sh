#!/usr/bin/env bash
# Reproducer for ASK-225: dispatch must pick FILE-DISJOINT issues, and a manual
# burst must ignore the daily cap without spending it.
#
# WHY A STUB AND NOT THE REAL THING
# ---------------------------------
# The suite NEVER dispatches a real agent. `kipi` is stubbed: `work` prints a
# canned ready list, `converge` writes START/END markers to a log and sleeps.
# Concurrency is then measured by replaying that log, which is the only honest
# way to assert "at most P at once" from the outside -- a PID count sampled at
# one instant would pass a script that briefly spiked to P+2.
#
# The DoR file sets come from KIPI_DISPATCH_DOR_FIXTURE, so only the NETWORK is
# stubbed. The parsing and the intersection -- the parts that decide whether two
# agents land in one file -- run for real against prd_split.py.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
DISPATCH="$REPO_ROOT/kipi-dispatch.sh"
PASS=0
FAIL=0

ok()   { PASS=$((PASS+1)); printf '  ok   %s\n' "$1"; }
bad()  { FAIL=$((FAIL+1)); printf '  FAIL %s\n     %s\n' "$1" "${2:-}"; }
check(){ if [ "$2" = "$3" ]; then ok "$1"; else bad "$1" "expected [$3] got [$2]"; fi; }

# --- fixture repo -----------------------------------------------------------
# Every run gets its own HOME so the daily counter, the paged marker and the
# heartbeat beacon cannot leak between cases or into the founder's real state.
SANDBOX=""
new_sandbox() {
  SANDBOX="$(mktemp -d)"
  export HOME="$SANDBOX/home"
  mkdir -p "$HOME/.config/kipi" "$SANDBOX/repo"
  export KIPI_STUB_LOG="$SANDBOX/converge.log"
  : > "$KIPI_STUB_LOG"
  cat > "$SANDBOX/repo/kipi" <<'STUB'
#!/usr/bin/env bash
case "${1:-}" in
  work)
    for i in $KIPI_STUB_READY; do echo "[dry] would work $i (attempt 1/3)"; done
    ;;
  converge)
    shift; ISSUE=""
    while [ $# -gt 0 ]; do case "$1" in --issue) shift; ISSUE="${1:-}" ;; esac; shift; done
    printf 'START %s\n' "$ISSUE" >> "$KIPI_STUB_LOG"
    sleep 1
    printf 'END %s\n' "$ISSUE" >> "$KIPI_STUB_LOG"
    ;;
esac
exit 0
STUB
  chmod +x "$SANDBOX/repo/kipi"
  printf '#!/usr/bin/env bash\nexit 0\n' > "$SANDBOX/notify.sh"
  chmod +x "$SANDBOX/notify.sh"
  export KIPI_REPO="$SANDBOX/repo"
  export KIPI_NOTIFY="$SANDBOX/notify.sh"
  export KIPI_DISPATCH_DOR_FIXTURE="$SANDBOX/dor.json"
  # Pin the live set. The real heartbeat runs on this same machine, so reading
  # the actual process table would make every concurrency assertion depend on
  # what the fleet happens to be doing while the suite runs -- which is how 7a
  # first failed: a live converge run for ASK-225 itself ate a slot.
  export KIPI_DISPATCH_FAKE_LIVE=""
}

# Write the DoR fixture: one Linear description per issue, in the real shape the
# drafter emits, so _dor_section/_extract_paths are exercised, not bypassed.
dor() {  # dor <issue> <files-bullet-body>
  python3 - "$KIPI_DISPATCH_DOR_FIXTURE" "$1" "$2" <<'PY'
import json, os, sys
path, issue, files = sys.argv[1], sys.argv[2], sys.argv[3]
data = json.load(open(path)) if os.path.exists(path) else {}
body = "## Definition of Ready\n\n**Outcome:** a thing works.\n\n"
if files:
    body += f"**Files:**\n\n{files}\n\n"
body += "**Check:** `bash something.sh`\n\n**Not doing:** nothing\n"
data[issue] = body
json.dump(data, open(path, "w"))
PY
}

run_dispatch() { bash "$DISPATCH" "$@" 2>&1; }

# Replay the START/END log to get the true peak concurrency.
peak_concurrency() {
  python3 - "$KIPI_STUB_LOG" <<'PY'
import sys
cur = peak = 0
for line in open(sys.argv[1]):
    if line.startswith("START"): cur += 1; peak = max(peak, cur)
    elif line.startswith("END"): cur -= 1
print(peak)
PY
}

# `grep -c` prints 0 AND exits 1 on no match, so `|| echo 0` would emit "0\n0"
# and every numeric comparison downstream would blow up. Count with a pipeline
# that always exits 0 instead.
count_lines() { grep "$1" "$KIPI_STUB_LOG" 2>/dev/null | grep -c . || true; }

wait_for_ends() {  # wait_for_ends <n>
  local want="$1" i=0
  while [ "$i" -lt 60 ]; do
    [ "$(count_lines '^END ')" -ge "$want" ] && return 0
    sleep 0.2; i=$((i+1))
  done
  return 1
}

started() { grep '^START ' "$KIPI_STUB_LOG" 2>/dev/null | awk '{print $2}' | sort | tr '\n' ' '; }
n_started() { count_lines '^START '; }

echo "== ASK-225 kipi-dispatch: file-disjoint picking + on-demand burst"

# --- 1. overlapping file sets: the second candidate is skipped, by path -----
new_sandbox
dor ASK-901 '* `q-system/.q-system/scripts/linear-worker.sh`'
dor ASK-902 '* `q-system/.q-system/scripts/linear-worker.sh`, `converge.sh`'
export KIPI_STUB_READY="ASK-901 ASK-902"
OUT="$(run_dispatch --burst 2 --parallel 2)"
wait_for_ends 1
check "1a overlapping pair dispatches only one" "$(n_started)" "1"
check "1b the survivor is the first candidate" "$(started)" "ASK-901 "
if printf '%s' "$OUT" | grep -q 'skip ASK-902' && \
   printf '%s' "$OUT" | grep -q 'q-system/.q-system/scripts/linear-worker.sh'; then
  ok "1c the skip line names the overlapping path"
else
  bad "1c the skip line names the overlapping path" "$OUT"
fi

# --- 2. disjoint file sets: both go ----------------------------------------
new_sandbox
dor ASK-903 '* `alpha.sh`'
dor ASK-904 '* `beta.sh`'
export KIPI_STUB_READY="ASK-903 ASK-904"
OUT="$(run_dispatch --burst 2 --parallel 2)"
wait_for_ends 2
check "2a disjoint pair both dispatch" "$(n_started)" "2"
check "2b both issues launched" "$(started)" "ASK-903 ASK-904 "

# --- 3. no Files line: fail closed -----------------------------------------
# An unknown file set intersects everything by assumption. Guessing is how two
# agents end up in one file, so a DoR with no **Files:** is never parallel.
new_sandbox
dor ASK-905 '* `gamma.sh`'
dor ASK-906 ''
export KIPI_STUB_READY="ASK-905 ASK-906"
OUT="$(run_dispatch --burst 2 --parallel 2)"
wait_for_ends 1
check "3a a Files-less candidate is not dispatched alongside" "$(n_started)" "1"
check "3b only the known-set issue ran" "$(started)" "ASK-905 "
if printf '%s' "$OUT" | grep -q 'skip ASK-906' && \
   printf '%s' "$OUT" | grep -qi 'no .*Files'; then
  ok "3c the skip says the file set is unknown"
else
  bad "3c the skip says the file set is unknown" "$OUT"
fi

# --- 4. the magnet file does not serialise the board -----------------------
# capability-manifest.json is edited by nearly every test-adding issue
# (sp-f3a2ad81). Intersecting on it would make almost everything conflict.
new_sandbox
dor ASK-907 '* `delta.sh`, `q-system/.q-system/capability-manifest.json`'
dor ASK-908 '* `epsilon.sh`, `q-system/.q-system/capability-manifest.json`'
export KIPI_STUB_READY="ASK-907 ASK-908"
OUT="$(run_dispatch --burst 2 --parallel 2)"
wait_for_ends 2
check "4a manifest-only overlap still dispatches both" "$(n_started)" "2"

# --- 5. --burst 5 --parallel 3: 5 total, never more than 3 at once ----------
new_sandbox
for n in 1 2 3 4 5; do dor "ASK-91$n" "* \`file$n.sh\`"; done
export KIPI_STUB_READY="ASK-911 ASK-912 ASK-913 ASK-914 ASK-915"
OUT="$(run_dispatch --burst 5 --parallel 3)"
wait_for_ends 5
check "5a burst 5 dispatches 5" "$(n_started)" "5"
PEAK="$(peak_concurrency)"
if [ "$PEAK" -le 3 ] && [ "$PEAK" -ge 2 ]; then
  ok "5b peak concurrency $PEAK is within --parallel 3"
else
  bad "5b peak concurrency within --parallel 3" "peak=$PEAK"
fi

# --- 6. burst neither reads nor increments the daily counter ---------------
# The cap exists to stop the UNATTENDED heartbeat spending the subscription
# overnight, not to limit what the founder asks for while present.
new_sandbox
TODAY="$(date +%Y-%m-%d)"
COUNT_FILE="$HOME/.config/kipi/dispatch-count-$TODAY"
printf '4' > "$COUNT_FILE"          # already at the default cap
dor ASK-921 '* `zeta.sh`'
dor ASK-922 '* `eta.sh`'
export KIPI_STUB_READY="ASK-921 ASK-922"
OUT="$(run_dispatch --burst 2 --parallel 2)"
wait_for_ends 2
check "6a burst runs with the daily counter already at the cap" "$(n_started)" "2"
check "6b burst leaves the counter untouched" "$(cat "$COUNT_FILE")" "4"
# and the full budget is still there for the next heartbeat tick
printf '0' > "$COUNT_FILE"
: > "$KIPI_STUB_LOG"
export KIPI_STUB_READY="ASK-921"
OUT="$(run_dispatch)"
wait_for_ends 1
check "6c a heartbeat right after a burst still has its budget" "$(n_started)" "1"
check "6d the heartbeat did spend one" "$(cat "$COUNT_FILE")" "1"

# --- 7. the heartbeat still honours BOTH caps ------------------------------
new_sandbox
dor ASK-931 '* `theta.sh`'
dor ASK-932 '* `iota.sh`'
dor ASK-933 '* `kappa.sh`'
export KIPI_STUB_READY="ASK-931 ASK-932 ASK-933"
export KIPI_DISPATCH_MAX=2
OUT="$(run_dispatch)"
wait_for_ends 2
check "7a heartbeat fills the concurrency cap, no more" "$(n_started)" "2"
: > "$KIPI_STUB_LOG"
printf '4' > "$HOME/.config/kipi/dispatch-count-$(date +%Y-%m-%d)"
OUT="$(run_dispatch)"
sleep 0.3
check "7b heartbeat at the daily cap dispatches nothing" "$(n_started)" "0"
if printf '%s' "$OUT" | grep -qi 'daily cap'; then
  ok "7c the daily-cap stop is reported"
else
  bad "7c the daily-cap stop is reported" "$OUT"
fi
unset KIPI_DISPATCH_MAX

# --- 8. no silent truncation: every skipped candidate is reported ----------
# "dispatched 3 of 10" with no reasons reads as "there were only 3".
new_sandbox
dor ASK-941 '* `lambda.sh`'
dor ASK-942 '* `lambda.sh`'          # overlaps 941
dor ASK-943 ''                        # unknown set
dor ASK-944 '* `mu.sh`'
export KIPI_STUB_READY="ASK-941 ASK-942 ASK-943 ASK-944"
OUT="$(run_dispatch --burst 1 --parallel 2)"   # target 1 of 4 candidates
wait_for_ends 1
DISPATCHED="$(n_started)"
SKIPS="$(printf '%s\n' "$OUT" | grep -c '^[^ ]* skip ASK-' || true)"
check "8a one dispatched" "$DISPATCHED" "1"
check "8b skips reported == candidates - dispatched" "$SKIPS" "3"

# --- 9. a candidate overlapping an ALREADY-LIVE run is held back -----------
# The case the cap-of-1 existed to prevent: ASK-223 edits the same
# linear-worker.sh region as the then-live ASK-222.
new_sandbox
export KIPI_DISPATCH_FAKE_LIVE="ASK-222"
dor ASK-222 '* `q-system/.q-system/scripts/linear-worker.sh`'
dor ASK-223 '* `q-system/.q-system/scripts/linear-worker.sh`'
dor ASK-224 '* `nu.sh`'
export KIPI_STUB_READY="ASK-223 ASK-224"
OUT="$(run_dispatch --burst 2 --parallel 2)"
wait_for_ends 1
check "9a the overlapping candidate is held back" "$(started)" "ASK-224 "
if printf '%s' "$OUT" | grep -q 'skip ASK-223.*linear-worker.sh'; then
  ok "9b the skip names the live run's file"
else
  bad "9b the skip names the live run's file" "$OUT"
fi

echo
printf '== %s passed, %s failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ] || exit 1
