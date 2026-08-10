#!/usr/bin/env bash
# Regression suite for slack-notify.sh's fixture-run guard.
#
# THE INVARIANT: a worker running against a FIXTURE Linear API must never be
# able to raise a real alert.
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
# SCAR 2026-08-10, and it is why this file's transport changed. The destination
# became a Linear ticket for Sana instead of a Slack message to the founder
# (ASK-636). This suite isolated itself by pointing KIPI_SLACK_WEBHOOK at a
# loopback capture server -- a stub aimed at a transport that no longer runs. It
# kept passing its own direction-1 assertions while its direction-2 cases filed
# a REAL ticket (ASK-635, canceled). Switching a chokepoint's destination
# silently invalidates every stub aimed at the old one, and the tests keep
# passing right up until they write to production.
#
# So the capture seam now belongs to the DESTINATION, not to this suite:
# KIPI_ALERT_CAPTURE is read inside alert-to-linear.py before anything else, so
# any runner that can set an env var is isolated, including runners nobody has
# written yet. That is the same reasoning that put the guard below in the shim
# rather than in each test.
#
# WHY THE ASSERTIONS RUN IN BOTH DIRECTIONS: a guard that refuses everything
# would pass a refusal-only suite while silently disabling every real alert --
# strictly worse than the bug it fixes. So every loopback case is paired with a
# production case that must still FILE.
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
WRITER="$SCRIPT_DIR/../alert-to-linear.py"

PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); printf '  ok   %s\n' "$1"; }
bad() { FAIL=$((FAIL+1)); printf '  FAIL %s\n     %s\n' "$1" "${2:-}"; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# --- the capture seam: stands in for a filed Linear ticket -------------------
# One appended line per alert that got through, which is what `wc -l` counts
# below. No server, no port, no background child: the previous HTTP capture
# server was the thing that went stale, and a file cannot drift from the
# transport because it IS the transport's own documented test seam.
export CAPTURE_FILE="$WORK/captured.txt"
export KIPI_ALERT_CAPTURE="$CAPTURE_FILE"
: > "$CAPTURE_FILE"

echo "== slack-notify.sh fixture guard (notify under test: $NOTIFY)"

# --- HARNESS SELF-TEST: prove the capture seam can register a hit ------------
# Without this, every "0 captured" below is ambiguous between "the guard
# refused" and "the capture seam was broken the whole time". A check that
# cannot record a hit cannot prove a miss.
# The loopback URL is a SECOND layer, not redundancy. KIPI_ALERT_CAPTURE alone
# is what isolates this call, and if the export were ever broken this one line
# would file a live ticket before the self-test below could notice -- which is
# precisely how ASK-635 happened. With a dead loopback URL, a broken capture
# seam degrades to a failed HTTP call instead of a real ticket. The writer
# returns on capture before it ever reads a URL, so this costs nothing when the
# seam works.
# fable-discipline-lint-skip -- KIPI_ALERT_CAPTURE + the loopback URL are the stub
env KIPI_LINEAR_API_URL="http://127.0.0.1:1/graphql" \
    python3 "$WRITER" "harness probe, not a real alert" >/dev/null 2>&1
if [ "$(wc -l < "$CAPTURE_FILE" | tr -d ' ')" = "1" ]; then
  ok "harness self-test: capture seam records a hit (a later 0 means refusal, not a dead harness)"
else
  bad "harness self-test: capture seam records a hit" "probe was not captured -- every assertion below is inert"
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
  printf '%s|%s' "$(wc -l < "$CAPTURE_FILE" | tr -d ' ')" "$(cat "$WORK/err")"
}

# --- direction 1: fixture API -> REFUSE, and say so on stderr ---------------
# Every form a loopback fixture server can take. test-worker-project-scope.sh
# and friends bind 127.0.0.1; the others are here so a future fixture that binds
# localhost or ::1 is covered before someone writes it.
#
# The UPPERCASE forms are a PR #58 review finding, not decoration: the host
# comparison used to be case-sensitive, so a fixture at LOCALHOST sent a real
# page. DNS hostnames are case-insensitive, so that was a live bypass.
for url in "http://127.0.0.1:54321/graphql" \
           "http://localhost:8080/graphql" \
           "http://LOCALHOST:8080/graphql" \
           "http://LocalHost:8080/graphql" \
           "http://[::1]:8080/graphql" \
           "http://0.0.0.0:9/graphql" \
           "http://127.0.0.53/graphql" \
           "http://127.255.255.255/graphql"; do
  R="$(send "KIPI_LINEAR_API_URL=$url")"
  N="${R%%|*}"; ERR="${R#*|}"
  if [ "$N" = "0" ]; then
    ok "refuses to alert from a fixture run ($url)"
  else
    bad "refuses to alert from a fixture run ($url)" "$N message(s) got through"
  fi
  # A refusal that says nothing is a silently dropped alert -- the exact failure
  # mode founder-notifications.md exists to prevent. The diagnostic must survive.
  case "$ERR" in
    *REFUSED*"guard suite probe"*) ok "refusal writes the unsent message to stderr ($url)" ;;
    *) bad "refusal writes the unsent message to stderr ($url)" "stderr was: [$ERR]" ;;
  esac
done

# --- direction 2: production API -> STILL FILES -----------------------------
# The half that keeps this guard from becoming an outage. If these go red, the
# fleet has lost alerting entirely and nobody would be told.
#
# 127.example.com is a PR #58 review finding. The old `127.*` shell pattern
# classified it as a fixture and SILENTLY SUPPRESSED its alert -- a real alert
# swallowed, the failure mode this guard exists to avoid becoming. Only four
# numeric octets in range are the 127.0.0.0/8 block; a string prefix is not.
#
# These reach alert-to-linear.py for real. They do not reach LINEAR for real,
# because KIPI_ALERT_CAPTURE is exported at the top of this file and the writer
# honors it before it looks at a key, a URL or a network. That is the fix for
# the ASK-635 incident, and it is asserted rather than assumed: the harness
# self-test above fails the suite if the seam is not working.
for url in "https://api.linear.app/graphql" \
           "https://127.example.com/graphql" \
           "https://127.EXAMPLE.COM/graphql" \
           "https://localhost.evil.example.com/graphql" \
           "https://1270.0.0.1/graphql" \
           "https://127.0.0.999/graphql"; do
  R="$(send "KIPI_LINEAR_API_URL=$url")"
  N="${R%%|*}"
  if [ "$N" = "1" ]; then
    ok "still alerts from a production run ($url)"
  else
    bad "still alerts from a production run ($url)" "expected 1 captured alert, got $N -- fleet alerting is BROKEN"
  fi
done

# The common production shape: the variable is not set at all. A guard keyed on
# a missing variable would silence every launchd job on the fleet.
R="$(send "")"
if [ "${R%%|*}" = "1" ]; then
  ok "still alerts when KIPI_LINEAR_API_URL is unset entirely (the launchd shape)"
else
  bad "still alerts when KIPI_LINEAR_API_URL is unset entirely" "expected 1 captured alert, got ${R%%|*}"
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
OUT="${KIPI_ALERT_CAPTURE:-}"; [ -n "$OUT" ] || exit 0
printf '%s\n' "$MSG" >> "$OUT"
exit 0
SH
: > "$CAPTURE_FILE"
env KIPI_LINEAR_API_URL="http://127.0.0.1:54321/graphql" bash "$UNGUARDED" "probe" 2>/dev/null
if [ "$(wc -l < "$CAPTURE_FILE" | tr -d ' ')" = "1" ]; then
  ok "negative self-test: an UNGUARDED notify does alert from a fixture run, so direction-1 is a real check"
else
  bad "negative self-test" "an unguarded notify did not alert either -- direction-1 passes for the wrong reason"
fi

echo
echo "  $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
