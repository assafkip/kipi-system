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
set -uo pipefail

MSG="${1:-}"
[ -n "$MSG" ] || exit 0

# Project label so the founder always knows which instance pinged. Resolved in order:
#   KIPI_INSTANCE_NAME (set by the fleet heartbeat = exact registry name)
#   -> git repo root basename -> cwd basename. Every message is prefixed "[label] ".
LABEL="${KIPI_INSTANCE_NAME:-}"
if [ -z "$LABEL" ]; then
  LABEL="$(basename "$(git rev-parse --show-toplevel 2>/dev/null || echo "$PWD")")"
fi
MSG="[$LABEL] $MSG"

HOOK="${KIPI_SLACK_WEBHOOK:-}"
if [ -z "$HOOK" ] && [ -f "$HOME/.config/kipi/slack-webhook" ]; then
  HOOK="$(tr -d '\n\r' < "$HOME/.config/kipi/slack-webhook")"
fi
[ -n "$HOOK" ] || exit 0   # not configured yet -> silent

PAYLOAD="$(python3 -c "import json,sys; print(json.dumps({'text': sys.argv[1]}))" "$MSG" 2>/dev/null)"
[ -n "$PAYLOAD" ] || exit 0
curl -fsS -X POST -H 'Content-type: application/json' --data "$PAYLOAD" "$HOOK" >/dev/null 2>&1 || true
exit 0
