#!/bin/bash
# Pins the exit contract of open-loops-heartbeat.sh (ASK-184).
#
# Why this test exists: the heartbeat ended with an unconditional `exit 0`, so a
# sweep whose agent run failed still reported success to launchd. That made
# fleet-health-daily.py's `launchd-failing` detector structurally blind to this
# job -- its failures reached Slack and a freeform log, never Linear. The four
# bars for a Linear-tracked job require failures to reach Linear, so the exit
# code is the wire.
#
# Runs fully hermetically: a temp SKEL, a fake instance, a `claude` shim, and a
# stubbed slack-notify. It never touches the live fleet, the real log, or Slack.
set -uo pipefail

SCRIPTS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SUT="$SCRIPTS/open-loops-heartbeat.sh"
AUDIT="$SCRIPTS/run-step-audit.py"
PASS=0
FAIL=0

# build_fixture <claude-exit-code> -> echoes the temp root
build_fixture() {
  local claude_rc="$1"
  local tmp skel inst
  tmp="$(mktemp -d)"
  skel="$tmp/skel"
  inst="$tmp/inst"
  mkdir -p "$skel/q-system/output" "$skel/q-system/.q-system/scripts"
  mkdir -p "$inst/q-system/.q-system/scripts" "$tmp/bin"

  cp "$SUT" "$skel/q-system/.q-system/scripts/open-loops-heartbeat.sh"
  cp "$AUDIT" "$skel/q-system/.q-system/scripts/run-step-audit.py"
  # Stub the ONE notification channel so a test can never reach the founder.
  printf '#!/bin/bash\nexit 0\n' > "$skel/q-system/.q-system/scripts/slack-notify.sh"

  # A fake instance that reports exactly one actionable loop, which is what
  # makes work_instance wake the (shimmed) agent instead of taking the cheap
  # 0-open-loops path.
  printf 'print("- [ ] fixture loop [needs you] -> do the thing")\n' \
    > "$inst/q-system/.q-system/scripts/open-loops.py"

  printf '{"instances":[{"name":"fake","path":"%s"}]}\n' "$inst" \
    > "$skel/instance-registry.json"

  printf '#!/bin/bash\nexit %s\n' "$claude_rc" > "$tmp/bin/claude"
  chmod +x "$tmp/bin/claude"

  printf '%s' "$tmp"
}

# run_case <name> <claude-exit-code> <expected-script-exit: zero|nonzero>
run_case() {
  local name="$1" claude_rc="$2" expect="$3"
  local tmp rc
  tmp="$(build_fixture "$claude_rc")"
  PATH="$tmp/bin:$PATH" KIPI_REPO="$tmp/skel" \
    bash "$tmp/skel/q-system/.q-system/scripts/open-loops-heartbeat.sh" >/dev/null 2>&1
  rc=$?

  local ok=0
  if [ "$expect" = "nonzero" ] && [ "$rc" -ne 0 ]; then ok=1; fi
  if [ "$expect" = "zero" ] && [ "$rc" -eq 0 ]; then ok=1; fi

  if [ "$ok" -eq 1 ]; then
    echo "PASS  $name (exit $rc, expected $expect)"
    PASS=$((PASS + 1))
  else
    echo "FAIL  $name (exit $rc, expected $expect)"
    echo "      run-log: $(cat "$tmp/skel/q-system/output/heartbeat-run-last.json" 2>/dev/null | tr -d '\n')"
    FAIL=$((FAIL + 1))
  fi
  rm -rf "$tmp"
}

echo "test-open-loops-heartbeat-exit"
# The bar-2 case: an instance whose agent run failed must NOT report success to
# launchd, or the launchd-failing detector never files the Linear issue.
run_case "failed agent run exits non-zero" 7 nonzero
# The guard against a fix that just always fails: a clean sweep stays exit 0.
run_case "clean sweep exits zero" 0 zero

echo "---"
echo "passed=$PASS failed=$FAIL"
[ "$FAIL" -eq 0 ] || exit 1
exit 0
