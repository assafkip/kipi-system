#!/usr/bin/env python3
"""review-redrive must see a reviewer slot that was NEVER POSTED (sp-d87c5416).

THE DEFECT
----------
`candidates()` did `slots = reviewer_slot_failing(pr_obj); if not slots: continue`.
That predicate is two-valued (failing / not-failing) over a three-valued world:

    failing        the reviewer objected or came back phantom   -> handled
    passing        a verdict exists and is green                -> correctly skipped
    NEVER POSTED   the reviewer has not run at all              -> ALSO skipped

The third state is silence, and silence was read as health. Measured 2026-08-06:
18 of 29 open PRs had no reviewer status context at all, so the majority of the
backlog was invisible to the only mechanism that could move it.

WHY THIS IS NOT THE ASK-318 CASE, WHICH STAYS REFUSED
-----------------------------------------------------
ASK-318 is "a FAILING slot with no verdict record on disk" -- the producer ran,
posted a failure, and recorded nothing. Re-reviewing that papers over a broken
producer, so the module refuses it, and TEST 3 holds that refusal in place.

An ABSENT slot is a different animal: there is no verdict to be missing, because
no review was ever claimed to have happened. Requiring a verdict record before
a PR may receive its FIRST review is circular, so the absent path deliberately
skips the record lookup.

WHY IT EMITS `re-review` AND NOT A NEW ACTION NAME
--------------------------------------------------
kipi-dispatch.sh:1000 branches on the exact string "re-review" to run
`pr-review-agent.sh <PR> --post`. ANY other action string falls through to
`./kipi converge` -- a full rework round against a review that does not exist.
So a new vocabulary word would not be a no-op, it would be an expensive wrong
action. The existing word already means "nobody read the code; there is no
spec", which is exactly true here. The distinction is carried in the REASON,
which is what select and the escalation message print.

Fixtures are the real producer's shapes, captured 2026-08-06 from
`gh pr view <n> --json statusCheckRollup`:
  PR #121 -> []                                              (the absent case)
  PR #80  -> CheckRun validate SUCCESS
             StatusContext kipi/reviewer-approved FAILURE
Nothing here shells gh: CI.list_prs is replaced with a fixture list.

Run: python3 test-review-redrive-absent.py   (exit 0 = pass, 1 = fail)
"""
import importlib.util
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent

spec = importlib.util.spec_from_file_location("rr", SCRIPTS / "review-redrive.py")
rr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rr)

failures = []


def check(name, got, want):
    if got != want:
        failures.append("%s: got %r, want %r" % (name, got, want))


# --- the real producer's rollup shapes -------------------------------------
ABSENT_ROLLUP = []                      # verbatim from PR #121
FAILING_ROLLUP = [
    {"__typename": "CheckRun", "name": "validate",
     "status": "COMPLETED", "conclusion": "SUCCESS"},
    {"__typename": "StatusContext", "context": "kipi/reviewer-approved",
     "state": "FAILURE"},
]
PASSING_ROLLUP = [
    {"__typename": "StatusContext", "context": "kipi/reviewer-approved",
     "state": "SUCCESS"},
]


def pr(number, rollup, branch="sana/ask-447-sweep", draft=False,
       title="Verify a launchd job's paused/running state against declared "
             "intent (ASK-447, sp-2c7e5819)"):
    """A PR object shaped like the one gh actually returns.

    `title` is NOT decoration. CI.attribute() reads the branch tail FIRST and
    the PR title SECOND, and this branch (`sana/ask-447-sweep`, a real one)
    yields nothing from its tail -- the issue id is only in the title. My first
    fixture omitted the field, attribute() returned None, and the reproducer
    stayed red for a reason that had nothing to do with the defect. An invented
    fixture tests the invention; this one carries what the producer sends.
    """
    return {
        "number": number, "isDraft": draft, "headRefName": branch,
        "title": title,
        "headRefOid": "b61f215a52007610ce66bf39c9b45ce0a837f838",
        "url": "https://github.com/assafkip/kipi-system/pull/%s" % number,
        "statusCheckRollup": rollup,
    }


def offered(pr_objs):
    """candidates() over a fixture list. records_dir is an empty tmpdir, so every
    read_record returns None -- which is the truth for all four fixtures."""
    rr.CI.list_prs = lambda repo_dir: pr_objs
    with tempfile.TemporaryDirectory() as records:
        return rr.candidates("/nonexistent-repo", Path(records))


# =============================================================================
# 1. THE REPRODUCER: a PR whose reviewer slot was never posted.
# =============================================================================
got = offered([pr(121, ABSENT_ROLLUP)])
check("REPRODUCER: an absent reviewer slot is offered", len(got), 1)
if got:
    check("REPRODUCER: and it is offered as re-review, the action dispatch "
          "actually routes to pr-review-agent", got[0]["action"], "re-review")
    check("REPRODUCER: the reason names the absence, so it is not confused "
          "with a phantom review", "never" in got[0]["reason"].lower(), True)

# =============================================================================
# 2. CONTROL, MUST SURVIVE: a posted, passing slot is still left alone.
# =============================================================================
# This is the assertion the fix could most easily break: if "not failing" became
# "offer it", every green PR in the fleet would be re-reviewed forever.
check("CONTROL: a passing reviewer slot is not offered",
      offered([pr(51, PASSING_ROLLUP)]), [])

# =============================================================================
# 3. CONTROL, MUST SURVIVE: the ASK-318 refusal is untouched.
# =============================================================================
# A FAILING slot with no verdict record is the absent-PRODUCER case and is
# deliberately left alone. The fix must not swallow it into the absent path.
check("CONTROL: failing slot with no verdict record is still refused (ASK-318)",
      offered([pr(80, FAILING_ROLLUP)]), [])

# =============================================================================
# 4. CONTROL, MUST SURVIVE: a draft is still the author saying not yet.
# =============================================================================
check("CONTROL: a draft with no reviewer slot is not offered",
      offered([pr(122, ABSENT_ROLLUP, draft=True)]), [])

# =============================================================================
# 5. An unattributable branch is a human's branch, absent slot or not.
# =============================================================================
check("CONTROL: an unattributable branch is left alone",
      offered([pr(999, ABSENT_ROLLUP, branch="dependabot/npm/lodash-4.17.21", title="Bump lodash from 4.17.20 to 4.17.21")]), [])

# =============================================================================
# 5b. A record ON DISK with no status posted is NOT a virgin PR.
# =============================================================================
# Codex review of PR #123, finding 1 (major), reproduced before accepting.
# pr-review-agent.sh writes the verdict record unconditionally but posts the
# status only inside `if [ "$POST" = "1" ]` (:917, :975). So `kipi review <PR>`
# without --post, a failed status post (":915 recorded but NO gate moved"), or a
# missing head sha all leave a usable REQUEST CHANGES record with an empty
# rollup -- and OUT_DIR (:111) is the same dir read_record reads.
#
# The first version of this fix skipped read_record on the absent path, so this
# shape was offered as re-review with the reason "the reviewer has never posted a
# verdict", while classify() on that very record said rework. That spends a
# review round manufacturing a second verdict next to a real one with findings,
# and points the operator at a producer bug that does not exist.
import json as _json
_tmp = tempfile.mkdtemp()
_sha = "b61f215a52007610ce66bf39c9b45ce0a837f838"
Path(_tmp, "pr-121.verdict.json").write_text(_json.dumps({
    "pr": 121, "issue": "ASK-447", "verdict": "REQUEST CHANGES",
    "stated": "REQUEST CHANGES", "usable": True, "round": 1,
    "review": "", "head_sha": _sha, "ts": "now"}))
rr.CI.list_prs = lambda repo_dir: [pr(121, ABSENT_ROLLUP)]
_got = rr.candidates("/nonexistent-repo", Path(_tmp))
check("a verdict record with no posted status is rework, not a first review",
      [(c["action"], c["reason"]) for c in _got],
      [("rework", "reviewer said REQUEST CHANGES at the current head")])


# =============================================================================
# 6. NEGATIVE SELF-TEST: test 1's assertion must be able to fail.
# =============================================================================
# A green test 1 could mean "the absent slot is now seen" or "offered() returns
# something for anything I hand it". Feed it a shape that must NOT be offered
# and prove the same assertion goes the other way. Without this, test 1 is a
# filter with an opinion rather than a filter with a rule.
neg = offered([pr(51, PASSING_ROLLUP)])
if len(neg) != 0:
    failures.append("NEGATIVE SELF-TEST: offered() returned %d for a passing "
                    "slot, so test 1's non-empty result proves nothing" % len(neg))
else:
    print("ok   negative self-test: the same call returns [] for a passing slot")

if failures:
    print("FAIL")
    for f in failures:
        print("  " + f)
    sys.exit(1)
print("PASS: review-redrive sees a never-posted reviewer slot")
sys.exit(0)
