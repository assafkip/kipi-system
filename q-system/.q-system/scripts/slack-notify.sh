#!/bin/bash
# Send a Slack message via an Incoming Webhook. Reliable, reaches the phone, works
# headless (unlike osascript desktop notifications, which are permission-gated and
# silently dropped from a sandboxed process).
#
# Webhook URL is a SECRET -- never committed. Resolved from, in order:
#   1. $KIPI_SLACK_WEBHOOK
#   2. ~/.config/kipi/slack-webhook  (gitignored file, one line)
# EXIT CONTRACT (ASK-534). Exit 0 means DELIVERED and nothing else:
#   0  delivered (curl succeeded)
#   1  send attempted and FAILED (curl status + stderr reported)
#   3  no webhook configured -- nothing to send on (a setup state, not an error)
#   4  refused: fixture run (see the guard below)
# Callers that do not care still work unchanged (`|| true`); callers that need to
# know whether a human was actually reached can finally ask.
#
# Usage: slack-notify.sh "message text"
set -uo pipefail

MSG="${1:-}"
[ -n "$MSG" ] || exit 0

# Project label so the founder always knows which instance pinged. Resolved in order:
#   KIPI_INSTANCE_NAME (set by the fleet heartbeat = exact registry name)
#   -> git repo root basename -> cwd basename. Every message is prefixed "[label] ".
# KIPI_NOTIFY_LABEL first: a caller that KNOWS which project it is reporting on
# states it, instead of leaving this script to re-derive it from ambient state.
# ASK-604. The prefix and the message body were two independent derivations, so
# they disagreed: one message read "[qep_agent]" while its body named
# consulting's files, and another posted as "[/]". auto-commit.py builds its body
# from basename(CLAUDE_PROJECT_DIR) but invoked this script with NO cwd, so the
# git-toplevel fallback resolved against whatever directory the agent happened to
# be in. basename(".") and basename("/") are where "[/]" came from.
LABEL="${KIPI_NOTIFY_LABEL:-${KIPI_INSTANCE_NAME:-}}"
if [ -z "$LABEL" ]; then
  LABEL="$(basename "$(git rev-parse --show-toplevel 2>/dev/null || echo "$PWD")")"
fi
# A degenerate label is worse than no label: it looks like a real answer. Say so
# instead of prefixing "[/]" and letting the founder guess which instance pinged.
case "$LABEL" in
  ""|"/"|"."|"..") LABEL="unknown-project" ;;
esac
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
    exit 4
  fi
fi

HOOK="${KIPI_SLACK_WEBHOOK:-}"
if [ -z "$HOOK" ] && [ -f "$HOME/.config/kipi/slack-webhook" ]; then
  HOOK="$(tr -d '\n\r' < "$HOME/.config/kipi/slack-webhook")"
fi
if [ -z "$HOOK" ]; then
  # NOT AN ERROR, and NOT a delivery either. Distinct from 1 so a caller can tell
  # "nothing to send on" (a setup state, common on a fresh instance) from "the
  # send failed" (an operational problem). Deliberately NOT 0: exit 0 is the
  # promise that a human was reached, and this script must never make that
  # promise on behalf of a webhook that does not exist.
  exit 3
fi

PAYLOAD="$(python3 -c "import json,sys; print(json.dumps({'text': sys.argv[1]}))" "$MSG" 2>/dev/null)"
if [ -z "$PAYLOAD" ]; then
  printf 'slack-notify: could not build the JSON payload; message NOT sent: %s\n' "$MSG" >&2
  exit 1
fi

# THE SEND RESULT IS REPORTED, NOT SWALLOWED (ASK-534, sp-8f879dc5).
#
# This line used to end in `|| true` followed by an unconditional `exit 0`, so a
# dead webhook, an HTTP 404, an expired URL and no-network were all
# indistinguishable from a delivered message. This is the SINGLE sanctioned
# founder-alert channel (founder-notifications.md bans osascript), so that one
# `|| true` meant every autonomous-run alert in the fleet could stop arriving
# with no symptom anywhere. Delivery was last confirmed BY HAND on 2026-07-29;
# nothing in the system would have reported it otherwise.
#
# Callers were audited before this changed (ASK-534): every one either ignores
# the status (`|| true`, or an unchecked subprocess.run) or already WANTS it.
# kipi-dispatch.sh:197 is the latter -- its `else` branch says "page did NOT go
# out; leaving the marker unset so the next heartbeat retries it" and was DEAD
# CODE, unreachable while this script always exited 0. This arms it.
#
# fable-escalate.py built the same distinction at its own call site as a
# workaround (notify_attempted / notify_channel_configured / notify_delivered).
# That workaround stays correct and is left alone; it is now backed by a
# chokepoint that tells the truth instead of a caller guessing around one.
CURL_ERR="$(curl -fsS -X POST -H 'Content-type: application/json' \
                 --data "$PAYLOAD" "$HOOK" 2>&1 >/dev/null)"
CURL_RC=$?
if [ "$CURL_RC" -ne 0 ]; then
  # The message goes to stderr so an alert that failed to send is still readable
  # in the job log. A silently swallowed alert is the exact failure mode
  # founder-notifications.md exists to prevent.
  printf 'slack-notify: send FAILED (curl exit %s: %s). Message NOT delivered: %s\n' \
         "$CURL_RC" "${CURL_ERR:-no stderr}" "$MSG" >&2
  exit 1
fi
exit 0
