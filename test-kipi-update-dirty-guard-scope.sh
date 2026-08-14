#!/bin/bash
# ASK-609: the dirty-tree guard must block on dirt the sync CAN write and must
# NOT block on dirt it cannot reach.
#
# THE SCAR. The guard was repo-wide. Measured 2026-08-10: 182 dirty files across
# four blocked instances, ZERO of them in a path the sync writes (Alice's 162 are
# investigation evidence under q-investigate/). Four instances were locked out of
# every fix -- including the ASK-607 fix written to unblock stuck instances --
# by a guard protecting an empty set.
#
# BOTH DIRECTIONS ARE THE POINT. Loosening a guard trades one failure mode for
# another, so a test that only proves "it stopped blocking" is worthless: it
# passes just as happily against a guard deleted outright. The blocking case
# below is the control that gives the passing case meaning.
#
# WHAT THIS FILE DOES NOT PROVE. restore_instance's `reset`/`checkout -- .` was
# scoped in the same change, because unscoping the guard while leaving the
# restore repo-wide would make the restore discard the very founder work the
# scoping stopped blocking on. That coupling is enforced by both sites using the
# same pathspec, and is asserted structurally at the bottom of this file. Proving
# it behaviourally needs a NON-dry run (dry mode operates on a clone, so the
# founder's real file is never in reach) and is not attempted here. Stated
# plainly rather than implied by a green tick.
#
# ONLY --dry-run is ever invoked, against a throwaway skeleton and instance.
#
# Run: bash test-kipi-update-dirty-guard-scope.sh
set -uo pipefail

REAL="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
T="$(mktemp -d)"
trap 'rm -r -- "$T" 2>/dev/null || true' EXIT
FAILURES=0

g() { git -c user.email=t@t -c user.name=t -c commit.gpgsign=false \
        -c init.defaultBranch=main "$@"; }

# $1 root, $2 "outside" | "inside" -- where the instance's dirt lives.
build_fleet() {
  local root="$1"
  local where="$2"
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

  # q-investigate/ is instance CONTENT: the skeleton has never written it and
  # never will. q-system/.q-system/ is squarely inside the sync's write set.
  mkdir -p "$inst/q-system/.q-system/scripts" "$inst/q-investigate/evidence"
  echo "skeleton-owned" > "$inst/q-system/.q-system/scripts/skel-tool.py"
  echo "skeleton CLAUDE" > "$inst/q-system/CLAUDE.md"
  echo "FOUNDER EVIDENCE v1" > "$inst/q-investigate/evidence/case-001.md"
  ( cd "$inst" && g init -q . && g add -A >/dev/null 2>&1 && g commit -qm inst ) >/dev/null 2>&1

  # Dirty a TRACKED file, which is what the guard tests.
  if [ "$where" = "outside" ]; then
    echo "FOUNDER EVIDENCE v2 -- unsaved work" \
      > "$inst/q-investigate/evidence/case-001.md"
  else
    # q-system/CLAUDE.md, NOT q-system/.q-system/. The first fixture used the
    # latter and the control did not block: AREA_MAP maps q-system/.q-system/
    # to `chore`, so the system-owned sweeper that runs just ABOVE the guard
    # commits it and the guard then sees a clean tree. That is sp-a442acf4
    # (auto-commit still sweeps mid-session WIP) reproducing independently --
    # a real hole in the guard, upstream of anything ASK-609 changed, and not
    # something this test should paper over by choosing a convenient path.
    echo "edited by hand" > "$inst/q-system/CLAUDE.md"
  fi
  echo "$skel"
}

# want=block | want=sync
assert_run() {
  local label="$1"
  local skel="$2"
  local want="$3"
  local out="$skel/../run.log"
  /bin/bash "$skel/kipi-update.sh" --dry-run --only fake > "$out" 2>&1
  if ! grep -q -- "--- fake (subtree) ---" "$out"; then
    echo "  FAIL [$label]: never reached the instance; measuring nothing"
    tail -4 "$out" | sed 's/^/      /'
    FAILURES=$((FAILURES + 1)); return
  fi
  local blocked=no
  grep -q "dirty working tree" "$out" && blocked=yes
  if [ "$want" = "block" ]; then
    if [ "$blocked" = "yes" ]; then
      echo "  OK [$label]: blocked, as it must"
    else
      echo "  FAIL [$label]: did NOT block on dirt inside the sync's write set."
      echo "      The guard is now too loose; a real edit could be packaged into an infra commit."
      FAILURES=$((FAILURES + 1))
    fi
  else
    if [ "$blocked" = "no" ] && grep -q "  OK (" "$out"; then
      echo "  OK [$label]: synced past dirt the sync cannot reach"
    else
      echo "  FAIL [$label]: still blocked by unreachable dirt (blocked=$blocked)"
      grep -m1 "dirty working tree" "$out" | sed 's/^/      /'
      FAILURES=$((FAILURES + 1))
    fi
  fi
}

echo "=== dirt OUTSIDE the sync's write set (q-investigate/) -> must SYNC ==="
assert_run "outside" "$(build_fleet "$T/out" outside)" "sync"

echo ""
echo "=== dirt INSIDE the sync's write set (q-system/CLAUDE.md) -> must BLOCK ==="
assert_run "inside" "$(build_fleet "$T/in" inside)" "block"

echo ""
echo "=== guard and restore must share one scope ==="
# A drift check, not a behaviour check. If someone re-broadens either site the
# two stop matching and this fails, which is the cheapest available defence
# against the restore silently going back to discarding the whole worktree.
#
# The restore half used to grep the literal
# `checkout -q -- "$CHECKPOINT_PREFIX/" .claude/ plugins/`. ASK-740 had to change
# that line: `git checkout -- A B C` is ALL-OR-NOTHING, so an instance tracking no
# .claude/ or plugins/ made it error and restore NOTHING, which is what left
# `M q-system/tracked.md` behind and pre-refused every later run. The specs are
# now filtered through `ls-files` before being passed. So this greps the line that
# DEFINES the restore scope instead of the line that spends it -- same property,
# and it still fails the moment either site is re-broadened. The unscoped-checkout
# assertion is kept explicit rather than implied by the first grep.
if grep -q 'for spec in "\$CHECKPOINT_PREFIX/" \.claude/ plugins/; do' "$REAL/kipi-update.sh" &&
   ! grep -qE 'checkout -q -- \.( |$)|checkout -q -- "\$target"' "$REAL/kipi-update.sh" &&
   grep -q 'diff --quiet -- "\$prefix/" \.claude/ plugins/' "$REAL/kipi-update.sh"; then
  echo "  OK [scope-pairing]: guard and restore both pathspec-limited"
else
  echo "  FAIL [scope-pairing]: guard and restore scopes have drifted apart."
  echo "      An unscoped restore discards founder work the scoped guard lets past."
  FAILURES=$((FAILURES + 1))
fi

echo ""
if [ "$FAILURES" = "0" ]; then echo "PASS"; exit 0; else echo "FAIL ($FAILURES)"; exit 1; fi
