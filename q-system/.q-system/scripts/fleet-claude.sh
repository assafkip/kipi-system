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

if [ "${KIPI_FLEET_API_KEYS:-1}" = "0" ]; then
  echo "fleet-claude: KIPI_FLEET_API_KEYS=0 -- this run bills the PLAN, not the API credit" >&2
  exec env -u ANTHROPIC_API_KEY "${KIPI_CLAUDE_BIN:-claude}" "$@"
fi

if [ ! -f "$HELPER" ]; then
  # Refuse rather than degrade: a missing helper means an un-metered run.
  echo "fleet-claude: $HELPER is missing; refusing to run on the plan instead" >&2
  exit 4
fi

exec python3 "$HELPER" exec --actor "${KIPI_AGENT:-unknown}" \
  ${_ticket_flags[@]+"${_ticket_flags[@]}"} -- "${KIPI_CLAUDE_BIN:-claude}" "$@"
