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
    # A child that dies the instant it starts. The dispatcher must not report
    # this one as dispatched: that is the silent-success shape main's PR #39
    # fixed for the single-issue path, and this branch launches N children.
    [ "${KIPI_STUB_CONVERGE_RC:-0}" != "0" ] && exit "$KIPI_STUB_CONVERGE_RC"
    # Long enough to still be running when a test tears down the dispatcher's
    # process group, which is what launchd does when the job's main process
    # exits. END is therefore the SURVIVAL marker, not just a tidy log line.
    sleep "${KIPI_STUB_CONVERGE_SLEEP:-1}"
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
  # A leaked 6s converge or an instant-death rc would silently change the
  # meaning of every later case, so both seams reset per sandbox.
  unset KIPI_STUB_CONVERGE_SLEEP KIPI_STUB_CONVERGE_RC
  # The dispatcher watches each child for CONFIRM_SECS before calling it
  # dispatched, and production's 10s is deliberately longer than the stub
  # converge lives (1s) -- unpinned, every multi-candidate case reports DISPATCH
  # DIED and the pass stops, which is what happened the first time this ran.
  # One check at t=0 is enough here: the stub is inside its sleep by then.
  # Cases that assert on a DEATH raise this so a second check lands after it.
  export KIPI_DISPATCH_CONFIRM_SECS=1
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
# A LONGER STUB CONVERGE, because this is the only case that measures OVERLAP.
# With the default 1s stub against a 1s confirm window, child N is at the edge of
# death when child N+1 launches, so on a loaded box the replayed peak drops to 1
# and the case fails for machine load rather than for a concurrency defect --
# observed once here while the fleet gate was running beside it. 4s makes the
# overlap outlast the launch sequence, so the assertion measures the cap again.
export KIPI_STUB_CONVERGE_SLEEP=4
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
# The budget day, NOT plain today: the counter is filed under a RESET_HOUR-
# shifted stamp (see section 24). Between midnight and 07:00 the two differ, so
# a plain-today spelling here checks a file the script never writes and passes
# vacuously -- the check would quietly stop testing for seven hours a night.
check "22d --burst 0 does not spend the daily counter" \
  "$([ -f "$HOME/.config/kipi/dispatch-count-$(date -v-"${KIPI_DISPATCH_RESET_HOUR:-7}"H +%Y-%m-%d)" ] && echo spent || echo clean)" "clean"

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

# --- 24. the spend budget rolls at RESET_HOUR, not at midnight --------------
# THE REGRESSION THIS EXISTS TO CATCH, found while merging main into this branch
# on 2026-07-28: this branch had rewritten kipi-dispatch.sh and, in the rewrite,
# dropped RESET_HOUR entirely -- counter back on `dispatch-count-$TODAY`, log
# line back to "stopping until local midnight", the plist key gone. All 58
# checks above still passed, because not one of them looked at WHICH day the
# counter is filed under. A silent revert of a founder safety decision.
#
# The decision, verbatim: "i rather have the cap restart in the morning. because
# midnight makes it so it can work while i sleep and thats not safe." A midnight
# roll refills the allowance at the moment the founder falls asleep, so an
# unattended overnight run gets the whole budget. Rolling at 07:00 means the
# night can only spend what is LEFT from the day before.
#
# RESET_HOUR is set ABOVE the current hour so the shift is guaranteed to land in
# yesterday whatever time this suite runs. Asserting on the FILENAME is the
# point: it is the only place the budget day is observable, and it is exactly
# what a rewrite that reaches for $TODAY gets wrong.
new_sandbox
dor ASK-923 '* `kappa923.sh`'
export KIPI_STUB_READY="ASK-923"
NOW_HOUR="$(date +%-H)"
export KIPI_DISPATCH_RESET_HOUR="$((NOW_HOUR + 1))"
SHIFTED_DAY="$(date -v-"${KIPI_DISPATCH_RESET_HOUR}"H +%Y-%m-%d)"
PLAIN_DAY="$(date +%Y-%m-%d)"
OUT="$(run_dispatch)"
wait_for_ends 1

# Guard the fixture itself: if these two ever match, the assertions below pass
# no matter what the script does, and the test silently stops testing.
check "24a the fixture actually separates the two days" \
  "$([ "$SHIFTED_DAY" != "$PLAIN_DAY" ] && echo separated || echo SAME)" "separated"
check "24b the counter is filed under the RESET_HOUR-shifted day" \
  "$([ -f "$HOME/.config/kipi/dispatch-count-$SHIFTED_DAY" ] && echo filed || echo missing)" "filed"
check "24c the counter is NOT filed under plain today" \
  "$([ -f "$HOME/.config/kipi/dispatch-count-$PLAIN_DAY" ] && echo filed || echo clean)" "clean"
unset KIPI_DISPATCH_RESET_HOUR

# The cap message has to name the hour it resumes. "until local midnight" on a
# 07:00 budget sends the founder back at the wrong time, and it is the string
# that gave the revert away.
new_sandbox
dor ASK-924 '* `lambda924.sh`'
export KIPI_STUB_READY="ASK-924"
export KIPI_DISPATCH_DAILY_MAX=1
BUDGET_DAY_NOW="$(date -v-"${KIPI_DISPATCH_RESET_HOUR:-7}"H +%Y-%m-%d)"
printf '9' > "$HOME/.config/kipi/dispatch-count-$BUDGET_DAY_NOW"
OUT="$(run_dispatch)"
sleep 0.3
check "24d a capped tick dispatches nothing" "$(n_started)" "0"
if printf '%s' "$OUT" | grep -qi 'midnight'; then
  bad "24e the cap message names the reset hour, not midnight" "$OUT"
else
  ok "24e the cap message names the reset hour, not midnight"
fi
unset KIPI_DISPATCH_DAILY_MAX

# --- 25. a Files block the tokenizer only PARTLY reads (r5 finding 1) -------
# THE DEFECT CLASS, not one more spelling. prd_split._split_candidates:513
# returns the backticked spans WHEN THERE ARE ANY, so a plain path sitting
# beside a backticked one is discarded -- the set looks complete, is not, and
# the gate certifies two agents into one file with `skipped 0`.
#
# The fix is NOT a third rescue regex (that is how rounds 3, 4 and 5 each found
# the next spelling). It is: when the block names a file the set does not
# contain, the set is UNKNOWN. Unknown already has a meaning here -- run alone,
# never in parallel -- so this fails closed on the intersection while keeping
# the throughput floor.
#
# UNKNOWN AND NOT UNREADABLE, deliberately. rc=2 skips the candidate outright
# (dispatch loop, CAND_RC -eq 2), which would make a mixed-markup DoR
# permanently undispatchable -- the same refuse-the-whole-board regression
# finding 1 of round 3 cost this file, arriving by a different door.
new_sandbox
dor ASK-931 '* `q-system/.q-system/scripts/shared931.sh`'
dor ASK-932 '* `q-system/.q-system/scripts/other932.sh` (extend)
* q-system/.q-system/scripts/shared931.sh'
export KIPI_STUB_READY="ASK-931 ASK-932"
OUT="$(run_dispatch --burst 2 --parallel 2)"
wait_for_ends 1
check "25a a Files block that is only PARTLY read does not dispatch in parallel" "$(n_started)" "1"
if printf '%s' "$OUT" | grep -q 'skip ASK-932' && printf '%s' "$OUT" | grep -q 'shared931.sh'; then
  ok "25b the skip names the path that was dropped"
else
  bad "25b the skip names the path that was dropped" "$OUT"
fi

# The control, and the reason 25a is about the SET and not about the
# intersection: the same two issues, uniform markup, already behaved.
new_sandbox
dor ASK-933 '* `q-system/.q-system/scripts/shared933.sh`'
dor ASK-934 '* `q-system/.q-system/scripts/other934.sh` (extend)
* `q-system/.q-system/scripts/shared933.sh`'
export KIPI_STUB_READY="ASK-933 ASK-934"
OUT="$(run_dispatch --burst 2 --parallel 2)"
wait_for_ends 1
check "25c control: uniform markup already intersected" "$(n_started)" "1"

# A file named with a line-number citation (`foo.sh:318`) is a path the
# tokenizer cannot take -- the colon fails _PATH_TOKEN_RE -- so the block is
# partly read and the same rule applies.
new_sandbox
dor ASK-935 '* `q-system/.q-system/scripts/shared935.sh`'
dor ASK-936 '* `q-system/.q-system/scripts/other936.sh`, plus q-system/.q-system/scripts/shared935.sh:318'
export KIPI_STUB_READY="ASK-935 ASK-936"
OUT="$(run_dispatch --burst 2 --parallel 2)"
wait_for_ends 1
check "25d a path written as a foo.sh:NN citation is not silently dropped" "$(n_started)" "1"

# THE GUARD ON THE FIX ITSELF. Over-detection is not free: every issue it
# mislabels unknown runs ALONE, which is the board-serialising regression this
# gate already made once. A fully-read block with ordinary prose beside it --
# including a NEGATED mention of the magnet file, which is the real shape of
# ASK-224 and ASK-218 -- still counts as known and still shares the board.
new_sandbox
dor ASK-937 '* `q-system/.q-system/scripts/alpha937.sh` (extend in place, no new test file, so no capability-manifest.json edit and no conflict on the magnet file)'
dor ASK-938 '* `q-system/.q-system/scripts/beta938.sh` -- extend in place; the mutex note covers it'
export KIPI_STUB_READY="ASK-937 ASK-938"
OUT="$(run_dispatch --burst 2 --parallel 2)"
wait_for_ends 2
check "25e a fully-read block with prose still runs in PARALLEL" "$(n_started)" "2"

# WHAT THE OPERATOR READS AT 3AM. A partly-read block runs alone, and the line
# saying so must not tell them to add a `**Files:**` list that is already there.
new_sandbox
dor ASK-939 '* `q-system/.q-system/scripts/other939.sh` (extend)
* q-system/.q-system/scripts/plain939.sh'
export KIPI_STUB_READY="ASK-939"
OUT="$(run_dispatch --burst 1 --parallel 2)"
wait_for_ends 1
check "25f a partly-read block still dispatches, alone" "$(n_started)" "1"
if printf '%s' "$OUT" | grep -q 'ALONE' && ! printf '%s' "$OUT" | grep -q 'names no files'; then
  ok "25g the ALONE line says the block was partly read, not that it names no files"
else
  bad "25g the ALONE line says the block was partly read, not that it names no files" "$OUT"
fi

# --- 26. the burst estimate quotes what can run, not what was typed (r5 f2) --
# The line's whole job is to let the founder say no BEFORE spending, so a 5x
# overstatement at that moment is the number failing at the one thing it is for.
# The pass can never dispatch more issues than it has candidates.
new_sandbox
dor ASK-941 '* `q-system/.q-system/scripts/alpha941.sh`'
dor ASK-942 '* `q-system/.q-system/scripts/beta942.sh`'
export KIPI_STUB_READY="ASK-941 ASK-942"
OUT="$(run_dispatch --burst 10 --parallel 2)"
wait_for_ends 2
if printf '%s' "$OUT" | grep -q 'estimated cost up to 12 '; then
  ok "26a the estimate is capped by the candidate count (2 x 3 x 2 = 12)"
else
  bad "26a the estimate is capped by the candidate count (2 x 3 x 2 = 12)" \
    "$(printf '%s' "$OUT" | grep 'estimated cost' || echo '<no estimate line>')"
fi
if printf '%s' "$OUT" | grep -q 'burst: up to 2 issue(s)'; then
  ok "26b the 'up to N' line is capped too"
else
  bad "26b the 'up to N' line is capped too" \
    "$(printf '%s' "$OUT" | grep 'burst: up to' || echo '<no line>')"
fi
check "26c the cap does not cost a dispatch" "$(n_started)" "2"

# --- 27. a malformed --parallel must not run a production tick (r4 f4) ------
# `--burst` with no value exits 2; `--parallel` with no value fell through to
# "use the default" and ran a full heartbeat pass under the founder's own
# command -- it dispatched a real agent during the review. The harm is not the
# rejected flag, it is the SIDE EFFECTS a typo bought: a launched agent and a
# spent daily counter. Assert those, not just the exit code.
new_sandbox
dor ASK-951 '* `q-system/.q-system/scripts/alpha951.sh`'
export KIPI_STUB_READY="ASK-951"
OUT="$(run_dispatch --parallel)"; RC=$?
sleep 1
check "27a --parallel with no value is refused, like --burst" "$RC" "2"
check "27b a malformed --parallel dispatches nothing" "$(n_started)" "0"
check "27c a malformed --parallel does not spend the daily counter" \
  "$(ls "$HOME/.config/kipi" | grep -c '^dispatch-count-' || true)" "0"
if printf '%s' "$OUT" | grep -q 'parallel wants a number'; then
  ok "27d the refusal names the flag"
else
  bad "27d the refusal names the flag" "$OUT"
fi
new_sandbox
dor ASK-952 '* `q-system/.q-system/scripts/alpha952.sh`'
export KIPI_STUB_READY="ASK-952"
OUT="$(run_dispatch --burst 1 --parallel 2)"
wait_for_ends 1
check "27e --parallel WITH a value, on a burst, still works" "$(n_started)" "1"
# This case USED to run `--parallel 2` with no --burst and assert that it
# dispatched. That is r6 finding 2: the one spelling of the flag that still
# parsed ran a full production heartbeat tick under the founder's name. The
# control moved onto the spelling the flag is documented for; case 33 owns the
# refusal.

# --- 28. an extensionless real file is a file (r4 f3) -----------------------
# The PARTIAL guard required a dot-extension on the basename, so the repo-root
# `kipi` CLI was neither extracted into the set nor flagged as missed: the guard
# whose job is "does the block NAME a file the set does not contain" reported
# the block fully read, and two issues both editing it dispatched with
# `skipped 0`. A dot is a spelling; "is a real file in this repo" is the fact.
new_sandbox
dor ASK-961 '* `q-system/.q-system/scripts/alpha961.sh`
* the repo-root `kipi` dispatch case'
dor ASK-962 '* `q-system/.q-system/scripts/beta962.sh`
* the repo-root `kipi` dispatch case'
export KIPI_STUB_READY="ASK-961 ASK-962"
OUT="$(run_dispatch --burst 2 --parallel 2)"
wait_for_ends 1
check "28a two issues naming the extensionless kipi CLI do not both dispatch" "$(n_started)" "1"
if printf '%s' "$OUT" | grep -q 'skip ASK-962'; then
  ok "28b the held candidate is reported, not silently dropped"
else
  bad "28b the held candidate is reported, not silently dropped" "$OUT"
fi

# THE GUARD ON THE GUARD. Over-detection is not free: every block it mislabels
# runs ALONE, which is the board-serialising failure round 3 already cost this
# file. A word that is not a real file, and a DIRECTORY that is, must both stay
# out of it.
new_sandbox
mkdir -p "$SANDBOX/repo/q-system/.q-system/scripts"
dor ASK-963 '* `q-system/.q-system/scripts/alpha963.sh` -- extend in place under q-system, nothing new'
dor ASK-964 '* `q-system/.q-system/scripts/beta964.sh` -- extend in place under q-system, nothing new'
export KIPI_STUB_READY="ASK-963 ASK-964"
OUT="$(run_dispatch --burst 2 --parallel 2)"
wait_for_ends 2
check "28c a real DIRECTORY named in prose does not make the set unknown" "$(n_started)" "2"

# ...and a COMMAND is not a file. Measured on the live board: accepting any
# real-file token flipped ASK-133 and ASK-135 to run-alone on `kipi update` and
# `kipi check` -- the CLI named as a command inside their Files block, not a
# file either one edits. 2 of 8 shareable issues is the board-serialising
# over-enforcement round 3 already cost this file. The real shape, verbatim.
new_sandbox
dor ASK-965 '* `q-system/.q-system/scripts/alpha965.sh`
* `settings-template.json` (repo root; the sync check aborts `kipi update` if the hook is here but not there)'
dor ASK-966 '* `q-system/.q-system/scripts/beta966.sh`
* `validate-separation.py` (register it so `kipi check` runs it)'
export KIPI_STUB_READY="ASK-965 ASK-966"
OUT="$(run_dispatch --burst 2 --parallel 2)"
wait_for_ends 2
check "28d the kipi CLI named as a COMMAND still shares the board" "$(n_started)" "2"

# --- 29. the pick lock must not have a state nobody can clear (r4 f2) -------
# `lock_holder_dead` reclaimed only when the pid file parsed as a number AND
# that pid was gone. Two states escaped with no age check anywhere, and each
# turned the loop off permanently and silently while the liveness beacon (taken
# BEFORE the lock) kept reporting healthy.
#
# B1: a lock dir with no pid file. The code called that "YOUNG, not stale --
# the microsecond between mkdir and the pid write", but young had no expiry, so
# it was young forever.
new_sandbox
mkdir -p "$HOME/.config/kipi/dispatch.lock"
touch -t 202001010000 "$HOME/.config/kipi/dispatch.lock"
dor ASK-971 '* `q-system/.q-system/scripts/alpha971.sh`'
export KIPI_STUB_READY="ASK-971"
OUT="$(run_dispatch)"
wait_for_ends 1
check "29a a lock dir with no pid file, past the grace window, is reclaimed" "$(n_started)" "1"

# The grace window is the point: the real mkdir -> pid-write race is
# microseconds, and stealing a lock inside it puts two pickers in flight, which
# is the race the lock exists to prevent.
new_sandbox
mkdir -p "$HOME/.config/kipi/dispatch.lock"
dor ASK-972 '* `q-system/.q-system/scripts/alpha972.sh`'
export KIPI_STUB_READY="ASK-972"
OUT="$(run_dispatch)"
sleep 1
check "29b a JUST-created lock dir with no pid file is honoured, not stolen" "$(n_started)" "0"

# B2: the recorded pid was REUSED after a reboot. `kill -0` succeeds, so the
# holder read as alive indefinitely. Deliberately left FRESH so only the
# command check can clear it -- an age fallback alone would pass this by
# accident and stay wrong for the first hour after every reboot.
new_sandbox
mkdir -p "$HOME/.config/kipi/dispatch.lock"
sleep 120 & REUSED_PID=$!
printf '%s' "$REUSED_PID" > "$HOME/.config/kipi/dispatch.lock/pid"
dor ASK-973 '* `q-system/.q-system/scripts/alpha973.sh`'
export KIPI_STUB_READY="ASK-973"
OUT="$(run_dispatch)"
wait_for_ends 1
check "29c a lock whose pid was REUSED by an unrelated process is reclaimed" "$(n_started)" "1"
kill "$REUSED_PID" 2>/dev/null; wait "$REUSED_PID" 2>/dev/null

# CONTROL: a lock held by a real, live dispatch pass is still honoured. The fix
# must clear the two dead states without ever stealing from a working one.
new_sandbox
mkdir -p "$SANDBOX/fakebin"
printf '#!/usr/bin/env bash\nsleep 120\n' > "$SANDBOX/fakebin/kipi-dispatch.sh"
chmod +x "$SANDBOX/fakebin/kipi-dispatch.sh"
bash "$SANDBOX/fakebin/kipi-dispatch.sh" & HOLDER_PID=$!
mkdir -p "$HOME/.config/kipi/dispatch.lock"
printf '%s' "$HOLDER_PID" > "$HOME/.config/kipi/dispatch.lock/pid"
dor ASK-974 '* `q-system/.q-system/scripts/alpha974.sh`'
export KIPI_STUB_READY="ASK-974"
OUT="$(run_dispatch)"
sleep 1
check "29d a lock held by a LIVE dispatch pass is honoured, not stolen" "$(n_started)" "0"

# ...and an ancient one that is STILL held is the outage that has no other
# signal: the tick exits 0 every 900s and the beacon says healthy. Stealing it
# would put two pickers in flight, so this pages instead -- once a day, like
# every other recurring condition here.
touch -t 202001010000 "$HOME/.config/kipi/dispatch.lock"
run_dispatch >/dev/null 2>&1
run_dispatch >/dev/null 2>&1
check "29e an ancient but still-held lock pages once, instead of silence" "$(paged 'pick lock')" "1"
kill "$HOLDER_PID" 2>/dev/null; wait "$HOLDER_PID" 2>/dev/null

# --- 30. the magnet exemption must not cite a rule that does not exist (f1) --
# The exemption said it "relies on the union-merge rule that already governs"
# capability-manifest.json. `.gitattributes` grants merge=union to exactly one
# path, and it is not this one -- so two parallel test-adding issues conflict on
# the manifest and leave it as invalid JSON. A comment is not enforcement; this
# case is, and it reads git's own answer rather than grepping the file.
#
# Deliberately NOT a banned-phrase grep. "must not say union-merge" cannot tell
# a claim from the sentence explaining why the claim was false, so it would go
# green the moment someone deleted the explanation. This asks the opposite, and
# fails in BOTH directions: git is the authority on whether a merge rule exists,
# and the script must carry the matching acknowledgement either way.
MAGNET_PATH="q-system/.q-system/capability-manifest.json"
MAGNET_ATTR="$(cd "$REPO_ROOT" && git check-attr merge -- "$MAGNET_PATH" 2>/dev/null | sed 's/.*: //')"
MAGNET_ACK="$(grep -c 'MAGNET CONFLICT IS UNMITIGATED' "$DISPATCH" || true)"
if [ "$MAGNET_ATTR" = "unspecified" ]; then
  check "30a no merge rule exists, so the exemption says the conflict is unmitigated" "$MAGNET_ACK" "1"
else
  check "30a a merge rule exists ($MAGNET_ATTR), so the unmitigated marker must go" "$MAGNET_ACK" "0"
fi

# And the wrong fix is blocked too: merge=union keeps BOTH sides' lines, which
# is right for an append-only .jsonl ledger and produces INVALID JSON for a
# .json object. Proven by the reviewer's repro, so it is a defect either way.
UNION_JSON="$(cd "$REPO_ROOT" && grep -E '\.json[[:space:]].*merge=union' .gitattributes 2>/dev/null | grep -vc 'jsonl' || true)"
check "30b no .json file is given merge=union (it yields invalid JSON)" "$UNION_JSON" "0"

# THE REPORT MOVES WITH THE DETECTOR. The waiver is a deliberate trade, so the
# operator has to learn about the conflict at DISPATCH time, not from a red PR.
new_sandbox
LIVE_FILE="$SANDBOX/live.txt"
export KIPI_DISPATCH_FAKE_LIVE_FILE="$LIVE_FILE"
printf 'ASK-980\n' > "$LIVE_FILE"
dor ASK-980 '* `q-system/.q-system/capability-manifest.json`, `q-system/.q-system/scripts/alpha980.sh`'
dor ASK-981 '* `q-system/.q-system/capability-manifest.json`, `q-system/.q-system/scripts/beta981.sh`'
export KIPI_STUB_READY="ASK-981"
OUT="$(run_dispatch --burst 1 --parallel 2)"
wait_for_ends 1
check "30c a magnet-only overlap still dispatches" "$(n_started)" "1"
if printf '%s' "$OUT" | grep -q 'capability-manifest.json' \
   && printf '%s' "$OUT" | grep -q 'ASK-980' \
   && printf '%s' "$OUT" | grep -qi 'conflict'; then
  ok "30d the waived magnet overlap is announced, naming the other run and the file"
else
  bad "30d the waived magnet overlap is announced, naming the other run and the file" "$OUT"
fi
unset KIPI_DISPATCH_FAKE_LIVE_FILE

# --- 31. THE MERGE ITSELF IS A REGRESSION SURFACE ---------------------------
# main's PR #39 proved that launchd reaps the job's whole process group when the
# main process exits, so `nohup ... & disown` children die the instant the pass
# returns -- invisibly, because the log file exists (created by the redirect),
# `dispatched X` still prints, and the budget is already spent. It fixed that on
# the SINGLE-issue tail. This branch rewrote that same tail into an N-candidate
# loop, so resolving the merge in this branch's favour silently undoes the fix,
# and all 91 cases above stayed green while it was broken.
#
# The launchd teardown is modelled deterministically -- kill the pass's process
# group after it exits -- so no launchd job has to be loaded on the founder's
# machine to see it.
run_dispatch_own_session() {  # run_dispatch_own_session <args...>
  local out="$SANDBOX/session.out"
  : > "$out"
  # start_new_session puts the pass in a process group of its own, holding
  # nothing but the pass and its children, so the kill below cannot reach the
  # suite. The pid of a session leader IS its process-group id.
  DISPATCH_PGID="$(python3 - "$DISPATCH" "$out" "$@" <<'PY'
import subprocess, sys
disp, out, argv = sys.argv[1], sys.argv[2], sys.argv[3:]
log = open(out, "ab", buffering=0)
p = subprocess.Popen(["bash", disp] + argv, stdout=log, stderr=log,
                     start_new_session=True)
print(p.pid, flush=True)
p.wait()
PY
)"
}
session_out() { cat "$SANDBOX/session.out" 2>/dev/null || true; }

new_sandbox
export KIPI_STUB_CONVERGE_SLEEP=6      # still running when the group is killed
export KIPI_DISPATCH_CONFIRM_SECS=2    # keep the alive-confirmation short
dor ASK-991 '* `q-system/.q-system/scripts/alpha991.sh`'
export KIPI_STUB_READY="ASK-991"
run_dispatch_own_session --burst 1 --parallel 1
kill -TERM -"$DISPATCH_PGID" 2>/dev/null || true   # what launchd does
sleep 8                                            # past the stub's own sleep
check "31a a dispatched child survives the launchd teardown of the pass's process group" \
  "$(count_lines '^END ')" "1"

# THE LOG IS EVIDENCE, SO IT IS APPENDED. A re-dispatch of the same issue used
# to truncate the previous run's output with `>`, which is the file the failure
# page points the operator at. The run boundary is what makes an appended log
# readable: without it they are reading the previous run's tail as this one's.
new_sandbox
dor ASK-992 '* `q-system/.q-system/scripts/alpha992.sh`'
export KIPI_STUB_READY="ASK-992"
printf 'PREVIOUS RUN OUTPUT\n' > "$HOME/.config/kipi/converge-ASK-992.log"
run_dispatch --burst 1 --parallel 1 >/dev/null
wait_for_ends 1
CONV_LOG="$(cat "$HOME/.config/kipi/converge-ASK-992.log" 2>/dev/null || true)"
if printf '%s' "$CONV_LOG" | grep -q 'PREVIOUS RUN OUTPUT' \
   && printf '%s' "$CONV_LOG" | grep -q 'dispatch ASK-992'; then
  ok "31b the converge log is appended with a run boundary, not truncated"
else
  bad "31b the converge log is appended with a run boundary, not truncated" "$CONV_LOG"
fi

# A CHILD THAT DIES INSTANTLY IS NOT A DISPATCH. The budget slot is already
# spent at this point, so reporting success is the expensive lie: the loop looks
# healthy, spends the subscription, and does no work.
new_sandbox
export KIPI_STUB_CONVERGE_RC=1
export KIPI_DISPATCH_CONFIRM_SECS=2
dor ASK-993 '* `q-system/.q-system/scripts/alpha993.sh`'
export KIPI_STUB_READY="ASK-993"
OUT="$(run_dispatch --burst 1 --parallel 1)"; RC=$?
check "31c a child that died is not reported as a dispatch" \
  "$(printf '%s' "$OUT" | grep -c 'confirmed running' || true)" "0"
if printf '%s' "$OUT" | grep -q 'DISPATCH DIED'; then
  ok "31d the death is named in the log, not inferred from silence"
else
  bad "31d the death is named in the log, not inferred from silence" "$OUT"
fi
check "31e a dead child pages the founder" "$(paged 'died')" "1"
check "31f a pass whose child died exits non-zero" "$RC" "1"

# GUARDS ON MY OWN REWRITE of the duplicate check. Both of these pass before and
# after; they exist because the rewrite is the place a boundary bug or a
# prefix-match would land, and that is the race the check exists to prevent.
new_sandbox
LIVE_FILE="$SANDBOX/live.txt"
export KIPI_DISPATCH_FAKE_LIVE_FILE="$LIVE_FILE"
printf 'ASK-15\n' > "$LIVE_FILE"
dor ASK-15 '* `q-system/.q-system/scripts/alpha15.sh`'
dor ASK-151 '* `q-system/.q-system/scripts/beta151.sh`'
export KIPI_STUB_READY="ASK-151"
run_dispatch --burst 1 --parallel 2 >/dev/null
wait_for_ends 1
check "31g a live ASK-15 does not make ASK-151 read as already live" "$(n_started)" "1"

new_sandbox
LIVE_FILE="$SANDBOX/live.txt"
export KIPI_DISPATCH_FAKE_LIVE_FILE="$LIVE_FILE"
printf 'ASK-151\n' > "$LIVE_FILE"
dor ASK-151 '* `q-system/.q-system/scripts/beta151.sh`'
export KIPI_STUB_READY="ASK-151"
run_dispatch --burst 1 --parallel 2 >/dev/null
check "31h an issue that IS already live is refused" "$(n_started)" "0"
unset KIPI_DISPATCH_FAKE_LIVE_FILE

# --- 32. the anti-silence page must not fire on the loop WORKING (r6 f1) ----
# LOCK_MAX_HOLD's comment said `> any legitimate hold`. The code disagreed: the
# lock is taken before the candidate loop and released at exit, so a burst holds
# it for its whole life, and that life is bounded by TARGET x SLOT_WAIT -- up to
# N x 600s. `--burst 4 --parallel 2` legitimately holds it 40-90 min against a
# 3600s threshold, so the alert r5 added to break silence fired on the normal
# duration of the feature this PR exists to add, telling the founder at 3am that
# "the Linear loop is STOPPED" and handing them a kill-and-rm for in-flight work.
#
# The fix is a ceiling DERIVED from the holder's own bound, written by the holder
# into its lock and read by whoever finds it -- not a bigger constant, which is
# just the same false positive further out.
backdate() {  # backdate <path> <seconds-ago>   BSD then GNU, like the script
  local stamp
  stamp="$(date -v-"$2"S +%Y%m%d%H%M.%S 2>/dev/null \
           || date -d "-$2 seconds" +%Y%m%d%H%M.%S 2>/dev/null)"
  touch -t "$stamp" "$1"
}
new_sandbox
LOCK="$HOME/.config/kipi/dispatch.lock"
LIVE_FILE="$SANDBOX/live.txt"
export KIPI_DISPATCH_FAKE_LIVE_FILE="$LIVE_FILE"
printf 'ASK-980\n' > "$LIVE_FILE"        # fills the one slot, so the burst waits
dor ASK-980 '* `held980.sh`'
dor ASK-981 '* `alpha981.sh`'
dor ASK-982 '* `beta982.sh`'
dor ASK-983 '* `gamma983.sh`'
dor ASK-984 '* `delta984.sh`'
export KIPI_STUB_READY="ASK-981 ASK-982 ASK-983 ASK-984"
export KIPI_DISPATCH_SLOT_WAIT=600
bash "$DISPATCH" --burst 4 --parallel 1 > "$SANDBOX/holder.out" 2>&1 &
HOLDER=$!
sleep 3                                   # the burst is inside its slot wait now
DECL="$(cat "$LOCK/max_hold" 2>/dev/null || echo 0)"
case "$DECL" in ''|*[!0-9]*) DECL=0 ;; esac
# The invariant, not a magic number: whatever ceiling it declares has to cover
# 4 candidates x (600s slot wait + the confirm window), and still be at least
# the old constant so a heartbeat's own hang is not detected any later.
if [ "$DECL" -ge "$(( 4 * (600 + KIPI_DISPATCH_CONFIRM_SECS) + 3600 ))" ]; then
  ok "32a the holder declares a ceiling that covers its own worst-case hold"
else
  bad "32a the holder declares a ceiling that covers its own worst-case hold" \
    "declared [$DECL]"
fi

backdate "$LOCK" 5000                     # past 3600, inside its own ceiling
export KIPI_STUB_READY="ASK-982"
OUT="$(run_dispatch)"
check "32b a heartbeat tick does not page while a WORKING burst holds the lock" \
  "$(paged 'pick lock')" "0"
if printf '%s' "$OUT" | grep -qi 'another dispatch pass is already picking'; then
  ok "32c the tick still says why in the log, so quiet is not silent"
else
  bad "32c the tick still says why in the log, so quiet is not silent" "$OUT"
fi

# ...and the anti-silence property survives: past the holder's OWN declared
# worst case, the hold is no longer explainable by the work, so it pages.
backdate "$LOCK" 20000
run_dispatch >/dev/null 2>&1
check "32d past its own declared ceiling, a held lock still pages" \
  "$(paged 'pick lock')" "1"
kill -9 "$HOLDER" 2>/dev/null; wait "$HOLDER" 2>/dev/null
unset KIPI_DISPATCH_SLOT_WAIT KIPI_DISPATCH_FAKE_LIVE_FILE

# THE THREE WAYS THE DECLARED CEILING CAN BE ABSENT OR WRONG. Every one of them
# has to keep the alert, because a file that can silence the loop's only
# anti-silence page is a worse defect than the false positive it fixes.
# fake_holder [declared-ceiling] -- a live process whose command line reads as a
# dispatch pass, holding an ancient lock.
#
# THE CEILING IS WRITTEN BEFORE THE BACKDATE, and that order is the fixture
# telling the truth rather than a tidiness choice: creating a file inside the
# lock directory updates the DIRECTORY's mtime, which is what lock_age reads. A
# fixture that wrote max_hold after backdating would reset the lock to 0s old and
# pass for the wrong reason -- which is exactly what the first cut of these two
# cases did. Production writes it in the same breath as the pid, at acquisition,
# for the same reason.
fake_holder() {
  mkdir -p "$SANDBOX/fakebin"
  printf '#!/usr/bin/env bash\nsleep 120\n' > "$SANDBOX/fakebin/kipi-dispatch.sh"
  chmod +x "$SANDBOX/fakebin/kipi-dispatch.sh"
  bash "$SANDBOX/fakebin/kipi-dispatch.sh" & HOLDER_PID=$!
  mkdir -p "$HOME/.config/kipi/dispatch.lock"
  printf '%s' "$HOLDER_PID" > "$HOME/.config/kipi/dispatch.lock/pid"
  [ $# -ge 1 ] && printf '%s' "$1" > "$HOME/.config/kipi/dispatch.lock/max_hold"
  touch -t 202001010000 "$HOME/.config/kipi/dispatch.lock"
}
new_sandbox
fake_holder                                # no max_hold: a SIGKILLed pass, or
dor ASK-985 '* `alpha985.sh`'              # a lock written by an older build
export KIPI_STUB_READY="ASK-985"
run_dispatch >/dev/null 2>&1
check "32e a lock with NO declared ceiling falls back to the constant, and pages" \
  "$(paged 'pick lock')" "1"
kill "$HOLDER_PID" 2>/dev/null; wait "$HOLDER_PID" 2>/dev/null

new_sandbox
fake_holder banana
dor ASK-986 '* `alpha986.sh`'
export KIPI_STUB_READY="ASK-986"
run_dispatch >/dev/null 2>&1
check "32f a garbage ceiling cannot mute the alert" "$(paged 'pick lock')" "1"
kill "$HOLDER_PID" 2>/dev/null; wait "$HOLDER_PID" 2>/dev/null

new_sandbox
fake_holder 999999999            # ~31 years, and a 30-digit one would overflow
dor ASK-987 '* `alpha987.sh`'
export KIPI_STUB_READY="ASK-987"
run_dispatch >/dev/null 2>&1
check "32g an absurd ceiling is capped, so the alert still fires" \
  "$(paged 'pick lock')" "1"
kill "$HOLDER_PID" 2>/dev/null; wait "$HOLDER_PID" 2>/dev/null

# --- 33. `--parallel N` alone is a burst flag with no burst (r6 f2) ---------
# `--parallel` with no value (r5) and `--burst 0` (r4) are both refused, for the
# stated reason that a founder who typed a burst-shaped flag got the SCHEDULER's
# behaviour under their own name. The one spelling that still parsed did exactly
# that: spent the daily counter, wrote the liveness beacon the beacon's own
# comment says a burst must never write (it masks a dead launchd job and fires a
# false RESUMED later), and paged. Assert the side effects, not the exit code.
new_sandbox
dor ASK-988 '* `q-system/.q-system/scripts/alpha988.sh`'
export KIPI_STUB_READY="ASK-988"
OUT="$(run_dispatch --parallel 2)"; RC=$?
sleep 1
check "33a --parallel with a value but no --burst is refused" "$RC" "2"
check "33b it dispatches nothing" "$(n_started)" "0"
check "33c it does not spend the daily counter" \
  "$(ls "$HOME/.config/kipi" | grep -c '^dispatch-count-' || true)" "0"
check "33d it does not write the liveness beacon" \
  "$(ls "$HOME/.config/kipi" | grep -c '^dispatch-lastbeat$' || true)" "0"
check "33e it does not page" "$(grep -c . "$PAGES" || true)" "0"
if printf '%s' "$OUT" | grep -q -- '--burst'; then
  ok "33f the refusal names the flag it needs"
else
  bad "33f the refusal names the flag it needs" "$OUT"
fi

# --- 34. the PARTIAL advice must be a fix the operator can follow (r6 f3) ----
# The line said "backtick every path there" for every shape that trips the
# guard. It trips on an already-backticked standalone span too, so the printed
# fix was already done and the operator had nothing to act on. The advice is now
# derived from the token: whatever spelling WOULD parse is the one it names.
new_sandbox
dor ASK-989 '* `q-system/.q-system/scripts/other989.sh` (extend)
* q-system/.q-system/scripts/plain989.sh'
export KIPI_STUB_READY="ASK-989"
OUT="$(run_dispatch --burst 1 --parallel 1)"
wait_for_ends 1
if printf '%s' "$OUT" | grep -q 'backtick `q-system/.q-system/scripts/plain989.sh`'; then
  ok "34a an UNbackticked path is told to be backticked, by name"
else
  bad "34a an UNbackticked path is told to be backticked, by name" "$OUT"
fi

# The r6 repro: the DoR bullet is verbatim `- `kipi-foo` (the new CLI
# entrypoint)` -- every path already backticked. Backticking is not the fix;
# giving it a path is, and `./kipi-foo` really does parse.
new_sandbox
: > "$SANDBOX/repo/kipi-foo"
dor ASK-990 '* `kipi-foo` (the new CLI entrypoint)'
export KIPI_STUB_READY="ASK-990"
OUT="$(run_dispatch --burst 1 --parallel 1)"
wait_for_ends 1
if printf '%s' "$OUT" | grep -q 'backtick'; then
  bad "34b an already-backticked span is not told to backtick itself" "$OUT"
else
  ok "34b an already-backticked span is not told to backtick itself"
fi
if printf '%s' "$OUT" | grep -q '`./kipi-foo`'; then
  ok "34c it names the spelling that would parse"
else
  bad "34c it names the spelling that would parse" "$OUT"
fi

# A citation is the third shape: backticked, dotted, and rejected for the line
# number. "Backtick it" is already done there too.
new_sandbox
dor ASK-991 '* `q-system/.q-system/scripts/cite991.sh:318`'
export KIPI_STUB_READY="ASK-991"
OUT="$(run_dispatch --burst 1 --parallel 1)"
wait_for_ends 1
if printf '%s' "$OUT" | grep -q 'without the' \
   && printf '%s' "$OUT" | grep -q 'cite991.sh'; then
  ok "34d a foo.sh:NN citation is told to drop the line number, not to backtick"
else
  bad "34d a foo.sh:NN citation is told to drop the line number, not to backtick" "$OUT"
fi

# --- 35. `./foo` and `foo` are ONE file (found by fixing 34c) ----------------
# Self-found while fixing r6 finding 3, and it is that fix that makes it matter:
# 34c now ADVISES operators to spell an extensionless file `./kipi-foo`, because
# that is the spelling the tokenizer takes. normalise() only collapsed
# absolute-vs-relative, so `./shared.sh` and the same file named absolutely were
# two different strings to an exact-match intersection -- and the advice was
# about to make the `./` spelling common. A fix that widens the hole it is
# adjacent to is worth one more case.
new_sandbox
mkdir -p "$SANDBOX/repo/q-system/.q-system/scripts"
dor ASK-995 '* `./q-system/.q-system/scripts/shared995.sh`'
dor ASK-996 "* \`$SANDBOX/repo/q-system/.q-system/scripts/shared995.sh\`"
export KIPI_STUB_READY="ASK-995 ASK-996"
OUT="$(run_dispatch --burst 2 --parallel 2)"
wait_for_ends 1
check "35a a ./-prefixed path and the same file named absolutely intersect" \
  "$(n_started)" "1"

# The control, because collapsing spellings is exactly where over-enforcement
# lands: two genuinely different files still share the board.
new_sandbox
dor ASK-997 '* `./q-system/.q-system/scripts/alpha997.sh`'
dor ASK-998 '* `./q-system/.q-system/scripts/beta998.sh`'
export KIPI_STUB_READY="ASK-997 ASK-998"
OUT="$(run_dispatch --burst 2 --parallel 2)"
wait_for_ends 2
check "35b two different ./-prefixed files still both dispatch" "$(n_started)" "2"

echo
printf '== %s passed, %s failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ] || exit 1
