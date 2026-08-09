#!/bin/bash
# Send a Slack message via an Incoming Webhook. Reliable, reaches the phone, works
# headless (unlike osascript desktop notifications, which are permission-gated and
# silently dropped from a sandboxed process).
#
# Webhook URL is a SECRET -- never committed. Resolved from, in order:
#   1. $KIPI_SLACK_WEBHOOK
#   2. ~/.config/kipi/slack-webhook  (gitignored file, one line)
# No webhook configured -> silent no-op (exit 0), so callers never break.
#
# Usage: slack-notify.sh "message text"
#
# Delivery verdict (opt-in): set KIPI_NOTIFY_VERDICT_FILE=<path> and this script
# writes exactly one line there saying what happened. See _kipi_verdict below.
set -uo pipefail

# --- the delivery verdict, reported where it is KNOWN --------------------------
# SCAR (PR #134 review round 5, reproduced 2026-08-09). This script exits 0 on
# EVERY path by design -- "no webhook configured -> silent no-op, so callers
# never break" -- and line 105's `|| true` extends that to a curl that could not
# reach Slack at all. So the exit code cannot distinguish a delivered page from a
# swallowed one, and two callers read it as if it could: `send_ping` in
# launchd-health-check.py and `notify_cap` in fable-escalate.py. Measured with a
# webhook pointing at a refused port: curl failed, both callers recorded
# DELIVERED, the watchdog committed the run, and the next 13 scheduled runs were
# silent -- the founder's phone showing exactly what a clean fleet shows.
#
# The outcome of the POST is knowable in exactly one place, which is here. So it
# is reported from here instead of being re-inferred by each caller. This is the
# same single-writer move the state file already got: a caller cannot guess right
# about something it cannot see.
#
# Opt-in on purpose. 30+ call sites invoke this script; every one of them keeps
# byte-for-byte identical behaviour (exit 0, nothing on stdout) unless it sets
# KIPI_NOTIFY_VERDICT_FILE. Absence of the file is read as NOT delivered by the
# Python reader, so a caller running against an older copy of this script pays a
# duplicate ping and never a missed one.
#
# Verdicts: delivered | send-failed rc=<n> | not-configured | refused-fixture
#           | empty-message | payload-failed
_kipi_verdict() {
  [ -n "${KIPI_NOTIFY_VERDICT_FILE:-}" ] || return 0
  printf '%s\n' "$1" > "$KIPI_NOTIFY_VERDICT_FILE" 2>/dev/null || true
}

MSG="${1:-}"
[ -n "$MSG" ] || { _kipi_verdict empty-message; exit 0; }

# Project label so the founder always knows which instance pinged. Resolved in order:
#   KIPI_INSTANCE_NAME (set by the fleet heartbeat = exact registry name)
#   -> git repo root basename -> cwd basename. Every message is prefixed "[label] ".
LABEL="${KIPI_INSTANCE_NAME:-}"
if [ -z "$LABEL" ]; then
  LABEL="$(basename "$(git rev-parse --show-toplevel 2>/dev/null || echo "$PWD")")"
fi
MSG="[$LABEL] $MSG"

# --- fixture-run guard: a test must never be able to page a human -------------
# SCAR 2026-08-01. Three tests were found paging the founder's real Slack and
# were fixed by stubbing KIPI_NOTIFY per test (PR #54). While that PR sat open
# and unmerged, an agent ran test-worker-project-scope.sh from a worktree cut
# off main -- which carries no stub -- and the founder was paged again, live.
# Per-test stubbing has three structural holes: it only protects branches that
# carry it, only tests someone remembered to fix, and its paired lint only fires
# at write-time on the edited file. A test written tomorrow still pages.
# This is the one chokepoint that needs none of those things to be remembered.
#
# THE SIGNAL. Every test in this repo points the worker at a fixture Linear on
# loopback (KIPI_LINEAR_API_URL=http://127.0.0.1:$PORT/graphql); production
# always points at the real Linear API. That asymmetry is total in both
# directions, which is what makes it safe to key a refusal on. This script is
# invoked as `bash "$NOTIFY" "msg"` from the worker, so it INHERITS the
# variable -- verified 2026-08-01 by running the same `env VAR=... bash parent`
# shape the tests use and reading the variable from the grandchild.
#
# DELIBERATELY NOT A SIGNAL: KIPI_STATE_DIR under a temp dir. A production job
# may legitimately keep state in a temp path (macOS $TMPDIR is exactly that), so
# keying on it would suppress real pages. A guard that swallows a genuine alert
# is worse than the bug it fixes, so the guard keys only on the one signal that
# cannot be true in production.
#
# The refused text goes to stderr rather than being dropped: a silently
# swallowed alert is the precise failure mode founder-notifications.md exists
# to prevent, and a fixture run still needs its diagnostic to be readable.
# Two review findings on PR #58 shaped this function, and they point in OPPOSITE
# directions -- which is why both halves are asserted in the paired suite:
#
#   1. A `127.*` shell pattern also matches non-loopback HOSTNAMES beginning
#      "127.", so `127.example.com` would have been read as a fixture and its
#      alert SILENTLY SUPPRESSED. That is the same failure class this guard
#      rejects KIPI_STATE_DIR-under-temp for. The real invariant is the
#      127.0.0.0/8 block -- four NUMERIC octets in range -- not a string prefix.
#   2. The comparison was case-sensitive, so `LOCALHOST` reached the webhook
#      from a fixture run. DNS hostnames are case-insensitive, so that was a
#      genuine bypass, not a theoretical one.
#
# Lowercasing uses tr, not ${var,,}: /bin/bash on macOS is 3.2, where ${var,,}
# is a syntax error. `[[ =~ ]]` + BASH_REMATCH do exist in 3.2, and the regex
# must stay in an UNQUOTED variable -- quoting it makes 3.2 match it literally.
_kipi_loopback_host() {
  local h re
  h="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')"
  case "$h" in
    localhost|*.localhost|::1|0.0.0.0|0) return 0 ;;
  esac
  re='^127\.([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})$'
  if [[ "$h" =~ $re ]]; then
    [ "${BASH_REMATCH[1]}" -le 255 ] && [ "${BASH_REMATCH[2]}" -le 255 ] \
      && [ "${BASH_REMATCH[3]}" -le 255 ] && return 0
  fi
  return 1
}

if [ -n "${KIPI_LINEAR_API_URL:-}" ]; then
  _KHOST="${KIPI_LINEAR_API_URL#*://}"   # drop scheme
  _KHOST="${_KHOST%%/*}"                 # drop path
  _KHOST="${_KHOST##*@}"                 # drop userinfo
  case "$_KHOST" in
    \[*\]*) _KHOST="${_KHOST#\[}"; _KHOST="${_KHOST%%\]*}" ;;  # [::1]:8080 -> ::1
    *)      _KHOST="${_KHOST%%:*}" ;;                          # host:port  -> host
  esac
  if _kipi_loopback_host "$_KHOST"; then
    printf 'slack-notify: REFUSED to page a human -- fixture run (KIPI_LINEAR_API_URL host "%s" is loopback). Message NOT sent: %s\n' \
           "$_KHOST" "$MSG" >&2
    _kipi_verdict refused-fixture
    exit 0
  fi
fi

HOOK="${KIPI_SLACK_WEBHOOK:-}"
if [ -z "$HOOK" ] && [ -f "$HOME/.config/kipi/slack-webhook" ]; then
  HOOK="$(tr -d '\n\r' < "$HOME/.config/kipi/slack-webhook")"
fi
[ -n "$HOOK" ] || { _kipi_verdict not-configured; exit 0; }   # not configured -> silent

PAYLOAD="$(python3 -c "import json,sys; print(json.dumps({'text': sys.argv[1]}))" "$MSG" 2>/dev/null)"
[ -n "$PAYLOAD" ] || { _kipi_verdict payload-failed; exit 0; }

# `-f` makes curl fail on an HTTP error status, so a revoked or 404 webhook lands
# here as a nonzero rc rather than as a 200-shaped silence. The rc is recorded and
# then discarded: the exit code stays 0 so no existing caller breaks.
curl -fsS -X POST -H 'Content-type: application/json' --data "$PAYLOAD" "$HOOK" >/dev/null 2>&1
_CURL_RC=$?
if [ "$_CURL_RC" -eq 0 ]; then
  _kipi_verdict delivered
else
  _kipi_verdict "send-failed rc=$_CURL_RC"
fi
exit 0
