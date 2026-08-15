#!/bin/bash
# sp-f6733ee3: the dry-run model must not strip a TRACKED file, and must still
# strip an untracked cache.
#
# THE SCAR. sp-b2f16971 was "the dry model copies 8.7G of caches", closed by
# adding a hardcoded list of cache directory names to MODEL_EXCLUDES with the
# comment "every path here is regenerable by its own toolchain and gitignored".
# That comment is false for real instances. Measured 2026-08-10: gtm-partner
# TRACKS 28 files under those names, interview-coach 1. Stripping a tracked file
# from the model makes the model's git see a deletion the real sync would never
# perform. A fix that relocated its own bug.
#
# BOTH DIRECTIONS. Deleting the exclusion list entirely would pass a
# "no false deletion" test and reintroduce the 8.7G problem, so the untracked
# case below is the control that gives the tracked case meaning.
#
# Only --dry-run is invoked, against a throwaway skeleton and instance.
#
# Run: bash test-kipi-update-cache-exclusion.sh
set -uo pipefail

REAL="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
T="$(mktemp -d)"
trap 'rm -r -- "$T" 2>/dev/null || true' EXIT
FAILURES=0

g() { git -c user.email=t@t -c user.name=t -c commit.gpgsign=false \
        -c init.defaultBranch=main "$@"; }

build_fleet() {
  local root="$1"
  local skel="$root/skeleton"
  local inst="$root/instance"
  mkdir -p "$skel"
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

  mkdir -p "$inst/q-system/.q-system/scripts" "$inst/build" "$inst/node_modules/junk"
  echo "skeleton-owned" > "$inst/q-system/.q-system/scripts/skel-tool.py"
  # TRACKED, under a name on the strip list. This is gtm-partner's shape.
  echo "<html>real deliverable</html>" > "$inst/build/index.html"
  ( cd "$inst" && g init -q . && g add -A >/dev/null 2>&1 && g commit -qm inst ) >/dev/null 2>&1
  # UNTRACKED cache, the 8.7G shape the strip list exists for.
  echo "regenerable garbage" > "$inst/node_modules/junk/blob.bin"
  echo "$skel"
}

SKEL="$(build_fleet "$T/a")"
INST="$T/a/instance"
LOG="$T/a/run.log"
/bin/bash "$SKEL/kipi-update.sh" --dry-run --only fake > "$LOG" 2>&1

if ! grep -q -- "--- fake (subtree) ---" "$LOG"; then
  echo "FAIL: run never reached the instance; measuring nothing"
  tail -4 "$LOG" | sed 's/^/    /'
  exit 1
fi

echo "=== a TRACKED file under build/ must not read as deleted ==="
# The model's git compares against a worktree the model built. If build/index.html
# was stripped, the model reports it deleted.
if grep -qE "(deleting|deleted:|^ D | D  )[[:space:]]*build/index\.html" "$LOG" ||
   grep -q "build/index.html" <(grep -iE "delet" "$LOG"); then
  echo "  FAIL: build/index.html reported as deleted -- the strip list ate a tracked file"
  grep -iE "delet.*build/index" "$LOG" | head -3 | sed 's/^/      /'
  FAILURES=$((FAILURES + 1))
else
  echo "  OK: no spurious deletion for the tracked file"
fi

echo ""
echo "=== the UNTRACKED cache must still be excluded (control) ==="
# Without this, deleting MODEL_EXCLUDES entirely would pass the test above.
# Ask the function directly rather than inferring from the log: source the
# script's own helper in a subshell so we read the real array it builds.
EXCL="$(
  cd "$SKEL" && /bin/bash -c '
    set -uo pipefail
    # Pull just the function out; running the whole script would start a sync.
    eval "$(sed -n "/^model_rsync_excludes()/,/^}/p" kipi-update.sh)"
    MODEL_SKIPPED_PATHS=()
    model_rsync_excludes "'"$INST"'" 2>/dev/null
    printf "%s\n" "${MODEL_EXCLUDES[@]}"
  ' 2>/dev/null
)"
if printf '%s' "$EXCL" | grep -q -- "--exclude=node_modules/"; then
  echo "  OK: untracked node_modules/ still stripped"
else
  echo "  FAIL: node_modules/ no longer excluded -- the 8.7G regression is back"
  FAILURES=$((FAILURES + 1))
fi
if printf '%s' "$EXCL" | grep -q -- "--exclude=build/"; then
  echo "  FAIL: build/ excluded despite holding a tracked file"
  FAILURES=$((FAILURES + 1))
else
  echo "  OK: build/ not excluded, because git tracks something there"
fi

echo ""
echo "=== negative self-test: revert the fix, the check must go RED ==="
# The first assertion above is absence-based and would pass against a run that
# died early. This one is positive and mutation-validated: strip the
# tracked-content case out of model_rsync_excludes and build/ must come back.
MUT="$T/mut.sh"
cp "$REAL/kipi-update.sh" "$MUT"
if python3 - "$MUT" <<'PY'
import sys
p = sys.argv[1]
s = open(p).read()
new = s.replace("""    case "$tracked_nl" in
      *$'\\n'"$cache_dir"/*|*"/$cache_dir"/*)
        # Tracked content lives here. Excluding it would fake a deletion.
        continue
        ;;
    esac
""", "")
if new == s:
    raise SystemExit(1)          # mutation did not apply; a green below is meaningless
open(p, "w").write(new)
PY
then
  MUT_EXCL="$(/bin/bash -c '
    set -uo pipefail
    eval "$(sed -n "/^model_rsync_excludes()/,/^}/p" '"$MUT"')"
    MODEL_SKIPPED_PATHS=()
    model_rsync_excludes "'"$INST"'" 2>/dev/null
    printf "%s\n" "${MODEL_EXCLUDES[@]}"' 2>/dev/null)"
  if printf '%s' "$MUT_EXCL" | grep -q -- "--exclude=build/"; then
    echo "  OK [mutant]: reverting the fix re-excludes build/, so the check can fail"
  else
    echo "  FAIL [mutant]: the mutant did NOT re-exclude build/."
    echo "      Either the mutation missed or the assertion is not measuring this line."
    FAILURES=$((FAILURES + 1))
  fi
else
  echo "  FAIL: mutation did not apply; the fix has moved and this test is stale"
  FAILURES=$((FAILURES + 1))
fi

echo ""
if [ "$FAILURES" = "0" ]; then echo "PASS"; exit 0; else echo "FAIL ($FAILURES)"; exit 1; fi
