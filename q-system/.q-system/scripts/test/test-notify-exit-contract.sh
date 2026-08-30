#!/bin/bash
# ASK-636: the fleet alert path must report whether the alert was FILED.
#
# WHAT THIS SUITE USED TO BE. It pinned the same contract against a Slack
# webhook (ASK-534 / sp-8f879dc5): the send line ended in `|| true` followed by
# an unconditional `exit 0`, so a dead webhook, an HTTP 404, an expired URL and
# no-network were all indistinguishable from a delivered message. On 2026-08-10
# the destination became a Linear ticket for Sana and the founder stopped being
# paged at all, so the webhook cases below are gone. The CONTRACT they defended
# is unchanged and is what this file still holds: exit 0 means the alert landed
# somewhere, and nothing else may claim it.
#
# WHY A REAL LOCAL SERVER AND NOT A STUBBED CLIENT. The original defect was that
# the script did not read its transport's status. A test that replaces the
# transport proves the stub works, not that the script reads the status of the
# thing it actually runs. So: a real HTTP server on loopback speaking GraphQL,
# and real POSTs against it.
#
# THE SPLIT, and it is load-bearing. slack-notify.sh REFUSES when
# KIPI_LINEAR_API_URL is loopback, because that is how a fixture run is
# identified. That guard makes it impossible to exercise the filing path
# through the shim. So the shim is tested for its GUARDS and its EXIT CODES,
# and alert-to-linear.py is driven DIRECTLY for the filing path, where a
# loopback URL means "talk to the fixture server" rather than "refuse".
# Testing only through the shim would leave every HTTP status unexercised,
# which is the exact hole ASK-534 was about.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NOTIFY="$HERE/../slack-notify.sh"
WRITER="$HERE/../alert-to-linear.py"
[ -f "$NOTIFY" ] || { echo "FAIL: slack-notify.sh not found at $NOTIFY"; exit 1; }
[ -f "$WRITER" ] || { echo "FAIL: alert-to-linear.py not found at $WRITER"; exit 1; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP" 2>/dev/null; [ -n "${SRV_PID:-}" ] && kill "$SRV_PID" 2>/dev/null' EXIT

PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); echo "PASS: $1"; }
bad()  { FAIL=$((FAIL+1)); echo "FAIL: $1"; }
check_rc() { # want, got, label
  if [ "$2" = "$1" ]; then ok "$3 (exit $2)"; else bad "$3 -- wanted exit $1, got $2"; fi
}

# A fake Linear. The path selects the behaviour so one server covers every case:
#   /ok       every query succeeds, issueCreate returns an issue
#   /errors   HTTP 200 carrying a GraphQL `errors` array (Linear's real shape
#             for an application-level failure, and the one a status-code-only
#             check reads as success)
#   /500      a hard HTTP failure
cat > "$TMP/srv.py" <<'PY'
import http.server, json, socketserver

class H(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or b"{}")
        q = body.get("query", "")
        if self.path == "/500":
            self.send_response(500); self.end_headers(); self.wfile.write(b"boom"); return
        if self.path == "/errors":
            out = {"errors": [{"message": "authentication failed"}]}
        elif "teams(filter" in q:
            out = {"data": {"teams": {"nodes": [{"id": "team-1", "key": "ASK"}]}}}
        elif "labels(first" in q:
            out = {"data": {"team": {"labels": {"nodes": [
                {"id": "lab-1", "name": "owner:sana"}]}}}}
        elif "issueCreate" in q:
            out = {"data": {"issueCreate": {"success": True, "issue": {
                "id": "iss-1", "identifier": "ASK-999",
                "url": "https://linear.app/fixture"}}}}
        else:
            out = {"data": {}}
        raw = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)
    def log_message(self, *a): pass

with socketserver.TCPServer(("127.0.0.1", 0), H) as s:
    print(s.server_address[1], flush=True)
    s.serve_forever()
PY
python3 "$TMP/srv.py" > "$TMP/port" 2>/dev/null &
SRV_PID=$!
for _ in $(seq 1 50); do [ -s "$TMP/port" ] && break; sleep 0.1; done
PORT="$(tr -d '[:space:]' < "$TMP/port")"
[ -n "$PORT" ] || { echo "FAIL: fixture server never reported a port"; exit 1; }

# Every case runs with HOME pointed at an empty dir, so neither
# ~/.config/kipi/linear-api-key nor the ~/.cache dedup state can leak in from
# the real machine. env -i also drops PYTEST_CURRENT_TEST, so the writer's
# pytest refusal is not what is being measured here.
mkdir -p "$TMP/home"
run()    { env -i PATH="$PATH" HOME="$TMP/home" "$@" bash "$NOTIFY" "test message" 2>"$TMP/err"; }

# write() drives alert-to-linear.py DIRECTLY, deliberately bypassing the shim's
# loopback refusal so the filing path can be exercised at all. That bypass is
# the only thing standing between this suite and a real ticket, so it is not
# left to the caller remembering to pass a loopback URL.
#
# fable-discipline-lint flagged this helper as an unstubbed outbound channel and
# it was RIGHT to: the reasoning "every call site happens to pass 127.0.0.1" is
# the same reasoning that produced ASK-635 an hour earlier, and it holds only
# until someone adds a case without one. So the invariant is asserted here
# instead of assumed. A call with a missing or non-loopback URL aborts the whole
# suite rather than filing.
# fable-discipline-lint-skip -- the guard below is the stub the lint asks for
write() {
  local url=""
  for kv in "$@"; do
    case "$kv" in KIPI_LINEAR_API_URL=*) url="${kv#KIPI_LINEAR_API_URL=}" ;; esac
  done
  case "$url" in
    http://127.0.0.1:*|http://localhost:*) : ;;
    *) echo "ABORT: write() called with a non-loopback Linear URL (${url:-unset}). \
This suite must never be able to file a real ticket."; exit 1 ;;
  esac
  env -i PATH="$PATH" HOME="$TMP/home" "$@" python3 "$WRITER" "test message" 2>"$TMP/err"
}

# === the shim: guards and exit codes =========================================

# --- 1. no Linear key -> 3, distinct from both filed and failed ---------------
run KIPI_LINEAR_API_KEY=
check_rc 3 "$?" "no Linear key configured exits 3"

# --- 2. fixture run -> 4, and the guard fires even with a key present ---------
run KIPI_LINEAR_API_KEY=stub KIPI_LINEAR_API_URL="http://127.0.0.1:9/graphql"
rc=$?
check_rc 4 "$rc" "fixture run is refused"
grep -q "REFUSED" "$TMP/err" || bad "fixture refusal did not say REFUSED on stderr"

# --- 3. the capture hatch -> 0, and NOTHING is filed --------------------------
# This is the seam the guard suite needs. It exists because switching this
# chokepoint's destination silently invalidated the old KIPI_SLACK_WEBHOOK stub
# and a test filed a real ticket (ASK-635).
run KIPI_LINEAR_API_KEY=stub KIPI_ALERT_CAPTURE="$TMP/captured.txt"
check_rc 0 "$?" "a captured alert exits 0"
grep -q "test message" "$TMP/captured.txt" 2>/dev/null \
  && ok "the captured alert text reached the capture file" \
  || bad "capture file did not receive the message"
grep -q "CAPTURED" "$TMP/err" \
  && ok "capture announces itself on stderr, never passing as a real delivery" \
  || bad "capture was silent, so a job log could mistake it for a filed ticket"

# --- 4. an unwritable capture path is a FAILURE, not a silent pass ------------
run KIPI_LINEAR_API_KEY=stub KIPI_ALERT_CAPTURE="$TMP/nope/deep/x.txt"
check_rc 1 "$?" "an unwritable capture path is a failure"

# === the writer: real HTTP against a real server =============================

# --- 5. filed -> 0 ------------------------------------------------------------
write KIPI_LINEAR_API_KEY=stub KIPI_LINEAR_API_URL="http://127.0.0.1:$PORT/ok"
rc=$?
check_rc 0 "$rc" "a successful issueCreate is a filed alert"

# --- 6. THE REGRESSION SHAPE. Linear answers HTTP 200 with an `errors` array on
#        an application failure. A status-code-only check calls that success.
write KIPI_LINEAR_API_KEY=stub KIPI_LINEAR_API_URL="http://127.0.0.1:$PORT/errors"
rc=$?
check_rc 1 "$rc" "HTTP 200 carrying a GraphQL errors array is a FAILURE"
grep -q "NOT filed" "$TMP/err" || bad "the errors array did not report 'NOT filed'"

# --- 7. hard HTTP failure -> 1 ------------------------------------------------
write KIPI_LINEAR_API_KEY=stub KIPI_LINEAR_API_URL="http://127.0.0.1:$PORT/500"
check_rc 1 "$?" "an HTTP 500 is a FAILURE"

# --- 8. unreachable Linear -> 1 -----------------------------------------------
write KIPI_LINEAR_API_KEY=stub KIPI_LINEAR_API_URL="http://127.0.0.1:1/graphql"
rc=$?
check_rc 1 "$rc" "an unreachable Linear is a FAILURE"
grep -q "NOT filed" "$TMP/err" || bad "unreachable host did not name the unfiled message"

# --- 9. the unfiled TEXT survives to stderr, so the alert is still readable ---
write KIPI_LINEAR_API_KEY=stub KIPI_LINEAR_API_URL="http://127.0.0.1:1/graphql"
grep -q "test message" "$TMP/err" \
  && ok "the unfiled message text is still readable in the job log" \
  || bad "the alert text was swallowed along with the failure"

# --- 10. NEGATIVE SELF-TEST. If the fixture server answered everything with a
#         success no matter what, cases 6-8 would pass while proving nothing.
#         Prove the /ok path and the /errors path actually differ.
write KIPI_LINEAR_API_KEY=stub KIPI_LINEAR_API_URL="http://127.0.0.1:$PORT/ok"
a=$?
write KIPI_LINEAR_API_KEY=stub KIPI_LINEAR_API_URL="http://127.0.0.1:$PORT/errors"
b=$?
[ "$a" != "$b" ] \
  && ok "negative self-test: the fixture server distinguishes success from failure" \
  || bad "fixture server returns the same result for both paths; cases 6-8 prove nothing"

echo
echo "passed=$PASS failed=$FAIL"
[ "$FAIL" -eq 0 ] || exit 1
exit 0
