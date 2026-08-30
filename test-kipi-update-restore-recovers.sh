#!/bin/bash
# sp-20c967ed, the half my dry-run fixture could not reach.
#
# THE NOTE. On a PARTIAL rsync --delete failure the updater used to tear down
# ARCHIVE_TMP -- which contains SNAP, the only copy of the instance's untracked
# files -- and continue, so the restore loop never ran. rsync deletes DURING
# transfer, so a disk-full or a signal mid-transfer lost instance-local files
# unrecoverably.
#
# WHAT WAS ALREADY PROVEN, and what was not. test-kipi-update-dataloss-guards.sh
# forces the failure branch and shows it is reached and reported. It CANNOT show
# that the file came back, because --dry-run works on a clone that is torn down
# at the end of the run, so the restored copy is unreachable from outside.
#
# WHY THIS DOES NOT JUST RUN THE UPDATER FOR REAL. A non-dry run is blocked by
# the destructive-op hook, correctly -- it rsyncs into every registered instance
# with a delete flag. Bypassing that to test it would be exactly the trade the
# hook exists to refuse. So instead this EXTRACTS the real restore_instance and
# its dependencies from the live kipi-update.sh and runs that text against a
# throwaway directory. It is not a re-implementation: the code under test is
# read out of the shipping file at run time, so it follows the code, and the
# mutation case below proves the assertion is actually bound to it.
#
# HONEST LIMIT. This proves restore_instance RECOVERS from SNAP, and asserts
# structurally that abandon_instance calls it BEFORE tearing ARCHIVE_TMP down.
# It does not execute both in one process against a real failing rsync. The
# remaining gap is a non-dry fixture, which needs the founder's approval to run.
#
# Run: bash test-kipi-update-restore-recovers.sh
set -uo pipefail

REAL="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$REAL/kipi-update.sh"
T="$(mktemp -d)"
trap 'rm -r -- "$T" 2>/dev/null || true' EXIT
FAILURES=0

# Pull the real functions out by name. If any extraction comes back empty the
# harness fails loudly rather than running against undefined functions -- an
# undefined function is command-not-found on stderr while the script carries on,
# which would look exactly like a pass.
extract() {
  local fn="$1"
  local body
  body="$(sed -n "/^${fn}() {/,/^}/p" "$SRC")"
  case "$body" in
    *"${fn}() {"*) printf '%s\n' "$body" ;;
    *) echo "FATAL: could not extract ${fn}() from kipi-update.sh" >&2; exit 1 ;;
  esac
}

build_probe() {   # $1 = "real" | "mutant"
  local mode="$1"
  local probe="$T/probe-$mode.sh"
  {
    printf 'set -uo pipefail\n'
    printf 'INSTANCE_OWNED_SUBTREES=(my-project canonical memory output research)\n'
    extract pathspec_owned_excludes
    extract checkpoint_untracked_list
    extract instance_rebase_in_flight
    if [ "$mode" = "real" ]; then
      extract restore_instance
    else
      # MUTANT: the same function with the SNAP recovery block removed. If the
      # assertion still passes against this, it is not measuring the recovery.
      extract restore_instance | sed '/ONLY copy is the preservation snapshot/,/done < "\$SNAP\/list" ) || true/d'
    fi
    printf 'restore_instance\n'
  } > "$probe"
  printf '%s' "$probe"
}

setup_instance() {
  local inst="$1"
  mkdir -p "$inst/q-system/.q-system/scripts"
  ( cd "$inst" && git -c init.defaultBranch=main init -q . &&
    echo tracked > q-system/.q-system/scripts/tool.py &&
    git -c user.email=t@t -c user.name=t add -A &&
    git -c user.email=t@t -c user.name=t commit -qm init ) >/dev/null 2>&1
  echo "INSTANCE ONLY" > "$inst/q-system/.q-system/scripts/scratch.txt"
}

# Stage the exact state the updater is in when a transfer dies half way:
# SNAP holds the pre-rsync copy, and the live file has been deleted.
stage_and_run() {
  local mode="$1"
  local inst="$T/$mode/instance"
  local snap="$T/$mode/archive/.snap"
  setup_instance "$inst"
  mkdir -p "$snap/f/q-system/.q-system/scripts"
  cp "$inst/q-system/.q-system/scripts/scratch.txt" \
     "$snap/f/q-system/.q-system/scripts/scratch.txt"
  printf 'q-system/.q-system/scripts/scratch.txt\0' > "$snap/list"
  local ckpt="$T/$mode/ckpt"; mkdir -p "$ckpt"
  : > "$ckpt/inflight"
  ( cd "$inst" && git -c user.email=t@t -c user.name=t ls-files -z --others \
      -- q-system/ 2>/dev/null ) > "$ckpt/untracked"
  # The partial failure: the file is gone from the worktree.
  rm -f "$inst/q-system/.q-system/scripts/scratch.txt"
  [ -f "$inst/q-system/.q-system/scripts/scratch.txt" ] && {
    echo "FATAL: setup did not remove the victim" >&2; exit 1; }

  CHECKPOINT_TARGET="$inst" CHECKPOINT_DIR="$ckpt" CHECKPOINT_PREFIX="q-system" \
    SNAP="$snap" /bin/bash "$(build_probe "$mode")" >/dev/null 2>&1
  echo "$inst"
}

echo "=== the real restore_instance recovers an untracked file from SNAP ==="
INST_REAL="$(stage_and_run real)"
VICTIM="q-system/.q-system/scripts/scratch.txt"
if [ -f "$INST_REAL/$VICTIM" ] &&
   [ "$(cat "$INST_REAL/$VICTIM")" = "INSTANCE ONLY" ]; then
  echo "  OK: recovered with its original content"
else
  echo "  FAIL: the file was not recovered from SNAP"
  FAILURES=$((FAILURES + 1))
fi

echo ""
echo "=== mutant: strip the SNAP block, recovery must NOT happen ==="
INST_MUT="$(stage_and_run mutant)"
if [ -f "$INST_MUT/$VICTIM" ]; then
  echo "  FAIL: the mutant recovered it too, so the assertion is not bound to"
  echo "        the SNAP block and the green above proves nothing"
  FAILURES=$((FAILURES + 1))
else
  echo "  OK: without the SNAP block the file stays gone"
fi

echo ""
echo "=== ordering: abandon_instance restores BEFORE tearing SNAP down ==="
# The note's actual defect was ordering, not the recovery logic. SNAP lives
# inside ARCHIVE_TMP, so a teardown that runs first destroys the only copy.
ABANDON="$(sed -n '/^abandon_instance() {/,/^}/p' "$SRC")"
RESTORE_LINE="$(printf '%s\n' "$ABANDON" | grep -n 'restore_instance' | head -1 | cut -d: -f1)"
TEARDOWN_LINE="$(printf '%s\n' "$ABANDON" | grep -n 'ARCHIVE_TMP' | head -1 | cut -d: -f1)"
if [ -n "$RESTORE_LINE" ] && [ -n "$TEARDOWN_LINE" ] &&
   [ "$RESTORE_LINE" -lt "$TEARDOWN_LINE" ]; then
  echo "  OK: restore_instance at line $RESTORE_LINE precedes ARCHIVE_TMP teardown at $TEARDOWN_LINE"
else
  echo "  FAIL: restore does not precede teardown (restore=$RESTORE_LINE teardown=$TEARDOWN_LINE)"
  echo "        SNAP lives inside ARCHIVE_TMP; tearing down first destroys the only copy"
  FAILURES=$((FAILURES + 1))
fi

echo ""
if [ "$FAILURES" = "0" ]; then echo "PASS"; exit 0; else echo "FAIL ($FAILURES)"; exit 1; fi
