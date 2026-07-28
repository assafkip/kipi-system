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
# The sandbox goes under /tmp with a template we control, NOT the default
# $TMPDIR: case 23 writes the sandbox's own ABSOLUTE path into a DoR and asserts
# it normalises against the repo-relative spelling of the same file, and macOS
# hands out `/var/folders/<hash>/T/` names that can carry characters no path
# tokenizer accepts. A test that fails on the shape of a temp dir name teaches
# nothing.
SANDBOX=""
new_sandbox() {
  SANDBOX="$(mktemp -d /tmp/kipi-dispatch-test.XXXXXX)"
  export HOME="$SANDBOX/home"
  mkdir -p "$HOME/.config/kipi" "$SANDBOX/repo"
  export KIPI_STUB_LOG="$SANDBOX/converge.log"
  : > "$KIPI_STUB_LOG"
  cat > "$SANDBOX/repo/kipi" <<'STUB'
#!/usr/bin/env bash
case "${1:-}" in
  work)
    # A non-zero rc models a CRASHED picker (the reviewer's repro was a
    # ConnectionResetError): a traceback on stderr and no ready list at all.
    if [ "${KIPI_STUB_WORK_RC:-0}" != "0" ]; then
      echo "Traceback (most recent call last):" >&2
      echo "ConnectionResetError: [Errno 54] Connection reset by peer" >&2
      exit "$KIPI_STUB_WORK_RC"
    fi
    # The infra shape of the REAL producer, which is the one that matters:
    # linear-worker.sh:238-241 prints one `INFRA:` line through its timestamped
    # `say`, prints NO ready list, and exits 0. A fixture that exits non-zero
    # here would keep passing while the production path stayed uncovered.
    # KEEP_LIST models the OTHER shape: a per-issue INFRA line (:763, :823)
    # printed while the board is fine and candidates are still returned.
    if [ -n "${KIPI_STUB_WORK_MSG:-}" ]; then
      echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $KIPI_STUB_WORK_MSG"
      [ -n "${KIPI_STUB_WORK_KEEP_LIST:-}" ] || exit 0
    fi
    # The worker's own board-total line. `--limit` truncates the LIST, never
    # this count, which is why the summary must quote it and not the window.
    [ -n "${KIPI_STUB_READY_COUNT:-}" ] && \
      echo "worker: $KIPI_STUB_READY_COUNT ready issue(s) (owner:sana, has a DoR, not owner:assaf)"
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
  # Record every page instead of swallowing it. A fix that buys silence is the
  # expensive kind, so the suite asserts on what the operator would actually
  # see at 3am, not just on what got dispatched.
  PAGES="$SANDBOX/pages.log"
  : > "$PAGES"
  printf '#!/usr/bin/env bash\nprintf "%%s\\n" "$1" >> %s\nexit 0\n' "$PAGES" > "$SANDBOX/notify.sh"
  chmod +x "$SANDBOX/notify.sh"
  export KIPI_REPO="$SANDBOX/repo"
  export KIPI_NOTIFY="$SANDBOX/notify.sh"
  export KIPI_DISPATCH_DOR_FIXTURE="$SANDBOX/dor.json"
  unset KIPI_STUB_WORK_RC KIPI_STUB_WORK_MSG KIPI_STUB_READY_COUNT
  unset KIPI_DISPATCH_PRD_SPLIT KIPI_DISPATCH_SLOT_WAIT KIPI_DISPATCH_FAKE_LIVE_FILE
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

# Run it with a wall clock. "It hung" is only assertable from the outside, and a
# plain run_dispatch on a deadlocked script would hang the SUITE instead of
# failing it -- which reads as CI being slow, not as a defect.
# The verdict goes to a FILE, not a variable: the caller reads this through
# `OUT="$(run_dispatch_bounded ...)"`, and a command substitution is a subshell,
# so an exported-variable verdict is discarded on the way out. That is how the
# first cut of 14a passed while the script under test hung for the full 20s.
run_dispatch_bounded() {  # run_dispatch_bounded <max-secs> <args...>
  local secs="$1"; shift
  local out="$SANDBOX/bounded.out" pid i=0
  : > "$out"
  printf '0' > "$SANDBOX/hung"
  bash "$DISPATCH" "$@" > "$out" 2>&1 &
  pid=$!
  while kill -0 "$pid" 2>/dev/null; do
    if [ "$i" -ge "$(( secs * 5 ))" ]; then
      kill -9 "$pid" 2>/dev/null
      printf '1' > "$SANDBOX/hung"
      break
    fi
    sleep 0.2; i=$((i+1))
  done
  wait "$pid" 2>/dev/null
  cat "$out"
}
bounded_hung() { cat "$SANDBOX/hung" 2>/dev/null || echo 0; }

# grep -c prints 0 AND exits 1 on no match; `|| true` keeps the count and drops
# the status, so the caller can compare a number instead of a number-or-nothing.
paged() { grep -c "$1" "$PAGES" 2>/dev/null || true; }

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

# ===========================================================================
# PR #36 review round 3. Each case below is a defect the reviewer reproduced
# against the REAL board, red before the fix.
# ===========================================================================

# --- 10. unknown set means NOT IN PARALLEL, not NEVER (review finding 1) ----
# The DoR's words are "NOT dispatchable in parallel". The first cut refused an
# unknown-set candidate outright, which on the real board (51 of 55 ready
# issues parse to an empty set) is a throughput cut from 1/tick to 0/tick --
# the change inverting its own purpose. An unknown set intersects everything,
# and "everything" is EMPTY when nothing is live and nothing else was launched.
new_sandbox
dor ASK-951 ''
export KIPI_STUB_READY="ASK-951"
OUT="$(run_dispatch --burst 1 --parallel 2)"
wait_for_ends 1
check "10a an unknown-set candidate runs ALONE when nothing is live" "$(n_started)" "1"

new_sandbox
dor ASK-952 ''                        # unknown set, comes first
dor ASK-953 '* `sigma.sh`'            # known set, comes second
export KIPI_STUB_READY="ASK-952 ASK-953"
OUT="$(run_dispatch --burst 2 --parallel 2)"
wait_for_ends 1
check "10b a solo unknown-set run ends the pass" "$(started)" "ASK-952 "
if printf '%s' "$OUT" | grep -q 'skip ASK-953' && \
   printf '%s' "$OUT" | grep -qi 'unknown file set'; then
  ok "10c the held candidate is told an unknown-set run holds the board"
else
  bad "10c the held candidate is told an unknown-set run holds the board" "$OUT"
fi

new_sandbox
export KIPI_DISPATCH_FAKE_LIVE="ASK-954"
dor ASK-954 '* `tau.sh`'
dor ASK-955 ''
export KIPI_STUB_READY="ASK-955"
OUT="$(run_dispatch --burst 1 --parallel 2)"
sleep 0.3
check "10d an unknown-set candidate is still refused while a run is live" "$(n_started)" "0"

# --- 11. `~/`-anchored paths are real files (review finding 1, root) --------
# _PATH_TOKEN_RE starts at [A-Za-z0-9_.], so `~/Library/LaunchAgents/x.plist`
# vanishes. For prd_split's SCOPE use that is merely narrow. For INTERSECTION
# it is a silent hazard: a Files list mixing a plist with a repo path presents
# a set that LOOKS complete, so two agents get sent into one plist.
new_sandbox
dor ASK-961 '* `~/Library/LaunchAgents/com.foo.plist`, `alpha961.sh`'
dor ASK-962 '* `~/Library/LaunchAgents/com.foo.plist`, `beta962.sh`'
export KIPI_STUB_READY="ASK-961 ASK-962"
OUT="$(run_dispatch --burst 2 --parallel 2)"
wait_for_ends 1
check "11a two issues sharing a ~/ plist do not both dispatch" "$(n_started)" "1"
if printf '%s' "$OUT" | grep -q 'skip ASK-962' && \
   printf '%s' "$OUT" | grep -q 'com.foo.plist'; then
  ok "11b the skip names the shared plist"
else
  bad "11b the skip names the shared plist" "$OUT"
fi

# --- 12. a LIVE run with an empty parsed set (review finding 2) -------------
# fileset_for returns non-zero only on a Python EXCEPTION. No **Files:** line
# produced success + an empty file, so `cat` appended nothing and the live run
# contributed no constraint -- candidates fail closed on that input, live runs
# failed open, two lines under a comment claiming the opposite.
new_sandbox
export KIPI_DISPATCH_FAKE_LIVE="ASK-971"
dor ASK-971 ''                        # live, and its file set is unknown
dor ASK-972 '* `upsilon.sh`'
export KIPI_STUB_READY="ASK-972"
OUT="$(run_dispatch --burst 1 --parallel 2)"
sleep 0.3
check "12a a live run with an unknown file set holds every candidate" "$(n_started)" "0"
if printf '%s' "$OUT" | grep -q 'skip ASK-972' && \
   printf '%s' "$OUT" | grep -qi 'unknown file set'; then
  ok "12b the skip names the live run's unknown set, not a phantom overlap"
else
  bad "12b the skip names the live run's unknown set, not a phantom overlap" "$OUT"
fi

# --- 13. the magnet exemption and the BARE spelling (review finding 3) ------
# Real ASK-224 and ASK-218 both write the bare `capability-manifest.json`
# inside a sentence saying they will NOT edit it. A full-path-only `grep -vxF`
# missed that spelling and serialised two of the four dispatchable issues on a
# file neither one touches.
new_sandbox
dor ASK-981 '* `phi.sh`, `capability-manifest.json`'
dor ASK-982 '* `chi.sh`, `capability-manifest.json`'
export KIPI_STUB_READY="ASK-981 ASK-982"
OUT="$(run_dispatch --burst 2 --parallel 2)"
wait_for_ends 2
check "13a the BARE magnet spelling does not fake a conflict" "$(n_started)" "2"

# --- 14. the slot wait terminates (review finding 4) ------------------------
# LIVE was read once at the top and frozen inside `while our_active + LIVE >=
# SLOTS`, so with the slots already full the condition could never go false.
new_sandbox
export KIPI_DISPATCH_FAKE_LIVE="ASK-991"
export KIPI_DISPATCH_SLOT_WAIT=4
dor ASK-991 '* `omega991.sh`'         # live, KNOWN set, disjoint from below,
dor ASK-992 '* `psi992.sh`'           # so the wait is what is under test
export KIPI_STUB_READY="ASK-992"
OUT="$(run_dispatch_bounded 20 --burst 1 --parallel 1)"
check "14a a burst with every slot held terminates" "$(bounded_hung)" "0"
if printf '%s' "$OUT" | grep -q 'skip ASK-992' && \
   printf '%s' "$OUT" | grep -qi 'free slot'; then
  ok "14b it says it gave up waiting for a slot"
else
  bad "14b it says it gave up waiting for a slot" "$OUT"
fi
unset KIPI_DISPATCH_SLOT_WAIT

# --- 15. a CRASHED picker is not an empty board (review finding 5) ----------
# WORK_RC was captured and never read, so a traceback out of `kipi work` read
# as "nothing ready", every 15 minutes, exit 0, no page. The fleet's own
# lesson: a zero result must prove it is empty, not broken.
new_sandbox
export KIPI_STUB_WORK_RC=1
dor ASK-993 '* `omega993.sh`'
export KIPI_STUB_READY="ASK-993"
OUT="$(run_dispatch)"; RC=$?
check "15a a crashed picker exits non-zero" "$RC" "1"
if printf '%s' "$OUT" | grep -qi 'nothing ready'; then
  bad "15b a crashed picker is not reported as an empty board" "$OUT"
else
  ok "15b a crashed picker is not reported as an empty board"
fi
if grep -qi 'kipi work' "$PAGES" 2>/dev/null; then
  ok "15c the operator is paged that the picker is broken"
else
  bad "15c the operator is paged that the picker is broken" "$(cat "$PAGES")"
fi
unset KIPI_STUB_WORK_RC

# --- 16. the summary quotes the BOARD, not the window (review finding 6) ----
# LOOKAHEAD = TARGET*3+2 truncates the list, so "of 5 candidate(s)" while 55
# issues are ready is the silent truncation the skip() comment warns about,
# committed by the summary line itself.
new_sandbox
export KIPI_STUB_READY_COUNT=55
dor ASK-995 '* `alpha995.sh`'
dor ASK-996 '* `beta996.sh`'
export KIPI_STUB_READY="ASK-995 ASK-996"
OUT="$(run_dispatch --burst 1 --parallel 2)"
wait_for_ends 1
if printf '%s' "$OUT" | grep -q 'done:.*55 ready on the board'; then
  ok "16a the closing summary names the real board total"
else
  bad "16a the closing summary names the real board total" "$(printf '%s' "$OUT" | tail -1)"
fi
unset KIPI_STUB_READY_COUNT

# --- 17. a pass that dispatches NOTHING pages, once (review finding 1) ------
# Nothing live + a non-empty candidate list + zero dispatched can now only mean
# the file sets could not be READ. That is a fault, and it had no page site:
# the liveness beacon kept reporting a healthy loop doing no work.
new_sandbox
export KIPI_DISPATCH_PRD_SPLIT="$SANDBOX/does-not-exist.py"
dor ASK-997 '* `alpha997.sh`'
export KIPI_STUB_READY="ASK-997"
OUT="$(run_dispatch)"
sleep 0.3
check "17a nothing is dispatched when a file set cannot be READ" "$(n_started)" "0"
if grep -qi 'dispatched nothing' "$PAGES" 2>/dev/null; then
  ok "17b the operator is paged that the board is stuck"
else
  bad "17b the operator is paged that the board is stuck" "$(cat "$PAGES")"
fi
OUT="$(run_dispatch)"
check "17c the stuck page fires once a day, not every tick" "$(paged 'dispatched nothing')" "1"
unset KIPI_DISPATCH_PRD_SPLIT

# ===========================================================================
# PR #36 review round 4. Same rule as round 3: each case is a defect the
# reviewer reproduced, red before the fix.
# ===========================================================================

# --- 18. a converge that starts MID-PASS is seen (finding 1) ----------------
# The union of live file sets was built ONCE before the candidate loop and
# never rebuilt. pgrep is fresh inside issue_is_live() and external_live(), so
# the SLOT WAIT could end because a live run finished and a different one
# started -- and the overlap check would still be reading the set from the top
# of the pass. Two agents in one file, reported as `skipped 0`.
#
# The wait is what makes the timing deterministic: the pass cannot get past it
# until the watcher has rewritten the live set, so "mid-pass" is by
# construction, not by luck.
new_sandbox
LIVE_FILE="$SANDBOX/live.txt"
export KIPI_DISPATCH_FAKE_LIVE_FILE="$LIVE_FILE"
printf 'ASK-900\nASK-901\n' > "$LIVE_FILE"      # both slots held, both disjoint
dor ASK-900 '* `held900.sh`'
dor ASK-901 '* `held901.sh`'
dor ASK-999 '* `q-system/.q-system/scripts/linear-worker.sh`'   # starts mid-pass
dor ASK-902 '* `q-system/.q-system/scripts/linear-worker.sh`'   # the candidate
export KIPI_STUB_READY="ASK-902"
export KIPI_DISPATCH_SLOT_WAIT=20
( sleep 2; printf 'ASK-999\n' > "$LIVE_FILE" ) &
WATCHER=$!
OUT="$(run_dispatch_bounded 30 --burst 1 --parallel 2)"
wait "$WATCHER" 2>/dev/null
check "18a a converge that starts mid-pass blocks an overlapping candidate" "$(n_started)" "0"
if printf '%s' "$OUT" | grep -q 'skip ASK-902' && \
   printf '%s' "$OUT" | grep -q 'linear-worker.sh'; then
  ok "18b the skip names the file the mid-pass run took"
else
  bad "18b the skip names the file the mid-pass run took" "$OUT"
fi
unset KIPI_DISPATCH_SLOT_WAIT

# --- 19. two dispatch passes cannot pick at once (finding 1, the lock) ------
# The heartbeat (launchd, 900s) and a foreground --burst are two producers of a
# pass, and the founder's own `kipi converge` is a third. Rebuilding the union
# covers the third; only a lock covers the first two, because both can read the
# same live set and reach the same disjointness answer before either launches.
new_sandbox
LIVE_FILE="$SANDBOX/live.txt"
export KIPI_DISPATCH_FAKE_LIVE_FILE="$LIVE_FILE"
printf 'ASK-910\n' > "$LIVE_FILE"
dor ASK-910 '* `held910.sh`'
dor ASK-911 '* `alpha911.sh`'
dor ASK-912 '* `beta912.sh`'
export KIPI_DISPATCH_SLOT_WAIT=8
export KIPI_STUB_READY="ASK-911"
bash "$DISPATCH" --burst 1 --parallel 1 > "$SANDBOX/passA.out" 2>&1 &
PASS_A=$!
sleep 2                                   # A is now inside its slot wait
export KIPI_STUB_READY="ASK-912"
OUT="$(run_dispatch)"                     # a heartbeat tick while A is picking
sleep 1   # the stub converge is backgrounded; count AFTER it could have started
check "19a a tick refuses to pick while another pass holds the lock" "$(count_lines '^START ASK-912')" "0"
if printf '%s' "$OUT" | grep -qi 'another dispatch pass'; then
  ok "19b the blocked tick says why, and does not read as an empty board"
else
  bad "19b the blocked tick says why, and does not read as an empty board" "$OUT"
fi
wait "$PASS_A" 2>/dev/null
unset KIPI_DISPATCH_SLOT_WAIT

# A lock nobody can clear is a worse outage than the race it prevents: the loop
# would go dark until a human noticed a directory. Same reclaim-on-read rule as
# the claim mutex (ASK-189) -- a pid that is not running is not a holder.
new_sandbox
mkdir -p "$HOME/.config/kipi/dispatch.lock"
printf '999999' > "$HOME/.config/kipi/dispatch.lock/pid"   # above macOS PID_MAX
dor ASK-913 '* `gamma913.sh`'
export KIPI_STUB_READY="ASK-913"
OUT="$(run_dispatch)"
wait_for_ends 1
check "19c a lock left behind by a KILLED pass is reclaimed, not honoured forever" "$(n_started)" "1"

# --- 20. a persistent infra fault pages ONCE a day (finding 2) --------------
# All three of these conditions stay true until a human fixes them, and at
# StartInterval 900 an ungated page is 96 identical Slack messages a day. The
# script's own page_once comment names that failure; these three sites did not
# use it. The LOG still gets a line every tick -- only Slack is deduped.
new_sandbox
dor ASK-914 '* `delta914.sh`'
export KIPI_STUB_READY="ASK-914"
KIPI_REPO="$SANDBOX/gone" run_dispatch >/dev/null 2>&1
KIPI_REPO="$SANDBOX/gone" run_dispatch >/dev/null 2>&1
KIPI_REPO="$SANDBOX/gone" run_dispatch >/dev/null 2>&1
check "20a repo-not-found pages once across 3 ticks" "$(paged 'repo not found')" "1"

new_sandbox
dor ASK-915 '* `epsilon915.sh`'
export KIPI_STUB_READY="ASK-915"
for _ in 1 2 3; do PATH=/usr/bin:/bin bash "$DISPATCH" >/dev/null 2>&1; done
check "20b gh-not-on-PATH pages once across 3 ticks" "$(paged 'gh CLI not on PATH')" "1"

new_sandbox
export KIPI_STUB_WORK_MSG="worker: infra_error unauthorized (401)"
dor ASK-916 '* `zeta916.sh`'
export KIPI_STUB_READY="ASK-916"
for _ in 1 2 3; do run_dispatch >/dev/null 2>&1; done
check "20c the Linear-unreachable page fires once across 3 ticks" "$(paged 'Linear is unreachable')" "1"
unset KIPI_STUB_WORK_MSG

# --- 21. the REAL producer's infra shape (finding 3) ------------------------
# linear-worker.sh:239 prints `INFRA: linear unreachable (<reason>)` and exits
# 0. The two likeliest reasons -- linear-sync.py:341 "no Linear API key..." and
# :380 "network: <errno>" -- contain none of infra_error/authentication/
# unauthorized. So the most common infra failure of all read as an empty board,
# every 15 minutes, exit 0, no page.
new_sandbox
export KIPI_STUB_WORK_MSG="INFRA: linear unreachable (no Linear API key. Create one at https://linear.app/settings/api). Not counted against any issue."
dor ASK-917 '* `eta917.sh`'
export KIPI_STUB_READY="ASK-917"
OUT="$(run_dispatch)"; RC=$?
check "21a the worker's own INFRA marker exits non-zero" "$RC" "1"
if printf '%s' "$OUT" | grep -qi 'nothing ready'; then
  bad "21b an infra fault is not reported as an empty board" "$OUT"
else
  ok "21b an infra fault is not reported as an empty board"
fi
check "21c the operator is paged for it" "$(paged 'Linear is unreachable')" "1"
unset KIPI_STUB_WORK_MSG

# A per-issue INFRA line (linear-worker.sh:763, :823) is NOT a dead board: the
# worker says it and keeps going. Stopping on it would turn one bad issue into
# a stopped loop, which is the same over-enforcement finding 1 was.
new_sandbox
export KIPI_STUB_WORK_MSG=""
dor ASK-918 '* `theta918.sh`'
export KIPI_STUB_READY="ASK-918"
OUT="$(KIPI_STUB_WORK_MSG='INFRA: claim failed rc=1 on ASK-777 (not counted against the issue)' KIPI_STUB_WORK_KEEP_LIST=1 run_dispatch)"
wait_for_ends 1
check "21d an INFRA line WITH candidates still dispatches" "$(n_started)" "1"
unset KIPI_STUB_WORK_MSG KIPI_STUB_WORK_KEEP_LIST

# --- 22. --burst 0 is refused (finding 4) -----------------------------------
# `--parallel 0` was rejected; `--burst 0` fell through every `[ "$BURST" -gt 0
# ]` branch and ran a full heartbeat tick -- spending the daily counter and
# writing the liveness beacon that the beacon's own comment says a burst must
# never write, because a burst resetting the gap masks a dead scheduler.
new_sandbox
dor ASK-919 '* `iota919.sh`'
export KIPI_STUB_READY="ASK-919"
OUT="$(run_dispatch --burst 0)"; RC=$?
sleep 0.3
check "22a --burst 0 is refused" "$RC" "2"
check "22b --burst 0 dispatches nothing" "$(n_started)" "0"
check "22c --burst 0 does not write the liveness beacon" \
  "$([ -f "$HOME/.config/kipi/dispatch-lastbeat" ] && echo wrote || echo clean)" "clean"
check "22d --burst 0 does not spend the daily counter" \
  "$([ -f "$HOME/.config/kipi/dispatch-count-$(date +%Y-%m-%d)" ] && echo spent || echo clean)" "clean"

# --- 23. one file, two spellings, one intersection (finding 5) --------------
# The r3 fix normalised `~/x` against `/Users/me/x`. It did not normalise the
# repo's own absolute path against the repo-relative spelling, so two issues
# editing one file could both dispatch. 6 real DoRs use an absolute repo path.
new_sandbox
dor ASK-921 '* `q-system/.q-system/scripts/linear-worker.sh`'
dor ASK-922 "* \`$SANDBOX/repo/q-system/.q-system/scripts/linear-worker.sh\`"
export KIPI_STUB_READY="ASK-921 ASK-922"
OUT="$(run_dispatch --burst 2 --parallel 2)"
wait_for_ends 1
check "23a an absolute and a relative spelling of one file intersect" "$(n_started)" "1"
if printf '%s' "$OUT" | grep -q 'skip ASK-922' && \
   printf '%s' "$OUT" | grep -q 'linear-worker.sh'; then
  ok "23b the skip names the file, in one spelling"
else
  bad "23b the skip names the file, in one spelling" "$OUT"
fi

echo
printf '== %s passed, %s failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ] || exit 1
