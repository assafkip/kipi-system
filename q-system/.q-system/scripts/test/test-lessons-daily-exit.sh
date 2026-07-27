#!/bin/bash
# Pins the exit contract of lessons-daily.sh (ASK-182).
#
# Why this test exists: the script ended on an `echo`, so its exit status was
# always 0. Live evidence, the 06:00 run on 2026-07-27 -- it logged
# "propagate FAILED" and Slacked it, and `launchctl list com.kipi.lessons-daily`
# still reported LastExitStatus = 0. That makes fleet-health-daily.py's
# `launchd-failing` detector structurally blind to this job, so its failures
# lived in Slack and a 2591-line log and never reached Linear.
#
# The exit code IS the wire to Linear: non-zero here -> LastExitStatus non-zero
# -> a deduped Linear issue on the next fleet-health run. Same contract as
# test-open-loops-heartbeat-exit.sh (ASK-184).
#
# Fully hermetic: a temp SKEL git repo, stubbed distill / kipi-update / claude /
# slack-notify. It never touches the live fleet, the real log, Slack, or git.
set -uo pipefail

SCRIPTS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SUT="$SCRIPTS/lessons-daily.sh"
PASS=0
FAIL=0

# build_fixture <distill-rc> <distill-stdout> <update-rc> -> echoes the temp root
build_fixture() {
  local distill_rc="$1" distill_out="$2" update_rc="$3"
  local tmp skel
  tmp="$(mktemp -d)"
  skel="$tmp/skel"
  mkdir -p "$skel/q-system/.q-system/scripts" "$skel/q-system/lessons" "$tmp/bin"

  cp "$SUT" "$skel/q-system/.q-system/scripts/lessons-daily.sh"
  # Stub the ONE notification channel so a test can never reach the founder.
  printf '#!/bin/bash\nexit 0\n' > "$skel/q-system/.q-system/scripts/slack-notify.sh"

  # The distiller: exit code and stdout are the two things the job reads.
  { printf '#!/usr/bin/env python3\nimport sys\nsys.stdout.write(%s)\nsys.exit(%s)\n' \
      "$(printf '%s' "$distill_out" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')" \
      "$distill_rc"; } > "$skel/q-system/.q-system/scripts/lessons-distill.py"

  printf '#!/bin/bash\nexit %s\n' "$update_rc" > "$skel/kipi-update.sh"

  # A real (empty) git repo: the job commits new lessons before propagating.
  git -C "$skel" init --quiet
  git -C "$skel" config user.email "test@example.com"
  git -C "$skel" config user.name "test"

  # `claude` present on PATH is the job's own precondition check.
  printf '#!/bin/bash\nexit 0\n' > "$tmp/bin/claude"
  chmod +x "$tmp/bin/claude" "$skel/kipi-update.sh" \
    "$skel/q-system/.q-system/scripts/slack-notify.sh"

  printf '%s' "$tmp"
}

# run_case <name> <distill-rc> <distill-stdout> <update-rc> <expect: zero|nonzero>
run_case() {
  local name="$1" distill_rc="$2" distill_out="$3" update_rc="$4" expect="$5"
  local tmp rc ok=0
  tmp="$(build_fixture "$distill_rc" "$distill_out" "$update_rc")"
  PATH="$tmp/bin:$PATH" \
    bash "$tmp/skel/q-system/.q-system/scripts/lessons-daily.sh" >/dev/null 2>&1
  rc=$?

  [ "$expect" = "nonzero" ] && [ "$rc" -ne 0 ] && ok=1
  [ "$expect" = "zero" ] && [ "$rc" -eq 0 ] && ok=1

  if [ "$ok" -eq 1 ]; then
    echo "PASS  $name (exit $rc, expected $expect)"
    PASS=$((PASS + 1))
  else
    echo "FAIL  $name (exit $rc, expected $expect)"
    echo "      log: $(tail -3 "$tmp/skel/q-system/output/lessons-daily.log" 2>/dev/null | tr '\n' ' ')"
    FAIL=$((FAIL + 1))
  fi
  rm -rf "$tmp"
}

PUBLISHED='{"scanned": 1, "published": ["a lesson"], "held": []}'
EMPTY='{"scanned": 0, "published": [], "held": []}'

echo "test-lessons-daily-exit"
# The bar-2 case, observed live on 2026-07-27: lessons published, fleet
# propagation failed, and launchd recorded a clean run.
run_case "propagate failure exits non-zero"   0 "$PUBLISHED" 1 nonzero
# A distiller that dies emits no JSON, so every count parses as 0 and the run
# reads as a quiet night. A zero result must prove it is empty, not broken.
run_case "distill crash exits non-zero"       1 ""           0 nonzero
run_case "distill non-JSON exits non-zero"    0 "Traceback"  0 nonzero
# Guards against a fix that just always fails.
run_case "clean publish+propagate exits zero" 0 "$PUBLISHED" 0 zero
run_case "nothing new exits zero"             0 "$EMPTY"     0 zero

echo "---"
echo "passed=$PASS failed=$FAIL"
[ "$FAIL" -eq 0 ] || exit 1
exit 0
