#!/usr/bin/env bash
# Pre-push: the capability gate's structure checks, scoped to this branch.
# Called from lefthook.yml `pre-push`. Test: q-system/.q-system/tests/test_prepush_capability_gate.py
#
# Why (ASK-4814, rca-pr794-round-cap-2026-11-12.md root cause #1): PR #794
# shipped startup_census.py with no caller and no declared_inert entry. CI said
# `inert-engine` 21 to 23 minutes after each of three pushes; the same finding
# takes about 17 seconds here. Pre-commit runs verify.sh, which has no gate call,
# and lefthook had no pre-push section, so nothing local ran it. The 2026-08-22
# RCA had named the same fix as a habit ("run the gate before every push"); a
# habit with no hook did not hold.
#
# --check-only: structure, wiring and data checks, no test run (CI runs those).
# --diff-base <merge-base>: a finding main already has is printed as a note and
# never blocks, so this refuses only what the branch itself adds.
#
# Exit 0 lets the push through, exit 1 refuses it.
# Known limit: the gate reads the WORKING TREE, so an uncommitted file can turn
# it red or green. Worker trees push from a clean tree, so the result there is
# the pushed commit's.
set -euo pipefail

root="$(git rev-parse --show-toplevel)"

# No origin/main means no base to scope to. Refusing every push from such a
# clone would get this step switched off; CI still runs the full gate on the head.
if ! base="$(git -C "$root" merge-base HEAD origin/main 2>/dev/null)"; then
  echo "capability pre-push: SKIPPED, no merge-base between HEAD and origin/main. CI still runs the gate." >&2
  exit 0
fi

echo "capability pre-push: capability-gate.py --check-only --diff-base ${base:0:12}" >&2
set +e
python3 "$root/q-system/.q-system/scripts/capability-gate.py" \
  --repo-root "$root" --check-only --diff-base "$base"
rc=$?
set -e

case "$rc" in
  0) exit 0 ;;
  # The gate refuses a .claude/worktrees copy as non-authoritative (exit 3).
  # Blocking there would stop every push from such a tree for a reason the
  # change did not cause, so it is a loud skip.
  3) echo "capability pre-push: SKIPPED, the gate refuses a .claude/worktrees copy. CI still runs it." >&2
     exit 0 ;;
  *) echo "capability pre-push: REFUSED (gate exit $rc). Fix the RED lines above: wire the script, or add a declared_inert entry under q-system/.q-system/capability/declared_inert/." >&2
     exit 1 ;;
esac
