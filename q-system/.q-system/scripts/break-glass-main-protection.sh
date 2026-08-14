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
# EXIT CODES (they mean different things and the difference matters)
#   0  did what you asked, fully audited
#   1  the GitHub API failed; protection is unchanged
#   2  REFUSED. Protection unchanged. `off` refuses when the audit ledger cannot
#      be written, or when no reason was given -- an override nobody can see is
#      the thing this switch exists to prevent, so it does not happen.
#   3  the state DID change, but an audit signal failed. Read the warnings: the
#      hatch may be open with nobody told. Announce it by hand.
#
# `off` writes its intent row BEFORE touching protection, so an unwritable ledger
# stops the override instead of being discovered once it is already open. `on` is
# deliberately NOT symmetric: bookkeeping never blocks CLOSING the hatch, because
# refusing to close would leave protection off, which is strictly worse.
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

# JSON string escaping in pure bash. python3 was doing this with a `|| echo '""'`
# fallback, so a missing interpreter silently DROPPED the reason -- and the reason
# is the audit. No external dependency, nothing to fall back from.
_json_str() {
  local s
  s="${1-}"
  s="${s//\\/\\\\}"
  s="${s//\"/\\\"}"
  s="${s//$'\n'/\\n}"
  s="${s//$'\r'/\\r}"
  s="${s//$'\t'/\\t}"
  printf '"%s"' "$s"
}

# Returns NON-ZERO when the row did not reach disk. It used to end in
# `|| true`, so bookkeeping "never changed the outcome" -- which read as
# prudence and meant the caller could not tell a written row from a lost one.
_log() {
  local action
  local reason
  local result
  action="$1"; reason="$2"; result="$3"
  mkdir -p "$(dirname "$LEDGER")" 2>/dev/null || return 1
  printf '{"ts":"%s","action":"%s","repo":"%s","branch":"%s","actor":"%s","result":"%s","reason":%s}\n' \
    "$(_now)" "$action" "$REPO" "$BRANCH" "${USER:-unknown}" "$result" \
    "$(_json_str "$reason")" \
    >> "$LEDGER" 2>/dev/null || return 1
  return 0
}

# Returns NON-ZERO when the alert did not send, including when the notifier is
# missing entirely. A missing notifier is not "nothing to do", it is "the alert
# will never arrive".
_notify() {
  [ -x "$NOTIFY" ] || return 1
  "$NOTIFY" "$1" >/dev/null 2>&1 || return 1
  return 0
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
  local before
  local after
  before="$(_read_state)"
  if [ "$before" = "false" ]; then
    echo "already OFF (hatch is open). Nothing to do."
    _log "off" "$reason" "noop-already-off" || true
    return 0
  fi

  # THE AUDIT ROW GOES FIRST, AND ITS FAILURE REFUSES THE OVERRIDE.
  #
  # This gate's entire justification is that the override is VISIBLE. Codex found
  # the hole: with the ledger unwritable AND the notifier failing, `off` disabled
  # protection and exited 0 -- no row, no Slack, no trace. That is the exact
  # property the hatch was built to guarantee, absent.
  #
  # Order is the fix, not just error handling. Writing the row AFTER the API call
  # means you discover the ledger is dead when protection is already off, and then
  # there is nothing useful to do about it. Writing an INTENT row first makes the
  # ledger's writability a precondition of the override: if it cannot be recorded,
  # it does not happen. Protection stays on and the operator gets a real error.
  #
  # A crash between the intent row and the outcome row leaves the intent row,
  # which still says someone tried. That is the direction to fail in.
  if ! _log "off-intent" "$reason" "about-to-disable"; then
    echo "REFUSING to open the hatch: the audit ledger could not be written." >&2
    echo "  ledger: $LEDGER" >&2
    echo "  An override nobody can see is the thing this switch exists to prevent." >&2
    echo "  Fix the ledger path (or set BREAK_GLASS_LEDGER to a writable file) and re-run." >&2
    echo "  Protection is UNCHANGED (enforce_admins is still $before)." >&2
    return 2
  fi

  if ! gh api -X DELETE "$API" >/dev/null 2>&1; then
    echo "FAILED to disable enforce_admins. Protection unchanged." >&2
    _log "off" "$reason" "api-failed" || true
    return 1
  fi
  after="$(_read_state)"
  if [ "$after" != "false" ]; then
    echo "API call returned success but the setting reads '$after'. NOT trusting the call." >&2
    _log "off" "$reason" "verify-failed:$after" || true
    return 1
  fi

  # Protection is now OFF. From here nothing may return 0 unless the trail is
  # complete, but nothing may hide the state change either -- the operator must
  # know the hatch is open even if the announcement failed.
  local audit_ok=0
  if ! _log "off" "$reason" "ok"; then
    echo "WARNING: the hatch is OPEN but its outcome row could not be written." >&2
    audit_ok=1
  fi
  if ! _notify "BREAK-GLASS OPEN: enforce_admins disabled on $REPO@$BRANCH by ${USER:-unknown}. Reason: $reason. Close it with: break-glass-main-protection.sh on"; then
    echo "WARNING: the hatch is OPEN but the Slack alert did NOT send." >&2
    echo "  Announce it by hand -- nobody has been told." >&2
    audit_ok=1
  fi

  echo "enforce_admins = false. HATCH IS OPEN."
  echo "Merge what you must, then close it:  $0 on"
  if [ "$audit_ok" -ne 0 ]; then
    echo "Exit 3: the hatch opened but at least one audit signal failed (see warnings above)." >&2
    return 3
  fi
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
  # DELIBERATELY ASYMMETRIC WITH `off`. Opening the hatch REFUSES when it cannot
  # be recorded, because an unrecorded override is the failure mode. Closing it
  # must never be blocked by bookkeeping: refusing to close would leave protection
  # OFF, which is strictly worse than closing it with an incomplete log. The safe
  # direction is always allowed to proceed; only the dangerous one has to earn it.
  local audit_ok=0
  _log "on" "" "ok" || { echo "WARNING: hatch closed but the ledger row was not written." >&2; audit_ok=1; }
  _notify "Break-glass CLOSED: enforce_admins re-enabled on $REPO@$BRANCH by ${USER:-unknown}." \
    || { echo "WARNING: hatch closed but the Slack alert did NOT send." >&2; audit_ok=1; }
  echo "enforce_admins = true. Hatch closed."
  [ "$audit_ok" -eq 0 ] || return 3
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
