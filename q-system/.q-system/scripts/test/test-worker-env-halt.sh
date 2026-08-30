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

echo
echo "  $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
