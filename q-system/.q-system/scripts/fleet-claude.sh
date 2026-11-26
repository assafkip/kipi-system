#!/usr/bin/env bash
# The drop-in a fleet call site uses in place of `env -u ANTHROPIC_API_KEY claude`
# (ASK-4311). Same arguments, same stdout bytes, billed to an Ultra Console
# credit instead of the founder's plan.
#
# WHY A SHELL SHIM AT ALL, when fleet_api_key.py could be called directly: the
# call sites are shell, and most of them build the `claude` invocation inside a
# quoted `bash -c` string (linear-worker.sh, pr-review-agent.sh). Replacing one
# token there is a safe edit; rewriting the quoting is not.
#
#   before:  env -u ANTHROPIC_API_KEY claude -p "$PROMPT" --model "$M"
#   after:   "$FLEET_CLAUDE" -p "$PROMPT" --model "$M"
#
# OFF SWITCH, DELIBERATELY LOUD. KIPI_FLEET_API_KEYS=0 goes back to billing the
# plan, and says so on stderr every call. A SILENT fallback is the bug this
# whole change exists to end: the run would succeed, the founder would pay, and
# nothing would say so. So the fallback exists (the founder may need it) and it
# is never quiet.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HELPER="$HERE/fleet_api_key.py"

# A critical ticket rides as this shim's own leading flags, never as env: env reached the model
# and its test runs, which then read the live focus gate (PR #874 rounds 3 and 4, PR #875
# round 1; rca-critical-ticket-routing-test-isolation-2026-11-24). Consumed here, before
# either branch, so neither branch hands them to claude.
_ticket_flags=()
while [ "$#" -ge 2 ]; do
  case "$1" in
    --kipi-ticket) _ticket_flags+=(--ticket "$2"); shift 2 ;;
    --kipi-focus-gate) _ticket_flags+=(--focus-gate "$2"); shift 2 ;;
    *) break ;;
  esac
done

# A --kipi-* flag anywhere else would reach the model CLI and the routing would be lost
# without a word (PR #875 round 2): refuse it.
for _a in "$@"; do
  case "$_a" in --kipi-*) echo "fleet-claude: $_a must lead the arguments; no run" >&2; exit 2 ;; esac
done

# THE PLAN IS THE DEFAULT (RULE-2026-11-26-PLAN45). Founder, 2026-11-26: "Move the fleet
# work to the claude account - Ensure it stops when usage gets to 45% of the weekly usage".
# Every call asks plan_usage_gate.py first, so a run that crosses 45% stops at its next
# `claude` launch. 3 = at or past the line, 4 = no reading; both stop, neither falls back
# to the key. KIPI_FLEET_API_KEYS=1 is the way back to the API key below.
if [ "${KIPI_FLEET_API_KEYS:-0}" = "0" ]; then
  # SILENT ON A RUN, ONE MACHINE LINE ON A STOP (PR #885 review round 1). Callers classify
  # this shim's 2>&1 with env-failure-lib.sh's is_environmental, which needs EVERY line to
  # be the machine's: a "run" line on every call hid real plan outages ("hit your 5-hour
  # limit") as ticket failures. A stop prints exactly one line, an ENV_MARKERS shape, so the
  # worker halts with no attempt charged. The gate's own detail goes to the gate log.
  PLAN_GATE_RC=0
  PLAN_GATE_LOG="${KIPI_PLAN_USAGE_LOG:-$HOME/.local/state/kipi/plan-usage-gate.log}"
  mkdir -p "$(dirname "$PLAN_GATE_LOG")" 2>/dev/null || true
  PLAN_GATE_LINE="$(python3 "$HERE/plan_usage_gate.py" 2>&1)" || PLAN_GATE_RC=$?
  printf '%s rc=%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$PLAN_GATE_RC" "$PLAN_GATE_LINE" >>"$PLAN_GATE_LOG" 2>/dev/null || true
  case "$PLAN_GATE_RC" in
    0) ;;
    3) echo "kipi plan gate: weekly stop line reached (RULE-2026-11-26-PLAN45)" >&2; exit 3 ;;
    *) echo "kipi plan gate: weekly usage unreadable (RULE-2026-11-26-PLAN45)" >&2; exit 4 ;;
  esac
  exec env -u ANTHROPIC_API_KEY "${KIPI_CLAUDE_BIN:-claude}" "$@"
fi

if [ ! -f "$HELPER" ]; then
  # Refuse rather than degrade: a missing helper means an un-metered run.
  echo "fleet-claude: $HELPER is missing; refusing to run on the plan instead" >&2
  exit 4
fi

exec python3 "$HELPER" exec --actor "${KIPI_AGENT:-unknown}" \
  ${_ticket_flags[@]+"${_ticket_flags[@]}"} -- "${KIPI_CLAUDE_BIN:-claude}" "$@"
