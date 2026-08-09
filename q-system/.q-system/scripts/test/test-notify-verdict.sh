#!/bin/bash
# Paired test for slack-notify.sh's DELIVERY VERDICT (ASK-447, PR #134 round 5).
#
# The scar: this script exits 0 on every path by design, and its curl line ends
# in `|| true`, so a webhook pointing at an unreachable endpoint returned exit 0
# having sent nothing. Two Python callers read that exit code as delivery and
# recorded a page that never left the machine; the watchdog then committed the
# run and went silent for 13 scheduled runs.
#
# So the POST outcome is reported from the one place that knows it, and this
# file is what stops it from silently going back to "always 0 means fine".
# Every case below asserts a verdict that a broken notifier would get WRONG:
# the delivered case uses a local sink that really accepts the POST, and the
# failed case uses a port that really refuses it.
#
# No real Slack contact: every endpoint here is on 127.0.0.1.
#
# Point it at another copy with:
#   KIPI_NOTIFY_UNDER_TEST=/tmp/old.sh bash test-notify-verdict.sh
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NOTIFY="${KIPI_NOTIFY_UNDER_TEST:-$HERE/../slack-notify.sh}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"; [ -n "${SINK_PID:-}" ] && kill "$SINK_PID" 2>/dev/null' EXIT

FAILED=0
pass() { printf '  ok   %s\n' "$1"; }
fail() { printf '  FAIL %s\n     expected: %s\n     actual:   %s\n' "$1" "$2" "$3"; FAILED=1; }

# Run the notifier in a clean environment: a fake HOME so a real
# ~/.config/kipi/slack-webhook on this machine cannot leak into the test, and no
# inherited KIPI_* variables.
run_notify() {  # $1 = verdict file (or "" for none), $2 = message, rest = env
  local vfile="$1"; shift
  local msg="$1"; shift
  env -i PATH="$PATH" HOME="$TMP/home" \
      ${vfile:+KIPI_NOTIFY_VERDICT_FILE="$vfile"} "$@" \
      bash "$NOTIFY" "$msg" >"$TMP/out" 2>"$TMP/err"
  echo $?
}

verdict() { cat "$TMP/v" 2>/dev/null; }

mkdir -p "$TMP/home"
echo "== slack-notify.sh delivery verdict =="

# --- a webhook that is not configured at all ---------------------------------
rm -f "$TMP/v"
RC=$(run_notify "$TMP/v" "no webhook here")
V=$(verdict)
[ "$RC" = "0" ] || fail "not-configured still exits 0" "0" "$RC"
[ "$V" = "not-configured" ] && pass "no webhook -> not-configured" \
  || fail "no webhook -> not-configured" "not-configured" "$V"

# --- a webhook that is configured but unreachable (THE SCAR) -----------------
# Port 9 is discard; a connection there is refused, so curl cannot succeed.
rm -f "$TMP/v"
RC=$(run_notify "$TMP/v" "never sent" KIPI_SLACK_WEBHOOK="http://127.0.0.1:9/x")
V=$(verdict)
[ "$RC" = "0" ] || fail "unreachable webhook still exits 0" "0" "$RC"
case "$V" in
  send-failed\ rc=*) pass "unreachable webhook -> $V (NOT delivered)" ;;
  *) fail "unreachable webhook -> send-failed" "send-failed rc=<n>" "$V" ;;
esac

# --- a webhook that really accepts the POST ----------------------------------
# Without this case the whole verdict could be hardcoded to "never delivered"
# and every other assertion here would still pass.
python3 - "$TMP/port" <<'PY' &
import http.server, sys, threading
class H(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0) or 0))
        # /hook accepts; every other path answers 404, which is how a REVOKED
        # Slack webhook behaves -- a reachable server saying no.
        self.send_response(200 if self.path == "/hook" else 404)
        self.end_headers(); self.wfile.write(b"ok")
    def log_message(self, *a): pass
srv = http.server.HTTPServer(("127.0.0.1", 0), H)
open(sys.argv[1], "w").write(str(srv.server_address[1]))
srv.serve_forever()
PY
SINK_PID=$!
for _ in $(seq 1 50); do [ -s "$TMP/port" ] && break; sleep 0.1; done
PORT="$(cat "$TMP/port" 2>/dev/null)"
if [ -z "$PORT" ]; then
  fail "local sink started" "a port" "sink never came up"
else
  rm -f "$TMP/v"
  RC=$(run_notify "$TMP/v" "really sent" KIPI_SLACK_WEBHOOK="http://127.0.0.1:$PORT/hook")
  V=$(verdict)
  [ "$RC" = "0" ] || fail "delivered still exits 0" "0" "$RC"
  [ "$V" = "delivered" ] && pass "webhook accepts the POST -> delivered" \
    || fail "webhook accepts the POST -> delivered" "delivered" "$V"

  # --- an HTTP error from a live endpoint is NOT delivery --------------------
  # A revoked webhook answers 404/410, which is a reachable server saying no.
  rm -f "$TMP/v"
  RC=$(run_notify "$TMP/v" "revoked hook" KIPI_SLACK_WEBHOOK="http://127.0.0.1:$PORT/nope")
  V=$(verdict)
  case "$V" in
    send-failed\ rc=*) pass "HTTP error status -> $V (NOT delivered)" ;;
    *) fail "HTTP error status -> send-failed" "send-failed rc=<n>" "$V" ;;
  esac

  # --- the fixture guard refuses, and says so -------------------------------
  rm -f "$TMP/v"
  RC=$(run_notify "$TMP/v" "fixture run" \
       KIPI_SLACK_WEBHOOK="http://127.0.0.1:$PORT/hook" \
       KIPI_LINEAR_API_URL="http://127.0.0.1:8080/graphql")
  V=$(verdict)
  [ "$V" = "refused-fixture" ] && pass "fixture run -> refused-fixture (not delivered)" \
    || fail "fixture run -> refused-fixture" "refused-fixture" "$V"
fi

# --- an empty message ---------------------------------------------------------
rm -f "$TMP/v"
RC=$(run_notify "$TMP/v" "")
V=$(verdict)
[ "$V" = "empty-message" ] && pass "empty message -> empty-message" \
  || fail "empty message -> empty-message" "empty-message" "$V"

# --- callers that never opt in are untouched ---------------------------------
# 30+ call sites invoke this script without the variable. They must see exactly
# what they saw before: exit 0, nothing on stdout, no files written.
rm -rf "$TMP/clean"; mkdir -p "$TMP/clean"
RC=$(run_notify "" "no verdict requested" KIPI_SLACK_WEBHOOK="http://127.0.0.1:9/x")
OUT="$(cat "$TMP/out")"
[ "$RC" = "0" ] && [ -z "$OUT" ] && [ -z "$(ls -A "$TMP/clean")" ] \
  && pass "no KIPI_NOTIFY_VERDICT_FILE -> exit 0, silent stdout, nothing written" \
  || fail "no KIPI_NOTIFY_VERDICT_FILE -> unchanged" "rc 0, empty stdout" "rc $RC, stdout '$OUT'"

if [ "$FAILED" -eq 0 ]; then
  echo "PASS: slack-notify delivery verdict"
  exit 0
fi
echo "FAIL: slack-notify delivery verdict"
exit 1
