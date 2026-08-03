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
    redrive         -> read-only. prints `<issue>\t<signature>\t<head_sha>`,
                       exit 0. Nothing to offer -> exit 1. gh could not answer
                       -> exit 2. Escalates any candidate whose attempt is spent.
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

PR_FIELDS = ("number,headRefName,headRefOid,url,title,statusCheckRollup,isDraft,"
             "baseRefName")


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


# --- a REQUIRED context nobody posted (ASK-313) ------------------------------
# failing_checks() above can only see contexts that were POSTED. An ABSENT
# required context contributes zero rollup entries, so every reader built on the
# rollup reads a wedged PR as healthy. On 2026-08-02 PR #75 sat BLOCKED with
# `validate` green, `kipi/reviewer-approved` absent, auto-merge armed, and zero
# alerts; `gh pr checks` said the checks had passed (cli/cli#6448 -- the CLI does
# not surface expected-but-unreported contexts, still open). The only way to see
# absence is to DIFF what protection DECLARES against what the head has actual.
#
# WHY NOT THE STANDARD GITHUB FIX. The documented remedy for a never-reported
# required check is a job that always posts it green (GHES 3.2 troubleshooting,
# "Handling skipped but required checks"; re-actors/alls-green; Mergify ci-gate).
# It is wrong here twice over:
#   1. Absence of `kipi/reviewer-approved` is a CORRECT refusal, not a
#      misconfiguration. linear-worker.sh:687 -- "Remove kipi/reviewer-approved
#      from that set and this becomes an unreviewed-merge machine."
#   2. GitHub requires BOTH when a check run and a commit status share a name
#      ("If a check and a commit status have the same name, both must pass when
#      that name is required"). An Actions job named `kipi/reviewer-approved`
#      would ADD a second thing to satisfy, deepening the deadlock it meant to
#      fix.
# So this does not fake the status. It finds the wedge and hands the PR to the
# REAL producer, pr-review-agent.sh, which is the only thing allowed to post it.

def required_contexts(repo_dir, branch, _cache={}):
    """Contexts branch protection REQUIRES on `branch`. Raises GhUnavailable.

    Both halves are read. GitHub populates `contexts` (legacy) and `checks` (the
    app-pinned form) and a reader that trusts one of them stops working the day
    the other is the only one written.

    404 AND EVERY OTHER FAILURE ARE DIFFERENT ANSWERS, and conflating them was
    a real bug in this function's first version. Round 1 raised on any non-zero
    rc, reasoning that repo-preflight.sh already refuses to dispatch against an
    unprotected repo so 404 could never legitimately arrive. That is a claim
    about the DEFAULT branch, and this is asked about a PR's BASE branch. The
    very first live run hit it:

        $ ci-redrive.py --repo-dir . wedged
        could not read branch protection for sana/block-expiry
          (rc 1): gh: Branch not protected (HTTP 404)   -- rc 2, whole sweep dead

    A stacked PR based on another agent's branch is ordinary here, and one
    unprotected base blinded the sweep for every other PR -- the exact silence
    this detector exists to end, reintroduced by the detector.

    So: 404 is DEFINITE ("no protection, therefore nothing required, therefore
    this PR cannot wedge") and yields the empty set. Anything else -- notably
    the 403 a token without admin gets -- stays INDEFINITE and raises, because
    reading "I am not allowed to look" as "nothing is required" would report
    every wedged PR healthy at the moment the tool lost the ability to tell.
    """
    if branch in _cache:
        return _cache[branch]
    gh = os.environ.get("KIPI_GH", "gh")
    cmd = [gh, "api", "repos/{owner}/{repo}/branches/%s/protection" % branch]
    try:
        proc = subprocess.run(cmd, cwd=repo_dir, capture_output=True, text=True)
    except OSError as exc:
        raise GhUnavailable("could not run %s: %s" % (gh, exc))
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        # gh's own format is `gh: <message> (HTTP <code>)`, and 404 here is the
        # documented body for "Branch not protected". Matched on the code, not
        # on the message text, so a wording change does not silently turn a
        # definite answer into an indefinite one.
        if "(HTTP 404)" in stderr:
            _cache[branch] = set()
            return _cache[branch]
        raise GhUnavailable(
            "could not read branch protection for %s (rc %d): %s"
            % (branch, proc.returncode, stderr[:200]))
    try:
        data = json.loads(proc.stdout or "{}")
    except ValueError as exc:
        raise GhUnavailable("branch protection for %s is unparseable: %s"
                            % (branch, exc))
    rsc = data.get("required_status_checks") or {}
    names = set(rsc.get("contexts") or [])
    for entry in rsc.get("checks") or []:
        if isinstance(entry, dict) and entry.get("context"):
            names.add(entry["context"])
    _cache[branch] = names
    return names


def posted_contexts(pr):
    """Every context name the head commit carries, WHATEVER its state.

    State is deliberately ignored. A required context posted and FAILING is a
    PR that was reviewed and rejected -- a visible state with its own consumer
    (the reviewer comments on the Linear issue and the worker re-dispatches).
    Folding red into absent would re-review every rejected PR forever.
    """
    names = set()
    for check in pr.get("statusCheckRollup") or []:
        if not isinstance(check, dict):
            continue
        if check.get("__typename") == "StatusContext":
            if check.get("context"):
                names.add(check["context"])
            continue
        if check.get("name"):
            names.add(check["name"])
    return names


def wedged_candidates(repo_dir):
    """Open PRs carrying a required context that nothing has posted.

    NOT filtered by attribute(): redrive hands a red PR back to the agent that
    owns the branch, so it only speaks for agent branches. Branch protection
    does not care who pushed. The founder's own hand-opened PR wedges
    identically, and it is the one class with no agent to hand it back to -- so
    excluding it would leave exactly the population that cannot self-heal.
    """
    out = []
    for pr in list_prs(repo_dir):
        if pr.get("isDraft"):
            continue          # not asking to merge; a review would be spend nobody asked for
        # RED CI OUTRANKS A WEDGE, and this is a spend rule learned from real
        # data. PR #76 on 2026-08-02 was BOTH: `validate` FAILURE and
        # `kipi/reviewer-approved` absent. Reviewing a PR whose build is broken
        # buys a codex review of a tree that is about to change, and the redrive
        # tier already owns that PR. It becomes this tier's business the moment
        # CI is green -- nothing is dropped, only ordered.
        if failing_checks(pr):
            continue
        base = pr.get("baseRefName") or "main"
        missing = sorted(required_contexts(repo_dir, base) - posted_contexts(pr))
        if not missing:
            continue
        attributed = attribute(pr)
        out.append({
            "pr": pr.get("number"),
            "url": pr.get("url"),
            "branch": pr.get("headRefName"),
            "head_sha": pr.get("headRefOid") or "",
            "issue": attributed[0] if attributed else None,
            "missing": missing,
            "signature": signature(missing),
        })
    return out


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


def reviewer_live(pr):
    """True if a reviewer for this PR is in the process table right now.

    A CLAIMED ATTEMPT IS NOT A COMPLETED ATTEMPT (codex on PR #78, major).
    The reviewer is launched DETACHED and takes minutes; the heartbeat is 900s.
    So the next run sees the ledger flag, reads it as "the machine tier is
    spent", and pages that the reviewer ran and the context is still absent --
    while it is mid-flight. That page also claims `wedged_escalated_<sig>`, so
    the one page owed to the founder is burnt on a false alarm and the REAL
    failure is then silent. Exactly the scar cmd_redrive already guards with
    converge_live; it was not carried into this tier.

    The dispatcher's own `WEDGED_PS` check does not cover this: that only stops
    a second reviewer being LAUNCHED. The escalation decision lives here.

    An unreadable table answers True, same direction as converge_live: skipping
    one heartbeat is recoverable, a false page that also burns the flag is not.
    """
    table = process_table()
    if table is None:
        sys.stderr.write("ci-redrive: could not read the process table -- treating "
                         "every wedged PR as already under review.\n")
        return True
    # `(?:\s|$)` MULTILINE so PR 7 does not match `pr-review-agent.sh 75`.
    pattern = re.compile(r"pr-review-agent\.sh\s+%s(?:\s|$)" % re.escape(str(pr)),
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
            "branch": pr.get("headRefName"),
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
    print("%s\t%s\t%s" % (chosen["issue"], chosen["signature"],
                          chosen["head_sha"]))
    return 0


def cmd_mark_dispatched(issue, sig, head_sha):
    """The atomic claim. 0 = it is yours to dispatch, 1 = it is not."""
    path = attempts_path()
    if not ledger_claim(path, issue, "ci_redrive_%s" % sig):
        sys.stderr.write(
            "ci-redrive: %s attempt for signature %s was already claimed (or the "
            "ledger could not be written) -- not dispatching.\n" % (issue, sig))
        return 1
    # Order matters: record WHICH head first, then the marker saying a head was
    # recorded at all. The reverse order lets a failure between the two claim
    # that a sha is on file when none is, and the escalation would then read a
    # missing sha as a push that never happened.
    if ledger_recorded(path, issue, head_flag(head_sha)):
        ledger_recorded(path, issue, "ci_redrive_headrec_%s" % sig)
    return 0


# --- the wedged tier (ASK-313) -----------------------------------------------
# Keyed by PR, not by issue. A wedge is a property of the PULL REQUEST -- the
# founder's hand-opened PR has no issue at all, and two PRs for one issue can
# wedge independently. `PR-<n>` is a plain dict key to attempts-ledger.py, the
# same single writer the redrive tier goes through, so the two tiers cannot
# race each other into exceeding a cap.

def wedged_key(cand):
    return "PR-%s" % cand["pr"]


def wedged_flag(cand):
    return "wedged_review_%s" % cand["signature"]


def escalate_wedged(path, cand):
    """One page, AFTER the machine tier is spent. Every clause an observation."""
    if not ledger_claim(path, wedged_key(cand),
                        "wedged_escalated_%s" % cand["signature"]):
        return False
    notify(
        "ci-redrive: PR #%s is BLOCKED on a required check nothing posted (%s) "
        "and the machine tier is spent -- the reviewer was run once for this "
        "and the context is still absent. %s"
        % (cand["pr"], ", ".join(cand["missing"]), cand["url"]))
    return True


def cmd_wedged(cands):
    """READ-ONLY. Offers one PR; the dispatcher spends it via mark-reviewed."""
    path = attempts_path()
    chosen = None
    for cand in cands:
        # A live converge for this issue reaches the reviewer at its own step 5,
        # so offering it here would buy a second codex review of the same head.
        # Only askable when the PR HAS an issue; a founder PR never does.
        if cand["issue"] and converge_live(cand["issue"]):
            sys.stderr.write(
                "ci-redrive: PR #%s is wedged but a converge for %s is live -- "
                "its own review will post the context\n"
                % (cand["pr"], cand["issue"]))
            continue
        # BEFORE both the offer and the escalation, for the two different
        # reasons cmd_redrive gives: offering would buy a second review of the
        # same head, and escalating would page that a still-running attempt had
        # stopped -- burning the one page owed to the founder. Found by codex
        # reviewing this change (PR #78, major).
        if reviewer_live(cand["pr"]):
            sys.stderr.write(
                "ci-redrive: PR #%s is wedged and its reviewer is still running "
                "-- not offering it and not escalating it this run\n" % cand["pr"])
            continue
        if ledger_get(path, wedged_key(cand), wedged_flag(cand)):
            escalate_wedged(path, cand)    # machine tier spent AND finished
            continue
        if chosen is None:
            chosen = cand
    if chosen is None:
        return 1
    sys.stderr.write(
        "ci-redrive: PR #%s is BLOCKED on required context(s) nothing posted: "
        "%s -- offering it to the reviewer\n"
        % (chosen["pr"], ", ".join(chosen["missing"])))
    print("%s\t%s\t%s" % (chosen["pr"], chosen["signature"], chosen["head_sha"]))
    return 0


def cmd_mark_reviewed(pr, sig):
    """The atomic claim. 0 = it is yours to review, 1 = it is not."""
    path = attempts_path()
    if not ledger_claim(path, "PR-%s" % pr, "wedged_review_%s" % sig):
        sys.stderr.write(
            "ci-redrive: the wedged-review attempt for PR #%s signature %s was "
            "already claimed (or the ledger could not be written) -- not "
            "running the reviewer.\n" % (pr, sig))
        return 1
    return 0


def main(argv):
    ap = argparse.ArgumentParser(
        description="Machine consumer for red CI on agent-opened PRs (ASK-295) "
                    "and for PRs wedged on an unposted required check (ASK-313).")
    ap.add_argument("op", choices=("scan", "redrive", "mark-dispatched",
                                   "wedged", "mark-reviewed"))
    ap.add_argument("--repo-dir", default=".",
                    help="checkout whose open PRs are read (gh runs here)")
    ap.add_argument("--issue", help="mark-dispatched: the issue being dispatched")
    ap.add_argument("--signature", help="mark-dispatched: signature from redrive")
    ap.add_argument("--head-sha", default="",
                    help="mark-dispatched: head sha from redrive")
    ap.add_argument("--pr", help="mark-reviewed: the PR being handed to the reviewer")
    args = ap.parse_args(argv[1:])

    if args.op == "mark-reviewed":
        if not args.pr or not args.signature:
            ap.error("mark-reviewed needs --pr and --signature")
        return cmd_mark_reviewed(args.pr, args.signature)

    # No gh call: mark-dispatched commits the offer the dispatcher is holding.
    # Re-probing here would decide against a world that may have moved between
    # the offer and the launch, which is a different PR state than the one the
    # dispatcher is about to act on.
    if args.op == "mark-dispatched":
        if not args.issue or not args.signature:
            ap.error("mark-dispatched needs --issue and --signature")
        return cmd_mark_dispatched(args.issue, args.signature, args.head_sha)

    if args.op == "wedged":
        try:
            return cmd_wedged(wedged_candidates(args.repo_dir))
        except GhUnavailable as exc:
            # 2, same contract as below: a claim about the PROBE, never about
            # the PRs. Folding an unreadable protection response into "nothing
            # is wedged" is the original defect wearing the detector's coat.
            sys.stderr.write("ci-redrive: %s -- nothing was claimed.\n" % exc)
            return 2

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
