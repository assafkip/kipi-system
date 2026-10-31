#!/bin/bash
# Pins the CALLER half of the fan-out count check (ASK-3574, PR #584 finding 2).
#
# Why this test exists: lessons-fanout-check.py shipped with no caller anywhere.
# Nothing in the fleet compared a count, which is exactly how the 2026-10-22
# fan-out reached 12 instances, missed one by 29 lessons, reported "propagated to
# fleet", exited 0, and stayed invisible for nine days. A checker nothing calls
# would have left that gap open.
#
# The source grep lives in test_lessons_fanout_check.py (ProducerAgreesCase).
# This file is the behavioural half: it RUNS lessons-daily.sh against a hermetic
# fleet and asserts the three outcomes that make the count load-bearing --
#   a short instance makes the run exit non-zero and says so in its one alert,
#   a level fleet stays green and says that too,
#   a checkout that is not the registered skeleton DISARMS instead of guessing.
#
# Fully hermetic: a temp SKEL git repo with its own instance-registry.json, and
# stubbed distill / kipi-update / claude / slack-notify. It never touches the
# live fleet, the real log, the real registry, Slack, or git.
set -uo pipefail

SCRIPTS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SUT="$SCRIPTS/lessons-daily.sh"
CHECK="$SCRIPTS/lessons-fanout-check.py"
PASS=0
FAIL=0

# build_fixture <skeleton-lessons> <instance-lessons> <registry-skeleton: self|other>
build_fixture() {
  local skel_n="$1" inst_n="$2" reg_mode="$3"
  local tmp skel inst
  tmp="$(mktemp -d)"
  skel="$tmp/skel"
  inst="$tmp/inst"
  mkdir -p "$skel/q-system/.q-system/scripts" "$skel/q-system/lessons" \
           "$inst/q-system/lessons" "$tmp/bin"

  cp "$SUT" "$skel/q-system/.q-system/scripts/lessons-daily.sh"
  cp "$CHECK" "$skel/q-system/.q-system/scripts/lessons-fanout-check.py"
  printf '#!/bin/bash\nexit 0\n' > "$skel/q-system/.q-system/scripts/slack-notify.sh"
  printf '#!/bin/bash\nexit 0\n' > "$skel/q-system/.q-system/scripts/install-plist.sh"
  printf '#!/bin/bash\nexit 0\n' > "$skel/kipi-update.sh"
  printf '#!/bin/bash\nexit 0\n' > "$tmp/bin/claude"
  cat > "$skel/q-system/.q-system/scripts/lessons-distill.py" <<'PY'
#!/usr/bin/env python3
import json, sys
sys.stdout.write(json.dumps({"scanned": 1, "published": ["a lesson"], "held": []}))
PY

  local i
  for ((i = 0; i < skel_n; i++)); do touch "$skel/q-system/lessons/l-$i.md"; done
  for ((i = 0; i < inst_n; i++)); do touch "$inst/q-system/lessons/l-$i.md"; done

  # The registry the check reads. "self" makes this temp tree the registered
  # skeleton, which is what arms the count; "other" is the DISARM case.
  local declared="$skel"
  [ "$reg_mode" = "other" ] && declared="$tmp/somewhere-else"
  python3 - "$skel/instance-registry.json" "$declared" "$inst" <<'PY'
import json, sys
out, declared, inst = sys.argv[1], sys.argv[2], sys.argv[3]
json.dump({"skeleton": {"path": declared},
           "instances": [{"name": "laggard", "path": inst}]},
          open(out, "w"))
PY

  git -C "$skel" init --quiet
  git -C "$skel" config user.email "test@example.com"
  git -C "$skel" config user.name "test"
  chmod +x "$tmp/bin/claude" "$skel/kipi-update.sh" \
    "$skel/q-system/.q-system/scripts/slack-notify.sh" \
    "$skel/q-system/.q-system/scripts/install-plist.sh"
  printf '%s' "$tmp"
}

# run_case <name> <skel-n> <inst-n> <reg-mode> <expect: zero|nonzero> <expect-log-substring>
run_case() {
  local name="$1" skel_n="$2" inst_n="$3" reg_mode="$4" expect="$5" needle="$6"
  local tmp rc log ok=1
  tmp="$(build_fixture "$skel_n" "$inst_n" "$reg_mode")"
  PATH="$tmp/bin:$PATH" \
    bash "$tmp/skel/q-system/.q-system/scripts/lessons-daily.sh" >/dev/null 2>&1
  rc=$?
  log="$tmp/skel/q-system/output/lessons-daily.log"

  [ "$expect" = "nonzero" ] && [ "$rc" -eq 0 ] && ok=0
  [ "$expect" = "zero" ] && [ "$rc" -ne 0 ] && ok=0
  grep -q -- "$needle" "$log" 2>/dev/null || ok=0

  if [ "$ok" -eq 1 ]; then
    echo "PASS  $name (exit $rc, log carries '$needle')"
    PASS=$((PASS + 1))
  else
    echo "FAIL  $name (exit $rc, expected $expect and '$needle')"
    echo "      log: $(tail -6 "$log" 2>/dev/null | tr '\n' ' ')"
    FAIL=$((FAIL + 1))
  fi
  rm -rf "$tmp"
}

echo "test-lessons-fanout-wiring"
# THE 2026-10-22 SHAPE: the fan-out exits 0 and one instance is short anyway.
# Before the caller existed this run exited 0 and its alert said only
# "propagated to fleet".
run_case "a short instance makes the run exit non-zero" \
  5 2 self nonzero "fan-out counts DISAGREE"
# The same disagreement has to reach the ONE alert line, not only the log body:
# a count nobody is told about is the silence this issue is about.
run_case "the disagreement reaches the slacked line" \
  5 2 self nonzero "slacked: .*fan-out counts DISAGREE"
# Guards against a fix that always fails.
run_case "a level fleet stays green and says so" \
  5 5 self zero "fan-out counts: every live instance is level"
# A surplus is not a fan-out failure (one instance carried 213 against the
# skeleton's 205 on 2026-10-31), so it must not turn the job red.
run_case "an instance ahead of the skeleton is not red" \
  5 8 self zero "fan-out counts: every live instance is level"
# Not the registered skeleton: the question belongs to the fleet's skeleton, and
# a guess made from somebody else's registry is worse than no answer.
run_case "a checkout that is not the registered skeleton disarms" \
  5 2 other zero "fan-out counts: DISARMED"

echo "---"
echo "passed=$PASS failed=$FAIL"
[ "$FAIL" -eq 0 ] || exit 1
