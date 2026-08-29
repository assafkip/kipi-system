#!/usr/bin/env bash
# reviewer-floor.yml must never RUN pr-controlled code while holding statuses:write.
#
# WHY THIS EXISTS (Codex major, PR #96). The job holds `statuses: write` and then
# executes a script out of its checkout. With no `ref:`, actions/checkout takes
# the PULL REQUEST's code, so on a same-repository PR the author could edit
# reviewer-floor.sh to post `success` and mint the very required context this
# workflow exists to defend.
#
# That is the ASK-312 phantom-approval hole -- unreviewed PRs merging on a forged
# kipi/reviewer-approved, twice on PR #74 -- re-entered through the workflow's
# PERMISSIONS rather than through the script's logic. reviewer-floor.sh itself is
# careful: FLOOR_STATE is a literal `failure` and its own test kills a
# floor-posts-success mutant. None of that helps if an attacker supplies the
# script.
#
# The property: the code that RUNS comes from the base (already on main, already
# reviewed); the PR head is only DATA -- the sha argument that gets inspected and
# posted to.
#
# Checked by grep rather than by parsing YAML on purpose: python3 here has no
# yaml module, and a check that cannot run on the machine that must run it is not
# a check. The assertions are on exact strings the workflow either has or does not.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WF="${REVIEWER_FLOOR_WORKFLOW:-$HERE/../../../../.github/workflows/reviewer-floor.yml}"
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  ok   $1"; }
bad() { FAIL=$((FAIL+1)); echo "  FAIL $1"; }

if [ ! -f "$WF" ]; then
  echo "  FAIL workflow not found at $WF"; exit 1
fi

# 1. The checkout is pinned to the BASE.
if grep -qE '^[[:space:]]*ref:[[:space:]]*\$\{\{[[:space:]]*github\.event\.pull_request\.base\.sha[[:space:]]*\}\}' "$WF"; then
  ok "checkout is pinned to pull_request.base.sha"
else
  bad "checkout is pinned to pull_request.base.sha (an unpinned checkout runs PR-controlled code)"
fi

# 2. It is NOT pinned to the head, which would be the defect wearing a ref:.
if grep -qE '^[[:space:]]*ref:.*pull_request\.head\.sha' "$WF"; then
  bad "checkout must not use head.sha as its ref (that is the PR's own code)"
else
  ok "checkout does not take its ref from the PR head"
fi

# 3. The head sha is still used, as the ARGUMENT. Without this the fix would
#    "pass" by posting to the wrong commit, which is a different outage.
if grep -qE 'reviewer-floor\.sh "\$\{\{[[:space:]]*github\.event\.pull_request\.head\.sha' "$WF"; then
  ok "the head sha is still what gets inspected and posted to"
else
  bad "the head sha is still what gets inspected and posted to"
fi

# 4. statuses:write is the privilege that makes the above load-bearing. If it
#    ever goes away this test should be re-read, not silently kept passing.
if grep -qE '^[[:space:]]*statuses:[[:space:]]*write' "$WF"; then
  ok "statuses: write is present (so the base-pin above is load-bearing)"
else
  bad "statuses: write not found -- re-read this test, its premise changed"
fi

echo
if [ "$FAIL" -eq 0 ]; then echo "PASS: $PASS checks green"; exit 0; fi
echo "FAILED: $FAIL"; exit 1
