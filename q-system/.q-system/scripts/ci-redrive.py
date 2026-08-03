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

3. ATTRIBUTION IS THE BRANCH NAME, with no Linear round-trip. The worker cuts
   every branch as `<agent>/<issue>` (`sana/ask-295`), so the branch already
   carries both facts this needs. A branch that does not match is not an agent
   PR and is none of this tool's business -- the founder's own PRs keep behaving
   exactly as they do today.

4. THE CAP IS ONE ATTEMPT PER PR PER FAILURE SIGNATURE, held in the existing
   attempts ledger (single-writer, flock'd -- attempts-ledger.py). The signature
   is the set of failing check NAMES, deliberately NOT the head sha: a re-push
   that fails the same check again is the same failure, and re-dispatching on it
   is how a handler re-runs a flake forever. ASK-295 names that risk by hand --
   one root cause of the 2026-08-02 redness was a measurement taken against the
   wrong tree, and a handler that re-runs CI without fixing tree isolation would
   have looped on it all night. A genuinely NEW failure gets its own fresh
   attempt, because it is a different problem.

WHAT IT DOES NOT DO
-------------------
It does not merge, close, comment on, or re-run anything on GitHub. It reads PR
state and answers one question: which issue should the dispatcher hand back to
its agent right now. The dispatching is the dispatcher's, and stays under the
dispatcher's caps.

    scan     -> JSON of red agent PRs (read-only, no ledger write, no page)
    redrive  -> claim one attempt, print the issue id, exit 0
                nothing claimable -> exit 1
                gh could not answer -> exit 2, nothing claimed

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
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LEDGER_SCRIPT = os.path.join(HERE, "attempts-ledger.py")
DEFAULT_NOTIFY = os.path.join(HERE, "slack-notify.sh")
DEFAULT_ATTEMPTS = os.path.join(
    os.environ.get("KIPI_STATE_DIR", os.path.expanduser("~/.config/kipi")),
    "linear-worker-attempts.json")

# `sana/ask-295` -> agent `sana`, issue `ASK-295`. Anchored at both ends on
# purpose: `sana/ask-295-followup` is a branch a human named, and guessing which
# issue a human meant is how the wrong issue gets re-dispatched.
BRANCH_RE = re.compile(r"^(?P<agent>[a-z][a-z0-9_-]*)/(?P<issue>[a-z]{2,6}-\d+)$")

# A CheckRun that COMPLETED with one of these is red. Everything else -- queued,
# in progress, skipped, neutral -- is not a failure, and treating "still running"
# as red would re-dispatch an issue whose CI has not finished answering.
FAILED_CONCLUSIONS = {"FAILURE", "TIMED_OUT", "CANCELLED", "STARTUP_FAILURE",
                      "ACTION_REQUIRED"}
# The legacy commit-status half of the same rollup speaks a different vocabulary.
FAILED_STATES = {"FAILURE", "ERROR"}

PR_FIELDS = "number,headRefName,url,title,statusCheckRollup,isDraft"


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


def failing_checks(pr):
    """Names of the checks that are red RIGHT NOW, sorted and de-duplicated."""
    names = set()
    for check in pr.get("statusCheckRollup") or []:
        if not isinstance(check, dict):
            continue
        kind = check.get("__typename")
        if kind == "StatusContext":
            if (check.get("state") or "").upper() in FAILED_STATES:
                names.add(check.get("context") or "(unnamed status)")
            continue
        # CheckRun, and anything else the rollup grows later that speaks
        # status/conclusion. A check that has not COMPLETED has not failed.
        if (check.get("status") or "").upper() != "COMPLETED":
            continue
        if (check.get("conclusion") or "").upper() in FAILED_CONCLUSIONS:
            names.add(check.get("name") or "(unnamed check)")
    return sorted(names)


def signature(names):
    """Identity of a FAILURE, not of a run.

    Head sha is left out deliberately -- see the module docstring. Same checks
    red again == same problem == the machine tier is already spent on it.
    """
    return hashlib.sha1("\n".join(names).encode("utf-8")).hexdigest()[:12]


def candidates(repo_dir):
    out = []
    for pr in list_prs(repo_dir):
        match = BRANCH_RE.match(pr.get("headRefName") or "")
        if not match:
            continue                       # not an agent branch, not ours
        failing = failing_checks(pr)
        if not failing:
            continue
        out.append({
            "issue": match.group("issue").upper(),
            "agent": match.group("agent"),
            "pr": pr.get("number"),
            "url": pr.get("url"),
            "branch": pr.get("headRefName"),
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


def ledger_claim(path, issue, flag):
    """True the first time this flag is claimed anywhere, False otherwise.

    A lock timeout (rc 3) or a hard write failure (rc 2) is FALSE, never True.
    Nothing was recorded, so nothing may act as though it was -- the next
    scheduled run claims it instead.
    """
    proc = subprocess.run(
        [sys.executable, LEDGER_SCRIPT, path, "claim-flag", issue, flag],
        capture_output=True, text=True)
    if proc.returncode not in (0, 1):
        sys.stderr.write("ci-redrive: ledger refused `%s` for %s: %s\n"
                         % (flag, issue, (proc.stderr or "").strip()[:200]))
    return proc.returncode == 0


def notify(message):
    script = os.environ.get("KIPI_NOTIFY", DEFAULT_NOTIFY)
    if not os.path.exists(script):
        return
    try:
        subprocess.run(["bash", script, message], capture_output=True, text=True)
    except OSError as exc:
        sys.stderr.write("ci-redrive: notify failed: %s\n" % exc)


def escalate(path, cand):
    """The founder's ONE message about this failure, and only after the machine.

    It says what was tried, per terminal-state-redrive-2026-08-01 item 3. Once
    per signature, because the dispatcher reaches this state on every heartbeat
    for as long as the PR sits red -- paging per run is a page every 15 minutes
    for one fact that has not changed.
    """
    if not ledger_claim(path, cand["issue"], "ci_escalated_%s" % cand["signature"]):
        return False
    notify(
        "ci-redrive: %s PR #%s is still red after the machine tier. The failing "
        "check is %s. What the machine tried: it re-dispatched %s to %s once for "
        "this exact failure and the same check failed again, so it stopped rather "
        "than re-run a flake. %s"
        % (cand["issue"], cand["pr"], ", ".join(cand["failing_checks"]),
           cand["issue"], cand["agent"], cand["url"]))
    return True


def cmd_redrive(cands):
    path = os.environ.get("KIPI_ATTEMPTS", DEFAULT_ATTEMPTS)
    chosen = None
    for cand in cands:
        flag = "ci_redrive_%s" % cand["signature"]
        # Read before claiming so EVERY spent candidate escalates on this pass,
        # not just the one that happens to sort first. The claim below is still
        # the atomic gate -- this read only decides who gets offered it.
        if ledger_get(path, cand["issue"], flag):
            escalate(path, cand)
            continue
        if chosen is not None:
            continue                       # one hand-back per run, like the pick
        if ledger_claim(path, cand["issue"], flag):
            chosen = cand
    if chosen is None:
        return 1
    sys.stderr.write(
        "ci-redrive: %s PR #%s red on %s -- handing it back to %s\n"
        % (chosen["issue"], chosen["pr"], ", ".join(chosen["failing_checks"]),
           chosen["agent"]))
    print(chosen["issue"])
    return 0


def main(argv):
    ap = argparse.ArgumentParser(
        description="Machine consumer for red CI on agent-opened PRs (ASK-295).")
    ap.add_argument("op", choices=("scan", "redrive"))
    ap.add_argument("--repo-dir", default=".",
                    help="checkout whose open PRs are read (gh runs here)")
    args = ap.parse_args(argv[1:])
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
