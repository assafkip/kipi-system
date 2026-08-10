#!/bin/bash
# End-to-end proof that kipi-update.sh preserves instance-only files.
#
# CONVERTED 2026-08-10 (ASK-608). The previous version lifted the snapshot ->
# preserve-scan -> rsync --delete -> restore sequence "verbatim from
# kipi-update.sh" into its own body. That proves the ALGORITHM and can
# structurally never observe two things that matter more:
#
#   * whether kipi-update.sh still CALLS the sequence, and
#   * which bash interprets it.
#
# Both went wrong the same day. The ASK-607 abort (`arr[*]` on an empty array is
# an unbound-variable error on /bin/bash 3.2, which is the only bash the fleet
# has) shipped with this file green, because a re-implementation runs under the
# TEST's interpreter and never reaches the code under test. `reimplementing-test-lint.py`
# now flags this shape; that lint flagged this very file, which is why it changed.
#
# So: the RED case still demonstrates the raw defect, because a reproducer that
# cannot show the bad behaviour is worthless. The GREEN case now drives the REAL
# kipi-update.sh through its real entry point and asserts the preservation
# messages the running program emits.
#
# Only --dry-run is invoked, against a throwaway skeleton and instance. Nothing
# here can reach a registered instance.
#
# Run: bash test-kipi-update-preserve-integration.sh
set -uo pipefail

REAL="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
T="$(mktemp -d)"
trap 'rm -r -- "$T" 2>/dev/null || true' EXIT
FAILURES=0

g() { git -c user.email=t@t -c user.name=t -c commit.gpgsign=false \
        -c init.defaultBranch=main "$@"; }

TARGET="q-system/.q-system/scripts/instance-only.py"

echo "=== RED: a raw rsync --delete destroys a tracked instance-only file ==="
# The 2026-06-24 failure, reproduced. fractional-cxo lost its income scanners
# this way for 6 days: the snapshot only ever covered UNTRACKED files, and a
# script the instance had COMMITTED inside the synced tree had no protection.
RED="$T/red"
mkdir -p "$RED/skeleton/q-system/.q-system/scripts" "$RED/instance/q-system/.q-system/scripts"
( cd "$RED/skeleton" && echo skel > q-system/.q-system/scripts/skel.py &&
  g init -q . && g add -A && g commit -qm init ) >/dev/null 2>&1
ARCH="$RED/archive"; mkdir -p "$ARCH"
git -C "$RED/skeleton" archive --format=tar HEAD -- q-system/ | tar -x -C "$ARCH"
( cd "$RED/instance" && echo skel > q-system/.q-system/scripts/skel.py &&
  echo MINE > "$TARGET" && g init -q . && g add -A && g commit -qm init ) >/dev/null 2>&1
rsync -a --delete "$ARCH/q-system/" "$RED/instance/q-system/" 2>/dev/null
if [ -f "$RED/instance/$TARGET" ]; then
  echo "  FAIL: the file survived a raw --delete, so this reproducer proves nothing"
  FAILURES=$((FAILURES + 1))
else
  echo "  OK: reproduced -- $TARGET was deleted with no protection"
fi

echo ""
echo "=== GREEN: the REAL kipi-update.sh preserves it ==="
SKEL="$T/green/skeleton"
INST="$T/green/instance"
mkdir -p "$T/green"
# Full skeleton copy: the updater runs fail-closed preflight gates that each
# require their own script, so a stub tree aborts before reaching the code under
# test -- which would be a green run that measured nothing.
cp -R "$REAL/q-system" "$SKEL/q-system" 2>/dev/null || { mkdir -p "$SKEL"; cp -R "$REAL/q-system" "$SKEL/q-system"; }
cp "$REAL"/*.py "$REAL"/*.sh "$SKEL/" 2>/dev/null
cp "$REAL"/*.json "$REAL"/*.yml "$SKEL/" 2>/dev/null
cp -R "$REAL/plugins" "$SKEL/plugins" 2>/dev/null
chmod +x "$SKEL/kipi-update.sh"
echo "skeleton-owned" > "$SKEL/q-system/.q-system/scripts/skel-tool.py"

cat > "$SKEL/instance-registry.json" <<JSON
{
  "skeleton": "$SKEL",
  "instances": [
    { "name": "fake", "path": "$INST", "subtree_prefix": "q-system",
      "instance_q_dir": "q-fake", "type": "subtree", "has_git": true }
  ],
  "standalone": [],
  "eliminated": []
}
JSON
( cd "$SKEL" && g init -q . && g add -A >/dev/null 2>&1 && g commit -qm skel ) >/dev/null 2>&1

mkdir -p "$INST/q-system/.q-system/scripts"
echo "skeleton-owned" > "$INST/q-system/.q-system/scripts/skel-tool.py"
echo "MINE" > "$INST/$TARGET"                       # TRACKED, instance-only
( cd "$INST" && g init -q . && g add -A >/dev/null 2>&1 && g commit -qm inst ) >/dev/null 2>&1
echo "NOTES" > "$INST/q-system/.q-system/scripts/untracked-note.txt"   # UNTRACKED

LOG="$T/green/run.log"
/bin/bash "$SKEL/kipi-update.sh" --dry-run --only fake > "$LOG" 2>&1

if ! grep -q -- "--- fake (subtree) ---" "$LOG"; then
  echo "  FAIL: the run never reached the instance, so nothing was measured"
  tail -4 "$LOG" | sed 's/^/      /'
  FAILURES=$((FAILURES + 1))
else
  # Positive signals emitted by the RUNNING program, not the absence of a
  # deletion line -- an absence would pass against a run that died early.
  if grep -q "tracked instance-only file(s) would be deleted" "$LOG" &&
     grep -q "instance-only.py" "$LOG"; then
    echo "  OK: the updater announced it was preserving the tracked file"
  else
    echo "  FAIL: no preservation warning for $TARGET"
    FAILURES=$((FAILURES + 1))
  fi
  if grep -q "restored untracked: $TARGET" "$LOG"; then
    echo "  OK: the tracked instance-only file was restored after --delete"
  else
    echo "  FAIL: $TARGET was not restored"
    grep -i "restored" "$LOG" | head -3 | sed 's/^/      /'
    FAILURES=$((FAILURES + 1))
  fi
  if grep -q "restored untracked: q-system/.q-system/scripts/untracked-note.txt" "$LOG"; then
    echo "  OK: the untracked file was restored too"
  else
    echo "  FAIL: the untracked file was not restored"
    FAILURES=$((FAILURES + 1))
  fi
fi

echo ""
if [ "$FAILURES" = "0" ]; then echo "PASS"; exit 0; else echo "FAIL ($FAILURES)"; exit 1; fi
