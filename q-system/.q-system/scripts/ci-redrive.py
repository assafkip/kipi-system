#!/usr/bin/env python3
"""The machine consumer for red CI on an agent-opened PR (ASK-295).

WHY THIS FILE EXISTS
--------------------
On 2026-08-02 the founder got three unprompted GitHub emails:

    [assafkip/kipi-system] PR run failed: Skeleton Validation - ... (ASK-292)
    [assafkip/kipi-system] PR run failed: Skeleton Validation - ... (ASK-288)
    [assafkip/kipi-system] Run failed: Skeleton Validation - sana/block-expiry

An autonomous agent opened each PR, CI went red, GitHub mailed the repo owner.
Both failures were a single CORRECT catch (test-terminal-states.sh, 13 passed
1 failed; main was green). True, and still useless to him -- he does not work on
the code. The agent that opened the PR does.

It is a dead end by construction, not by oversight. `ready()` in linear-worker.sh
returns only backlog/unstarted issues, and an issue with a live PR is In Progress.
So nothing in this repo ever looks at that PR again, GitHub's notifier is the only
thing that notices, and its only addressee is the repo owner. ASK-294's instrument
(the slack-notify.sh chokepoint plus a producer audit) structurally cannot reach
this: the producer is GitHub, driven by workflow conclusion, outside every sink
this repo owns. The only lever inside the repo is to stop the condition persisting.

THE FOUR DECISIONS, MADE (ASK-295's Definition of Ready)
-------------------------------------------------------
1. DOES A RED AGENT PR REACH THE FOUNDER? No. Not on the red itself. He is
   reached exactly once per failure, after the machine tier is spent, by a
   message that says what the machine already tried. `founder_never_the_next_actor`.

2. WHERE THE CONSUMER RUNS: inside the existing registry-driven dispatcher
   (kipi-dispatch.sh), as a preferred pick ahead of a fresh issue -- NOT a new
   launchd job. Per-repo jobs die silently (the income-scanner scar: 6 days dark)
   and the dispatcher already owns every cap this needs: MAX_CONCURRENT, the
   daily budget, the liveness assert, the notify sink. A second job would be a
   second copy of all four, drifting.

3. ATTRIBUTION IS THE BRANCH FIRST, THE PR TITLE SECOND, and never a guess.

4. THE CAP IS ONE ATTEMPT PER PR PER FAILURE SIGNATURE, held in the existing
   attempts ledger (single-writer, flock'd -- attempts-ledger.py), and spent by
   the DISPATCHER confirming a dispatch, not by this script offering a pick.

Points 3 and 4 each cost a defect in round 1 and are written out below.

ATTRIBUTION: TWO SOURCES, RANKED, NEITHER OF THEM A GUESS (review finding 3)
---------------------------------------------------------------------------
Round 1 read the issue id out of the branch name and nothing else, on the
reasoning that the worker cuts every branch as `<agent>/<issue>`. The worker
does. A SANA SESSION DRIVEN BY HAND DOES NOT: `sana/block-expiry` is PR #69, it
is one of the three PRs that mailed the founder in the scar above, it was red on
`validate` while I wrote the rule that skipped it, and the rule's own docstring
cited it as motivation. A tool that misses the case it was built for is worse
than no tool, because the gap is now believed to be covered.

So: the branch tail if it is an issue id (`sana/ask-295` -> ASK-295), otherwise
the PR TITLE, which carries the id because `linear-issue-ref-check.py` makes it
mandatory in the commit message the title is cut from. Reading a stated id is
not guessing. Guessing is what is still refused: a title naming TWO distinct
issues is ambiguous and is left alone, because picking either is how the wrong
issue gets re-dispatched.

The `<agent>/` prefix must be a KNOWN agent (AGENT_BRANCH_OWNERS). This errs
toward doing nothing: an unrecognised owner is treated as a human's branch and
left exactly as it behaves today. Handing a founder's branch to an agent is the
expensive direction of this error, so the ambiguity resolves the cheap way.

A REVIEW VERDICT IS NOT CI (review finding 1)
---------------------------------------------
`pr-review-agent.sh` posts its verdict as a commit STATUS -- `kipi/reviewer-approved`
for the primary engine, `kipi/<engine>-approved` for the advisory one -- and
anything that is not an approval is posted as `state: failure`. That status rides
in the same `statusCheckRollup` as the CI checks, so round 1 counted every
REQUEST CHANGES review as red CI. Live consequence, on this script's own PR: #73
had `validate: SUCCESS` and `kipi/reviewer-approved: FAILURE`, so the handler
would have re-dispatched a PR with a passing build and then paged the founder
that the build was still red.

It is also already handled: the reviewer comments on the Linear issue and the
worker re-dispatches from there. Two consumers for one event is how a PR gets
worked twice. So the reviewer's own slots are excluded and nothing else is -- a
third-party commit status (`ci/external-builder`) is real CI and stays in.

THE CAP IS SPENT ON THE DISPATCH, NOT ON THE OFFER (review finding 2)
--------------------------------------------------------------------
Round 1 claimed the attempt inside `redrive`, at the moment it printed the pick.
kipi-dispatch.sh can still abort after that -- a converge run already live for
that issue exits 0 without launching anything. The attempt was then spent on a
dispatch that never happened, and on the very next heartbeat the founder was
paged with a message asserting a re-dispatch AND a second CI failure, neither of
which had occurred.

Two changes. `redrive` is READ-ONLY: it offers a pick and writes nothing, so an
aborted heartbeat costs nothing and the next one offers the same PR again. The
dispatcher calls `mark-dispatched` immediately before it launches, and that call
is the atomic claim: rc 0 means it is yours to dispatch, rc 1 means someone else
already has it and you must not. A lock timeout is rc 1 as well -- nothing was
recorded, so nothing may act as though it was.

And the escalation now says only what it observed. It records the head sha at
dispatch time and compares it with the head sha now: the head moved (the agent
pushed and the same check failed again) and the head did not move (it was handed
back and nothing landed) are DIFFERENT facts and get different sentences.

A RUN STILL IN FLIGHT IS NOT A DEAD END (round 2, findings 1 and 2)
-------------------------------------------------------------------
The dispatcher's heartbeat is 900s; a converge run is minutes to tens of minutes.
So the heartbeat AFTER a redrive dispatch finds the same PR still red -- the
agent has not pushed yet -- with the attempt flag already set. Round 2 went
straight to `escalate()` there and paged the founder that the machine tier was
spent and the branch "stopped rather than hand back an unchanged tree", about a
converge that was at that moment still running.

The second half is the worse half. `escalate()` claims `ci_escalated_<sig>` on
its way out, so when the converge really did end and leave the PR red, the one
true page had already been spent on the false one. A wrong page that also
silences the right page is strictly worse than no page.

The same blindness cost the fresh pick too. `redrive` offered the live issue,
kipi-dispatch.sh overwrote NEXT with it, and the duplicate-dispatch guard 40
lines later exited 0 -- so a ready issue that WAS dispatchable was discarded,
every heartbeat, for as long as that converge ran.

Both are one missing fact: is a converge for this issue running right now.
`converge_live()` answers it from the process table, the same source and the same
command line kipi-dispatch.sh's own duplicate guard reads (`ps -Ao args=`, no
pipe -- see that guard's comment for why a pipe into `grep -q` under pipefail is
load-dependent). A live candidate is neither offered nor escalated.

ONE reader, not two. The shell could have grown its own copy of this check, but
two liveness rules drifting apart is the defect class this repo keeps paying for,
and only the Python side can suppress the escalation. So the guard lives here and
the dispatcher inherits it by not being offered the pick.

AN UNREADABLE PROCESS TABLE COUNTS AS LIVE. It is the cheap direction of the
error: erring the other way pages the founder about a run that may be in flight
and burns the once-per-signature flag doing it, while erring this way costs one
quiet heartbeat -- which is exactly the behaviour before this file existed.

THE SIGNATURE IS THE CHECK SET, AND TODAY THAT IS ONE CHECK (review finding 4)
-----------------------------------------------------------------------------
The signature is the set of failing check NAMES, deliberately NOT the head sha:
a re-push that fails the same check again is the same failure, and re-dispatching
on it is how a handler re-runs a flake forever. ASK-295 names that risk by hand.

Stated plainly rather than promised: this repo posts exactly ONE CI check
(`validate`, from Skeleton Validation), so the signature is constant per PR here
and the effective cap is ONE hand-back per PR, full stop. The "a genuinely new
failure earns a fresh attempt" behaviour is real in the code and unreachable in
this repo until a second required check exists. Round 1's docstring sold it as a
live property, which is a claim the repo could not honour.

WHAT IT DOES NOT DO
-------------------
It does not merge, close, comment on, or re-run anything on GitHub. It reads PR
state and answers one question: which issue should the dispatcher hand back to
its agent right now. The dispatching is the dispatcher's, and stays under the
dispatcher's caps.

    scan            -> JSON of red agent PRs (read-only, no ledger write, no page)
    redrive         -> read-only. prints
                       `<issue>\t<signature>\t<head_sha>\t<branch>\t<pr>`,
                       exit 0. Nothing to offer -> exit 1. gh could not answer
                       -> exit 2. Escalates any candidate whose attempt is spent.
                       <branch> is the head this selector OBSERVED, empty when
                       the board did not confirm the head lives in this repo;
                       the dispatcher's branch_guard reads it instead of asking
                       gh a second time.
    mark-dispatched -> the atomic claim. exit 0 = dispatch it, exit 1 = do not.

THE PROBE'S rc IS PART OF ITS ANSWER. `gh pr list` failing is not "no red PRs":
reading it that way is how a real red PR goes unhandled behind a clean exit. It
is the same class as arm_automerge's three-state armed/unarmed/could-not-tell,
and it is why a gh failure is exit 2 with no ledger write rather than exit 1.
"""

import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LEDGER_SCRIPT = os.path.join(HERE, "attempts-ledger.py")
DEFAULT_NOTIFY = os.path.join(HERE, "slack-notify.sh")
DEFAULT_ATTEMPTS = os.path.join(
    os.environ.get("KIPI_STATE_DIR", os.path.expanduser("~/.config/kipi")),
    "linear-worker-attempts.json")

# `<owner>/<anything>`. The owner has to be a KNOWN agent -- see the attribution
# section of the docstring. An unknown owner is a human's branch.
BRANCH_RE = re.compile(r"^(?P<owner>[a-z][a-z0-9_-]*)/(?P<tail>.+)$")
AGENT_BRANCH_OWNERS = frozenset(
    o.strip() for o in os.environ.get("KIPI_AGENT_BRANCH_OWNERS", "sana").split(",")
    if o.strip())

# `ask-295` as a whole branch tail, anchored: `ask-295-followup` is a name a
# human chose and is not an issue id.
TAIL_ISSUE_RE = re.compile(r"^(?P<issue>[a-z]{2,6}-\d+)$")
# `(ASK-288)` anywhere in a PR title. linear-issue-ref-check.py makes the id
# mandatory in the commit message, and the PR title is cut from it.
TITLE_ISSUE_RE = re.compile(r"\b([A-Za-z]{2,6}-\d+)\b")

# The reviewer's own verdict slots: `kipi/reviewer-approved` (primary engine) and
# `kipi/<engine>-approved` (advisory). Posted by pr-review-agent.sh, NOT by CI,
# and already consumed by the reviewer's own comment on the Linear issue.
REVIEWER_CONTEXT_RE = re.compile(r"^kipi/[a-z0-9-]+-approved$")

# A CheckRun that COMPLETED with one of these is red. Everything else -- queued,
# in progress, skipped, neutral -- is not a failure, and treating "still running"
# as red would re-dispatch an issue whose CI has not finished answering.
FAILED_CONCLUSIONS = {"FAILURE", "TIMED_OUT", "CANCELLED", "STARTUP_FAILURE",
                      "ACTION_REQUIRED"}
# The legacy commit-status half of the same rollup speaks a different vocabulary.
FAILED_STATES = {"FAILURE", "ERROR"}

# isCrossRepository says whether the head branch lives in THIS repo or in a fork.
# Every other field here is chosen by whoever opened the PR, including the two
# `attribute()` reads (branch name and title), so on a public repo they are all
# attacker-supplied. This one is GitHub's answer, not the author's, and it is the
# only field that separates "an agent pushed this branch" from "a stranger named
# their fork branch that". Requested for every consumer; read today by
# review-redrive.branch_for (PR #211 round 1, MAJOR 2).
PR_FIELDS = ("number,headRefName,headRefOid,url,title,statusCheckRollup,"
             "isDraft,isCrossRepository")

# Where a PR's head lives, as the BOARD answered it. Three values, not a boolean,
# because "somebody else's repo" and "the board did not say" are different facts
# and the readers pay opposite costs for confusing them. THIS is the authority --
# review-redrive.py aliases these names rather than keeping a second copy, because
# the field is requested here and two hand-maintained copies of one trust rule is
# how a surface ends up owned by neither (PR #211 round 3, MAJOR 1).
SAME_REPO = "same-repo"
FORK = "fork"
UNSTATED = "unstated"


def head_provenance(pr_obj):
    """SAME_REPO / FORK / UNSTATED for one PR's head.

    ABSENCE IS NOT CONFIRMATION. `isCrossRepository` is requested in PR_FIELDS,
    so a PR arriving without it is a board that did not answer the question, not
    a board answering same-repo. A caller that cannot tell those apart has to
    pick one cost for both, and the two callers here want opposite ones.
    """
    flagged = pr_obj.get("isCrossRepository")
    if flagged is False:
        return SAME_REPO
    if flagged is None:
        return UNSTATED
    return FORK


class GhUnavailable(Exception):
    """gh could not answer. NOT the same claim as `no red PRs`."""


def list_prs(repo_dir):
    gh = os.environ.get("KIPI_GH", "gh")
    cmd = [gh, "pr", "list", "--state", "open", "--json", PR_FIELDS,
           "--limit", "50"]
    try:
        proc = subprocess.run(cmd, cwd=repo_dir, capture_output=True, text=True)
    except OSError as exc:
        raise GhUnavailable("could not run %s: %s" % (gh, exc))
    if proc.returncode != 0:
        raise GhUnavailable(
            "`gh pr list` exited %d: %s"
            % (proc.returncode, (proc.stderr or "").strip()[:200]))
    try:
        return json.loads(proc.stdout or "[]")
    except ValueError as exc:
        raise GhUnavailable("`gh pr list` returned unparseable JSON: %s" % exc)


# --- attribution -------------------------------------------------------------

def branch_owner(branch):
    """The agent that owns this branch, or None if no known agent does."""
    match = BRANCH_RE.match(branch or "")
    if not match:
        return None
    owner = match.group("owner")
    return owner if owner in AGENT_BRANCH_OWNERS else None


def title_issue(title):
    """The ONE issue id a title names, or None.

    Two distinct ids is ambiguity, and this refuses ambiguity rather than
    resolving it -- the wrong issue re-dispatched is worse than none.
    """
    found = {m.upper() for m in TITLE_ISSUE_RE.findall(title or "")}
    return found.pop() if len(found) == 1 else None


def attribute(pr):
    """(issue, agent, source) for an agent PR, or None. Never a guess."""
    branch = pr.get("headRefName") or ""
    agent = branch_owner(branch)
    if agent is None:
        return None
    tail = BRANCH_RE.match(branch).group("tail")
    tail_match = TAIL_ISSUE_RE.match(tail)
    if tail_match:
        return (tail_match.group("issue").upper(), agent, "branch")
    issue = title_issue(pr.get("title"))
    if issue:
        return (issue, agent, "title")
    return None


# --- what counts as red ------------------------------------------------------

def is_reviewer_slot(name):
    return bool(REVIEWER_CONTEXT_RE.match((name or "").strip()))


def failing_checks(pr):
    """Names of the CI checks that are red RIGHT NOW, sorted and de-duplicated.

    The reviewer's verdict slots are not CI and are excluded -- see the docstring.
    Applied to both halves of the rollup: the status API is where the verdict is
    posted today, and a name-based rule that only guards one half is a rule that
    stops working the day the producer changes shape.
    """
    names = set()
    for check in pr.get("statusCheckRollup") or []:
        if not isinstance(check, dict):
            continue
        if check.get("__typename") == "StatusContext":
            context = check.get("context") or "(unnamed status)"
            if is_reviewer_slot(context):
                continue
            if (check.get("state") or "").upper() in FAILED_STATES:
                names.add(context)
            continue
        # CheckRun, and anything else the rollup grows later that speaks
        # status/conclusion. A check that has not COMPLETED has not failed.
        name = check.get("name") or "(unnamed check)"
        if is_reviewer_slot(name):
            continue
        if (check.get("status") or "").upper() != "COMPLETED":
            continue
        if (check.get("conclusion") or "").upper() in FAILED_CONCLUSIONS:
            names.add(name)
    return sorted(names)


# --- is work on this issue already in flight ---------------------------------
# `kipi converge --issue ASK-n` execs converge.sh with those same arguments, so
# the process table holds `... converge.sh --issue ASK-n --max-rounds N`. Same
# command line kipi-dispatch.sh's duplicate-dispatch guard matches, on purpose:
# one shape, read in one place, so the two cannot drift.

def process_table():
    """Every running command line, or None if the table could not be read.

    None is a THIRD answer and callers must not fold it into "nothing running" --
    same rule as GhUnavailable above. No shell pipe: `ps | grep -q` dies to
    SIGPIPE under pipefail often enough to look correct in testing and fail in
    production, which is what kipi-dispatch.sh's own guard was fixed for.
    """
    try:
        proc = subprocess.run(shlex.split(os.environ.get("KIPI_PS", "ps -Ao args=")),
                              capture_output=True, text=True)
    except OSError:
        return None
    return proc.stdout if proc.returncode == 0 else None


def converge_live(issue):
    """True if a converge run for this issue is in the process table right now.

    An unreadable table answers True: see the module docstring. Skipping one
    heartbeat is recoverable; a false page that also burns the once-per-signature
    flag is not.
    """
    table = process_table()
    if table is None:
        sys.stderr.write("ci-redrive: could not read the process table -- treating "
                         "every candidate as already in flight, offering nothing.\n")
        return True
    # `(?:\s|$)` with MULTILINE so `--issue ASK-29` does not match `ASK-295`.
    pattern = re.compile(r"converge\.sh\s+--issue\s+%s(?:\s|$)" % re.escape(issue),
                         re.MULTILINE)
    return bool(pattern.search(table))


def signature(names):
    """Identity of a FAILURE, not of a run.

    Head sha is left out deliberately -- see the module docstring. Same checks
    red again == same problem == the machine tier is already spent on it. In
    THIS repo that means one hand-back per PR, because `validate` is the only
    CI check posted; the discrimination is real code waiting on a second check.
    """
    return hashlib.sha1("\n".join(names).encode("utf-8")).hexdigest()[:12]


def candidates(repo_dir):
    out = []
    for pr in list_prs(repo_dir):
        # A FORK IS NEVER A CANDIDATE (PR #211 round 3, MAJOR 1). This repo is
        # PUBLIC. `attribute` below reads exactly two facts -- the head branch
        # name and the PR title -- and on a fork the person who opened the PR
        # chose both. So anyone could open `sana/ask-358` titled "... (ASK-358)"
        # against this repo, let its CI go red, and have that PR selected as the
        # machine's work for a real Linear issue: the agent gets handed back an
        # issue on the strength of a stranger's branch, and the once-per-PR
        # attempt for the REAL PR is spent on it.
        #
        # The field was requested in PR_FIELDS and then never read, which is the
        # worst of the three states: the query looks defended and answers nothing.
        # It is not a null check. `isCrossRepository` is the only field in the
        # rollup that GitHub asserts rather than the author, and it is the whole
        # boundary between "an agent pushed this branch" (which needs push
        # access) and "a stranger named their fork branch that" (which needs a
        # GitHub account).
        #
        # UNSTATED IS KEPT, BUT LOSES ITS BRANCH -- the same asymmetry
        # review-redrive.candidates() takes, from the same predicate. Dropping
        # every unconfirmed head would let one board that stops returning the
        # field switch the whole red-CI lane off silently, which is the sibling
        # defect class. So a CONFIRMED fork is dropped, and an unconfirmed head
        # is still worked but may not ROUTE the work: field 4 of the offer goes
        # out empty and branch_guard falls back to the naming rule, which is the
        # legitimate branch, never a head we could not vouch for.
        provenance = head_provenance(pr)
        if provenance == FORK:
            sys.stderr.write(
                "ci-redrive: PR #%s head %s lives in a fork -- not a candidate, "
                "its branch name and title are the author's to choose\n"
                % (pr.get("number"), pr.get("headRefName")))
            continue
        attributed = attribute(pr)
        if attributed is None:
            continue                       # not an agent PR, or not attributable
        issue, agent, source = attributed
        failing = failing_checks(pr)
        if not failing:
            continue
        out.append({
            "issue": issue,
            "agent": agent,
            "issue_source": source,
            "pr": pr.get("number"),
            "url": pr.get("url"),
            "branch": pr.get("headRefName") if provenance == SAME_REPO else None,
            "head_sha": pr.get("headRefOid") or "",
            "failing_checks": failing,
            "signature": signature(failing),
        })
    return out


# --- the ledger, through its single writer -----------------------------------
# Never a direct read-modify-write of the attempts file. attempts-ledger.py is
# the one writer for exactly the reason its docstring gives: six unsynchronised
# copies of this let an issue exceed a cap and keep being dispatched.

def ledger_get(path, issue, key):
    proc = subprocess.run(
        [sys.executable, LEDGER_SCRIPT, path, "get", issue, key, ""],
        capture_output=True, text=True)
    return (proc.stdout or "").strip() if proc.returncode == 0 else ""


def _ledger_claim_rc(path, issue, flag):
    proc = subprocess.run(
        [sys.executable, LEDGER_SCRIPT, path, "claim-flag", issue, flag],
        capture_output=True, text=True)
    if proc.returncode not in (0, 1):
        sys.stderr.write("ci-redrive: ledger refused `%s` for %s: %s\n"
                         % (flag, issue, (proc.stderr or "").strip()[:200]))
    return proc.returncode


def _ledger_claim_rc_uncapped(path, issue, flag):
    """Raw rc of `claim-flag-uncapped`: 0 claimed, 1 already, 4 parked, 2/3 unwritten.

    Separate from `_ledger_claim_rc` because the caller must distinguish 4 from
    the rest; folding it into a bool here would put the park back in the same
    bucket as "someone else owns it" and lose the operator line that names how to
    un-park it.
    """
    proc = subprocess.run(
        [sys.executable, LEDGER_SCRIPT, path, "claim-flag-uncapped", issue, flag],
        capture_output=True, text=True)
    if proc.returncode not in (0, 1, 4):
        sys.stderr.write("ci-redrive: ledger refused `%s` for %s: %s\n"
                         % (flag, issue, (proc.stderr or "").strip()[:200]))
    return proc.returncode


def ledger_claim(path, issue, flag):
    """True the first time this flag is claimed anywhere, False otherwise.

    A lock timeout (rc 3) or a hard write failure (rc 2) is FALSE, never True.
    Nothing was recorded, so nothing may act as though it was -- the next
    scheduled run claims it instead.
    """
    return _ledger_claim_rc(path, issue, flag) == 0


def ledger_recorded(path, issue, flag):
    """True if the flag is now set, whether this call or an earlier one set it.

    Different question from `ledger_claim`, and the difference is load-bearing:
    for a fact being RECORDED, "someone already wrote it" is success. Only a
    lock timeout or a write failure is not.
    """
    return _ledger_claim_rc(path, issue, flag) in (0, 1)


def redrive_flag(cand):
    return "ci_redrive_%s" % cand["signature"]


def head_flag(head_sha):
    return "ci_redrive_head_%s" % (head_sha or "unknown")[:12]


def head_recorded_flag(cand):
    return "ci_redrive_headrec_%s" % cand["signature"]


def notify(message):
    script = os.environ.get("KIPI_NOTIFY", DEFAULT_NOTIFY)
    if not os.path.exists(script):
        return
    try:
        subprocess.run(["bash", script, message], capture_output=True, text=True)
    except OSError as exc:
        sys.stderr.write("ci-redrive: notify failed: %s\n" % exc)


def what_happened_since(path, cand):
    """The one sentence about the branch that this run can actually evidence.

    Three states, and the third is named rather than folded into one of the
    first two. `ci_redrive_headrec_<sig>` says a head sha WAS recorded at
    dispatch; `ci_redrive_head_<sha>` says which one. Absent recording is not
    evidence of a push.
    """
    checks = ", ".join(cand["failing_checks"])
    if not ledger_get(path, cand["issue"], head_recorded_flag(cand)):
        return "what has happened on the branch since is not recorded."
    if ledger_get(path, cand["issue"], head_flag(cand["head_sha"])):
        return ("no new commit has landed on the branch since, so it stopped "
                "rather than hand back an unchanged tree.")
    return ("a new commit landed and %s failed again, so it stopped rather "
            "than re-run a flake." % checks)


def escalate(path, cand):
    """The founder's ONE message about this failure, and only after the machine.

    It says what was tried, per terminal-state-redrive-2026-08-01 item 3. Once
    per signature, because the dispatcher reaches this state on every heartbeat
    for as long as the PR sits red -- paging per run is a page every 15 minutes
    for one fact that has not changed.

    Every clause is an observation. Round 1 asserted a re-dispatch and a second
    CI failure unconditionally; both were untrue on the very first heartbeat
    after an offer the dispatcher never launched.
    """
    if not ledger_claim(path, cand["issue"], "ci_escalated_%s" % cand["signature"]):
        return False
    notify(
        "ci-redrive: %s PR #%s is still red on %s after the machine tier. What "
        "the machine tried: it handed %s back to %s once for this failure; %s %s"
        % (cand["issue"], cand["pr"], ", ".join(cand["failing_checks"]),
           cand["issue"], cand["agent"], what_happened_since(path, cand),
           cand["url"]))
    return True


def attempts_path():
    return os.environ.get("KIPI_ATTEMPTS", DEFAULT_ATTEMPTS)


# --- the cap-out park, read by BOTH redrives ---------------------------------
# ONE DEFINITION, TWO CALLERS (ASK-871), for the same reason `is_reviewer_slot`
# lives here: review-redrive.py imports this module rather than keeping its own
# copy, and two hand-maintained copies of a refusal rule is how a state ends up
# owned by both consumers or by neither.
#
# THE FACT IT READS: converge.sh stopped this ISSUE at its round cap and wrote it
# to the ledger. Every other bound in this loop keys on a PR and a head sha,
# which is deliberate -- a PR that pushes a real fix must earn a fresh attempt --
# and it is exactly why nothing caught ASK-830 on 2026-08-16: each of its six
# rounds moved the head, so every per-sha cap read as fresh while the ISSUE had
# already been given up on. This is the missing axis, not a tightening of that one.

CAPOUT_CLEAR = ("python3 q-system/.q-system/scripts/attempts-ledger.py "
                "%s clear-capout %s")


def capout(path, issue):
    """The recorded reason converge gave up on this issue, or "" if it has not.

    HONEST BOUNDARY: `ledger_get` answers "" both for "no cap-out" and for a
    ledger it could not read at all, so a ledger that will not parse reads as
    "not capped" and the redrive proceeds. That is the pre-existing direction of
    every budget in this file (the `get` op swallows a read failure and returns
    the default), not something this gate introduces -- but it means the silence
    of this function is not proof the issue was never capped.
    """
    if not ledger_get(path, issue, "capout"):
        return ""
    return ledger_get(path, issue, "capout_why") or "no reason recorded"


def capout_skip(path, issue, who, pr):
    """True if this issue is parked; writes the operator line saying so.

    Says how to UN-park it in the same breath. A refusal a human cannot reverse
    is a permanent park, and the founder reading this line is the only thing
    standing between a parked issue and the 29-hour outage.
    """
    why = capout(path, issue)
    if not why:
        return False
    sys.stderr.write(
        "%s: %s PR #%s -- converge already gave up on this issue (%s). Not "
        "re-entering it until a human clears the cap-out: %s\n"
        % (who, issue, pr, why, CAPOUT_CLEAR % (path, issue)))
    return True


def claim_unless_capped(path, issue, flag, who, pr=""):
    """The atomic claim, refusing a parked issue in the SAME transaction.

    True only when this run now owns the attempt. Replaces `ledger_claim` at both
    mark-dispatched call sites (codex on PR #210, major): `capout_skip` guards the
    read-only OFFER, and the claim that actually spends the attempt asked only
    whether the flag was free. kipi-dispatch.sh does real work between the two --
    a ps snapshot, a converge-live probe, a budget read -- so a cap-out landing in
    that window authorized the dispatch it was written to stop.

    Reading capout here, before calling claim-flag, would only shrink the window.
    Two subprocesses cannot be atomic against a third writer, so the refusal is
    delegated to the ledger's `claim-flag-uncapped`, which answers under the same
    flock that sets the flag. rc 4 is the park; anything else non-zero is the
    pre-existing "someone else owns it, or nothing was written" answer.

    ONE DEFINITION, TWO CALLERS, like `capout_skip` and `is_reviewer_slot` above
    and for the same reason: the two redrives must refuse the same parked issue.
    """
    rc = _ledger_claim_rc_uncapped(path, issue, flag)
    if rc == 0:
        return True
    if rc == 4:
        # LOUD, not quiet. A skipped dispatch nobody can see is the silent-park
        # failure mode; the founder was already paged once by converge's exit-2,
        # so this line is for whoever reads the dispatch log -- and it carries the
        # clearing command because a park with no exit is the worse outage.
        sys.stderr.write(
            "%s: %s%s -- converge already gave up on this issue (%s). NOT "
            "dispatching, and the attempt is NOT spent. Clear it with: %s\n"
            % (who, issue, (" PR #%s" % pr) if pr else "",
               capout(path, issue) or "no reason recorded",
               CAPOUT_CLEAR % (path, issue)))
        return False
    sys.stderr.write(
        "%s: the attempt for %s%s was already claimed (or the ledger could not be "
        "written) -- not dispatching.\n"
        % (who, issue, (" PR #%s" % pr) if pr else ""))
    return False


def cmd_redrive(cands):
    """READ-ONLY. Offers one pick; the dispatcher spends it via mark-dispatched."""
    path = attempts_path()
    chosen = None
    for cand in cands:
        # BEFORE both the offer and the escalation, because a live converge
        # invalidates both: the dispatcher would discard its fresh pick for a
        # candidate it cannot launch, and the founder would be paged that a
        # still-running attempt had stopped -- burning the one page owed to him
        # when it really does. Round 2 did both. See the module docstring.
        if converge_live(cand["issue"]):
            sys.stderr.write(
                "ci-redrive: %s PR #%s is red but a converge for it is already "
                "live -- not offering it and not escalating it this run\n"
                % (cand["issue"], cand["pr"]))
            continue
        # AND BEFORE THE ESCALATION TOO, same reasoning as the gate above. A
        # capped-out issue has ALREADY paged the founder from converge.sh's
        # exit-2 path, with the clearing command in the line; escalating here
        # would be a second alarm about one unchanged fact 15 minutes later,
        # which is the cry-wolf failure that trains the reader to skim.
        if capout_skip(path, cand["issue"], "ci-redrive", cand["pr"]):
            continue
        if ledger_get(path, cand["issue"], redrive_flag(cand)):
            escalate(path, cand)           # machine tier already spent on this
            continue
        if chosen is None:
            chosen = cand                  # one hand-back per run, like the pick
    if chosen is None:
        return 1
    sys.stderr.write(
        "ci-redrive: %s PR #%s red on %s -- offering it back to %s\n"
        % (chosen["issue"], chosen["pr"], ", ".join(chosen["failing_checks"]),
           chosen["agent"]))
    # FIELDS 4 AND 5 ARE THE OBSERVATION, NOT A RE-QUERY (PR #211 round 3,
    # MAJOR 2). The selector has just READ the branch the chosen PR is on; the
    # dispatcher's branch_guard used to throw that away and ask gh the same
    # question again, which opens a window between the two answers. If the PR
    # closes in between, the second answer is "no open PR", the guard takes its
    # fail-open arm, and the work lands on exactly the branch the guard exists
    # to reject. A guard whose whole thesis is "refuse a dispatch that would land
    # on a branch no open PR is on" must not itself fail open on a stale read.
    #
    # EMPTY IS A REAL VALUE HERE. `candidates` leaves the branch empty for an
    # UNSTATED head, and the dispatcher reads an empty field 4 as "no earlier
    # observation" and takes the fail-open arm on purpose -- see candidates().
    print("%s\t%s\t%s\t%s\t%s" % (chosen["issue"], chosen["signature"],
                                    chosen["head_sha"], chosen["branch"] or "",
                                    chosen["pr"]))
    return 0


def cmd_mark_dispatched(issue, sig, head_sha):
    """The atomic claim. 0 = it is yours to dispatch, 1 = it is not."""
    path = attempts_path()
    # NOT `ledger_claim`. The park has to be refused inside the claim's own
    # transaction, not read before it -- see claim_unless_capped.
    if not claim_unless_capped(path, issue, "ci_redrive_%s" % sig,
                               "ci-redrive [signature %s]" % sig):
        return 1
    # Order matters: record WHICH head first, then the marker saying a head was
    # recorded at all. The reverse order lets a failure between the two claim
    # that a sha is on file when none is, and the escalation would then read a
    # missing sha as a push that never happened.
    if ledger_recorded(path, issue, head_flag(head_sha)):
        ledger_recorded(path, issue, "ci_redrive_headrec_%s" % sig)
    return 0


def main(argv):
    ap = argparse.ArgumentParser(
        description="Machine consumer for red CI on agent-opened PRs (ASK-295).")
    ap.add_argument("op", choices=("scan", "redrive", "mark-dispatched"))
    ap.add_argument("--repo-dir", default=".",
                    help="checkout whose open PRs are read (gh runs here)")
    ap.add_argument("--issue", help="mark-dispatched: the issue being dispatched")
    ap.add_argument("--signature", help="mark-dispatched: signature from redrive")
    ap.add_argument("--head-sha", default="",
                    help="mark-dispatched: head sha from redrive")
    args = ap.parse_args(argv[1:])

    # No gh call: mark-dispatched commits the offer the dispatcher is holding.
    # Re-probing here would decide against a world that may have moved between
    # the offer and the launch, which is a different PR state than the one the
    # dispatcher is about to act on.
    if args.op == "mark-dispatched":
        if not args.issue or not args.signature:
            ap.error("mark-dispatched needs --issue and --signature")
        return cmd_mark_dispatched(args.issue, args.signature, args.head_sha)

    try:
        cands = candidates(args.repo_dir)
    except GhUnavailable as exc:
        # 2, and deliberately neither 0 nor 1. 1 means "nothing to redrive",
        # which is a claim about the PRs; this is a claim about the probe.
        sys.stderr.write("ci-redrive: %s -- nothing was claimed.\n" % exc)
        return 2
    if args.op == "scan":
        print(json.dumps(cands, indent=2))
        return 0
    return cmd_redrive(cands)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
