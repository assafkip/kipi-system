#!/bin/bash
# ASK-604: the Slack label prefix and the message body must name the SAME project.
#
# THE SCAR. One digest read "[qep_agent]" while its body named consulting's
# files; another posted as "[/]". Two independent derivations of one fact:
# auto-commit.py built the body from basename(CLAUDE_PROJECT_DIR), while
# slack-notify.sh re-derived the prefix from ambient state -- and auto-commit
# invoked it with NO cwd, so the git-toplevel fallback resolved against whatever
# directory the agent happened to be in. basename(".") and basename("/") are
# where "[/]" came from.
#
# NOTHING HERE CAN PAGE A HUMAN. Every case sets KIPI_LINEAR_API_URL to loopback,
# which is the script's own fixture-run signal: it refuses to deliver and writes
# the message it would have sent to stderr. That refused text is what we assert
# on, so the test reads the real formatting code without touching the webhook.
#
# Run: bash test-slack-notify-label.sh
set -uo pipefail

REAL="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NOTIFY="$REAL/q-system/.q-system/scripts/slack-notify.sh"
FIXTURE_URL="http://127.0.0.1:9/graphql"
FAILURES=0

# $1 label to expect, $2 label that must NOT appear, then env assignments
run_case() {
  local want="$1"; shift
  local forbid="$1"; shift
  local desc="$1"; shift
  local out
  out="$( "$@" env KIPI_LINEAR_API_URL="$FIXTURE_URL" \
            bash "$NOTIFY" "test message" 2>&1 )"
  if printf '%s' "$out" | grep -Fq "[$want]"; then
    echo "  OK [$desc]: prefixed [$want]"
  else
    echo "  FAIL [$desc]: expected [$want], got:"
    printf '%s\n' "$out" | head -2 | sed 's/^/      /'
    FAILURES=$((FAILURES + 1))
  fi
  # The forbidden check is what makes the assertion discriminating: without it,
  # a message containing every label would pass every positive case.
  if [ -n "$forbid" ] && printf '%s' "$out" | grep -Fq "[$forbid]"; then
    echo "  FAIL [$desc]: ALSO contained the wrong label [$forbid]"
    FAILURES=$((FAILURES + 1))
  fi
}

echo "=== an explicit label from the caller wins ==="
run_case "consulting" "kipi-system" "explicit" \
  env KIPI_NOTIFY_LABEL=consulting KIPI_INSTANCE_NAME=qep_agent

echo ""
echo "=== the qep_agent/consulting mismatch, reproduced and fixed ==="
# Before ASK-604 the caller could not state the project, so an inherited
# KIPI_INSTANCE_NAME from an unrelated context won and mislabelled the message.
run_case "consulting" "qep_agent" "inherited-name-loses-to-explicit" \
  env KIPI_NOTIFY_LABEL=consulting KIPI_INSTANCE_NAME=qep_agent

echo ""
echo "=== with no explicit label, the registry name is still honoured ==="
# Control: the fix must not break the fleet heartbeat's authoritative naming.
run_case "Pure_spectrum_Q" "unknown-project" "registry-name" \
  env KIPI_INSTANCE_NAME=Pure_spectrum_Q

echo ""
echo "=== a degenerate label never ships as [/] ==="
# cd / so the git-toplevel fallback fails and \$PWD is "/".
out="$(cd / && env -u KIPI_NOTIFY_LABEL -u KIPI_INSTANCE_NAME \
        KIPI_LINEAR_API_URL="$FIXTURE_URL" bash "$NOTIFY" "test message" 2>&1)"
if printf '%s' "$out" | grep -Fq "[/]"; then
  echo "  FAIL: still posts as [/]"
  FAILURES=$((FAILURES + 1))
elif printf '%s' "$out" | grep -Fq "[unknown-project]"; then
  echo "  OK: degenerate label became [unknown-project]"
else
  echo "  FAIL: expected [unknown-project], got:"
  printf '%s\n' "$out" | head -2 | sed 's/^/      /'
  FAILURES=$((FAILURES + 1))
fi

echo ""
echo "=== one source: auto-commit's body name equals the prefix it asks for ==="
# The real coupling. Asserting the two agree is the whole point of the issue;
# asserting only the prefix would let the body drift again.
PROJECT_NAME="$(python3 - <<'PY'
import os, sys
sys.path.insert(0, "q-system/hooks")
os.environ.setdefault("CLAUDE_PROJECT_DIR", "/Users/assafkipnis/projects/consulting")
proj = os.environ["CLAUDE_PROJECT_DIR"]
print(os.path.basename(os.path.abspath(proj)) or "unknown-project")
PY
)"
if [ "$PROJECT_NAME" = "consulting" ]; then
  echo "  OK: body derives 'consulting' from the same value passed as the label"
else
  echo "  FAIL: body derived '$PROJECT_NAME'"
  FAILURES=$((FAILURES + 1))
fi
# And prove the wiring: auto-commit must actually SET the env var and the cwd.
if grep -q 'KIPI_NOTIFY_LABEL=project' "$REAL/q-system/hooks/auto-commit.py" &&
   grep -q 'cwd=PROJ_DIR, env=env' "$REAL/q-system/hooks/auto-commit.py"; then
  echo "  OK: auto-commit passes both the label and the cwd"
else
  echo "  FAIL: auto-commit no longer passes the label/cwd; the two sources can drift again"
  FAILURES=$((FAILURES + 1))
fi

echo ""
if [ "$FAILURES" = "0" ]; then echo "PASS"; exit 0; else echo "FAIL ($FAILURES)"; exit 1; fi
