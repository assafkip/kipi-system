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
    ABSENT  (never posted)            -> HERE, as a first re-review (sp-d87c5416).
                                         ASK-318/ASK-313 still own the PRODUCER
                                         question of why it never posted.
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
- A PR whose slot is FAILING but has no verdict record. The producer ran, posted
  a failure, and recorded nothing; re-reviewing that papers over a broken producer,
  which is the harder and more important bug. Still ASK-318/ASK-313.
  NOT the same as a slot that was NEVER POSTED -- there is no verdict to be
  missing there, and since 2026-08-06 that case IS selected (sp-d87c5416). The
  two were conflated while absence was rare; it is now 18 of 29 open PRs.
- A PR whose reviewer slot is POSTED and not FAILURE. A stale record next to a
  green slot means a newer review already landed. Note the word posted: the old
  wording said "not currently FAILURE", which silently included never-posted.
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
import re
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

# Where a PR's head lives, as the board answered it. ALIASED, NOT REDEFINED
# (PR #211 round 3, MAJOR 1). Round 2 put this predicate here, and the finding
# that followed was ci-redrive.candidates() -- the OTHER reader of the same two
# attacker-chosen facts -- having no such check at all. The field is requested in
# ci-redrive's PR_FIELDS, so the answer to "whose head is this" belongs in the
# module that asks the question, and every reader names that one copy.
SAME_REPO = CI.SAME_REPO
FORK = CI.FORK
UNSTATED = CI.UNSTATED


def record_path(records_dir, pr):
    return os.path.join(records_dir, "pr-%s.verdict.json" % pr)


# A THIRD answer, alongside a record and no record. json.JSONDecodeError IS a
# ValueError, so the original `except (OSError, ValueError): return None`
# reported a TRUNCATED record and an ABSENT one identically -- and every caller
# then states, in the operator-facing reason, that no verdict exists. That is
# the same false statement finding 1 was about, arriving through the other door.
# Latent rather than live: 0 unparseable across 96 records sampled 2026-08-06.
# (Independent probe on PR #123, sp-3e57348e.)
CORRUPT_RECORD = object()


def read_record(records_dir, pr):
    """The verdict record, None if absent, CORRUPT_RECORD if unreadable."""
    try:
        with open(record_path(records_dir, pr)) as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None
    except OSError:
        # Unreadable for a reason that is not absence (permissions, a directory
        # where a file belongs). Refusing beats claiming the review never ran.
        return CORRUPT_RECORD
    except ValueError:
        return CORRUPT_RECORD


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


# NOTE, unresolved on purpose (sp-833a2b76): should this be the GATING context
# only, or any reviewer slot?
#
# pr-review-agent.sh:189 writes `kipi/reviewer-approved` for the PRIMARY engine
# and an advisory `kipi/<engine>-approved` otherwise, and ci-redrive.py:202 says
# the split exists so neither engine "can answer for the other".
# CI.is_reviewer_slot matches `^kipi/[a-z0-9-]+-approved$`, i.e. BOTH, so a green
# ADVISORY slot currently reports the GATE as spoken (codex review of PR #123,
# finding 2, reproduced).
#
# It is left BROAD here because narrowing it flips an existing deliberate
# assertion -- test-review-redrive.sh:157 fixtures `kipi/codex-approved` green
# and requires "the live status must win over the record". Those two cannot both
# hold, and picking between them is a scope call about which question this
# predicate answers ("did SOME review land" vs "has the GATE spoken"), not a
# detail of making absence visible. Captured rather than decided here.
#
# THE REACHABILITY SENTENCE THAT USED TO SIT HERE IS NOW WRONG, and it was the
# only thing making this note feel safe to leave open. It read: "Unreachable
# today regardless: KIPI_REVIEW_PRIMARY_ENGINE defaults to codex, so
# `kipi/codex-approved` needs a hand-run with a non-default primary." The
# 2026-09-06 flip made claude PRIMARY, so `kipi/codex-approved` is exactly what
# an ordinary `--engine codex` run posts now.
#
# THE EXPOSURE DID NOT CHANGE, only the engine name in it: before the flip the
# reachable advisory slot was `kipi/claude-approved` and this predicate matched
# that one just as broadly. Nothing scheduled dispatches the advisory engine in
# either direction (linear-worker.sh names the primary explicitly), so an
# advisory slot still only exists after a hand-run. The decision above stays
# open on the same terms; what is corrected is a claim about WHY, because a
# stale safety argument is how an open note stops being re-examined.
GATING_SLOT = "kipi/reviewer-approved"  # named for the pending decision above


def reviewer_slot_posted(pr_obj):
    """True if the GATING reviewer slot appears in the rollup, whatever its state.

    The distinction reviewer_slot_failing() structurally cannot make. That
    predicate is two-valued -- failing / not-failing -- over a three-valued
    world: failing, passing, and NEVER POSTED. Callers that branch only on
    `not failing` read the third state as the second, so silence becomes health.

    Scar (sp-d87c5416, measured 2026-08-06): candidates() did
    `if not slots: continue`, so a PR the reviewer had never run against was
    skipped before its verdict record was even read. 18 of 29 open PRs were in
    that state, which made the MAJORITY of the backlog invisible to the only
    mechanism that could move it -- while `select` still printed 8 confident
    rework candidates and read like a full account of the queue.

    Deliberately state-blind: it answers "did the producer ever speak", never
    "what did it say". Folding the state back in here would recreate the same
    two-valued collapse one function further down.
    """
    for check in pr_obj.get("statusCheckRollup") or []:
        if not isinstance(check, dict):
            continue
        if check.get("__typename") == "StatusContext":
            name = check.get("context") or ""
        else:
            name = check.get("name") or ""
        # BROAD on purpose, and this is contested -- see GATING_SLOT above.
        if CI.is_reviewer_slot(name):
            return True
    return False


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


# THE ONE PLACE THE QUESTION IS ANSWERED, and since round 3 that place is
# ci-redrive.py. Round 2 answered it here and ci-redrive.candidates() -- reading
# the very same two attacker-chosen facts -- still had no check, which is exactly
# the "two copies of one trust rule, owned by neither" shape this name was
# introduced to end. Bound here so both callers below read as they did.
head_provenance = CI.head_provenance


def candidates(repo_dir, records_dir):
    out = []
    for pr_obj in CI.list_prs(repo_dir):
        # A FORK IS NEVER A CANDIDATE (PR #211 round 2, MAJOR 1; captured first
        # as sp-f7e6334d and arriving here as a finding).
        #
        # On a public repo anyone can open `sana/evil` titled "(ASK-352)", and
        # both of those are facts `CI.attribute` believes. That made an external
        # PR a REWORK candidate for someone else's issue. The second cost is the
        # expensive one: field 5 then carries `sana/evil` into `branch_guard`,
        # which compares it against `sana/ask-352`, refuses, and PARKS the real
        # issue every cycle until a human closes the external PR. The guard built
        # to stop wrong-target work becomes the thing that stalls the queue.
        #
        # THE POSTURE HERE IS THE OPPOSITE OF `branch_for`'s, FROM THE SAME
        # PREDICATE, and that asymmetry is the point rather than an oversight.
        # A skip in `branch_for` degrades to "no branch known", whose caller
        # already treats that as proceed -- fail-open. A skip HERE degrades to
        # "offer nothing", which silently stalls the whole redrive lane, the
        # exact defect class of the sibling finding in this same review. So a
        # CONFIRMED fork is dropped, and an UNSTATED provenance is kept as a
        # candidate but loses its branch below: an unconfirmed head may not route
        # work, and it may not switch the lane off either.
        provenance = head_provenance(pr_obj)
        if provenance == FORK:
            continue
        # An unconfirmed head is still worked, but it never ROUTES the work. The
        # dispatcher reads an empty field 5 as "no earlier observation" and takes
        # its fail-open arm, so the branch the naming rule produces is used --
        # which is the legitimate branch, never a head we could not vouch for.
        head_branch = pr_obj.get("headRefName") if provenance == SAME_REPO else None
        # A DRAFT IS THE AUTHOR SAYING NOT YET, and re-entering one spends a
        # converge round or a codex call on a tree nobody asked to be judged.
        #
        # THE DOCSTRING CLAIMED THIS AND THE CODE DID NOT DO IT (codex round 2 on
        # PR #91, minor). It also claimed "same rule as ci-redrive", and
        # ci-redrive does not filter drafts either -- it fetches `isDraft` in
        # PR_FIELDS and never reads it. So the comment was wrong twice, which is
        # the exact defect class this whole selector exists because of: ci-redrive
        # excluded the reviewer slots on the strength of a sentence asserting
        # something no code did. Captured separately for ci-redrive's own copy.
        if pr_obj.get("isDraft"):
            continue
        attributed = CI.attribute(pr_obj)
        if attributed is None:
            continue
        issue, agent, source = attributed
        slots = reviewer_slot_failing(pr_obj)
        pr = pr_obj.get("number")
        record = read_record(records_dir, pr)
        if not slots:
            if reviewer_slot_posted(pr_obj):
                # A gating verdict exists and is not failing. Nothing to redrive.
                continue
            if record is CORRUPT_RECORD:
                # Say what is true: the record is there and unreadable. Naming it
                # "never posted" would send the operator after a producer bug.
                sys.stderr.write(
                    "review-redrive: PR #%s has a verdict record that will not "
                    "parse -- refusing to call it absent. Left alone.\n" % pr)
                continue
            if record is not None:
                # NO STATUS, BUT A VERDICT RECORD EXISTS. Not a virgin PR.
                #
                # pr-review-agent.sh writes the record unconditionally but posts
                # the status only inside `if [ "$POST" = "1" ]` (:917, :975). So
                # `kipi review <PR>` without --post, the ":915 recorded but NO
                # gate moved" branch, and the missing-head-sha branch all leave
                # this shape, in the very directory read_record reads (:111).
                #
                # classify() answers "is this a refusal", which is the WRONG
                # question here. It returns (None, ...) for any non-refusal, and
                # the shared tail below does `if action is None: continue` -- so
                # a review that PASSED but was never posted fell out silently.
                # Sampled 2026-08-06 across 96 records: APPROVE WITH NITS 54,
                # REQUEST CHANGES 23, APPROVE 17, BLOCK 1, empty 1. The dropped
                # non-refusals are 71 of 96, the MAJORITY, and PR #23 is one --
                # approved, never posted, auto-merge armed and waiting forever on
                # a status nobody sends. The cheapest PR in the queue was the one
                # the selector could not see. (Independent probe on PR #123.)
                head_sha = pr_obj.get("headRefOid") or ""
                action, reason = classify(record, head_sha)
                if action is None:
                    # A PASSING review with no status. Not a refusal, not virgin.
                    action = REREVIEW
                    reason = ("the review passed but its status was never "
                              "posted (%s)" % (record.get("verdict") or "no verdict"))
                out.append({
                    "action": action, "reason": reason,
                    "issue": issue, "agent": agent, "issue_source": source,
                    "pr": pr, "url": pr_obj.get("url"),
                    "branch": head_branch,
                    "head_sha": head_sha, "slots": [],
                })
                continue
            else:
                # NEVER POSTED and never recorded -- the reviewer has not run
                # against this PR at all.
                #
                # NOT the ASK-318 case below. There, a FAILING slot with no record
                # means the producer ran and recorded nothing, so re-reviewing
                # papers over a broken producer. Here nothing ever claimed a
                # review happened, so there is no verdict to be missing.
                #
                # It emits the EXISTING re-review action on purpose.
                # kipi-dispatch.sh:1000 matches that exact string to run
                # pr-review-agent.sh --post; any other value falls through to
                # `./kipi converge`, so a new vocabulary word would not be inert,
                # it would silently buy a full rework round against a review that
                # does not exist. The word already means "nobody read the code,
                # there is no spec", which is precisely this state. The
                # distinction rides in the reason, which select prints.
                out.append({
                    "action": REREVIEW,
                    "reason": "the reviewer has never posted a verdict for this PR",
                    "issue": issue, "agent": agent, "issue_source": source,
                    "pr": pr, "url": pr_obj.get("url"),
                    "branch": head_branch,
                    "head_sha": pr_obj.get("headRefOid") or "",
                    "slots": [],
                })
                continue
        elif record is CORRUPT_RECORD:
            sys.stderr.write(
                "review-redrive: PR #%s has %s failing and an unreadable verdict "
                "record -- refusing to guess. Left alone.\n" % (pr, ",".join(slots)))
            continue
        elif record is None:
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
            "branch": head_branch, "head_sha": head_sha,
            "slots": slots,
        })
    return out


def branch_for(repo_dir, issue):
    """The ONE branch this issue's OPEN PRs live on, or a refusal (ASK-358).

    WHY (measured on ASK-352). converge.sh:83 derives the branch it commits into
    from the issue id alone -- `BRANCH="sana/$(lower ISSUE)"`. ASK-352 has TWO
    branches: `sana/ask-352` backs PR #90, which is CLOSED, and `sana/ask-352-clean`
    backs PR #91, which is open. So a rework dispatched for ASK-352 lands on the
    closed branch, where no PR and no reviewer will ever read it. That is
    silent-wrong-target, which is worse than a stall: the work looks done and is
    unreachable.

    `candidates()` above already fetches `headRefName` into every candidate dict
    and nothing downstream ever reads it. This is the reader.

    ONLY OPEN PRs, because `CI.list_prs` is `--state open` -- and that is the
    point rather than an accident. The closed branch is invisible here by
    construction, so "the issue's branch" and "the open PR's branch" differing is
    the whole signal.

    AMBIGUITY IS REFUSED, NOT RESOLVED, the same rule `title_issue` already
    applies to two ids in one title: two live branches for one issue means any
    pick is a guess, and the wrong branch worked is the defect this exists to
    stop. Returns a LIST so the caller can name them; the caller decides.

    FORK PRs ARE NOT EVIDENCE (PR #211 round 1, MAJOR 2). `CI.attribute` reads
    two facts and a fork's author chooses both: the head branch name and the PR
    title. On a public repo that means anyone can open `sana/evil` titled
    "... (ASK-352)" and this function would answer `sana/evil` for ASK-352 --
    which does not merely mislead, it PARKS the issue, because the guard
    downstream then sees a mismatch every cycle until a human closes the external
    PR. So the branch namespace is only believed from a head that lives in this
    repo, which requires push access to create.

    ABSENCE IS NOT CONFIRMATION. `isCrossRepository` is requested in PR_FIELDS,
    so a PR arriving without it is a board that did not answer the question, not
    a board answering "same repo". Unconfirmed provenance is skipped: the cost is
    an unresolved branch, which the caller already treats as "proceed", and that
    is the fail-open-on-not-knowing posture the whole guard is built on.
    """
    branches = []
    for pr_obj in CI.list_prs(repo_dir):
        # ONE PREDICATE, SHARED WITH `candidates()` (PR #211 round 2, MAJOR 1).
        # Both readers trust the same two attacker-chosen facts, so both ask the
        # same question through `head_provenance`. Here BOTH non-same-repo answers
        # skip, because this caller's skip is fail-OPEN: fewer branches means rc 1,
        # which the guard already treats as "round one, proceed".
        if head_provenance(pr_obj) != SAME_REPO:
            continue
        attributed = CI.attribute(pr_obj)
        if attributed is None:
            continue
        if attributed[0].upper() != issue.upper():
            continue
        head = pr_obj.get("headRefName")
        if head and head not in branches:
            branches.append(head)
    return sorted(branches)


def cmd_branch_for(repo_dir, issue):
    """rc 0 = the one branch (printed), 1 = no open PR, 3 = ambiguous.

    rc 2 is reserved for `gh could not answer` and is raised by the caller in
    main(), so a caller can never read an unreadable board as a fact. Three
    distinct non-zero codes because the caller's move differs for each: proceed
    (no PR yet, round one), refuse and name the branch (mismatch), refuse and
    name all of them (ambiguous).
    """
    branches = branch_for(repo_dir, issue)
    if not branches:
        sys.stderr.write(
            "review-redrive: %s has no OPEN PR, so no branch to resolve.\n" % issue)
        return 1
    if len(branches) > 1:
        sys.stderr.write(
            "review-redrive: %s maps to %d live branches (%s) -- refusing to "
            "guess which one the work belongs on.\n"
            % (issue, len(branches), ", ".join(branches)))
        return 3
    print(branches[0])
    return 0


def flag(cand):
    """One attempt per PR per action per head sha. See the module docstring."""
    return "review_%s_pr%s_%s" % (cand["action"].replace("-", ""),
                                  cand["pr"], (cand["head_sha"] or "nohead")[:12])


def reviewer_live(pr):
    """True if pr-review-agent.sh is reviewing THIS PR in the process table now.

    THE SYMMETRIC GATE TO converge_live, AND IT WAS MISSING (codex round 4 on
    PR #91, major). `mark-dispatched` claims the attempt flag the instant a
    re-review is handed out; pr-review-agent.sh then runs for 3-8 minutes. Every
    heartbeat inside that window read the flag as set, called the one attempt
    spent, and escalated -- paging about an outcome that did not exist yet. And
    because escalate() is once per PR per action per sha, THE FALSE PAGE ATE THE
    REAL ONE: the actual result, whatever it turned out to be, could never page.

    converge_live's own docstring already named this hazard ("a false page that
    also burns the once-per-signature flag is not [recoverable]"). REWORK was
    gated on it from the start and REREVIEW never was -- two paths, one guarded,
    which is this repo's recurring class.

    AN UNREADABLE TABLE ANSWERS TRUE, the same direction converge_live errs in
    and for the same reason. Reading "I cannot see the process table" as
    "nothing is running" is the direction that FIRES the false page, and the
    false page is the unrecoverable outcome; skipping one heartbeat is not.
    """
    table = CI.process_table()
    if table is None:
        sys.stderr.write(
            "review-redrive: could not read the process table -- treating the "
            "reviewer as live, offering nothing.\n")
        return True
    # `(?:\s|$)` with MULTILINE so a live review of PR #1010 does not read as a
    # review of #101 -- the same boundary converge_live's pattern guards for
    # `--issue ASK-29` against `ASK-295`.
    pattern = re.compile(
        r"pr-review-agent\.sh\s+%s(?:\s|$)" % re.escape(str(pr)), re.MULTILINE)
    return bool(pattern.search(table))


def escalate_flag(cand):
    return "review_escalated_%s_pr%s_%s" % (
        cand["action"].replace("-", ""), cand["pr"],
        (cand["head_sha"] or "nohead")[:12])


def escalate(path, cand):
    """The ONE message about this PR, and only after the machine tier is spent.

    WHY IT EXISTS (codex review of PR #91, major). Without it, the spent-attempt
    branch above just wrote a stderr line and moved on, so a PR that got its one
    redrive and stayed failing was silently ignored forever. That is the exact
    defect this whole selector was built to kill -- a terminal state with no
    consumer -- reintroduced one level down, inside the fix for it. A cap with no
    escalation is not a cap, it is a quieter version of the 29-hour park.

    ONCE PER PR PER ACTION PER HEAD SHA, matching the attempt flag it reports on.
    The dispatcher reaches this state on every heartbeat for as long as the PR
    sits failing, so paging per run is a page every 15 minutes about one fact
    that has not changed -- the cry-wolf failure that trains the reader to skim.
    Keyed on the sha and not on the PR alone because a push is new information:
    the next sha earns its own attempt and, if that also fails, its own page.

    EVERY CLAUSE IS AN OBSERVATION. It says which action was spent and what the
    reviewer's record actually holds now, because the two failures look identical
    from outside and the reader's next move is different for each: a spent
    RE-REVIEW that is still unusable means the reviewer cannot review this PR at
    all, while a spent REWORK still refused means the agent could not satisfy it.

    The claim is the gate: `ledger_claim` is False if another run already paged,
    and False on a lock timeout or write failure -- nothing was recorded, so
    nothing may act as though it was, and the next run pages instead.
    """
    if not CI.ledger_claim(path, cand["issue"], escalate_flag(cand)):
        return False
    CI.notify(
        "review-redrive: %s PR #%s still has %s failing after the machine tier. "
        "What the machine tried: one %s at %s. The reviewer's record now reads "
        "%s. %s"
        % (cand["issue"], cand["pr"], (", ".join(cand["slots"]) or "(never posted)"), cand["action"],
           (cand["head_sha"] or "an unknown head")[:8], cand["reason"],
           cand["url"]))
    return True


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
        # THE CAP-OUT PARK, FIRST (ASK-871). converge.sh stopping this ISSUE at
        # its round cap is a refusal to touch it at all, so it outranks every
        # question below -- which action, is anything live, is the attempt spent.
        #
        # IMPORTED FROM ci-redrive, NOT REIMPLEMENTED, for the same reason
        # `is_reviewer_slot` is: both redrives must refuse the same parked issue,
        # and two copies of one refusal rule is how a state ends up owned by
        # neither. It reads a fact, writes nothing, and cannot page -- so putting
        # it ahead of the in-flight gates does not reintroduce the false-page
        # hazard those gates exist for.
        if CI.capout_skip(path, c["issue"], "review-redrive", c["pr"]):
            continue
        # IN-FLIGHT GATES, BOTH ACTIONS, BEFORE THE LEDGER IS READ. Each action
        # launches a different long-running process, so each needs its own
        # liveness question -- but the reason is one reason, and the ledger read
        # below must not be reached while the work it reports on is still going.
        #
        # A rework becomes a converge on the issue, so a converge already live for
        # it means the work is in flight and offering it would cost the fresh pick
        # its slot (ci-redrive PR #73 r2, finding 2).
        if c["action"] == REWORK and CI.converge_live(c["issue"]):
            sys.stderr.write(
                "review-redrive: %s PR #%s needs rework but a converge for it is "
                "already live -- not offering it.\n" % (c["issue"], c["pr"]))
            continue
        # A re-review launches pr-review-agent.sh on the PR, not a converge on the
        # issue, so it asks the process table a different question -- and for a
        # while it asked none at all. The comment that used to sit here said a
        # re-review "is not gated on that" and stopped, reading the absence of the
        # converge gate as a decision rather than a gap. See reviewer_live.
        if c["action"] == REREVIEW and reviewer_live(c["pr"]):
            sys.stderr.write(
                "review-redrive: %s PR #%s needs re-review but a reviewer for it "
                "is already live -- not offering it.\n" % (c["issue"], c["pr"]))
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
            escalate(path, c)   # machine tier spent and the slot is STILL failing
            continue
        sys.stderr.write("review-redrive: %s PR #%s -> %s (%s)\n"
                         % (c["issue"], c["pr"], c["action"], c["reason"]))
        # FIELD 5 IS THE BRANCH (PR #211 round 1, MAJOR 3). candidates() has
        # always carried headRefName and this line dropped it, so the dispatcher
        # had to ask gh a SECOND time to learn where the work belonged. Two reads
        # of mutable state is a window: PR #91 closing in between makes the second
        # answer "no open PR", which the guard reads as round one and lets the
        # work land on exactly the branch it exists to reject. Appended rather
        # than inserted so every existing `cut -f1..f4` reader is untouched.
        print("%s\t%s\t%s\t%s\t%s" % (c["action"], c["issue"], c["pr"],
                                      c["head_sha"], c.get("branch") or ""))
        return 0
    return 1


def cmd_mark_dispatched(issue, action, pr, head_sha):
    # THE SAME SHARED CLAIM ci-redrive uses, not `ledger_claim` (codex on PR #210).
    # `cmd_select`'s capout gate gates the OFFER; this is where the attempt is
    # spent, and a cap-out recorded between the two used to sail straight through
    # it. Imported rather than reimplemented for the reason `capout_skip` is: two
    # copies of one refusal rule is how a state ends up owned by neither.
    cand = {"action": action, "pr": pr, "head_sha": head_sha}
    return 0 if CI.claim_unless_capped(
        CI.attempts_path(), issue, flag(cand), "review-redrive", pr) else 1


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

    bfp = sub.add_parser("branch-for")
    bfp.add_argument("--issue", required=True)

    args = ap.parse_args(argv)
    if args.cmd == "mark-dispatched":
        return cmd_mark_dispatched(args.issue, args.action, args.pr, args.head_sha)
    if args.cmd == "branch-for":
        try:
            return cmd_branch_for(args.repo_dir, args.issue)
        except CI.GhUnavailable as exc:
            # Same rc as `select`, and for the same reason: an unreadable board
            # is not the fact "no branch". The caller must be able to tell them
            # apart or it will refuse a dispatch over one gh outage.
            sys.stderr.write("review-redrive: %s -- no branch resolved.\n" % exc)
            return 2
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
