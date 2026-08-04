#!/usr/bin/env python3
"""The machine consumer for a PR the REVIEWER refused (ASK-352).

WHY THIS FILE EXISTS
--------------------
Six PRs sat parked for ~29 hours with `kipi/codex-approved: FAILURE`. Nothing in
this repo looks at a PR in that state, so nothing ever re-entered it.

`ready()` in linear-worker.sh returns backlog/unstarted issues only, and an issue
with a live PR is In Progress -- so the fresh-pick path cannot see it.
ci-redrive.py deliberately EXCLUDES the reviewer's own verdict slots
(`kipi/reviewer-approved`, `kipi/<engine>-approved`) from what it calls red CI,
and that exclusion is CORRECT and stays: including them re-dispatched PRs whose
build was passing (PR #73, live). But the exclusion rests on a claim in its own
docstring --

    "It is also already handled: the reviewer comments on the Linear issue and
     the worker re-dispatches from there."

-- and that is false. There is no such selector. The exclusion was right about
what ci-redrive should not do and wrong about what something else was doing.
This is that something else. Two consumers, one event each, neither reading the
other's slot.

THE THREE STATES A REQUIRED CONTEXT CAN BE IN, AND WHO OWNS EACH
----------------------------------------------------------------
    ABSENT  (never posted)            -> ASK-318 producer + ASK-313 detector
    SUCCESS (but nothing merges)      -> ASK-310, pr-land-if-green.sh
    FAILURE (the reviewer refused)    -> here

ASK-310 scopes to "CLEAN with all required contexts SUCCESS" and cannot touch a
failing context; ASK-318 scopes to absence and calls absence a correct refusal.
The gap was named in ASK-310's own checklist ("alarm on a required context ABSENT
past N minutes, distinct from failing") and never built.

FAILURE IS TWO OPPOSITE THINGS, AND THE VERDICT DOES NOT SEPARATE THEM
-----------------------------------------------------------------------
This is the whole difficulty, and it is why sp-2a832233 had to land first.

    PR #82 -- a real review, one real major, REQUEST CHANGES.
              Someone objected. There are findings to work.   -> REWORK
    PR #80 -- codex echoed the prompt's own FINDINGS template and answered
              "Reply `OK` and I'll execute". Nobody read the code, and the
              record ALSO says REQUEST CHANGES.               -> RE-REVIEW

Measured over all 79 verdict records on 2026-08-03: 13 unusable, carrying every
verdict in the range -- APPROVE on 11 (all merged), REQUEST CHANGES on #80 and
#83, empty on #89. #80's `stated` verdict was lifted out of the PROMPT'S grading
rule, echoed to stdout by `codex exec`, so it is byte-identical to a real
objection. A selector reading the verdict, or reading the `failure` status it
produces, hands a never-reviewed PR to an agent with nothing to fix -- which
burns a rework round and ends in the same failure state, forever.

The only reliable signal is `review_is_usable()` (ASK-274) on the review FILE.
pr-review-agent.sh now persists that answer as `usable` in the record, so this
script reads a stored fact rather than re-deriving one from a file it does not
own and that rotates away.

WHERE USABILITY COMES FROM, RANKED, AND NEVER FROM A REIMPLEMENTATION
---------------------------------------------------------------------
1. `usable` in the record (records written from ASK-352 onward).
2. Otherwise, if the review file still exists: ask the LIB, by sourcing
   pr-verdict-lib.sh and running review_is_usable. Not a Python port of it. A
   second implementation of "did a review happen" is exactly the drift
   pr-verdict-lib.sh was extracted to end, and it would drift toward permissive.
3. Otherwise UNKNOWN -> treated as NOT usable, i.e. re-review.

Direction of that last error, deliberately: a needless re-review costs one codex
call and produces a real verdict. A needless rework costs a full converge round
against a review with no findings in it and lands back here. The cap below bounds
the first; nothing bounds the second except the cap it would waste.

WHAT IT REFUSES TO TOUCH
------------------------
- A PR with no verdict record at all. That is ABSENT, and it belongs to
  ASK-318/ASK-313. Manufacturing a review for a PR whose producer never ran would
  paper over the missing producer, which is the harder and more important bug.
- A PR whose reviewer slot is not currently FAILURE. A stale record next to a
  green slot means a newer review already landed.
- A PR that is a draft, or not attributable to an agent+issue. Same rule as
  ci-redrive: an unrecognised branch owner is a human's branch, left alone.

THE CAP, AND WHY IT IS KEYED ON THE SHA
---------------------------------------
One attempt per PR per action per HEAD SHA, in the same flock'd attempts ledger
(attempts-ledger.py) ci-redrive and the worker use. Keyed on the sha and not on a
failure signature because the failure here is always the same string -- the slot
name -- so a signature would collapse to one attempt per PR forever, and a PR
that pushed a real fix could never be re-reviewed.

The consequence is the honest one: a re-review that comes back unusable AGAIN at
the same sha is not retried. It escalates once and stops. Retrying a phantom is
how the loop that burned 29 hours started.

THE OFFER IS NOT THE CLAIM (ci-redrive PR #73 review, finding 2)
----------------------------------------------------------------
`select` writes nothing. The dispatcher calls `mark-dispatched` immediately before
it launches, past every guard that can still abort, and THAT call is the atomic
claim: rc 0 means it is yours, rc non-zero means someone else has it or the ledger
could not be written -- the same answer, because nothing was recorded.
"""

import argparse
import importlib.util
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, "pr-verdict-lib.sh")
DEFAULT_RECORDS = os.path.join(
    os.path.expanduser("~"), ".config", "kipi", "pr-reviews")


def _load_ci_redrive():
    """Import ci-redrive.py for the parts both selectors must agree on.

    IMPORTED, NOT COPIED. `is_reviewer_slot` is the single definition of which
    contexts belong to the reviewer: ci-redrive EXCLUDES exactly that set and this
    script SELECTS exactly that set. Two hand-maintained copies of one regex is
    how a slot ends up owned by both consumers or by neither, and "owned by
    neither" is the 29-hour park this file exists to end.

    `attribute`, `list_prs` and `converge_live` come along for the same reason:
    the attribution rules (branch tail, then PR title, never a guess) cost a
    defect each to get right and must not be re-derived here.
    """
    path = os.path.join(HERE, "ci-redrive.py")
    spec = importlib.util.spec_from_file_location("ci_redrive", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


CI = _load_ci_redrive()

# Verdicts that mean a human-equivalent reviewer objected and left a spec behind.
# Kept as a literal set rather than "not an approval": an EMPTY verdict is not an
# objection, it is an unstated one, and routing empty to rework is precisely the
# #89 mistake (the review never ran, so there is nothing to rework toward).
REWORK_VERDICTS = {"REQUEST CHANGES", "BLOCK"}

REWORK = "rework"
REREVIEW = "re-review"


def record_path(records_dir, pr):
    return os.path.join(records_dir, "pr-%s.verdict.json" % pr)


def read_record(records_dir, pr):
    try:
        with open(record_path(records_dir, pr)) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def usable_from_lib(review_file):
    """Ask pr-verdict-lib.sh, the one definition, or None if it cannot answer.

    None is a THIRD answer and callers must not fold it into False-with-confidence
    -- it is folded into "treat as not usable" one level up, where the reason is
    recorded, so a legacy record and a genuinely phantom review do not report the
    same cause to the operator.
    """
    if not review_file or not os.path.exists(review_file):
        return None
    if not os.path.exists(LIB):
        return None
    proc = subprocess.run(
        ["bash", "-c",
         '. "$1" >/dev/null 2>&1 || exit 2; review_is_usable "$2"',
         "_", LIB, review_file],
        capture_output=True, text=True)
    if proc.returncode == 2:
        return None
    return proc.returncode == 0


def usability(record):
    """(is_usable, why) for a verdict record.

    `usable` is a real JSON boolean from ASK-352 onward. It is checked with `is
    None` and not with truthiness on purpose: the key can legitimately be False,
    and `if not record.get("usable")` reads a present-and-False the same as an
    absent key, which would send every phantom down the legacy path and report
    the wrong reason for the same action.
    """
    stored = record.get("usable")
    if stored is not None:
        return bool(stored), "record"
    probed = usable_from_lib(record.get("review", ""))
    if probed is None:
        return False, "unknown (pre-ASK-352 record, review file gone)"
    return probed, "probed the review file"


def reviewer_slot_failing(pr_obj):
    """The reviewer slot names that are FAILURE on this PR right now.

    Both halves of the rollup, same as ci-redrive's failing_checks -- the verdict
    is posted as a StatusContext today, and a name rule that guards one half is a
    rule that stops working the day the producer changes shape.
    """
    names = []
    for check in pr_obj.get("statusCheckRollup") or []:
        if not isinstance(check, dict):
            continue
        if check.get("__typename") == "StatusContext":
            context = check.get("context") or ""
            if CI.is_reviewer_slot(context) and \
                    (check.get("state") or "").upper() in CI.FAILED_STATES:
                names.append(context)
            continue
        name = check.get("name") or ""
        if not CI.is_reviewer_slot(name):
            continue
        if (check.get("status") or "").upper() != "COMPLETED":
            continue
        if (check.get("conclusion") or "").upper() in CI.FAILED_CONCLUSIONS:
            names.append(name)
    return sorted(names)


def classify(record, head_sha):
    """(action, reason) for a PR whose reviewer slot is failing.

    DRIFT OUTRANKS THE VERDICT, same posture rework_gate takes for exit 40: a
    verdict is a statement about a diff at a moment, and if the head moved the
    statement is about code that is no longer there. Re-review first; the fresh
    record then decides. Absent is not drift -- a record with no head_sha predates
    ASK-216 and falls through to the verdict, because reading absent-as-drift
    would re-review every parked PR on the board at once.
    """
    is_usable, why = usability(record)
    if not is_usable:
        return REREVIEW, "the review never ran (%s)" % why

    reviewed_sha = (record.get("head_sha") or "").strip()
    if reviewed_sha and head_sha and reviewed_sha != head_sha:
        return REREVIEW, "reviewed %s but head is now %s" % (
            reviewed_sha[:8], head_sha[:8])

    verdict = (record.get("verdict") or "").strip()
    if verdict in REWORK_VERDICTS:
        return REWORK, "reviewer said %s at the current head" % verdict
    if not verdict:
        # A usable review that stated nothing. Rare, and it is still not a spec:
        # there are no findings to work from, so the answer is another review,
        # never a rework round guessing at what to change.
        return REREVIEW, "the review is usable but states no verdict"
    return None, "verdict %s is not a refusal" % verdict


def candidates(repo_dir, records_dir):
    out = []
    for pr_obj in CI.list_prs(repo_dir):
        attributed = CI.attribute(pr_obj)
        if attributed is None:
            continue
        issue, agent, source = attributed
        slots = reviewer_slot_failing(pr_obj)
        if not slots:
            continue
        pr = pr_obj.get("number")
        record = read_record(records_dir, pr)
        if record is None:
            # ABSENT, not FAILURE-with-no-record. Owned by ASK-318/ASK-313.
            sys.stderr.write(
                "review-redrive: PR #%s has %s failing but NO verdict record -- "
                "that is the absent-producer case (ASK-318), not this one. "
                "Left alone.\n" % (pr, ",".join(slots)))
            continue
        head_sha = pr_obj.get("headRefOid") or ""
        action, reason = classify(record, head_sha)
        if action is None:
            continue
        out.append({
            "action": action, "reason": reason, "issue": issue, "agent": agent,
            "issue_source": source, "pr": pr, "url": pr_obj.get("url"),
            "branch": pr_obj.get("headRefName"), "head_sha": head_sha,
            "slots": slots,
        })
    return out


def flag(cand):
    """One attempt per PR per action per head sha. See the module docstring."""
    return "review_%s_pr%s_%s" % (cand["action"].replace("-", ""),
                                  cand["pr"], (cand["head_sha"] or "nohead")[:12])


def cmd_select(cands, show_all):
    if not cands:
        return 1
    if show_all:
        for c in cands:
            print("%s\t%s\t%s\t%s\t%s" % (
                c["action"], c["issue"], c["pr"], c["head_sha"], c["reason"]))
        return 0

    path = CI.attempts_path()
    for c in cands:
        # A rework becomes a converge on the issue, so a converge already live for
        # it means the work is in flight and offering it would cost the fresh pick
        # its slot (ci-redrive PR #73 r2, finding 2). A re-review launches the
        # reviewer, not a converge, so it is not gated on that.
        if c["action"] == REWORK and CI.converge_live(c["issue"]):
            sys.stderr.write(
                "review-redrive: %s PR #%s needs rework but a converge for it is "
                "already live -- not offering it.\n" % (c["issue"], c["pr"]))
            continue
        # A READ. NOT ci-redrive's `ledger_recorded`, which is a WRITE wearing a
        # reader's name: it calls `claim-flag` and answers True on rc 0 (just
        # claimed) OR rc 1 (already claimed). Using it here made `select` claim
        # every candidate the first time it ran and then skip all of them for
        # having been claimed -- so the selector reported "already had its one
        # attempt" for 14 PRs on its first ever invocation and offered nothing.
        # A selector that silently offers nothing is indistinguishable from the
        # 29-hour park it was built to end. Caught by the live acceptance run,
        # not by the 13 unit cases, because those all used `--all`, which returns
        # before the ledger is touched.
        #
        # `get` is the only read op the ledger exposes; op_claim stores `True`,
        # so a set flag reads back as the string "True" and an unset one as the
        # default. Empty default, not "0": "0" is a non-empty string and would
        # make every unset flag read as recorded, which is this same bug again.
        if CI.ledger_get(path, c["issue"], flag(c)):
            sys.stderr.write(
                "review-redrive: %s PR #%s already had its one %s attempt at %s "
                "-- not offering it again.\n"
                % (c["issue"], c["pr"], c["action"], (c["head_sha"] or "?")[:8]))
            continue
        sys.stderr.write("review-redrive: %s PR #%s -> %s (%s)\n"
                         % (c["issue"], c["pr"], c["action"], c["reason"]))
        print("%s\t%s\t%s\t%s" % (c["action"], c["issue"], c["pr"], c["head_sha"]))
        return 0
    return 1


def cmd_mark_dispatched(issue, action, pr, head_sha):
    cand = {"action": action, "pr": pr, "head_sha": head_sha}
    return 0 if CI.ledger_claim(CI.attempts_path(), issue, flag(cand)) else 1


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-dir", default=".")
    ap.add_argument("--records-dir", default=os.environ.get(
        "KIPI_VERDICT_DIR", DEFAULT_RECORDS))
    sub = ap.add_subparsers(dest="cmd", required=True)

    sel = sub.add_parser("select")
    sel.add_argument("--all", action="store_true")

    mark = sub.add_parser("mark-dispatched")
    mark.add_argument("--issue", required=True)
    mark.add_argument("--action", required=True, choices=[REWORK, REREVIEW])
    mark.add_argument("--pr", required=True)
    mark.add_argument("--head-sha", default="")

    args = ap.parse_args(argv)
    if args.cmd == "mark-dispatched":
        return cmd_mark_dispatched(args.issue, args.action, args.pr, args.head_sha)
    try:
        cands = candidates(args.repo_dir, args.records_dir)
    except CI.GhUnavailable as exc:
        # rc 2 is NOT "nothing to do": the caller must keep its fresh pick rather
        # than read an unreadable board as an empty one.
        sys.stderr.write("review-redrive: %s -- nothing was claimed.\n" % exc)
        return 2
    return cmd_select(cands, args.all)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
