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

echo
echo "  $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
