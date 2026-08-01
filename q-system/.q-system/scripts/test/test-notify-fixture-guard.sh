#!/usr/bin/env bash
# Regression suite for slack-notify.sh's fixture-run guard.
#
# THE INVARIANT: a worker running against a FIXTURE Linear API must never be
# able to page a real human.
#
# SCAR 2026-08-01. Three tests were found paging the founder's real Slack and
# were fixed by stubbing KIPI_NOTIFY per test (PR #54). While that PR sat open
# and unmerged, an agent ran test-worker-project-scope.sh from a worktree cut
# off main -- which carries no stub -- and the founder was paged again, live,
# with "repo identity 'no-such-project-anywhere' matches no Linear project".
# Per-test stubbing only protects branches that carry it and tests someone
# remembered to fix. The guard under test here is the chokepoint that protects
# every test on every branch, including tests nobody has written yet.
#
# WHY THE ASSERTIONS RUN IN BOTH DIRECTIONS: a guard that refuses everything
# would pass a refusal-only suite while silently disabling every real founder
# alert -- strictly worse than the bug it fixes. So every loopback case is
# paired with a production case that must still SEND.
#
# THIS SUITE NEVER TOUCHES REAL SLACK. It exports KIPI_SLACK_WEBHOOK at its own
# loopback capture server before the first invocation, and slack-notify.sh
# checks that variable BEFORE ~/.config/kipi/slack-webhook, so the founder's
# real hook file is never read even on a machine where it exists.
#
# REF HATCH: KIPI_NOTIFY_UNDER_TEST points the suite at a different copy of
# slack-notify.sh, so the PRE-GUARD copy can be checked out from a git ref and
# watched to FAIL. A regression case added after its own fix has never been
# observed red, and an unobserved-red case is an assertion about nothing.
#
#   git show <pre-guard-ref>:q-system/.q-system/scripts/slack-notify.sh > /tmp/old.sh
#   KIPI_NOTIFY_UNDER_TEST=/tmp/old.sh bash test-notify-fixture-guard.sh
#
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NOTIFY="${KIPI_NOTIFY_UNDER_TEST:-$SCRIPT_DIR/../slack-notify.sh}"

PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); printf '  ok   %s\n' "$1"; }
bad() { FAIL=$((FAIL+1)); printf '  FAIL %s\n     %s\n' "$1" "${2:-}"; }

WORK="$(mktemp -d)"
trap 'kill "${CAP_PID:-}" 2>/dev/null; rm -rf "$WORK"' EXIT

# --- capture endpoint: stands in for the founder's Incoming Webhook ----------
# Its stdout/stderr go to FILES, never to the inherited ones. A long-lived child
# holding this suite's stderr open keeps the pipeline's write end open, so a
# caller doing `| tail` hangs forever after the script already exited.
cat > "$WORK/capture.py" <<'PY'
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
CAPTURE_FILE = os.environ["CAPTURE_FILE"]
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n).decode("utf-8", "replace")
        with open(CAPTURE_FILE, "a") as fh:
            fh.write(body.replace("\n", " ") + "\n")
        out = b"ok"
        self.send_response(200)
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)
srv = HTTPServer(("127.0.0.1", 0), H)
print(srv.server_port, flush=True)
srv.serve_forever()
PY

export CAPTURE_FILE="$WORK/captured.txt"
: > "$CAPTURE_FILE"
python3 "$WORK/capture.py" > "$WORK/port" 2> "$WORK/cap.err" &
CAP_PID=$!
for _ in $(seq 1 100); do
  PORT="$(cat "$WORK/port" 2>/dev/null)"; [ -n "${PORT:-}" ] && break; sleep 0.1
done
[ -n "${PORT:-}" ] || { echo "capture server did not start: $(cat "$WORK/cap.err" 2>/dev/null)"; exit 1; }
export KIPI_SLACK_WEBHOOK="http://127.0.0.1:$PORT/capture"

echo "== slack-notify.sh fixture guard (notify under test: $NOTIFY)"

# --- HARNESS SELF-TEST: prove the capture endpoint can register a hit --------
# Without this, every "0 captured" below is ambiguous between "the guard
# refused" and "the capture endpoint was broken the whole time". A check that
# cannot record a hit cannot prove a miss.
curl -fsS -X POST -H 'Content-type: application/json' \
     --data '{"text":"harness probe, not a real page"}' "$KIPI_SLACK_WEBHOOK" >/dev/null 2>&1
if [ "$(wc -l < "$CAPTURE_FILE" | tr -d ' ')" = "1" ]; then
  ok "harness self-test: capture endpoint records a hit (a later 0 means refusal, not a dead harness)"
else
  bad "harness self-test: capture endpoint records a hit" "probe was not captured -- every assertion below is inert"
  echo "  $PASS passed, $FAIL failed"; exit 1
fi

# send <env-assignment-or-empty> -> echoes "<captured-count>|<stderr>"
send() {
  : > "$CAPTURE_FILE"
  if [ -n "${1:-}" ]; then
    env "$1" bash "$NOTIFY" "guard suite probe" 2> "$WORK/err"
  else
    env -u KIPI_LINEAR_API_URL bash "$NOTIFY" "guard suite probe" 2> "$WORK/err"
  fi
  sleep 0.3
  printf '%s|%s' "$(wc -l < "$CAPTURE_FILE" | tr -d ' ')" "$(cat "$WORK/err")"
}

# --- direction 1: fixture API -> REFUSE, and say so on stderr ---------------
# Every form a loopback fixture server can take. test-worker-project-scope.sh
# and friends bind 127.0.0.1; the others are here so a future fixture that binds
# localhost or ::1 is covered before someone writes it.
for url in "http://127.0.0.1:54321/graphql" \
           "http://localhost:8080/graphql" \
           "http://[::1]:8080/graphql" \
           "http://0.0.0.0:9/graphql" \
           "http://127.0.0.53/graphql"; do
  R="$(send "KIPI_LINEAR_API_URL=$url")"
  N="${R%%|*}"; ERR="${R#*|}"
  if [ "$N" = "0" ]; then
    ok "refuses to page from a fixture run ($url)"
  else
    bad "refuses to page from a fixture run ($url)" "$N message(s) reached the webhook"
  fi
  # A refusal that says nothing is a silently dropped alert -- the exact failure
  # mode founder-notifications.md exists to prevent. The diagnostic must survive.
  case "$ERR" in
    *REFUSED*"guard suite probe"*) ok "refusal writes the unsent message to stderr ($url)" ;;
    *) bad "refusal writes the unsent message to stderr ($url)" "stderr was: [$ERR]" ;;
  esac
done

# --- direction 2: production API -> STILL SENDS -----------------------------
# The half that keeps this guard from becoming an outage. If these go red, the
# fleet has lost founder alerting entirely and nobody would be told.
for url in "https://api.linear.app/graphql" \
           "https://localhost.evil.example.com/graphql" \
           "https://1270.0.0.1/graphql"; do
  R="$(send "KIPI_LINEAR_API_URL=$url")"
  N="${R%%|*}"
  if [ "$N" = "1" ]; then
    ok "still pages from a production run ($url)"
  else
    bad "still pages from a production run ($url)" "expected 1 delivered message, got $N -- founder alerting is BROKEN"
  fi
done

# The common production shape: the variable is not set at all. A guard keyed on
# a missing variable would silence every launchd job on the fleet.
R="$(send "")"
if [ "${R%%|*}" = "1" ]; then
  ok "still pages when KIPI_LINEAR_API_URL is unset entirely (the launchd shape)"
else
  bad "still pages when KIPI_LINEAR_API_URL is unset entirely" "expected 1 delivered message, got ${R%%|*}"
fi

# --- NEGATIVE SELF-TEST -----------------------------------------------------
# Proves this suite can go red. Without it every assertion above is compatible
# with a notify script that never sends anything, and with a capture file that
# is never written. Stands in for the PRE-GUARD slack-notify.sh: a copy with no
# guard at all must be caught by the direction-1 assertion.
UNGUARDED="$WORK/unguarded-notify.sh"
cat > "$UNGUARDED" <<'SH'
#!/bin/bash
set -uo pipefail
MSG="${1:-}"; [ -n "$MSG" ] || exit 0
HOOK="${KIPI_SLACK_WEBHOOK:-}"; [ -n "$HOOK" ] || exit 0
PAYLOAD="$(python3 -c "import json,sys; print(json.dumps({'text': sys.argv[1]}))" "$MSG" 2>/dev/null)"
curl -fsS -X POST -H 'Content-type: application/json' --data "$PAYLOAD" "$HOOK" >/dev/null 2>&1 || true
exit 0
SH
: > "$CAPTURE_FILE"
env KIPI_LINEAR_API_URL="http://127.0.0.1:54321/graphql" bash "$UNGUARDED" "probe" 2>/dev/null
sleep 0.3
if [ "$(wc -l < "$CAPTURE_FILE" | tr -d ' ')" = "1" ]; then
  ok "negative self-test: an UNGUARDED notify does page from a fixture run, so direction-1 is a real check"
else
  bad "negative self-test" "an unguarded notify did not page either -- direction-1 passes for the wrong reason"
fi

echo
echo "  $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
