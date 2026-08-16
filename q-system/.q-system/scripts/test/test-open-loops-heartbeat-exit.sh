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

# --- ASK-869: one machine-wide condition is ONE alert, not one per instance ---
# Measured 2026-08-15: the account hit its weekly limit, every `claude -p` in the
# sweep died on it, and the heartbeat filed a ticket per instance -- 10, plus a
# step-audit ticket for the 10 "failed" steps, plus the job's own exit-1 ticket.
# Twelve tickets for one fact, and the sweep kept waking agents that could not
# run after the answer was already known.
#
# The fixture uses THREE instances and a claude shim that emits the real line from
# that log. Three is the minimum that can tell "one alert" from "one per instance"
# AND show that the sweep stopped early rather than merely deduping its output.
build_env_fixture() {
  local tmp skel
  tmp="$(mktemp -d)"
  skel="$tmp/skel"
  mkdir -p "$skel/q-system/output" "$skel/q-system/.q-system/scripts" "$tmp/bin"
  cp "$SUT"   "$skel/q-system/.q-system/scripts/open-loops-heartbeat.sh"
  cp "$AUDIT" "$skel/q-system/.q-system/scripts/run-step-audit.py"

  # The notify stub COUNTS instead of exiting silently: the whole assertion is
  # how many times this channel was reached, so a stub that records nothing
  # could not fail. Still never reaches the founder.
  printf '#!/bin/bash\necho "$*" >> "%s/notifies"\nexit 0\n' "$tmp" \
    > "$skel/q-system/.q-system/scripts/slack-notify.sh"

  local names=(alpha bravo charlie) inst
  local reg='{"instances":['
  for n in "${names[@]}"; do
    inst="$tmp/$n"
    mkdir -p "$inst/q-system/.q-system/scripts"
    printf 'print("- [ ] fixture loop [needs you] -> do the thing")\n' \
      > "$inst/q-system/.q-system/scripts/open-loops.py"
    reg="$reg{\"name\":\"$n\",\"path\":\"$inst\"},"
  done
  printf '%s]}\n' "${reg%,}" > "$skel/instance-registry.json"

  # The exact string the live log carried, once per failing instance. Records
  # every invocation so the test can prove the later instances were never tried.
  cat > "$tmp/bin/claude" <<EOF
#!/bin/bash
echo "\$PWD" >> "$tmp/claude-calls"
echo "You've hit your weekly limit · resets Aug 18 at 2pm (America/Los_Angeles)"
exit 1
EOF
  chmod +x "$tmp/bin/claude"
  printf '%s' "$tmp"
}

TMP="$(build_env_fixture)"
PATH="$TMP/bin:$PATH" KIPI_REPO="$TMP/skel" \
  bash "$TMP/skel/q-system/.q-system/scripts/open-loops-heartbeat.sh" >/dev/null 2>&1
ENV_RC=$?
N_NOTIFY="$(wc -l < "$TMP/notifies" 2>/dev/null | tr -d ' ')"
N_CALLS="$(wc -l < "$TMP/claude-calls" 2>/dev/null | tr -d ' ')"

if [ "${N_NOTIFY:-0}" = "1" ]; then
  echo "PASS  weekly-limit files ONE alert, not one per instance (notifies=$N_NOTIFY)"
  PASS=$((PASS + 1))
else
  echo "FAIL  weekly-limit filed $N_NOTIFY alert(s); one machine-wide condition is one alert"
  FAIL=$((FAIL + 1))
fi

# The sweep must STOP, not merely stay quiet. Continuing wakes agents that cannot
# run: every later instance shares the environment that just refused this one.
if [ "${N_CALLS:-0}" = "1" ]; then
  echo "PASS  sweep halts on the environmental failure (agent invoked $N_CALLS time)"
  PASS=$((PASS + 1))
else
  echo "FAIL  sweep kept waking agents after the environment refused: $N_CALLS invocation(s)"
  FAIL=$((FAIL + 1))
fi

# ASK-184's exit contract is not weakened by the halt: an environmental halt is
# still a failed sweep, or fleet-health's launchd-failing detector goes blind.
if [ "$ENV_RC" -ne 0 ]; then
  echo "PASS  environmental halt still reports failure to launchd (exit $ENV_RC)"
  PASS=$((PASS + 1))
else
  echo "FAIL  environmental halt reported success to launchd; ASK-184's contract is broken"
  FAIL=$((FAIL + 1))
fi

# The unreached instances must not be recorded as `failed`: nobody attempted them.
# Logging them as failures is what produced the step-audit ticket on top of the ten.
#
# NAMED instances, not a bare grep for the word "skipped". The first cut of this
# assertion searched the whole run-log for that substring and PASSED against the
# unfixed script, because instances legitimately skip for other reasons. An
# assertion that cannot fail is not an assertion -- the exact trap this suite is
# meant to catch. bravo and charlie are the two the halt must leave untried, and
# their status is read from their own rows.
UNREACHED_OK=1
for n in bravo charlie; do
  st="$(python3 - "$TMP/skel/q-system/output/heartbeat-run-last.json" "$n" <<'PY' 2>/dev/null || echo missing
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    print("missing"); raise SystemExit(0)
steps = d.get("steps", d) if isinstance(d, dict) else d
row = next((s for s in steps if isinstance(s, dict) and s.get("id") == sys.argv[2]), None)
print(row.get("status") if row else "missing")
PY
)"
  [ "$st" = "skipped" ] || { UNREACHED_OK=0; echo "      $n status=$st (want skipped)"; }
done
if [ "$UNREACHED_OK" = "1" ]; then
  echo "PASS  unreached instances are recorded as skipped, not failed"
  PASS=$((PASS + 1))
else
  echo "FAIL  an instance the halt never attempted is not recorded as skipped"
  FAIL=$((FAIL + 1))
fi
rm -rf "$TMP"

# THE GUARD ON THE GUARD. An ordinary per-instance failure must STILL alert per
# instance and must NOT halt the sweep. Without this case, a classifier that
# matched too broadly would turn every routine failure into a fleet-wide halt and
# a single vague ticket -- strictly worse than the noise being removed, and
# invisible to every assertion above, all of which only exercise the limit path.
TMP2="$(build_env_fixture)"
# Same fixture, ordinary failure: no limit line, just a non-zero exit.
printf '#!/bin/bash\necho "$PWD" >> "%s/claude-calls"\necho "TypeError: something broke"\nexit 7\n' \
  "$TMP2" > "$TMP2/bin/claude"
chmod +x "$TMP2/bin/claude"
PATH="$TMP2/bin:$PATH" KIPI_REPO="$TMP2/skel" \
  bash "$TMP2/skel/q-system/.q-system/scripts/open-loops-heartbeat.sh" >/dev/null 2>&1
ORD_NOTIFY="$(wc -l < "$TMP2/notifies" 2>/dev/null | tr -d ' ')"
ORD_CALLS="$(wc -l < "$TMP2/claude-calls" 2>/dev/null | tr -d ' ')"
# 3 instances tried, 3 per-instance alerts (+1 step-audit alert for the 3 failed
# steps, which is the pre-existing behaviour this change does not touch).
if [ "${ORD_CALLS:-0}" = "3" ] && [ "${ORD_NOTIFY:-0}" -ge 3 ]; then
  echo "PASS  an ordinary failure still alerts per instance and does not halt (calls=$ORD_CALLS notifies=$ORD_NOTIFY)"
  PASS=$((PASS + 1))
else
  echo "FAIL  ordinary failure path changed: calls=$ORD_CALLS (want 3), notifies=$ORD_NOTIFY (want >=3)"
  FAIL=$((FAIL + 1))
fi
rm -rf "$TMP2"

echo "---"
echo "passed=$PASS failed=$FAIL"
[ "$FAIL" -eq 0 ] || exit 1
exit 0
