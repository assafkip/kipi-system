#!/bin/bash
# ASK-534 / sp-8f879dc5: slack-notify.sh must report whether the message was sent.
#
# THE DEFECT. The send line ended in `|| true` followed by an unconditional
# `exit 0`, so a dead webhook, an HTTP 404, an expired URL and no-network were
# all indistinguishable from a delivered message. This is the SINGLE sanctioned
# founder-alert channel (founder-notifications.md bans osascript), so that one
# `|| true` meant every autonomous-run alert in the fleet could stop arriving
# with no symptom anywhere. Delivery was last confirmed BY HAND on 2026-07-29.
#
# WHY A REAL LOCAL SERVER AND NOT A STUBBED curl. The whole defect is that the
# script did not read curl's status. A test that replaces curl proves the test's
# stub works, not that the script reads the status of the thing it actually
# runs. So: a real HTTP server on loopback, one endpoint returning 200 and one
# returning 404, and curl -f run for real against both. The 404 case is the one
# that matters -- a webhook that Slack has revoked answers exactly that way, and
# it is the shape the old code called success.
#
# NOTE the deliberate asymmetry: the webhook URL points at loopback here, which
# is FINE. The fixture guard keys on KIPI_LINEAR_API_URL, a different variable.
# Case 2 below pins that the guard still fires, so this test cannot accidentally
# prove the guard away.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NOTIFY="$HERE/../slack-notify.sh"
[ -f "$NOTIFY" ] || { echo "FAIL: slack-notify.sh not found at $NOTIFY"; exit 1; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP" 2>/dev/null; [ -n "${SRV_PID:-}" ] && kill "$SRV_PID" 2>/dev/null' EXIT

PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); echo "PASS: $1"; }
bad()  { FAIL=$((FAIL+1)); echo "FAIL: $1"; }
check_rc() { # want, got, label
  if [ "$2" = "$1" ]; then ok "$3 (exit $2)"; else bad "$3 -- wanted exit $1, got $2"; fi
}

# A fake Slack: /ok returns 200, anything else 404. Bound to an ephemeral port so
# two runs of this suite cannot collide.
cat > "$TMP/srv.py" <<'PY'
import http.server, socketserver, threading, sys
class H(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0)); self.rfile.read(n)
        code = 200 if self.path == "/ok" else 404
        self.send_response(code); self.end_headers(); self.wfile.write(b"x")
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

# Every case runs with HOME pointed at an empty dir so the
# ~/.config/kipi/slack-webhook fallback cannot resolve and leak a real webhook.
mkdir -p "$TMP/home"
run() { env -i PATH="$PATH" HOME="$TMP/home" "$@" bash "$NOTIFY" "test message" 2>"$TMP/err"; }

# --- 1. no webhook configured -> 3, distinct from both delivered and failed ---
run KIPI_SLACK_WEBHOOK=
check_rc 3 "$?" "no webhook configured exits 3"

# --- 2. fixture run -> 4, and the guard still fires with a webhook present ----
run KIPI_SLACK_WEBHOOK="http://127.0.0.1:$PORT/ok" KIPI_LINEAR_API_URL="http://127.0.0.1:9/graphql"
rc=$?
check_rc 4 "$rc" "fixture run is refused"
grep -q "REFUSED" "$TMP/err" || bad "fixture refusal did not say REFUSED on stderr"

# --- 3. delivered -> 0 --------------------------------------------------------
run KIPI_SLACK_WEBHOOK="http://127.0.0.1:$PORT/ok"
check_rc 0 "$?" "a 200 from the webhook is a delivery"

# --- 4. HTTP 404 -> 1. THE REGRESSION. A revoked Slack webhook answers 404 and
#        the old code reported that as success.
run KIPI_SLACK_WEBHOOK="http://127.0.0.1:$PORT/revoked"
rc=$?
check_rc 1 "$rc" "an HTTP 404 (revoked webhook) is a FAILURE, not a delivery"
grep -q "send FAILED" "$TMP/err" || bad "404 did not report 'send FAILED' on stderr"

# --- 5. unreachable host -> 1 -------------------------------------------------
run KIPI_SLACK_WEBHOOK="http://127.0.0.1:1/definitely-dead"
rc=$?
check_rc 1 "$rc" "an unreachable webhook is a FAILURE"
grep -q "Message NOT delivered" "$TMP/err" || bad "unreachable host did not name the undelivered message"

# --- 6. the undelivered TEXT survives to stderr, so the alert is still readable
run KIPI_SLACK_WEBHOOK="http://127.0.0.1:1/definitely-dead"
grep -q "test message" "$TMP/err" \
  && ok "the undelivered message text is still readable in the job log" \
  || bad "the alert text was swallowed along with the failure"

echo
echo "passed=$PASS failed=$FAIL"
[ "$FAIL" -eq 0 ] || exit 1
exit 0
