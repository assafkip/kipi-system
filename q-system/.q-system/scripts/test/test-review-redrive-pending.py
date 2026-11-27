#!/usr/bin/env python3
"""review-redrive must offer a PR whose reviewer slot is PENDING forever (ASK-5841).

THE DEFECT: PR #903 (ASK-5802) sat 5h with every CI check green and the gating
status `kipi/reviewer-approved` at PENDING (live rollup, 2026-11-27). The floor
posted a PENDING placeholder, and no verdict record existed. candidates() read
`reviewer_slot_posted()` as "a verdict exists and is not failing" and skipped it,
while linear-worker.sh said "the reviewer redrive owns it". Nothing picked it up.
A PENDING slot is not a verdict: the producer has not spoken yet. Silence read as
health is the same two-valued collapse sp-d87c5416 fixed for the absent slot.

The fix reuses the existing re-review action (kipi-dispatch.sh routes that exact
word to pr-review-agent.sh --post), and the dispatcher's own cap and
reviewer_live() guard still apply. No new action word.

Fixture: the verbatim shape of #903's rollup (gh pr view 903, 2026-11-27).
Run: python3 test-review-redrive-pending.py   (exit 0 = pass, 1 = fail)
"""
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("rr", SCRIPTS / "review-redrive.py")
rr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rr)

failures = []


def check(name, got, want):
    if got != want:
        failures.append("%s: got %r, want %r" % (name, got, want))


def rollup(state, floor=True):
    floor_run = [{"__typename": "CheckRun", "name": "reviewer-floor",
                  "status": "COMPLETED", "conclusion": "SUCCESS"}] if floor else []
    return floor_run + [
        {"__typename": "CheckRun", "name": "validate",
         "status": "COMPLETED", "conclusion": "SUCCESS"},
        {"__typename": "StatusContext", "context": "kipi/reviewer-approved",
         "state": state},
    ]


def pr(number, state, floor=True):
    return {"number": number, "isDraft": False, "isCrossRepository": False,
            "headRefName": "sana/ask-5802-step-0", "headRefOid": "9a0b8c6a" * 5,
            "title": "ASK-5802: step 0 improve_ground", "url": "u",
            "statusCheckRollup": rollup(state, floor)}


def offered(pr_objs):
    rr.CI.list_prs = lambda repo_dir: pr_objs
    with tempfile.TemporaryDirectory() as records:
        return rr.candidates("/nonexistent-repo", Path(records))


# 1. REPRODUCER: PENDING gating slot, no record -> one re-review.
got = offered([pr(903, "PENDING")])
check("REPRODUCER: pending slot with no record is offered", len(got), 1)
if got:
    check("REPRODUCER: as the existing re-review action", got[0]["action"], "re-review")

# 2. CONTROLS, MUST SURVIVE: a terminal SUCCESS slot is still left alone, and a
# FAILURE with no record is still the ASK-318 refusal.
check("CONTROL: SUCCESS slot not offered", offered([pr(904, "SUCCESS")]), [])
check("CONTROL: FAILURE slot, no record, not offered (ASK-318)",
      offered([pr(905, "FAILURE", floor=False)]), [])

# 2b. CONTROL: a terminal slot beside a pending one is settled (a verdict exists).
mixed = pr(907, "PENDING")
mixed["statusCheckRollup"].append({"__typename": "StatusContext",
                                   "context": "kipi/codex-approved", "state": "SUCCESS"})
check("CONTROL: terminal slot beside a pending one is not offered", offered([mixed]), [])

# 3. EXPECTED (a queued, never-started status) reads the same as PENDING.
check("EXPECTED slot is offered", len(offered([pr(906, "EXPECTED")])), 1)

if failures:
    print("FAIL")
    for f in failures:
        print("  " + f)
    sys.exit(1)
print("PASS: review-redrive offers a pending reviewer slot")
