#!/bin/bash
# Regression test for ASK-607: kipi-update.sh must survive an EMPTY bash array
# under `set -u` on bash 3.2, which is what `#!/bin/bash` resolves to on macOS.
#
# THE SCAR (2026-08-10). The ASK-605 block added at :1226 reads
#     case " ${sys_owned_dirty[*]} " in ...
# On bash 4.4+ an empty array expands to nothing. On bash 3.2.57 -- the ONLY
# bash at /bin/bash on this fleet's machines -- `arr[*]` on an empty array is an
# unbound-variable error, and `set -e` then kills the whole run. Measured:
#   /bin/bash: "line 4: arr[*]: unbound variable", exit 1.
#
# The trigger is exactly the case ASK-605 was written to fix: an instance where
# NONE of the three hand-listed system paths are dirty (so the array is still
# empty) but the classifier finds system exhaust (so the loop body runs). The
# block built to unblock stuck instances aborted the sync for them instead.
#
# WHY THIS TEST DRIVES THE REAL SCRIPT. The existing preservation test lifts the
# guard sequence "verbatim from kipi-update.sh" into the test body, so it proves
# the algorithm and can never see the wiring or the interpreter. This one copies
# the skeleton and runs the actual kipi-update.sh through its actual entry point,
# because the defect lives in neither the algorithm nor the helper -- it lives in
# how one line is written and which bash reads it.
#
# ONLY --dry-run is ever invoked. A dry run operates on a throwaway clone of a
# throwaway instance; nothing here can reach a registered instance.
#
# Run: bash test-kipi-update-bash32-empty-array.sh
set -uo pipefail

REAL="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
T="$(mktemp -d)"
trap 'rm -r -- "$T" 2>/dev/null || true' EXIT
FAILURES=0

g() { git -c user.email=t@t -c user.name=t -c commit.gpgsign=false \
        -c init.defaultBranch=main "$@"; }

# Build a skeleton + one instance whose ONLY dirty file is classifier-caught
# system exhaust. That is the shape that empties the array while entering the
# loop; an instance dirty in a hand-listed path would mask the bug.
build_fleet() {
  # Split, not chained: on bash 3.2 a later assignment in the SAME `local` does
  # not see an earlier one, so `local root="$1" skel="$root/x"` is unbound.
  local root="$1"
  local skel="$root/skeleton"
  local inst="$root/instance"
  mkdir -p "$skel"
  # The preflight gates resolve siblings off their own repo root and are
  # fail-closed, so a partial copy aborts before reaching the code under test.
  cp -R "$REAL/q-system" "$skel/q-system"
  cp "$REAL"/*.py "$REAL"/*.sh "$skel/" 2>/dev/null
  cp "$REAL"/*.json "$REAL"/*.yml "$skel/" 2>/dev/null
  cp -R "$REAL/plugins" "$skel/plugins" 2>/dev/null
  chmod +x "$skel/kipi-update.sh"
  echo "skeleton-owned" > "$skel/q-system/.q-system/scripts/skel-tool.py"

  cat > "$skel/instance-registry.json" <<JSON
{
  "skeleton": "$skel",
  "instances": [
    { "name": "fake", "path": "$inst", "subtree_prefix": "q-system",
      "instance_q_dir": "q-fake", "type": "subtree", "has_git": true }
  ],
  "standalone": [],
  "eliminated": []
}
JSON
  ( cd "$skel" && g init -q . && g add -A >/dev/null 2>&1 && g commit -qm skel ) >/dev/null 2>&1

  mkdir -p "$inst/q-system/.q-system/scripts" "$inst/q-system/my-project" \
           "$inst/q-system/memory"
  echo "skeleton-owned" > "$inst/q-system/.q-system/scripts/skel-tool.py"
  echo "FOUNDER_DATA"   > "$inst/q-system/my-project/clients.json"
  ( cd "$inst" && g init -q . && g add -A >/dev/null 2>&1 && g commit -qm inst ) >/dev/null 2>&1

  # Untracked system exhaust. open-loops.json is the exact file named in the
  # ASK-605 comment: written by a background heartbeat, `chore` to the
  # classifier, absent from the hand-maintained list.
  echo '{"loops": []}' > "$inst/q-system/memory/open-loops.json"
  echo "$skel"
}

# A run is only meaningful if it REACHED the block under test. Asserting the
# absence of an error message alone would pass on a run that died in preflight.
assert_run() {
  local label="$1"
  local skel="$2"
  local want="$3"
  local out="$skel/../run.log"
  /bin/bash "$skel/kipi-update.sh" --dry-run --only fake > "$out" 2>&1
  if ! grep -q -- "--- fake (subtree) ---" "$out"; then
    echo "  FAIL [$label]: run never reached the instance; test is not measuring anything"
    tail -5 "$out" | sed 's/^/      /'
    FAILURES=$((FAILURES + 1)); return
  fi
  if grep -q "unbound variable" "$out"; then
    if [ "$want" = "crash" ]; then
      echo "  OK [$label]: reproduced -- $(grep -m1 'unbound variable' "$out" | sed 's/^.*: //')"
    else
      echo "  FAIL [$label]: unbound variable on an empty array"
      grep -m1 "unbound variable" "$out" | sed 's/^/      /'
      FAILURES=$((FAILURES + 1))
    fi
  else
    if [ "$want" = "crash" ]; then
      echo "  FAIL [$label]: expected the mutant to crash and it did not."
      echo "      The mutation did not apply, so the green case proves nothing."
      FAILURES=$((FAILURES + 1))
    else
      echo "  OK [$label]: reached the instance and survived the empty array"
    fi
  fi
}

echo "bash at /bin/bash: $(/bin/bash --version | head -1)"
echo ""

echo "=== GREEN: the shipped kipi-update.sh ==="
SKEL="$(build_fleet "$T/green")"
assert_run "shipped" "$SKEL" "clean"

echo ""
echo "=== RED (negative self-test): revert the guard, same fleet ==="
# Mutate the fix back to the pre-ASK-607 spelling. If this does NOT crash, the
# green case above was not testing this line and the whole file is decoration.
SKEL2="$(build_fleet "$T/red")"
if ! grep -q 'sys_owned_dirty\[\*\]:-' "$SKEL2/kipi-update.sh"; then
  echo "  FAIL: could not find the guarded expansion to mutate; the fix moved."
  FAILURES=$((FAILURES + 1))
else
  perl -pi -e 's/\$\{sys_owned_dirty\[\*\]:-\}/\${sys_owned_dirty[*]}/' \
    "$SKEL2/kipi-update.sh"
  grep -q 'sys_owned_dirty\[\*\]}' "$SKEL2/kipi-update.sh" || {
    echo "  FAIL: mutation did not apply"; FAILURES=$((FAILURES + 1)); }
  assert_run "mutant" "$SKEL2" "crash"
fi

echo ""
if [ "$FAILURES" = "0" ]; then echo "PASS"; exit 0; else echo "FAIL ($FAILURES)"; exit 1; fi
