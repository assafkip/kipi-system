#!/bin/bash
# THE FLEET ALERT PATH. Files a Linear ticket for Sana. Pages nobody.
#
# FOUNDER-DIRECTED 2026-08-10: "I dont want to see any of these. Any of the ones
# that need attention should go to Sana - not me." Offered one carve-out so the
# fable-escalation cap could still reach him, the answer was "the fable
# escalation should be gone. I gave it clear instructions." So there is no
# founder path in this script, no flag that re-opens one, and no webhook call.
#
# THE NAME IS NOW WRONG ON PURPOSE. It is still slack-notify.sh because ~30 call
# sites across six repos invoke it by that path, and a rename is a separate,
# larger change than switching the destination. Renaming it and updating every
# caller is captured in .prd-os/spillover.jsonl rather than bundled in here.
# Nothing in this file sends to Slack.
#
# WHY IT CHANGED. #general carried 100 messages between 09:35 and 14:06 PDT on
# 2026-08-10. 51 were auto-commit naming a file set that changed every turn; 35
# were one cole-gtm notice re-announcing a config state once per run, in
# duplicate pairs. The six that mattered -- four security reverts of unsanctioned
# .claude/ changes and a Notion job dead since 13:00 -- were unreadable
# underneath. The destination changed AND both flood sources were fixed at the
# emitter in the same change; routing a flood to Linear would only make it
# harder to clear, since a ticket has to be closed by hand.
#
# Repeats are deduped by alert-to-linear.py: one ticket per alert SHAPE, with a
# counter, not one ticket per firing.
#
# EXIT CONTRACT, unchanged from when this sent to Slack, so callers that read the
# status (kipi-dispatch.sh:197) keep working:
#   0  filed (ticket opened, or a repeat recorded on the open one)
#   1  attempted and FAILED (reason + the message text on stderr)
#   3  nothing to file on: no Linear API key configured (a setup state)
#   4  refused: fixture run
#
# Usage: slack-notify.sh "message text"
set -uo pipefail

MSG="${1:-}"
[ -n "$MSG" ] || exit 0

# Project label so a ticket always names which instance raised it. Resolved in
# order: KIPI_INSTANCE_NAME (set by the fleet heartbeat = exact registry name)
# -> git repo root basename -> cwd basename. Every message is prefixed "[label] ".
LABEL="${KIPI_INSTANCE_NAME:-}"
if [ -z "$LABEL" ]; then
  LABEL="$(basename "$(git rev-parse --show-toplevel 2>/dev/null || echo "$PWD")")"
fi
MSG="[$LABEL] $MSG"

# THE LABEL ABOVE IS NOT ROUTING, AND WAS BEING ASKED TO BE (ASK-839, PR #191
# review). alert-to-linear.py resolves the ticket's Linear project from a
# candidate list whose second rung is the repo PATH through
# instance-registry.json -- "the only rung that survives a worktree or a renamed
# directory", per its own docstring, which then said this script resolves that
# path. It did not. KIPI_ALERT_REPO_PATH was unset on every real alert, so rung 2
# was dead in production and only the basename above was left to route on.
#
# WHAT THAT COSTS. A checkout whose basename is not its board alias misses rung 3
# (basename vs registry `name`) and rung 4 (basename as a project name) and lands
# on rung 5 -- the checkout alert-to-linear.py itself lives in -- so the ticket is
# filed against kipi-system instead of the repo that raised the alert. Measured
# against the live registry 2026-08-15: 7 of 25 instances are that shape
# (`strategy`/`KTLYST_strategy`, `consulting`/`ASK Consulting`, `product`/
# `ktlyst`, `kipi-investigations`/`investigations`, ...), plus every worktree,
# which is how the fleet's own agents run.
#
# --git-common-dir, NOT --show-toplevel. From a worktree, --show-toplevel returns
# the WORKTREE, which equals no registry row, so rung 2 would still match nothing
# while looking supplied. --git-common-dir points at the MAIN checkout's .git in
# both a worktree and an ordinary clone, and the main checkout is what the
# registry stores. Same correction linear-claim.py needed at ASK-188.
#
# NOTHING IS INVENTED OUTSIDE A REPO. 22 of the 81 unset alert tickets were
# raised from a cwd of `/`. Exporting that would hand rung 2 a guaranteed miss and
# make the candidate list longer without making it truer; rung 5 already covers
# that case honestly. An explicit caller value is never overwritten -- rung 1 is
# "an explicit statement by the caller" and a derived value must not outrank it.
if [ -z "${KIPI_ALERT_REPO_PATH:-}" ]; then
  # --path-format is git 2.31+; without it --git-common-dir is relative to the
  # cwd in an ordinary clone (`.git`) and must be resolved before dirname.
  _KCOMMON="$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" \
    || _KCOMMON=""
  if [ -z "$_KCOMMON" ]; then
    _KCOMMON="$(git rev-parse --git-common-dir 2>/dev/null)" || _KCOMMON=""
    case "$_KCOMMON" in ""|/*) ;; *) _KCOMMON="$PWD/$_KCOMMON" ;; esac
  fi
  if [ -n "$_KCOMMON" ]; then
    _KREPO="$(cd "$(dirname "$_KCOMMON")" 2>/dev/null && pwd -P)" || _KREPO=""
    [ -n "$_KREPO" ] && export KIPI_ALERT_REPO_PATH="$_KREPO"
  fi
fi

# --- fixture-run guard: a test must never open a live ticket -------------------
# SCAR 2026-08-01. Three tests were found paging the founder's real Slack and
# were fixed by stubbing KIPI_NOTIFY per test (PR #54). While that PR sat open,
# an agent ran test-worker-project-scope.sh from a worktree cut off main -- which
# carried no stub -- and the founder was paged again, live. Per-test stubbing
# only protects branches that carry it and tests someone remembered to fix.
#
# THE SIGNAL. Every test in this repo points the worker at a fixture Linear on
# loopback (KIPI_LINEAR_API_URL=http://127.0.0.1:$PORT/graphql); production
# always points at the real Linear API. That asymmetry is total in both
# directions, which is what makes it safe to key a refusal on.
#
# Kept EXACTLY as-is through the Slack->Linear switch. It would have been easy to
# argue it away ("a loopback Linear IS the fixture server, so let the write
# through") -- but the bash suites assert exit 4 here, and a fixture server that
# is not listening would turn their clean refusal into a failed send. The guard
# also now covers a second runner: alert-to-linear.py refuses independently on
# PYTEST_CURRENT_TEST, which catches python tests that set no URL at all.
#
# DELIBERATELY NOT A SIGNAL: KIPI_STATE_DIR under a temp dir. A production job
# may legitimately keep state in a temp path (macOS $TMPDIR is exactly that), so
# keying on it would suppress real alerts. A guard that swallows a genuine alert
# is worse than the bug it fixes.
#
# The refused text goes to stderr rather than being dropped: a silently swallowed
# alert is the precise failure mode this path exists to prevent.
# Two review findings on PR #58 shaped this function, in OPPOSITE directions:
#   1. A `127.*` shell pattern also matches non-loopback HOSTNAMES beginning
#      "127.", so `127.example.com` would have been read as a fixture and its
#      alert SILENTLY SUPPRESSED. The real invariant is the 127.0.0.0/8 block --
#      four NUMERIC octets in range -- not a string prefix.
#   2. The comparison was case-sensitive, so `LOCALHOST` got through from a
#      fixture run. DNS hostnames are case-insensitive: a genuine bypass.
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
    printf 'slack-notify: REFUSED to file a ticket -- fixture run (KIPI_LINEAR_API_URL host "%s" is loopback). Message NOT filed: %s\n' \
           "$_KHOST" "$MSG" >&2
    exit 4
  fi
fi

WRITER="$(dirname "${BASH_SOURCE[0]}")/alert-to-linear.py"
if [ ! -f "$WRITER" ]; then
  printf 'slack-notify: alert-to-linear.py missing at %s; message NOT filed: %s\n' \
         "$WRITER" "$MSG" >&2
  exit 1
fi

# BOUNDED. This is called from Stop hooks and launchd jobs, where a hung network
# call costs the caller its whole turn. alert-to-linear.py caps its own HTTP at
# 30s, which is far too long to hold a Stop hook, so the wall clock is enforced
# here too. `timeout` is GNU coreutils and is not on a stock macOS, so it is used
# only when present rather than assumed -- an alert path must not become
# dependent on a homebrew install.
TIMEOUT_BIN=""
command -v timeout  >/dev/null 2>&1 && TIMEOUT_BIN="timeout"
[ -z "$TIMEOUT_BIN" ] && command -v gtimeout >/dev/null 2>&1 && TIMEOUT_BIN="gtimeout"

if [ -n "$TIMEOUT_BIN" ]; then
  "$TIMEOUT_BIN" 20 python3 "$WRITER" "$MSG"
else
  python3 "$WRITER" "$MSG"
fi
RC=$?

# 124 is timeout's own "killed on the clock". Report it as a failed send (1)
# rather than leaking a code no caller's contract mentions.
if [ "$RC" -eq 124 ]; then
  printf 'slack-notify: timed out filing the ticket. Message NOT filed: %s\n' "$MSG" >&2
  exit 1
fi
exit "$RC"
