#!/usr/bin/env bash
# An exhausted account is the MACHINE's condition, not each issue's (ASK-873).
#
# WHAT IT PROVES
# --------------
# Run A (the outage). `claude` exits 0 having printed nothing but the real
# weekly-limit line, exactly as measured on 2026-08-15:
#   1. zero attempts are charged to the dispatched issue
#   2. the loop HALTS -- the next ready issue is never dispatched
#   3. exactly ONE alert is sent, and it names the condition and the count
#   4. the run exits non-zero, so launchd still sees a failed run (ASK-184)
#
# Run B (the negative fixture, and it is mandatory). An ordinary agent that
# exits 0, says something mundane and opens no PR must STILL be charged an
# attempt and must NOT halt the loop. The attempts cap is the runaway brake: a
# fix that quietly disables it trades eleven burned issues for an issue that
# retries forever.
#
# THE OUTAGE, MEASURED. The dispatcher marched the whole ready queue at ~31
# minutes per issue for six hours, charged four attempts to each of eleven
# issues and marked them TERMINAL. Verified 2026-08-16 for all eleven: no remote
# branch, local branch 0 commits ahead of main, worktree clean, no refusal
# sentinel. The harness worked; the agent produced literally nothing, because
# the account could not answer -- and the worker charged the ISSUE for it.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_SCRIPTS="$(cd "$SCRIPT_DIR/.." && pwd)"
WORKER="${KIPI_WORKER_UNDER_TEST:-$REPO_SCRIPTS/linear-worker.sh}"

PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); printf '  ok   %s\n' "$1"; }
bad() { FAIL=$((FAIL+1)); printf '  FAIL %s\n     %s\n' "$1" "${2:-}"; }

WORK="$(mktemp -d)"
trap 'kill "${SRV_PID:-}" 2>/dev/null; rm -rf "$WORK"' EXIT

# --- fixture Linear: three ready in-repo issues ------------------------------
# THREE, not one. "The loop halted" is only assertable if there was something
# after the halt for it to skip, and the count in the alert needs a queue to
# count. With a single-issue board both assertions are vacuous.
cat > "$WORK/fixture-server.py" <<'PY'
import json
from http.server import BaseHTTPRequestHandler, HTTPServer

def issue(ident):
    return {"id": ident, "identifier": ident, "title": "fixture " + ident,
            "description": "## Definition of Ready\nOutcome: x",
            "state": {"name": "backlog", "type": "backlog"},
            "project": {"name": "kipi-system"},
            "labels": {"nodes": [{"name": "owner:sana"}]}}

BOARD = [issue("ASK-811"), issue("ASK-812"), issue("ASK-813")]

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"])).decode()
        data = ({"teams": {"nodes": [{"id": "t"}]}} if "teams(" in body else
                {"issues": {"nodes": BOARD,
                            "pageInfo": {"hasNextPage": False, "endCursor": None}}})
        out = json.dumps({"data": data}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out))); self.end_headers()
        self.wfile.write(out)

srv = HTTPServer(("127.0.0.1", 0), H)
print(srv.server_port, flush=True)
srv.serve_forever()
PY
python3 "$WORK/fixture-server.py" > "$WORK/port" 2> "$WORK/server.err" &
SRV_PID=$!
for _ in $(seq 1 100); do PORT="$(cat "$WORK/port" 2>/dev/null)"; [ -n "${PORT:-}" ] && break; sleep 0.1; done
[ -n "${PORT:-}" ] || { echo "fixture server did not start"; exit 1; }

# --- shared stubs ------------------------------------------------------------
# No PRs exist in either world: the whole point is a run that produced nothing.
cat > "$WORK/gh" <<'SH'
#!/usr/bin/env bash
exit 0
SH
chmod +x "$WORK/gh"

printf '#!/usr/bin/env bash\nexit 0\n' > "$WORK/fake-reviewer.sh"
printf '#!/usr/bin/env bash\nexit 0\n' > "$WORK/fake-codex.sh"

# The alert is RECORDED, not stubbed away. "exactly one alert" is the assertion,
# and the only deterministic answer is a file the notify sink wrote.
make_notify() {  # make_notify <path>
  cat > "$1" <<'SH'
#!/usr/bin/env bash
printf 'NOTIFY %s\n' "$*" >> "${TEST_NOTIFY_LOG:-/dev/null}"
exit 0
SH
  chmod +x "$1"
}
make_notify "$WORK/recording-notify.sh"

# THE OBSERVED LINE, VERBATIM (ASK-869 makes the same demand, and this suite
# would be worthless without it). Copied from the heartbeat's log for
# 2026-08-15; not a pattern invented to match the detector.
LIMIT_LINE="You've hit your weekly limit - resets Aug 18 at 2pm (America/Los_Angeles)"

# --- a real git repo per run -------------------------------------------------
# One skeleton per run, never shared: run A leaves sana/ask-811 checked out in
# its own worktree and git refuses to check one branch out twice. The BASENAME
# is load-bearing -- the worker derives repo identity from the checkout's
# directory name and filters the board to the matching Linear project, so a
# skeleton called anything else picks nothing and every assertion goes vacuous.
make_skel() {  # make_skel <parent-dir> -> echoes the skeleton path
  local parent="$1" skel="$1/kipi-system"
  mkdir -p "$parent"
  git init --quiet --bare "$parent/origin.git"
  git init --quiet "$skel"
  git -C "$skel" config user.email t@t; git -C "$skel" config user.name t
  : > "$skel/seed"; git -C "$skel" add seed; git -C "$skel" commit --quiet -m seed
  git -C "$skel" remote add origin "$parent/origin.git"
  git -C "$skel" push --quiet -u origin HEAD:main 2>/dev/null
  printf '%s' "$skel"
}

# ============================================================================
# RUN A -- the outage
# ============================================================================
STUB_A="$WORK/stub-a"; mkdir -p "$STUB_A"
cp "$WORK/gh" "$STUB_A/gh"
# EXITS 0. That is the measured shape and it is the whole difficulty: the failure
# branch never ran, so the run reached the "exited 0 but opened no PR" bump as an
# ordinary silent agent and was charged for the machine's condition.
cat > "$STUB_A/claude" <<SH
#!/usr/bin/env bash
printf '%s\n' "$LIMIT_LINE"
exit 0
SH
chmod +x "$STUB_A/claude"

SKEL_A="$(make_skel "$WORK/run-a")"
STATE_A="$WORK/state-a"
NOTIFY_A="$WORK/notify-a.log"
# REDIRECTED TO A FILE, never captured with $( ): run_bounded backgrounds a
# watchdog whose orphaned `sleep` holds the inherited stdout for the full
# timeout, so a command substitution blocks long after the worker has exited.
PATH="$STUB_A:$PATH" \
   KIPI_SKEL="$SKEL_A" KIPI_STATE_DIR="$STATE_A" \
   KIPI_LINEAR_API_URL="http://127.0.0.1:$PORT/graphql" \
   KIPI_LINEAR_API_KEY="fixture-key-not-a-secret" \
   KIPI_PR_REVIEWER="bash $WORK/fake-reviewer.sh" \
   KIPI_CODEX_RUNNER="bash $WORK/fake-codex.sh" \
   KIPI_NOTIFY="$WORK/recording-notify.sh" \
   TEST_NOTIFY_LOG="$NOTIFY_A" \
   bash "$WORKER" --apply --limit 2 > "$WORK/run-a.out" 2>&1
RC_A=$?
OUT_A="$(cat "$WORK/run-a.out" 2>/dev/null)
$(cat "$STATE_A/linear-worker.log" 2>/dev/null)"
ATT_A="$STATE_A/linear-worker-attempts.json"

echo "== worker environmental halt (worker under test: $WORKER)"

# --- A0. POSITIVE SELF-TEST FIRST -------------------------------------------
# Cases A2 and A3 read ABSENCES, and a run that dispatched nothing satisfies
# them for free. Pin that ASK-811 really was dispatched before reading them.
if grep -q "start ASK-811" <<<"$OUT_A"; then
  ok "positive self-test: run A really dispatched ASK-811 (the absences below are real)"
else
  bad "positive self-test: run A dispatched ASK-811" \
      "no 'start ASK-811' line -- every assertion below would pass on a run that did nothing. Output: $(tr '\n' '|' <<<"$OUT_A" | cut -c1-500)"
fi

# --- A1. no attempt is charged ----------------------------------------------
# THE DEFECT, stated as a number. Four charges each against eleven healthy
# issues is what drove them to TERMINAL; the ledger is where that became
# permanent, so the ledger is what this reads.
if [ -f "$ATT_A" ] && python3 -c "
import json,sys
d=json.load(open('$ATT_A'))
sys.exit(0 if d.get('ASK-811',{}).get('count',0)>0 else 1)" 2>/dev/null; then
  bad "an unattempted issue is charged no attempt" \
      "THE DEFECT: ASK-811 has a nonzero attempt count for a failure that belongs to the machine: $(cat "$ATT_A")"
else
  ok "an unattempted issue is charged no attempt (the account was down, the issue was fine)"
fi

# --- A2. the loop halts ------------------------------------------------------
# --limit 2 means a healthy run reaches ASK-812. Reaching it here would mean the
# dispatcher marched into a known-dead environment, which cost six hours and
# eleven issues on 2026-08-15.
if grep -q "start ASK-812" <<<"$OUT_A"; then
  bad "the dispatcher halts instead of marching on" \
      "THE DEFECT: ASK-812 was dispatched into an environment already known to be dead"
else
  ok "the dispatcher HALTS: the next ready issue is never dispatched"
fi

# ...and the issues behind the halt are charged nothing either. An absence of
# dispatch is not the same fact as an absence of charge.
if [ -f "$ATT_A" ] && python3 -c "
import json,sys
d=json.load(open('$ATT_A'))
sys.exit(0 if any(d.get(i,{}).get('count',0) for i in ('ASK-812','ASK-813')) else 1)" 2>/dev/null; then
  bad "the issues behind the halt are charged nothing" \
      "an issue the run never reached has an attempt count: $(cat "$ATT_A")"
else
  ok "the issues behind the halt are charged nothing"
fi

# --- A3. exactly ONE alert ---------------------------------------------------
# One machine-wide condition is one ticket. Eleven identical pages is the
# alert-fatigue that teaches the reader to mute the channel.
N_ALERTS="$(grep -c '^NOTIFY ' "$NOTIFY_A" 2>/dev/null)" || true
if [ "${N_ALERTS:-0}" -eq 1 ]; then
  ok "exactly one alert is sent for the whole halted run"
else
  bad "exactly one alert is sent" \
      "got ${N_ALERTS:-0} alert(s): $(cat "$NOTIFY_A" 2>/dev/null | tr '\n' '|' | cut -c1-400)"
fi

# ...and it says WHAT and HOW MANY. An alert that pages without naming the
# condition sends the reader back to the log this exists to replace.
ALERT_A="$(cat "$NOTIFY_A" 2>/dev/null)"
if grep -qi 'weekly limit' <<<"$ALERT_A" && grep -qi 'not attempted' <<<"$ALERT_A"; then
  ok "the alert names the observed condition and the unattempted count"
else
  bad "the alert names the condition and the count" \
      "alert text: '${ALERT_A:-<empty>}'"
fi

# --- A4. the run does NOT report success to launchd --------------------------
# ASK-184 pinned this: a failed run reporting 0 blinds fleet-health-daily.py's
# launchd-failing detector to the job entirely. A halt is a failed run -- the
# dispatcher stopped early with ready work behind it.
if [ "$RC_A" -ne 0 ]; then
  ok "the halted run exits non-zero (rc=$RC_A), so launchd still sees a failure"
else
  bad "the halted run exits non-zero" \
      "THE DEFECT: rc=0 makes an outage byte-identical to a healthy run, and launchd-failing goes blind"
fi

# ============================================================================
# RUN B -- THE NEGATIVE FIXTURE (mandatory: the cap is a runaway brake)
# ============================================================================
STUB_B="$WORK/stub-b"; mkdir -p "$STUB_B"
cp "$WORK/gh" "$STUB_B/gh"
# ORDINARY SILENCE. Exits 0, opens no PR, and says something entirely mundane --
# the ASK-221 shape the attempts cap exists for. The output deliberately MENTIONS
# limits in prose, mid-sentence, because that is the false-halt this detector
# must not take: an agent working on this very issue writes exactly that.
cat > "$STUB_B/claude" <<'SH'
#!/usr/bin/env bash
printf 'Read the DoR. I considered whether we hit your weekly limit here and it is not that.\n'
printf 'No changes were needed.\n'
exit 0
SH
chmod +x "$STUB_B/claude"

SKEL_B="$(make_skel "$WORK/run-b")"
STATE_B="$WORK/state-b"
NOTIFY_B="$WORK/notify-b.log"
PATH="$STUB_B:$PATH" \
   KIPI_SKEL="$SKEL_B" KIPI_STATE_DIR="$STATE_B" \
   KIPI_LINEAR_API_URL="http://127.0.0.1:$PORT/graphql" \
   KIPI_LINEAR_API_KEY="fixture-key-not-a-secret" \
   KIPI_PR_REVIEWER="bash $WORK/fake-reviewer.sh" \
   KIPI_CODEX_RUNNER="bash $WORK/fake-codex.sh" \
   KIPI_NOTIFY="$WORK/recording-notify.sh" \
   TEST_NOTIFY_LOG="$NOTIFY_B" \
   bash "$WORKER" --apply --limit 2 > "$WORK/run-b.out" 2>&1
RC_B=$?
OUT_B="$(cat "$WORK/run-b.out" 2>/dev/null)
$(cat "$STATE_B/linear-worker.log" 2>/dev/null)"
ATT_B="$STATE_B/linear-worker-attempts.json"

if [ -f "$ATT_B" ] && python3 -c "
import json,sys
d=json.load(open('$ATT_B'))
sys.exit(0 if d.get('ASK-811',{}).get('count',0)==1 else 1)" 2>/dev/null; then
  ok "NEGATIVE FIXTURE: an ordinary exit-0-no-PR run is STILL charged an attempt"
else
  bad "NEGATIVE FIXTURE: an ordinary exit-0-no-PR run is still charged an attempt" \
      "THE REGRESSION: the fix disabled the runaway brake. Ledger: $(cat "$ATT_B" 2>/dev/null || echo '<no ledger written>')"
fi

# ...and prose that MENTIONS a limit mid-sentence does not halt the fleet. A
# substring match would stop every issue on one agent's choice of words.
if grep -q "start ASK-812" <<<"$OUT_B"; then
  ok "NEGATIVE FIXTURE: an ordinary failure does not halt the loop (ASK-812 still dispatched)"
else
  bad "NEGATIVE FIXTURE: an ordinary failure does not halt the loop" \
      "ASK-812 was never dispatched -- a mid-sentence mention of a limit stopped the whole queue"
fi

if [ "$RC_B" -eq 0 ] && ! grep -qi 'HALTED' <<<"$OUT_B"; then
  ok "NEGATIVE FIXTURE: an ordinary run exits 0 and reports no halt"
else
  bad "NEGATIVE FIXTURE: an ordinary run exits 0 and reports no halt" \
      "rc=$RC_B, and the run claimed a halt it did not have"
fi

if [ ! -s "$NOTIFY_B" ] || ! grep -qi 'runner itself is unavailable' "$NOTIFY_B" 2>/dev/null; then
  ok "NEGATIVE FIXTURE: no environmental alert is sent for an ordinary failure"
else
  bad "NEGATIVE FIXTURE: no environmental alert for an ordinary failure" \
      "an outage page fired on a healthy runner: $(cat "$NOTIFY_B")"
fi

# ============================================================================
# THE DETECTOR ITSELF -- sourced, never retyped
# ============================================================================
# A COPY of the pattern would prove the copy works, which is the one thing
# nobody needs to know. This sources the same file the worker sources, so a
# widened pattern is caught here.
. "$REPO_SCRIPTS/env-failure-lib.sh"

if is_environmental "$LIMIT_LINE"; then
  ok "the shared detector recognises the observed line"
else
  bad "the shared detector recognises the observed line" "is_environmental said no to the measured string"
fi

if is_environmental "I checked whether you've hit your weekly limit and you have not"; then
  bad "the detector is anchored, not a substring match" \
      "THE FALSE HALT: agent prose that MENTIONS a limit mid-sentence would stop the whole fleet"
else
  ok "the detector is anchored: a mid-sentence mention is not a halt"
fi

if is_environmental "the tests failed, see the log"; then
  bad "negative self-test: the detector rejects ordinary output" \
      "is_environmental matched a line with no environmental marker at all -- it is matching everything"
else
  ok "negative self-test: the detector rejects ordinary output (it can say no)"
fi

# ----------------------------------------------------------------------------
# THE SENTENCE-PREFIX FALSE HALT (PR #200 review, major)
# ----------------------------------------------------------------------------
# Anchoring at the START of a line is not enough, because every marker is also a
# legal opening for an ordinary English sentence. An agent that FIXES auth
# handling writes "Invalid API key handling is now covered." at the left margin
# of its summary, and a start-anchored detector reads its own success report as
# the machine being dead: the fleet halts, no attempt is charged, and the redrive
# re-runs it into the same false halt forever. The runner's utterance is the
# WHOLE line; agent prose continues past the marker into more sentence. Each case
# below is a real shape (the middle two were produced by the reviewer against the
# start-anchored version and all three halted).
while IFS='|' read -r want text; do
  [ -n "$want" ] || continue
  if is_environmental "$text"; then got=halt; else got=continue; fi
  if [ "$got" = "$want" ]; then
    ok "detector, whole-line: $want <- $text"
  else
    bad "detector, whole-line: expected $want, got $got" "input: $text"
  fi
done <<'CASES'
halt|You've hit your weekly limit - resets Aug 18 at 2pm (America/Los_Angeles)
halt|Invalid API key · Please run /login
halt|Invalid API key
halt|Credit balance is too low.
halt|usage limit reached
continue|Invalid API key handling is now covered by regression tests.
continue|Please run /login only when the session has expired.
continue|Credit balance is too low in the fixture, so the test asserts a halt.
continue|Invalid API key, expired token and logged-out CLI are all handled now.
CASES

# ----------------------------------------------------------------------------
# THE SEPARATOR-TAIL FALSE HALT (PR #200 review round 4, major)
# ----------------------------------------------------------------------------
# Ending the line at the marker was still not enough, because the tail exemption
# that let the machine's own line through -- "a separator, then anything" -- is
# also the commonest way English continues a clause. A dash after a noun phrase
# is a summary bullet, not machine formatting:
#   Invalid API key - fixed by adding a retry with backoff.
# All four lines below halted the fleet on the `.*` tail. The exemption exists
# for exactly two observed machine tails and must admit only those shapes: a
# `resets ...` clause, or a SECOND marker (`· Please run /login`). A tail that
# resumes with any other word is prose.
#
# The halt rows are the negative self-test for that narrowing: tighten the tail
# past the observed machine lines and they go red here rather than silently
# turning the detector off.
while IFS='|' read -r want text; do
  [ -n "$want" ] || continue
  if is_environmental "$text"; then got=halt; else got=continue; fi
  if [ "$got" = "$want" ]; then
    ok "detector, separator tail: $want <- $text"
  else
    bad "detector, separator tail: expected $want, got $got" "input: $text"
  fi
done <<'CASES'
continue|Invalid API key - fixed by adding a retry with backoff.
continue|usage limit reached - added a regression test for the reset path.
continue|Please run /login - documented in the runbook.
continue|Credit balance is too low - the top-up flow now handles it.
halt|You've hit your weekly limit - resets Aug 18 at 2pm (America/Los_Angeles)
halt|You've hit your 5-hour limit - resets at 2pm
halt|Invalid API key · Please run /login
CASES

# The pipe is the field separator of the two tables above, so the pipe-tail case
# cannot live in one. It is the same defect: `|` is in the separator class, and
# an agent writing a table row would halt the fleet.
env_pipe_case="Credit balance is too low | see the fixture table in the test."
if is_environmental "$env_pipe_case"; then
  bad "detector, separator tail: expected continue, got halt" "input: $env_pipe_case"
else
  ok "detector, separator tail: continue <- $env_pipe_case"
fi

# ----------------------------------------------------------------------------
# THE QUOTED-MARKER FALSE HALT (PR #200 review round 2, major)
# ----------------------------------------------------------------------------
# Whole-LINE anchoring is still not enough, because an agent that is WORKING on
# auth quotes a marker on a line of its own -- in a fenced block, a diff, a test
# name, a bullet -- inside an otherwise ordinary multi-line report. Matching any
# ONE line of a long transcript reads that report as the machine being dead.
#
# The machine says its piece and stops: on 2026-08-15 `claude -p` printed the
# limit line and NOTHING else. An agent that produced a transcript is, by the
# existence of the transcript, a runner that ran. So the discriminator is the
# whole OUTPUT, not a line inside it: every non-blank line must be the machine's.
#
# Each case is a real shape. Case 1 is the reviewer's verbatim reproducer.
env_case() {  # env_case <halt|continue> <label> <payload>
  local want="$1" label="$2" text="$3" got
  if is_environmental "$text"; then got=halt; else got=continue; fi
  if [ "$got" = "$want" ]; then
    ok "detector, whole-output: $want <- $label"
  else
    bad "detector, whole-output: expected $want, got $got" \
        "$label -- payload: $(printf '%s' "$text" | tr '\n' '|' | cut -c1-300)"
  fi
}

env_case continue "a marker quoted in a fenced block inside an agent report" \
  "$(printf '%s\n' \
     'Implemented auth handling and added this regression fixture:' \
     '```text' \
     'Invalid API key' \
     '```' \
     'All tests pass.')"

env_case continue "a marker on its own line at the END of an agent report" \
  "$(printf '%s\n' \
     'Added the negative fixture for the auth path. The string under test is:' \
     'Invalid API key')"

env_case continue "a marker on its own line at the START of an agent report" \
  "$(printf '%s\n' \
     'usage limit reached' \
     'is the exact string the new fixture asserts on. 24 passed, 0 failed.')"

# ...and the machine's own message still halts when the CLI pads it with blank
# lines, which is formatting, not a second utterance.
env_case halt "the observed line surrounded by blank lines" \
  "$(printf '\n%s\n\n' "$LIMIT_LINE")"

# NEGATIVE SELF-TEST for the totality rule itself: a machine message that really
# is two marker lines is still a halt. Without this, "every line matches" could
# be silently narrowed to "exactly one line" and nothing here would notice.
env_case halt "a two-line machine message where BOTH lines are the machine's" \
  "$(printf '%s\n%s\n' "Invalid API key" "Please run /login")"

# environmental_reason must recognise exactly what is_environmental recognises.
# Two patterns drifting apart means a real outage halts with an EMPTY reason, so
# the Linear note and the page say nothing about why the fleet stopped.
if [ -n "$(environmental_reason "$LIMIT_LINE")" ]; then
  ok "environmental_reason returns the line the detector matched"
else
  bad "environmental_reason returns the line the detector matched" \
      "is_environmental says yes but environmental_reason returned empty -- the two patterns have drifted"
fi

# ============================================================================
# RUN C -- A CONCURRENT WORKER'S OUTPUT IN THE SHARED LOG (PR #200 review r3)
# ============================================================================
# Concurrent workers are SUPPORTED here (test-linear-worker-parallel.sh, the
# per-worktree claim lock). They all append to one $LOG. The classifier used to
# read THIS run's output as a byte slice of that shared file, so any line another
# worker appended inside the window landed in the slice.
#
# That breaks the detector in the direction that costs money. is_environmental
# requires EVERY non-blank line to be the machine's, so one foreign "ok ASK-999"
# in the slice turns a real outage into ordinary output: no halt, and the issue
# is charged an attempt for the machine's condition -- the exact ASK-873 defect,
# re-entered through the log instead of through the ledger.
#
# The stub below is the other worker: it appends one ordinary line straight to
# the shared log, then speaks the measured limit line as its own output.
STUB_C="$WORK/stub-c"; mkdir -p "$STUB_C"
cp "$WORK/gh" "$STUB_C/gh"
cat > "$STUB_C/claude" <<SH
#!/usr/bin/env bash
printf 'ok ASK-999 (a concurrent worker, mid-dispatch, writing to the shared log)\n' \\
  >> "\$KIPI_STATE_DIR/linear-worker.log"
printf '%s\n' "$LIMIT_LINE"
exit 0
SH
chmod +x "$STUB_C/claude"

SKEL_C="$(make_skel "$WORK/run-c")"
STATE_C="$WORK/state-c"
NOTIFY_C="$WORK/notify-c.log"
PATH="$STUB_C:$PATH" \
   KIPI_SKEL="$SKEL_C" KIPI_STATE_DIR="$STATE_C" \
   KIPI_LINEAR_API_URL="http://127.0.0.1:$PORT/graphql" \
   KIPI_LINEAR_API_KEY="fixture-key-not-a-secret" \
   KIPI_PR_REVIEWER="bash $WORK/fake-reviewer.sh" \
   KIPI_CODEX_RUNNER="bash $WORK/fake-codex.sh" \
   KIPI_NOTIFY="$WORK/recording-notify.sh" \
   TEST_NOTIFY_LOG="$NOTIFY_C" \
   bash "$WORKER" --apply --limit 2 > "$WORK/run-c.out" 2>&1
RC_C=$?
OUT_C="$(cat "$WORK/run-c.out" 2>/dev/null)
$(cat "$STATE_C/linear-worker.log" 2>/dev/null)"
ATT_C="$STATE_C/linear-worker-attempts.json"

if grep -q "start ASK-811" <<<"$OUT_C"; then
  ok "positive self-test: run C dispatched ASK-811"
else
  bad "positive self-test: run C dispatched ASK-811" \
      "output: $(tr '\n' '|' <<<"$OUT_C" | cut -c1-400)"
fi

if [ -f "$ATT_C" ] && python3 -c "
import json,sys
d=json.load(open('$ATT_C'))
sys.exit(0 if d.get('ASK-811',{}).get('count',0)>0 else 1)" 2>/dev/null; then
  bad "a concurrent worker's log line does not hide the outage" \
      "THE DEFECT: another worker's line landed in this run's classifier slice, so a real outage read as ordinary output and ASK-811 was charged: $(cat "$ATT_C")"
else
  ok "a concurrent worker's log line does not hide the outage (no attempt charged)"
fi

if grep -q "start ASK-812" <<<"$OUT_C"; then
  bad "the dispatcher still halts despite the shared log" \
      "THE DEFECT: the outage was classified as ordinary output, so the loop marched on to ASK-812"
else
  ok "the dispatcher still halts despite a concurrent writer in the shared log"
fi

if [ "$RC_C" -ne 0 ]; then
  ok "the halted run still exits non-zero with a contaminated shared log (rc=$RC_C)"
else
  bad "the halted run exits non-zero with a contaminated shared log" \
      "rc=0 -- launchd sees a healthy run"
fi

# ============================================================================
# RUN D -- ONE RUN'S HALT MARKER MUST NOT SPEAK FOR ANOTHER (PR #200 r3)
# ============================================================================
# The halt marker lived at ONE path under $STATE_DIR and was never removed after
# it was read. Two supported concurrent runs therefore share it:
#
#   t0  run D-healthy starts, clears the shared path, dispatches a slow issue
#   t1  run D-outage starts, hits the outage, WRITES the shared path, exits 9
#   t2  run D-healthy finishes its loop, reads the marker D-outage left, and
#       reports a halt it never had -- a second page for one condition, and a
#       healthy run reporting failure to launchd.
#
# Each run gets its own skeleton so the only thing they share is the state dir,
# which is the resource under test; the shared-worktree collision is already
# owned by test-linear-worker-parallel.sh.
STATE_D="$WORK/state-d"          # SHARED between the two runs, on purpose.
NOTIFY_D_HEALTHY="$WORK/notify-d-healthy.log"
NOTIFY_D_OUTAGE="$WORK/notify-d-outage.log"

STUB_D_HEALTHY="$WORK/stub-d-healthy"; mkdir -p "$STUB_D_HEALTHY"
cp "$WORK/gh" "$STUB_D_HEALTHY/gh"
# Slow ON PURPOSE: the window this defect lives in is "one run is still working
# while another finishes", and a 10s dispatch makes that window deterministic
# rather than a race the suite would only lose sometimes.
cat > "$STUB_D_HEALTHY/claude" <<'SH'
#!/usr/bin/env bash
sleep 10
printf 'Read the DoR. No changes were needed.\n'
exit 0
SH
chmod +x "$STUB_D_HEALTHY/claude"

STUB_D_OUTAGE="$WORK/stub-d-outage"; mkdir -p "$STUB_D_OUTAGE"
cp "$WORK/gh" "$STUB_D_OUTAGE/gh"
cat > "$STUB_D_OUTAGE/claude" <<SH
#!/usr/bin/env bash
printf '%s\n' "$LIMIT_LINE"
exit 0
SH
chmod +x "$STUB_D_OUTAGE/claude"

SKEL_D_HEALTHY="$(make_skel "$WORK/run-d-healthy")"
SKEL_D_OUTAGE="$(make_skel "$WORK/run-d-outage")"

PATH="$STUB_D_HEALTHY:$PATH" \
   KIPI_SKEL="$SKEL_D_HEALTHY" KIPI_STATE_DIR="$STATE_D" \
   KIPI_LINEAR_API_URL="http://127.0.0.1:$PORT/graphql" \
   KIPI_LINEAR_API_KEY="fixture-key-not-a-secret" \
   KIPI_PR_REVIEWER="bash $WORK/fake-reviewer.sh" \
   KIPI_CODEX_RUNNER="bash $WORK/fake-codex.sh" \
   KIPI_NOTIFY="$WORK/recording-notify.sh" \
   TEST_NOTIFY_LOG="$NOTIFY_D_HEALTHY" \
   bash "$WORKER" --apply --limit 1 > "$WORK/run-d-healthy.out" 2>&1 &
D_HEALTHY_PID=$!
sleep 3
PATH="$STUB_D_OUTAGE:$PATH" \
   KIPI_SKEL="$SKEL_D_OUTAGE" KIPI_STATE_DIR="$STATE_D" \
   KIPI_LINEAR_API_URL="http://127.0.0.1:$PORT/graphql" \
   KIPI_LINEAR_API_KEY="fixture-key-not-a-secret" \
   KIPI_PR_REVIEWER="bash $WORK/fake-reviewer.sh" \
   KIPI_CODEX_RUNNER="bash $WORK/fake-codex.sh" \
   KIPI_NOTIFY="$WORK/recording-notify.sh" \
   TEST_NOTIFY_LOG="$NOTIFY_D_OUTAGE" \
   bash "$WORKER" --apply --limit 1 > "$WORK/run-d-outage.out" 2>&1
RC_D_OUTAGE=$?
wait "$D_HEALTHY_PID"; RC_D_HEALTHY=$?
OUT_D_HEALTHY="$(cat "$WORK/run-d-healthy.out" 2>/dev/null)"

# POSITIVE SELF-TEST: the outage run really did halt and really did write a
# marker. Without it the assertions below pass on a run that never halted.
if [ "$RC_D_OUTAGE" -eq 9 ] && grep -qi 'runner itself is unavailable' "$NOTIFY_D_OUTAGE" 2>/dev/null; then
  ok "positive self-test: the concurrent outage run halted and paged (rc=$RC_D_OUTAGE)"
else
  bad "positive self-test: the concurrent outage run halted and paged" \
      "rc=$RC_D_OUTAGE, alerts: $(cat "$NOTIFY_D_OUTAGE" 2>/dev/null | tr '\n' '|' | cut -c1-300)"
fi

if [ "$RC_D_HEALTHY" -eq 0 ]; then
  ok "a healthy concurrent run exits 0 (it does not inherit another run's halt)"
else
  bad "a healthy concurrent run exits 0" \
      "THE DEFECT: rc=$RC_D_HEALTHY -- the healthy run read the halt marker another run left at the shared path"
fi

if grep -qi 'HALTED' <<<"$OUT_D_HEALTHY"; then
  bad "a healthy concurrent run does not report another run's halt" \
      "THE DEFECT: it announced a halt it never had: $(grep -i HALTED <<<"$OUT_D_HEALTHY" | head -2)"
else
  ok "a healthy concurrent run does not report another run's halt"
fi

if [ -s "$NOTIFY_D_HEALTHY" ] && grep -qi 'runner itself is unavailable' "$NOTIFY_D_HEALTHY" 2>/dev/null; then
  bad "one machine condition pages once, not once per concurrent run" \
      "THE DEFECT: the healthy run sent a SECOND page for the other run's outage: $(cat "$NOTIFY_D_HEALTHY")"
else
  ok "one machine condition pages once, not once per concurrent run"
fi

# ============================================================================
# RUN E -- THE CODEX FALLBACK'S OWN OUTAGE (PR #200 review r3)
# ============================================================================
# When Sana refuses on a missing capability the issue is handed to Codex before
# parking. That second runner's output was never classified, so an exhausted
# Codex account -- a condition of the MACHINE, identical for every issue -- read
# as "Codex left no commit" and the issue was parked `blocked:capability`
# FOREVER: the label pulls it out of the picker and only a human takes it back.
#
# That is ASK-873's defect one runner deeper, and worse than the original,
# because a charged attempt decays and a park does not.
#
# It must NOT halt the whole dispatcher, and that is the second assertion here.
# Sana is THE runner, so her outage makes every later dispatch waste; Codex is
# reached only on a capability refusal, so stopping the queue for it would trade
# a rare park for a fleet-wide stop -- the false-halt cost this file already
# spent two review rounds refusing to pay.
STUB_E="$WORK/stub-e"; mkdir -p "$STUB_E"
cp "$WORK/gh" "$STUB_E/gh"
cat > "$STUB_E/claude" <<'SH'
#!/usr/bin/env bash
printf '%s' "the harness refused the sensitive path .claude/settings.json" \
  > .sana-blocked-capability
printf 'Not equipped for this one; wrote the capability sentinel.\n'
exit 0
SH
chmod +x "$STUB_E/claude"

cat > "$WORK/quota-codex.sh" <<SH
#!/usr/bin/env bash
printf '%s\n' "$LIMIT_LINE"
exit 0
SH

SKEL_E="$(make_skel "$WORK/run-e")"
STATE_E="$WORK/state-e"
NOTIFY_E="$WORK/notify-e.log"
PATH="$STUB_E:$PATH" \
   KIPI_SKEL="$SKEL_E" KIPI_STATE_DIR="$STATE_E" \
   KIPI_LINEAR_API_URL="http://127.0.0.1:$PORT/graphql" \
   KIPI_LINEAR_API_KEY="fixture-key-not-a-secret" \
   KIPI_PR_REVIEWER="bash $WORK/fake-reviewer.sh" \
   KIPI_CODEX_RUNNER="bash $WORK/quota-codex.sh" \
   KIPI_NOTIFY="$WORK/recording-notify.sh" \
   TEST_NOTIFY_LOG="$NOTIFY_E" \
   bash "$WORKER" --apply --limit 2 > "$WORK/run-e.out" 2>&1
RC_E=$?
OUT_E="$(cat "$WORK/run-e.out" 2>/dev/null)
$(cat "$STATE_E/linear-worker.log" 2>/dev/null)"
ATT_E="$STATE_E/linear-worker-attempts.json"

if grep -q "handing to the Codex runner" <<<"$OUT_E"; then
  ok "positive self-test: run E reached the Codex fallback"
else
  bad "positive self-test: run E reached the Codex fallback" \
      "the capability sentinel path never ran, so every assertion below is vacuous: $(tr '\n' '|' <<<"$OUT_E" | cut -c1-500)"
fi

if grep -qi 'second runner is unavailable' <<<"$OUT_E"; then
  ok "an exhausted Codex is named as the machine's condition, not the issue's"
else
  bad "an exhausted Codex is named as the machine's condition" \
      "THE DEFECT: the Codex outage was not classified at all: $(grep -i codex <<<"$OUT_E" | tr '\n' '|' | cut -c1-400)"
fi

if grep -qi 'Codex is ALSO not equipped\|Codex left no commit' <<<"$OUT_E"; then
  bad "an exhausted Codex does not park the issue as blocked:capability" \
      "THE DEFECT: a machine outage was recorded as a permanent capability block -- the picker never offers the issue again"
else
  ok "an exhausted Codex does not park the issue as blocked:capability"
fi

if [ -f "$ATT_E" ] && python3 -c "
import json,sys
d=json.load(open('$ATT_E'))
sys.exit(0 if d.get('ASK-811',{}).get('count',0)>0 else 1)" 2>/dev/null; then
  bad "a Codex outage charges the issue no attempt" \
      "ledger: $(cat "$ATT_E")"
else
  ok "a Codex outage charges the issue no attempt"
fi

# ...and it does NOT stop the queue. Sana is fine; only the rarely-reached
# fallback is down.
if grep -q "start ASK-812" <<<"$OUT_E"; then
  ok "a Codex outage does not halt the dispatcher (Sana is still healthy)"
else
  bad "a Codex outage does not halt the dispatcher" \
      "THE OVERREACH: the whole queue stopped because the SECOND runner was down"
fi

# ============================================================================
# RUN F -- NEGATIVE FIXTURE for run E: an honest Codex refusal STILL parks
# ============================================================================
# Without this, "never park on a Codex refusal" would be a silent way to pass
# run E, and the park -- which is the correct outcome when neither runner is
# equipped -- would be gone.
STUB_F="$WORK/stub-f"; mkdir -p "$STUB_F"
cp "$WORK/gh" "$STUB_F/gh"
cp "$STUB_E/claude" "$STUB_F/claude"

cat > "$WORK/refusing-codex.sh" <<'SH'
#!/usr/bin/env bash
printf '%s' "codex has no browser and the DoR needs one" > .codex-blocked-capability
printf 'I am also not equipped for this.\n'
exit 0
SH

SKEL_F="$(make_skel "$WORK/run-f")"
STATE_F="$WORK/state-f"
NOTIFY_F="$WORK/notify-f.log"
PATH="$STUB_F:$PATH" \
   KIPI_SKEL="$SKEL_F" KIPI_STATE_DIR="$STATE_F" \
   KIPI_LINEAR_API_URL="http://127.0.0.1:$PORT/graphql" \
   KIPI_LINEAR_API_KEY="fixture-key-not-a-secret" \
   KIPI_PR_REVIEWER="bash $WORK/fake-reviewer.sh" \
   KIPI_CODEX_RUNNER="bash $WORK/refusing-codex.sh" \
   KIPI_NOTIFY="$WORK/recording-notify.sh" \
   TEST_NOTIFY_LOG="$NOTIFY_F" \
   bash "$WORKER" --apply --limit 2 > "$WORK/run-f.out" 2>&1
OUT_F="$(cat "$WORK/run-f.out" 2>/dev/null)
$(cat "$STATE_F/linear-worker.log" 2>/dev/null)"

if grep -qi 'Codex is ALSO not equipped' <<<"$OUT_F"; then
  ok "NEGATIVE FIXTURE: an honest Codex capability refusal still parks the issue"
else
  bad "NEGATIVE FIXTURE: an honest Codex capability refusal still parks the issue" \
      "THE REGRESSION: the environmental branch swallowed a real refusal: $(grep -i codex <<<"$OUT_F" | tr '\n' '|' | cut -c1-400)"
fi

if grep -qi 'second runner is unavailable' <<<"$OUT_F"; then
  bad "NEGATIVE FIXTURE: an honest refusal is not called an outage" \
      "a reasoned refusal was classified as a machine condition"
else
  ok "NEGATIVE FIXTURE: an honest refusal is not called an outage"
fi

# ============================================================================
# ONE MACHINE CONDITION, ONE PAGE -- ACROSS PROCESSES (PR #200 review round 5)
# ============================================================================
# Run A asserted "exactly one alert" WITHIN one process. That is the wrong unit.
# The condition being reported is a property of the MACHINE, and every dispatcher
# process on that machine meets it: two supported concurrent workers (the
# per-worktree claim lock and test-linear-worker-parallel.sh are what make them
# supported) each halt on the same exhausted account and each page, so one outage
# arrives as two identical tickets at 3am and a human diffs them to find they are
# the same fact. The 15-minute launchd tick is the same defect on the time axis:
# a six-hour outage was twenty-four halted runs, so "one alert per run" is
# twenty-four pages for one condition -- the cry-wolf shape founder-notifications.md
# names, and the one that teaches the reader to mute the channel.
#
# So the dedupe has to live where the condition lives: one shared claim in
# $STATE_DIR, which concurrent workers already share (that sharing is exactly what
# forced the halt marker and the run-output file to become per-pid in round 3).
# The claim is NOT per-pid for the same reason those two are.

# --- H. the primitive is atomic under real concurrency ----------------------
# Asserted on the primitive rather than only through the worker because "exactly
# one of N concurrent processes wins" is the whole claim, and eight racing
# subshells can assert it in milliseconds where eight racing workers could not be
# made deterministic. mkdir is the atomicity: it is a single syscall that either
# creates the directory or fails because it exists, with no read-then-write window
# for a second process to land in (a `[ -f ] && >` claim has exactly that window).
CLAIM_STATE="$WORK/claim-race"; mkdir -p "$CLAIM_STATE"
CLAIM_WINNERS="$WORK/claim-winners"; : > "$CLAIM_WINNERS"
CLAIM_PIDS=""
for _i in 1 2 3 4 5 6 7 8; do
  (
    . "$REPO_SCRIPTS/env-failure-lib.sh" 2>/dev/null || exit 0
    # A start barrier, so the eight actually overlap instead of running in file
    # order. Without it the first would finish before the second began and the
    # case would pass on a non-atomic claim too -- a test that cannot go red.
    # Bounded, because a barrier that can wait forever is a hung suite rather
    # than a failing one, and a suite that hangs reports nothing at all.
    _spins=0
    while [ ! -f "$WORK/claim-go" ] && [ "$_spins" -lt 2000000 ]; do _spins=$((_spins+1)); done
    if env_alert_claim "$CLAIM_STATE" 2>/dev/null; then printf 'win\n' >> "$CLAIM_WINNERS"; fi
  ) &
  CLAIM_PIDS="$CLAIM_PIDS $!"
done
: > "$WORK/claim-go"
# EACH PID EXPLICITLY, never a bare `wait`. The fixture HTTP server above is also
# a background child of this shell and it serves forever, so a bare `wait` never
# returns and the whole suite hangs at this line instead of reporting.
for _p in $CLAIM_PIDS; do wait "$_p" 2>/dev/null || true; done
N_WIN="$(grep -c '^win$' "$CLAIM_WINNERS" 2>/dev/null)" || true
if [ "${N_WIN:-0}" -eq 1 ]; then
  ok "the alert claim is atomic: exactly 1 of 8 concurrent processes may page"
else
  bad "the alert claim is atomic: exactly 1 of 8 concurrent processes may page" \
      "got ${N_WIN:-0} winner(s). 0 means no shared claim exists at all (every process pages); >1 means the claim has a read-then-write window and concurrent workers still double-page."
fi

# ...and a claim that can never be released is a permanent mute, which is a worse
# failure than the duplicate it prevents: the NEXT outage, weeks later, would page
# nobody. Released explicitly, so this can go red on its own.
if command -v env_alert_release >/dev/null 2>&1 || type env_alert_release >/dev/null 2>&1; then
  env_alert_release "$CLAIM_STATE" 2>/dev/null || true
  if env_alert_claim "$CLAIM_STATE" 2>/dev/null; then
    ok "a released claim can be taken again (the guard is not a permanent mute)"
    env_alert_release "$CLAIM_STATE" 2>/dev/null || true
  else
    bad "a released claim can be taken again" \
        "THE PERMANENT MUTE: once one outage pages, no later outage ever can"
  fi
else
  bad "a released claim can be taken again" "env_alert_release is not defined"
fi

# --- G. two dispatcher runs, one machine, one page --------------------------
# ONE skeleton and ONE $STATE_DIR across both runs, because that is the production
# shape: launchd runs the same worker against the same checkout every 15 minutes.
# Separate state dirs would make each run its own island and the assertion vacuous
# -- the thing under test is precisely what crosses the process boundary.
SKEL_G="$(make_skel "$WORK/run-g")"
STATE_G="$WORK/state-g"
NOTIFY_G="$WORK/notify-g.log"

run_g() {  # run_g <stub-dir> <out-file>
  PATH="$1:$PATH" \
     KIPI_SKEL="$SKEL_G" KIPI_STATE_DIR="$STATE_G" \
     KIPI_LINEAR_API_URL="http://127.0.0.1:$PORT/graphql" \
     KIPI_LINEAR_API_KEY="fixture-key-not-a-secret" \
     KIPI_PR_REVIEWER="bash $WORK/fake-reviewer.sh" \
     KIPI_CODEX_RUNNER="bash $WORK/fake-codex.sh" \
     KIPI_NOTIFY="$WORK/recording-notify.sh" \
     TEST_NOTIFY_LOG="$NOTIFY_G" \
     bash "$WORKER" --apply --limit 2 > "$2" 2>&1
}

# The outage stub is run A's, verbatim: same measured line, same exit 0.
STUB_G="$WORK/stub-g"; mkdir -p "$STUB_G"
cp "$WORK/gh" "$STUB_G/gh"; cp "$STUB_A/claude" "$STUB_G/claude"

run_g "$STUB_G" "$WORK/run-g1.out"; RC_G1=$?
run_g "$STUB_G" "$WORK/run-g2.out"; RC_G2=$?

# POSITIVE SELF-TEST FIRST. Both cases below read a COUNT, and a second run that
# never dispatched anything would hold the count at 1 for free -- passing the
# assertion while proving nothing about dedupe.
if grep -q "start ASK-811" "$WORK/run-g2.out" "$STATE_G/linear-worker.log" 2>/dev/null; then
  ok "positive self-test: the second run really did dispatch and halt again"
else
  bad "positive self-test: the second run really dispatched" \
      "the second run reached no issue, so the alert count below is 1 for the wrong reason: $(tr '\n' '|' < "$WORK/run-g2.out" | cut -c1-400)"
fi

N_G="$(grep -c 'runner itself is unavailable' "$NOTIFY_G" 2>/dev/null)" || true
if [ "${N_G:-0}" -eq 1 ]; then
  ok "two halted runs on one machine send ONE page, not one page each"
else
  bad "two halted runs on one machine send ONE page, not one page each" \
      "THE DEFECT: got ${N_G:-0} page(s) for one machine condition. At the 15-minute tick a six-hour outage is 24 of these; two concurrent workers double it again."
fi

# The suppression is of the PAGE, never of the halt. A run that stays quiet must
# still refuse to march into a dead environment and must still hand launchd a
# failure -- otherwise dedupe has silently bought back the ASK-184 blindness.
if [ "$RC_G2" -ne 0 ] && ! grep -q "start ASK-812" "$WORK/run-g2.out" 2>/dev/null; then
  ok "the un-paging run still halts and still exits non-zero (rc=$RC_G2)"
else
  bad "the un-paging run still halts and still exits non-zero" \
      "rc=$RC_G2, and ASK-812 dispatched=$(grep -c 'start ASK-812' "$WORK/run-g2.out" 2>/dev/null). Suppressing the page must not suppress the halt or the exit code."
fi

# --- G3/G4. the machine recovers, and the NEXT outage pages ------------------
# The re-arm is what keeps this a dedupe rather than a mute. There is no "the
# outage ended" event to subscribe to, so the release is the observation that
# stands in for one: a run that completed WITHOUT halting saw a working runner.
# That is founder-notifications.md's "alert on state change, once" -- the page
# fires on the healthy->down edge, and the edge re-arms on the way back up.
STUB_G3="$WORK/stub-g3"; mkdir -p "$STUB_G3"
cp "$WORK/gh" "$STUB_G3/gh"; cp "$STUB_B/claude" "$STUB_G3/claude"
run_g "$STUB_G3" "$WORK/run-g3.out"; RC_G3=$?

if [ "$RC_G3" -eq 0 ]; then
  ok "positive self-test: the recovery run completed healthy (rc=0), so it could release"
else
  bad "positive self-test: the recovery run completed healthy" \
      "rc=$RC_G3 -- it did not reach the release, so the re-arm case below cannot fail honestly"
fi

run_g "$STUB_G" "$WORK/run-g4.out"
N_G4="$(grep -c 'runner itself is unavailable' "$NOTIFY_G" 2>/dev/null)" || true
if [ "${N_G4:-0}" -eq 2 ]; then
  ok "after the runner recovers, the NEXT outage pages again (2 pages, 2 outages)"
else
  bad "after the runner recovers, the NEXT outage pages again" \
      "expected 2 total pages for 2 separate outages, got ${N_G4:-0}. 1 means the claim is never released and every future outage is silent -- a worse failure than the duplicate this fixes."
fi

echo
echo "  $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
