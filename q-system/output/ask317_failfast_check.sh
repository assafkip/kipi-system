#!/usr/bin/env bash
# Negative self-test for PR #80 minor 2: the reproducer must NOT exit 0 when its
# setup fails. Before the fix it did, so automation could accept evidence that
# never ran.
#
# The reviewer's own repro was TMPDIR=/dev/null. That is environment-dependent --
# it failed inside their codex sandbox, and on this host mktemp still resolves a
# usable directory, so it exits 0 for a reason that has nothing to do with the
# fix. A check that cannot fail for the reason you care about is decoration, so
# case 1 forces the failure deterministically with a stub mktemp on PATH.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
REPRO="$ROOT/q-system/output/ask317_phantom_finding_repro.sh"
FAILED=0

BIN="$(mktemp -d)" || { echo "FATAL: mktemp -d failed" >&2; exit 1; }
trap 'rm -rf "$BIN"' EXIT
printf '%s\n' '#!/bin/sh' 'exit 1' > "$BIN/mktemp"
chmod +x "$BIN/mktemp"

check() {  # name expected_nonzero_or_zero
  local name="$1" want="$2" rc=0
  shift 2
  "$@" >/dev/null 2>&1 || rc=$?
  if [ "$want" = nonzero ] && [ "$rc" -eq 0 ]; then
    echo "FAIL: $name -> rc=0, expected non-zero"; FAILED=1
  elif [ "$want" = zero ] && [ "$rc" -ne 0 ]; then
    echo "FAIL: $name -> rc=$rc, expected 0"; FAILED=1
  else
    echo "PASS: $name -> rc=$rc"
  fi
}

check "mktemp fails (stub on PATH)"  nonzero env "PATH=$BIN:$PATH" bash "$REPRO"
check "capture path does not exist"  nonzero bash "$REPRO" "$ROOT/q-system/output/does-not-exist.md"
check "capture exists but is empty"  nonzero bash "$REPRO" /dev/null
check "happy path"                   zero    bash "$REPRO"

[ "$FAILED" -eq 0 ] && echo "ALL PASS" || echo "SOME FAILED"

# THE CHECK MUST BE ABLE TO FAIL. Run case 1 against the PRE-FIX script (branch
# tip before main was merged). If that also passes, this file is decoration.
echo
echo "=== discrimination: same case against the pre-fix repro (25340b59) ==="
OLD="$BIN/old-repro.sh"
git -C "$ROOT" show 25340b59:q-system/output/ask317_phantom_finding_repro.sh > "$OLD"
old_rc=0
env "PATH=$BIN:$PATH" bash "$OLD" >/dev/null 2>&1 || old_rc=$?
echo "pre-fix rc with a failing mktemp = $old_rc  (0 == the bug the reviewer found)"
[ "$old_rc" -eq 0 ] || echo "WARNING: the pre-fix script also failed; case 1 is not discriminating"

exit "$FAILED"
