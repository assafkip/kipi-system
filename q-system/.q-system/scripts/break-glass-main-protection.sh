#!/usr/bin/env bash
# break-glass-main-protection.sh - the escape hatch for `enforce_admins: true` on main.
#
# WHY THIS EXISTS (ASK-798, 2026-08-14)
#
# main requires two checks: `validate` and `kipi/reviewer-approved`. The second is
# posted by a LOCAL script (pr-review-agent.sh), not a GitHub Action. With
# enforce_admins:true, nobody -- including an admin -- can merge past a required
# check. So if the reviewer's posting path is down, main is FROZEN for everyone,
# including the person trying to land the fix for whatever broke it.
#
# That was the known cost of flipping enforce_admins on. This script is the
# agreed break-glass: one command, reversible, loud, and logged.
#
# THE TRADE, stated plainly: before this flip the escape hatch was `--admin`,
# which is silent, always available, and indistinguishable from a normal merge.
# Now the escape hatch is turning a documented switch off, which leaves a row in
# a ledger and a message in Slack. Same capability, no longer invisible.
#
# USAGE
#   break-glass-main-protection.sh status
#   break-glass-main-protection.sh off "<reason>"    # open the hatch
#   break-glass-main-protection.sh on                # close it again
#
# AFTER USING `off`: merge what you must, then run `on` IMMEDIATELY. An open
# hatch protects nothing, and the whole point of ASK-798 was that a permanently
# available bypass is the same as no gate.

set -uo pipefail

REPO="${BREAK_GLASS_REPO:-assafkip/kipi-system}"
BRANCH="${BREAK_GLASS_BRANCH:-main}"
LEDGER="${BREAK_GLASS_LEDGER:-$HOME/.claude/audit/break-glass-main-protection.jsonl}"
NOTIFY="${KIPI_NOTIFY:-$(dirname "${BASH_SOURCE[0]}")/slack-notify.sh}"

API="repos/$REPO/branches/$BRANCH/protection/enforce_admins"

_now() { date -u +%Y-%m-%dT%H:%M:%SZ; }

_log() {
  # Never let bookkeeping change the outcome.
  local action="$1" reason="$2" result="$3"
  mkdir -p "$(dirname "$LEDGER")" 2>/dev/null || return 0
  printf '{"ts":"%s","action":"%s","repo":"%s","branch":"%s","actor":"%s","result":"%s","reason":%s}\n' \
    "$(_now)" "$action" "$REPO" "$BRANCH" "${USER:-unknown}" "$result" \
    "$(printf '%s' "$reason" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))' 2>/dev/null || echo '""')" \
    >> "$LEDGER" 2>/dev/null || true
}

_notify() {
  [ -x "$NOTIFY" ] || return 0
  "$NOTIFY" "$1" >/dev/null 2>&1 || true
}

# Read the AUTHORITATIVE sub-resource, not the protection roll-up. A roll-up is a
# summary; this endpoint is the setting itself.
_read_state() {
  gh api "$API" -q '.enabled' 2>/dev/null
}

cmd_status() {
  local s
  s="$(_read_state)"
  if [ -z "$s" ]; then
    echo "UNKNOWN: could not read $API (auth? repo? network?)" >&2
    return 2
  fi
  echo "enforce_admins on $REPO@$BRANCH = $s"
  if [ "$s" = "true" ]; then
    echo "  protection is ON. Admins are subject to required checks. This is the intended steady state."
  else
    echo "  protection is OFF -- the break-glass hatch is OPEN."
    echo "  Close it as soon as the emergency merge is done:  $0 on"
  fi
  return 0
}

cmd_off() {
  local reason="${1-}"
  if [ -z "$reason" ]; then
    echo "refusing: 'off' requires a reason, recorded in the ledger." >&2
    echo "usage: $0 off \"reviewer posting path is down, landing fix for X\"" >&2
    return 2
  fi
  local before after
  before="$(_read_state)"
  if [ "$before" = "false" ]; then
    echo "already OFF (hatch is open). Nothing to do."
    _log "off" "$reason" "noop-already-off"
    return 0
  fi
  if ! gh api -X DELETE "$API" >/dev/null 2>&1; then
    echo "FAILED to disable enforce_admins. Protection unchanged." >&2
    _log "off" "$reason" "api-failed"
    return 1
  fi
  after="$(_read_state)"
  if [ "$after" != "false" ]; then
    echo "API call returned success but the setting reads '$after'. NOT trusting the call." >&2
    _log "off" "$reason" "verify-failed:$after"
    return 1
  fi
  _log "off" "$reason" "ok"
  _notify "BREAK-GLASS OPEN: enforce_admins disabled on $REPO@$BRANCH by ${USER:-unknown}. Reason: $reason. Close it with: break-glass-main-protection.sh on"
  echo "enforce_admins = false. HATCH IS OPEN."
  echo "Merge what you must, then close it:  $0 on"
  return 0
}

cmd_on() {
  local before after
  before="$(_read_state)"
  if [ "$before" = "true" ]; then
    echo "already ON. Nothing to do."
    _log "on" "" "noop-already-on"
    return 0
  fi
  if ! gh api -X POST "$API" >/dev/null 2>&1; then
    echo "FAILED to enable enforce_admins. Protection is STILL OFF -- retry or fix by hand:" >&2
    echo "  gh api -X POST $API" >&2
    _log "on" "" "api-failed"
    return 1
  fi
  after="$(_read_state)"
  if [ "$after" != "true" ]; then
    echo "API call returned success but the setting reads '$after'. NOT trusting the call." >&2
    _log "on" "" "verify-failed:$after"
    return 1
  fi
  _log "on" "" "ok"
  _notify "Break-glass CLOSED: enforce_admins re-enabled on $REPO@$BRANCH by ${USER:-unknown}."
  echo "enforce_admins = true. Hatch closed."
  return 0
}

case "${1-}" in
  status) cmd_status ;;
  off)    shift; cmd_off "${1-}" ;;
  on)     cmd_on ;;
  *)
    echo "usage: $0 {status|off \"<reason>\"|on}" >&2
    echo "  status  read the authoritative setting"
    echo "  off     open the hatch (requires a reason; logged + Slack)"
    echo "  on      close the hatch"
    exit 2
    ;;
esac
