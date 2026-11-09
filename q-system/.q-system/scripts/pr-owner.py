#!/usr/bin/env python3
"""pr-owner.py -- every open PR in a fleet repo gets an owner, whatever its branch (ASK-3962).

Usage:
  python3 q-system/.q-system/scripts/pr-owner.py [--apply] [--skip <owner/repo#n | repo#n>]...

Dry by default: it prints what it would do and writes nothing, not even its state
file. --apply acts. Hourly as com.kipi.pr-owner, from its own pinned checkout
(job-checkouts.json, kipi-job-pinned.sh).

WHY IT EXISTS. The dead-end audit of 2026-11-08 (~/.config/kipi/handoffs/
2026-11-08-dead-end-audit.md, rows 25, 46 and 54) found open PRs nothing moved:
  * ci-redrive.py and review-redrive.py select `sana` branches only, and
    linear-worker.sh wip_release counts only `sana/` heads (OWN_PREFIX), so a fix/
    or human-shaped PR was never selected. kipi-system #526 (fix/) sat open from
    2026-10-07.
  * wip_release moves a PR only when a repo holds 5 open sana/ PRs. No target repo
    held more than 3, so brag #2 (since 10-24) and ktlyst #8 (since 11-01) sat
    under the ceiling with no mover in either system (audit C3).
This job is their consumer: terminal-states.json ticket_states `open-pr` names it
as the by-age exit, and test-fleet-liveness.py holds the row to this file.

WHY A JOB OF ITS OWN, NOT INSIDE wip_release. linear-worker.sh and kipi-dispatch.sh
are edited by live lanes (#651, #655, #656 on 2026-11-08). One agent per file
(iteration-speed.md rule 7), so this reads those files and never edits them.

WHICH REPOS. The dispatcher's own set: fleet_candidates() and
dispatch_targets_default() are cut out of kipi-dispatch.sh and run here, the way
rearm-degraded-approvals.sh does it. A second copy of "dispatch-enabled" is the
drift this repo keeps paying for, so there is no copy of the rule in this file.
Then, per repo: a `.kipi-no-dispatch` file skips it (repo-preflight.sh's kill
switch), and the archived engagement (RULE-2026-10-23-B) is asked of the founder's
hook ps-archive-deny.sh before anything reads the repo. A missing hook refuses the
run. Client repos are in (RULE-2026-10-30-A).

WHAT IT DOES TO ONE PR, decide() below. A PR younger than 48 hours belongs to
whatever opened it, and a PR pushed in the last 12 hours belongs to whoever pushed.
The design on ASK-3962 put the 12 hours in front of closes only; the second live
dry run (2026-11-08 20:4xZ) would then have run a review on ktlyst #8 minutes after
an agent pushed it and held its review on purpose. So it gates every write. Then:
  * a lessons PR whose every ledger entry is already on its base: close as
    superseded. Decided by content, the way the 4 weekly batches (#515, #518, #536,
    #539) were measured and closed on 2026-11-08, not by age or branch name.
  * kipi/reviewer-approved green, our read of CI green (or no workflow file on
    the base, logged as that and never as CI green), and GitHub says mergeable
    and CLEAN, HAS_HOOKS or UNSTABLE: `gh pr merge --auto --squash <n>`, run from the
    repo's own checkout: the shape automerge_arm in pr-verdict-lib.sh runs, and
    the shape merge-bypass-gate.py permits, asked of that gate first. On those
    three states gh merges at once (gh 2.103.2, isImmediatelyMergeable). UNSTABLE is allowed ONLY because our read of CI
    must be green first: round 1 of PR #659 caught a merge on UNSTABLE with CI red,
    and round 2 caught the over-fix, where dropping UNSTABLE sent an approved PR
    whose only non-green status was the advisory kipi/codex-approved to rework
    and then close. The CI read is the guard; GitHub's merge state is not.
  * approved, CI green and conflict-free, but BEHIND its base: `gh pr
    update-branch`, once per head (BEHIND IS UPDATED, NOT CLOSED, in decide()).
  * CI green and never reviewed: `kipi review <n> --repo <path> --post`, at most one
    per run, at most one per head.
  * red (CI failure, conflict, REQUEST CHANGES or BLOCK or no verdict, review cap,
    draft, approved but not mergeable, no check at a head whose base has workflows):
      - open ticket whose worker branch sana/<id> this is, in a state the worker
        picks: rework. A PR comment, the ticket back to Backlog with "resume
        from branch X at sha Y", the PR left
        open once. Still red at the same head one age (48h) later: close.
      - the same, in a state linear-worker.sh does not pick (Triage): close with
        the resume note, as below. A rework round would wait 48h on nobody.
      - open ticket on any other branch: close, then the same resume note.
      - no ticket, or a closed one: close with a comment.
  * checks still running, or GitHub has not computed mergeability: wait.
A close never deletes the branch. Reopening the PR undoes it: a PR open at the
head pr-owner closed it at is left alone until a new push (state["closed"]).
The close comment says "Reopen this PR within 30 days to undo", and the ticket
note says "reopen the PR within 30 days to undo": after that the record is pruned
(THE STATE FILE STAYS BOUNDED, at prune_state()).

A FORK IS NEVER ACTED ON (PR #659 round 1, major). On a public repo the branch
name and the title are strings the PR's author chose, and both bind a PR to a
ticket here. A stranger's PR on `sana/ask-2540` would have moved a live lane's
ticket to Backlog 48 hours later. So provenance is read before any ticket is,
through ci-redrive.py's head_provenance (the rule review-redrive.py imports too),
and a fork or an unstated head gets `outside`: no read of Linear, no comment, no
close. It waits behind the same 48h age and 12h quiet as every PR (round 3,
minor: a drive-by PR reached Sana's queue within the hour). Its next actor is the
alert lane: --apply files one alert per PR through slack-notify.sh (a Linear
ticket for Sana, which linear-alert-triage.py takes nightly), and never a second
for the same PR (PR #659 round 2: a line in pr-owner.log alone is read by nothing).
The alert is recorded only when the sink's own line names a ticket (round 3,
major): see outside_alert() for why exit 0 is not that proof.

A PR THE CAP LADDER OWNS IS YIELDED (ASK-3824). cap-ladder.py (com.kipi.cap-ladder,
nightly 04:40, PR #662) is the one consumer of every cap: a capout, 3 attempts, a
paged conflict, an escalated review, a review round cap. Two writers on one PR
is how it gets reworked by one job while the other splits its ticket. So any PR
its ladder_owns() claims gets `ladder`, nothing else. Before PR #662 is in this
checkout, pr-owner yields every PR the ladder COULD own (see ladder_check).

A LIVE LANE IS NEVER CLOSED. A ticket started inside linear-sync.py's
STARTED_STALE_HOURS window, or with a live worker claim, holds its PR. Same rule
as linear-worker.sh lane_hold, same race (ASK-3826 trap 1): the orchestrator moves
a lane's ticket to In Progress by hand, and a lane reworking an old PR can go hours
before its first push.

ONE WRITER. The state file ~/.local/state/kipi/pr-owner/state.json (strikes,
review attempts, closes, fork alerts and updates, per PR and head) is written only here, under a lock, as a temp
file plus rename. Linear writes go through linear-sync.py requeue and progress,
the same two writers wip_release uses, and a fork's one alert goes through
slack-notify.sh to alert-to-linear.py.

NOT IN THIS JOB: LGTM's 14-day stale close in chief (stale_close_scope still names
kipi-system). Chief is out of the dispatch set and the worker cannot reach a Chief
checkout ("UNREACHABLE: no local checkout for Chief", dry run 2026-11-08). LGTM
stays a later second closer of kipi-system PRs. Closing a closed PR is a no-op, so
the overlap is bounded. Decided on ASK-3962, 2026-11-08 18:27Z.

Exit: 0 clean, 2 a repo could not be read or an action failed, 3 refused, 64 usage.
"""

from __future__ import annotations

import argparse
import base64
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import shlex
import subprocess
import sys
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
# scripts/ -> .q-system/ -> q-system/ -> repo root. KIPI_REPO is the dispatcher's
# own name for the home checkout, so a test points both at one fixture.
ROOT = Path(os.environ.get("KIPI_REPO") or SCRIPTS.parents[2])

# 48 hours: two daily cycles of the worker, converge and both redrives. A PR older
# than that with no mover is what the audit counted. 12 hours of quiet before any
# close: a PR somebody pushed to this morning is somebody's live work.
AGE_S = 48 * 3600
QUIET_S = 12 * 3600
# 30 days: how long a record outlives its PR's last appearance in an open list.
# The close comment says this number in words; the contract test reads both.
KEEP_DAYS = 30
KEEP_S = KEEP_DAYS * 86400
LIST_LIMIT = 200
PER_PR_MAPS = ("closed", "strikes", "reviews", "outside", "updates")

REVIEWER_CONTEXT = "kipi/reviewer-approved"
LEDGER = "lesson-candidates/.processed.json"
OWN_PREFIX = "sana/"
# The board's only team (audit 2026-11-08: 2382 open ASK issues). A prefix list,
# not "any WORD-123": lessons/weekly-2026-10-19 would read as WEEKLY-2026.
TEAM_KEYS = ("ASK",)
AGENT = "pr-owner"

GREEN_RUN = {"SUCCESS", "NEUTRAL", "SKIPPED"}
RUNNING_STATUS = {"PENDING", "EXPECTED", "QUEUED", "IN_PROGRESS", "WAITING", "REQUESTED"}
MERGE_READY = {"CLEAN", "HAS_HOOKS", "UNSTABLE"}


def now_s() -> int:
    # A test sets the clock; the job never does.
    return int(os.environ.get("KIPI_PR_OWNER_NOW") or datetime.now(timezone.utc).timestamp())


def state_path() -> Path:
    return Path(os.environ.get("KIPI_PR_OWNER_STATE")
                or Path.home() / ".local" / "state" / "kipi" / "pr-owner" / "state.json")


def worker_state_dir() -> Path:
    # The worker's KIPI_STATE_DIR: its worktrees/ (claims) and pr-reviews/ live there.
    return Path(os.environ.get("KIPI_STATE_DIR") or Path.home() / ".config" / "kipi")


def iso_s(text) -> int | None:
    try:
        return int(datetime.strptime(str(text), "%Y-%m-%dT%H:%M:%SZ")
                   .replace(tzinfo=timezone.utc).timestamp())
    except (TypeError, ValueError):
        return None


def iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def hours(sec: int) -> str:
    return f"{sec / 3600:.1f}h"


# ---------------------------------------------------------------- side effects
# Every subprocess goes through run(), so a test swaps one function and sees every
# command this job would send.

def run(argv, timeout=120, env=None, cwd=None):
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                           env=env, cwd=cwd, stdin=subprocess.DEVNULL)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"timed out after {timeout}s"
    except OSError as exc:
        return 127, "", str(exc)


def run_logged(argv, log: Path, timeout=2700):
    """(rc, tail of the log) for a long child whose output nobody reads live.

    A FILE, NEVER A PIPE. pr-review-agent.sh starts a watchdog
    `( sleep "$secs"; ... ) &` that inherits stdout. run() reads through a pipe
    until EOF, and the sleep holds the pipe open, so the hourly run would sit up
    to 40 minutes after the review was done (found 2026-11-08 by the Sonnet vs
    Opus agent; a stub with a 20s sleep measured 20.0s). A file lets this return
    when the reviewer exits. The verdict is read from GitHub on the next run,
    not from this output.
    """
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        with open(log, "w") as fh:
            rc = subprocess.run(argv, stdout=fh, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, timeout=timeout).returncode
    except subprocess.TimeoutExpired:
        rc = 124
    except OSError as exc:
        return 127, str(exc)
    try:
        tail = " ".join(log.read_text(errors="replace").split())[-160:]
    except OSError:
        tail = ""
    return rc, tail


# THE ONE DOOR FOR A GITHUB WRITE. A close or merge that deletes the branch loses
# the only copy of the work, and the destructive-op hook does not see a gh call
# made from Python. So the refusal lives at the chokepoint, not in each caller.
# The merge gate is asked here too, for the same reason (merge_gate_verdict).
def gh_write(argv, cwd=None, env=None):
    if argv[:2] in (["pr", "close"], ["pr", "merge"]) and ("--delete-branch" in argv or "-d" in argv):
        raise SystemExit("REFUSED: pr-owner never deletes a branch: " + " ".join(argv))
    if argv[:2] == ["pr", "merge"]:
        why = merge_gate_verdict(argv, cwd or os.getcwd())
        if why:
            return 3, "", f"merge-bypass-gate.py refused it: {why}"
    return run(["gh"] + argv, env=env, cwd=cwd)


MERGE_GATE = SCRIPTS / "merge-bypass-gate.py"


def gh_env() -> dict:
    # GH_REPO and GH_HOST never reach a gh call made from a checkout. The checkout
    # is what names the repo there, and it is what the merge gate judges: the gate
    # denies those two as an env prefix because they retarget gh without changing
    # one argument, and an env passed from Python is the same retarget, unseen.
    return {k: v for k, v in os.environ.items() if k not in ("GH_REPO", "GH_HOST")}


def merge_gate_verdict(gh_args, cwd) -> str:
    """"" when merge-bypass-gate.py allows `gh <gh_args>` from cwd, else why not.

    ASKED OF THE GATE, NOT HIDDEN FROM IT (PR #659 round 7, minor). The merge was
    `gh pr merge <n> -R <slug> --squash --match-head-commit <sha>`, a shape the
    gate denies (measured 2026-11-09: the real gate denies that exact argv), and
    a gh call from Python reaches no PreToolUse hook, so the fleet's one
    merge gate could not see the one merge it would deny. Now the merge is the
    gate's own shape, and the gate is run on it through its hook contract (stdin
    payload; silent exit 0 allows; a deny line denies). a deny or no answer is no merge:
    a crashed or missing gate is not an allow, the rule archived() keeps for the
    archive hook.
    """
    payload = json.dumps({"tool_name": "Bash", "cwd": str(cwd),
                          "tool_input": {"command": shlex.join(["gh"] + [str(a) for a in gh_args])}})
    try:
        p = subprocess.run([sys.executable, str(MERGE_GATE)], input=payload, capture_output=True,
                           text=True, timeout=30, env=gh_env())
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"the gate could not answer ({exc})"
    tail = " ".join((p.stderr or p.stdout or "").split())[-160:]
    if p.returncode != 0:
        return f"the gate exited {p.returncode} ({tail})"
    if not p.stdout.strip():
        return ""
    try:
        out = (json.loads(p.stdout) or {}).get("hookSpecificOutput") or {}
    except (ValueError, AttributeError):
        return f"the gate printed something outside its contract ({tail})"
    if out.get("permissionDecision") == "deny":
        return " ".join(str(out.get("permissionDecisionReason") or "deny").split())[:240]
    return f"the gate answered neither allow nor deny ({tail})"


def gh_json(argv):
    rc, out, err = run(["gh"] + argv)
    if rc != 0:
        raise RuntimeError(" ".join(err.split())[:200] or f"gh exited {rc}")
    return json.loads(out or "null")


_FLOOR_RE = re.compile(r'^FLOOR_DESC="([^"]+)"', re.M)


def floor_desc() -> str:
    # ONE SOURCE. reviewer-floor.sh posts a red kipi/reviewer-approved on a PR with
    # no review, so "red" alone cannot tell "never reviewed" from "rejected". Its
    # description is the only difference, read from the file that posts it. A copy
    # here would drift, and the drift would close never-reviewed PRs as rejected.
    try:
        m = _FLOOR_RE.search((SCRIPTS / "reviewer-floor.sh").read_text())
    except OSError:
        m = None
    return m.group(1) if m else ""


# ---------------------------------------------------------------- repo set

_CUT = r'''
set -u
say() { printf 'fleet: %s\n' "$*" >&2; }
REPO="$1"; DISPATCH="$REPO/kipi-dispatch.sh"
[ -f "$DISPATCH" ] || { echo "no kipi-dispatch.sh at $DISPATCH" >&2; exit 3; }
for fn in dispatch_targets_default fleet_candidates; do
  body="$(awk -v head="$fn() {" 'index($0, head) == 1 { on = 1 } on { print } on && $0 == "}" { exit }' "$DISPATCH")"
  [ -n "$body" ] || { echo "kipi-dispatch.sh has no $fn()" >&2; exit 3; }
  eval "$body"
done
KIPI_DISPATCH_TARGETS="$(dispatch_targets_default)"
export KIPI_DISPATCH_TARGETS
printf 'targets\t%s\n' "$KIPI_DISPATCH_TARGETS"
fleet_candidates
'''

_SLUG = r'''
. "$1/q-system/.q-system/scripts/repo-slug-lib.sh"
KIPI_SLUG_REGISTRY="$2" KIPI_DISPATCH_TARGETS="$3" slug_for_repo "$4"
'''


def fleet_repos(root: Path = ROOT):
    """[(name, path, remote)], home first, plus the overlay path, from the dispatcher's own code."""
    rc, out, err = run(["bash", "-c", _CUT, "pr-owner-cut", str(root)])
    if rc != 0:
        raise SystemExit(f"REFUSED: the dispatch set could not be read: {' '.join(err.split())[:200]}")
    targets, rows = "", []
    for line in out.splitlines():
        parts = line.split("\t")
        if parts[0] == "targets" and len(parts) == 2:
            targets = parts[1]
        elif len(parts) == 3 and parts[0]:
            rows.append(tuple(parts))
    return rows, targets


def slug_for(root: Path, path: str, targets: str) -> str:
    registry = os.environ.get("KIPI_DISPATCH_REGISTRY") or str(root / "instance-registry.json")
    rc, out, _ = run(["bash", "-c", _SLUG, "pr-owner-slug", str(root), registry, targets, path])
    return out.strip() if rc == 0 else ""


def archive_guard() -> Path:
    # HOME is the seam, not a KIPI_* knob: a variable would be a documented way to
    # aim the archive guard at /bin/true (rearm-degraded-approvals.sh, same reason).
    return Path.home() / ".claude" / "hooks" / "ps-archive-deny.sh"


def archived(path: str, label: str) -> bool:
    """True when ps-archive-deny.sh denies a read of this repo.

    A GUARD THAT CANNOT ANSWER IS NOT AN ALLOW (PR #659 contract test). The hook
    allows by exiting 0 with no output and denies by exiting 0 with a deny line,
    so any other exit is no answer. The first cut read only a missing or hung
    guard as a deny; a guard that crashed (jq gone, a syntax error) read as an
    allow, and the run read and closed PRs in what may be the archive, exit 0.
    Now every non-answer raises, and main() leaves the repo unread and exits 2.
    """
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": f"ls {path} {label}"}})
    env = {k: v for k, v in os.environ.items() if k != "ALLOW_PS_ARCHIVE"}
    try:
        p = subprocess.run(["bash", str(archive_guard())], input=payload, capture_output=True,
                           text=True, timeout=30, env=env)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"the archive guard could not answer ({exc})") from exc
    if p.returncode != 0:
        raise RuntimeError(f"the archive guard exited {p.returncode} "
                           f"({' '.join((p.stderr or p.stdout).split())[-120:]})")
    return '"permissionDecision":"deny"' in p.stdout.replace(" ", "")


# ---------------------------------------------------------------- reading a PR

PR_FIELDS = ("number,title,url,headRefName,headRefOid,baseRefName,createdAt,isDraft,"
             "isCrossRepository,mergeable,mergeStateStatus,statusCheckRollup")
# Read per aged PR, never in the list. Measured 2026-11-08, first live dry run:
# `commits` in a 200-PR list traverses the authors connection and GitHub refuses the
# whole query ("requesting up to 1,000,000 possible nodes"), so every repo read as
# unreadable and the run owned nothing.
# mergeable and mergeStateStatus again, because the list answers UNKNOWN for an old
# PR until something asks GitHub to compute it, and a per-PR view is that ask.
# Measured 2026-11-08: #526 read UNKNOWN from the list and MERGEABLE from a view,
# and without this it would have waited forever.
DETAIL_FIELDS = "commits,files,mergeable,mergeStateStatus"


_CI = None


def ci_redrive():
    # IMPORTED, NOT COPIED, as review-redrive.py does it. Which contexts are an
    # engine's verdict slot (is_reviewer_slot) and whether a head is a fork
    # (head_provenance) each cost a defect to get right in ci-redrive.py. The first
    # cut here hardcoded two slot names, so a third engine's slot read as red CI
    # and would have closed a green PR (PR #659 round 1, minor).
    global _CI
    if _CI is None:
        spec = importlib.util.spec_from_file_location("ci_redrive", SCRIPTS / "ci-redrive.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _CI = mod
    return _CI


def ci_state(rollup) -> tuple[str, list]:
    """("green"|"running"|"red"|"none", names). Engine verdict slots are not CI.

    NO CHECK IS NOT GREEN (PR #659 round 7, minor). An empty or null rollup, or
    one whose every entry is an engine slot, came out "green": every check of none passed.
    So in a repo with no CI the merge gate was one agent review, logged as "CI
    green". "none" makes main() ask whether the base has a workflow file at all.
    """
    red, running, seen = [], [], 0
    for c in rollup or []:
        name = c.get("name") or c.get("context") or "?"
        if ci_redrive().is_reviewer_slot(name):
            continue
        seen += 1
        if c.get("__typename") == "CheckRun" or "conclusion" in c:
            if (c.get("status") or "COMPLETED") != "COMPLETED":
                running.append(name)
            elif (c.get("conclusion") or "") not in GREEN_RUN:
                red.append(f"{name}={c.get('conclusion') or '?'}")
        else:
            st = (c.get("state") or "").upper()
            if st in RUNNING_STATUS:
                running.append(name)
            elif st != "SUCCESS":
                red.append(f"{name}={st or '?'}")
    if red:
        return "red", red
    if running:
        return "running", running
    return ("green", []) if seen else ("none", [])


def no_workflows(slug: str, base: str) -> bool:
    """True when the base branch has no Actions workflow file. Raises RuntimeError when GitHub cannot say.

    Asked for a PR with no check at its head. No workflow file (brag on
    2026-11-09) means the review is the repo's one check by design, and the log
    says exactly that. A workflow file with no check at this head means CI should
    have run and did not, which is red, not a merge.
    """
    rc, out, err = run(["gh", "api", f"repos/{slug}/contents/.github/workflows?ref={urllib.parse.quote(base, safe='')}"])
    if rc != 0:
        if "404" in err or "Not Found" in err:
            return True
        raise RuntimeError(f"workflows on {base}: {' '.join(err.split())[:160]}")
    try:
        items = json.loads(out or "[]")
    except ValueError as exc:
        raise RuntimeError(f"workflows on {base}: not JSON ({exc})") from exc
    if not isinstance(items, list):
        raise RuntimeError(f"workflows on {base}: .github/workflows is not a directory")
    return not any(str((i or {}).get("name") or "").endswith((".yml", ".yaml")) for i in items if isinstance(i, dict))


# ONE SOURCE, the floor_desc() rule. linear-worker.sh picks a ticket in these state
# types and no other (plus a started one it releases), so a rework round promised to any
# other state is a promise to nobody. Read from the worker's own line; a copy here
# would drift the day the worker learns a new state. () when it cannot be read.
WORKER_SH = SCRIPTS / "linear-worker.sh"
_QUEUE_RE = re.compile(r"^QUEUE_STATES = \(([^)]*)\)", re.M)
_QUEUE: dict = {}


def worker_queue_states() -> tuple:
    key = str(WORKER_SH)
    if key not in _QUEUE:
        try:
            m = _QUEUE_RE.search(WORKER_SH.read_text())
        except OSError:
            m = None
        _QUEUE[key] = tuple(re.findall(r'"([a-z_]+)"', m.group(1))) if m else ()
    return _QUEUE[key]


def reviewer_state(statuses, floor: str) -> tuple[str, str]:
    """("unreviewed"|"approved"|"rejected"|"cap"|"pending", description) for the head."""
    mine = [s for s in statuses or [] if s.get("context") == REVIEWER_CONTEXT]
    if not mine:
        return "unreviewed", "no kipi/reviewer-approved status at this head"
    s = mine[0]  # the combined-status API returns the newest per context
    st, desc = (s.get("state") or "").lower(), s.get("description") or ""
    if st == "success":
        return "approved", desc
    if st == "pending":
        # pr-review-agent.sh posts pending for one thing only: its round cap.
        return ("cap", desc) if "cap" in desc.lower() else ("pending", desc)
    if desc == floor:
        return "unreviewed", desc
    return "rejected", desc or st


def ticket_candidates(branch: str, title: str) -> list:
    out = []
    for text in (branch or "", title or ""):
        for key, num in re.findall(r"(?<![A-Za-z0-9])([A-Za-z]{2,10})-(\d{1,6})(?![0-9])", text):
            ident = f"{key.upper()}-{num}"
            if key.upper() in TEAM_KEYS and ident not in out:
                out.append(ident)
    return out


def worker_branch_issue(branch: str) -> str:
    # sana/ask-901 -> ASK-901, linear-worker.sh's rule. A lane branch
    # (sana/ask-901-slug) gives "": the worker commits only onto sana/<id>, so a
    # rework request for a lane PR would land on a branch no PR is on.
    tail = branch[len(OWN_PREFIX):] if branch.startswith(OWN_PREFIX) else ""
    head, _sep, num = tail.partition("-")
    return (head.upper() + "-" + num) if head.isalpha() and num.isdigit() else ""


def ledger_at(slug: str, sha: str) -> dict:
    """The lessons ledger at one commit; {} when the file is not there."""
    rc, out, err = run(["gh", "api", f"repos/{slug}/contents/{LEDGER}?ref={sha}"])
    if rc != 0:
        if "404" in err or "Not Found" in err:
            return {}
        raise RuntimeError(f"ledger at {sha[:8]}: {' '.join(err.split())[:160]}")
    blob = json.loads(out)
    data = json.loads(base64.b64decode(blob.get("content") or "").decode("utf-8") or "{}")
    return data if isinstance(data, dict) else {}


def lessons_verdict(slug: str, pr: dict) -> dict:
    """{"batch": n, "on_base": n} for a PR that changes the lessons ledger.

    The batch is every entry the PR adds or changes against its merge base. It is
    superseded when every one of them is already in the base branch's ledger: main
    consumed those candidates, and merging would publish duplicate lessons.
    """
    cmp = gh_json(["api", f"repos/{slug}/compare/{pr['base']}...{pr['head']}"])
    mb = ((cmp or {}).get("merge_base_commit") or {}).get("sha") or ""
    if not mb:
        raise RuntimeError("no merge base")
    head, at_mb, base = ledger_at(slug, pr["head"]), ledger_at(slug, mb), ledger_at(slug, pr["base"])
    batch = [k for k, v in head.items() if at_mb.get(k) != v]
    return {"batch": len(batch), "on_base": sum(1 for k in batch if k in base)}


def normalize(slug: str, name: str, path: str, raw: dict) -> dict:
    commits = raw.get("commits") or []
    pushed = iso_s((commits[-1] if commits else {}).get("committedDate"))
    ci, ci_names = ci_state(raw.get("statusCheckRollup"))
    return {
        "slug": slug, "repo": name, "path": path,
        "number": int(raw["number"]), "title": raw.get("title") or "", "url": raw.get("url") or "",
        "branch": raw.get("headRefName") or "", "head": raw.get("headRefOid") or "",
        "base": raw.get("baseRefName") or "",
        "created": iso_s(raw.get("createdAt")),
        # The head commit's committer date. A rebase or amend rewrites it, so it is
        # the last push for every way the fleet pushes; an old commit pushed as-is
        # would read older than it is, and the 48h age gate still stands in front.
        "pushed": pushed,
        "draft": bool(raw.get("isDraft")),
        "mergeable": raw.get("mergeable") or "UNKNOWN",
        "merge_state": raw.get("mergeStateStatus") or "UNKNOWN",
        "ci": ci, "ci_names": ci_names,
        "touches_ledger": any((f.get("path") or "") == LEDGER for f in raw.get("files") or []),
        "provenance": ci_redrive().head_provenance(raw),
    }


# ---------------------------------------------------------------- Linear

_LS = None


def linear_sync():
    global _LS
    if _LS is None:
        spec = importlib.util.spec_from_file_location("ls", SCRIPTS / "linear-sync.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _LS = mod
    return _LS


TICKET_Q = "query($id: String!) { issue(id: $id) { id identifier startedAt state { name type } } }"


def read_ticket(ident: str):
    """The ticket, or None when Linear says it does not exist. Raises when Linear cannot answer."""
    ls = linear_sync()
    try:
        node = (ls.graphql(TICKET_Q, {"id": ident}) or {}).get("issue") or {}
    except ls.LinearAPIError as exc:
        if ls._ENTITY_NOT_FOUND_RE.search(str(exc)):
            return None
        raise
    if not node.get("id"):
        return None
    st = node.get("state") or {}
    claim = ""
    if st.get("type") == "started":
        claim = ls.live_claim(str(worker_state_dir() / "worktrees"), node.get("identifier") or ident)
    return {"id": node.get("identifier") or ident, "state_type": st.get("type") or "",
            "state_name": st.get("name") or "", "started": iso_s((node.get("startedAt") or "")[:19] + "Z"),
            "claim": claim, "lane_hours": ls.STARTED_STALE_HOURS}


def resolve_ticket(pr: dict, load):
    """(ticket or None, error). The first candidate Linear knows wins."""
    for ident in ticket_candidates(pr["branch"], pr["title"]):
        try:
            t = load(ident)
        except Exception as exc:  # could not look is not "there is none"
            return None, f"Linear could not answer for {ident} ({str(exc)[:100]})"
        if t:
            return t, ""
    return None, ""


# ---------------------------------------------------------------- an approved PR GitHub will not merge

VERDICT_LIB = SCRIPTS / "pr-verdict-lib.sh"
_GATE_SH = r'''
. "$1" >/dev/null 2>&1 || exit 99
rework_gate "APPROVE" "$2"
'''
_GATE_RC: dict = {}


def approved_gate(merge_state: str) -> int:
    """pr-verdict-lib.sh rework_gate on an approval: 10 terminal, 30 a rebase round, else unknown.

    ASKED, NOT COPIED (PR #659 round 5, major). This file's own table sent an
    approved, green PR that GitHub calls BLOCKED or UNKNOWN to rework and then
    close. rework_gate is the repo's one reader of that field, and it calls both
    terminal: BLOCKED is branch protection a rebase cannot fix, UNKNOWN is GitHub
    still computing. Rounds 1 and 2 moved one constant of this table twice; the
    RCA's lesson is to ask the other side's code, so this runs it. A local read
    with no side effect, so it calls subprocess directly, like archived(), and a
    test drives the real lib.
    """
    key = (str(VERDICT_LIB), merge_state)
    if key not in _GATE_RC:
        try:
            _GATE_RC[key] = subprocess.run(["bash", "-c", _GATE_SH, "pr-owner-gate", str(VERDICT_LIB), merge_state],
                                           capture_output=True, text=True, timeout=30,
                                           stdin=subprocess.DEVNULL).returncode
        except (OSError, subprocess.TimeoutExpired):
            _GATE_RC[key] = 99
    return _GATE_RC[key]


# ---------------------------------------------------------------- the cap ladder

# Read by path from THIS checkout. The job runs from its own pinned tree
# (job-checkouts.json), so this is the ladder that tree carries. A test points it
# at a temp copy.
CAP_LADDER = SCRIPTS / "cap-ladder.py"
_LADDER_MODS: dict = {}


def ladder_check(pr: dict, state_dir: str | None = None) -> str:
    """"" when cap-ladder.py does not own this PR, else why pr-owner yields it.

    ASKED, NOT COPIED. ladder_owns() (cap-ladder.py, PR #662) answers from the
    same cap_sigs() the ladder itself acts on, so the two jobs cannot disagree
    about who owns a capped PR. A copy here is the second writer it prevents.
    Raises RuntimeError when the file is there and cannot answer: main() holds
    the PR, because "could not ask" is not "the ladder does not own it".
    """
    sd = state_dir or str(worker_state_dir())
    if not CAP_LADDER.is_file():
        return _ladder_absent(pr, sd)
    try:
        mod = _LADDER_MODS.get(str(CAP_LADDER))
        if mod is None:
            spec = importlib.util.spec_from_file_location("cap_ladder", CAP_LADDER)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            _LADDER_MODS[str(CAP_LADDER)] = mod
        return mod.ladder_owns(pr["slug"], int(pr["number"]), pr["branch"], sd) or ""
    except Exception as exc:
        raise RuntimeError(f"cap-ladder.py could not answer ({type(exc).__name__}: {exc})") from exc


def _ladder_absent(pr: dict, sd: str) -> str:
    """PR #662 is not in this checkout: yield every PR the ladder COULD own.

    A superset of ladder_owns(), on purpose: a review-cap marker for this PR, or
    any worker-attempts record for the ticket of a sana/ask-N branch (lane
    branches too). Yielding too much costs a few PRs one more day with the
    mover they have today. Yielding too little puts two writers on one PR the
    morning #662 merges. Once cap-ladder.py is in the pinned tree this path is
    dead, and ladder_owns() answers instead.
    """
    name = f".round-cap-{pr['slug'].replace('/', '_')}-pr-{pr['number']}"
    reviews = Path(sd) / "pr-reviews"
    why = "cap-ladder.py is not in this checkout yet (PR #662, ASK-3824), and "
    if (reviews / name).exists() or (reviews / "codex" / name).exists():
        return why + "this PR has a review-cap marker; yielded until it lands"
    m = re.match(r"^sana/(ask-\d+)", pr.get("branch") or "", re.I)
    if not m:
        return ""
    ident = m.group(1).upper()
    try:
        ledger = json.loads((Path(sd) / "linear-worker-attempts.json").read_text())
    except FileNotFoundError:
        return ""
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"the worker attempts ledger is unreadable ({exc})") from exc
    if isinstance(ledger, dict) and ledger.get(ident):
        return why + f"{ident} has a worker-attempts record; yielded until it lands"
    return ""


# ---------------------------------------------------------------- the fork alert

_SINK = None
_REF_LETTERS = str.maketrans("0123456789abcdef", "ghijklmnopqrstuv")


def alert_sink():
    # The sink's own _FILED_LINE, imported, so "the line names a ticket" means
    # what alert-to-linear.py prints, not what this file believes it prints.
    global _SINK
    if _SINK is None:
        spec = importlib.util.spec_from_file_location("alert_to_linear", SCRIPTS / "alert-to-linear.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _SINK = mod
    return _SINK


def alert_ref(key: str) -> str:
    r"""This PR's identity in a word alert-to-linear.py's fingerprint keeps.

    PR #659 round 3, major. The sink dedups on the SHAPE of a message: it strips
    every `\S*/\S*` (the slug, the URL), every digit (the PR number) and every
    7+ hex run. So "brag PR #2" and "kipi-system PR #526" were one fingerprint:
    the second fork PR became a counted repeat on the first one's ticket, and no
    Linear object ever named it. pr-review-agent.sh met the same wall at PR #501
    and spells the PR number in letters (a-j). That carries no repo, and a-f
    letters can still read as hex, so this hashes the whole key and spells the
    hash in g-v: letters only, never hex, one word, distinct per PR, the same
    word every run for one PR so a retry repeats on that PR's own ticket.
    """
    return "ref" + hashlib.sha256(key.encode()).hexdigest()[:16].translate(_REF_LETTERS)


def outside_alert(pr: dict, reason: str) -> str:
    key = f"{pr['slug']}#{pr['number']}"
    return (f"pr-owner: {pr['slug']} PR #{pr['number']} ({pr['url']}) is outside the fleet ({reason}). "
            f"pr-owner never acts on it. Decide: review, merge or close it, then record why on the PR. "
            f"Dedup key {alert_ref(key)}.")


def filed_ticket(out: str) -> str:
    """The ticket the sink names for THIS alert, or "".

    EXIT 0 IS NOT A RECORD (PR #659 round 3, major). slack-notify.sh exits 0 for
    a new ticket, a counted repeat, a noise suppression, a sustained-rule
    deferral and a test capture. Only the first two name a ticket. The alert's
    own line is the first stdout line (file_and_drain prints it before any retry
    line), so a drained retry's "filed ASK-n" is never read as this one's.
    """
    for line in (out or "").splitlines():
        if line.startswith("alert-to-linear: "):
            m = alert_sink()._FILED_LINE.match(line[len("alert-to-linear: "):])
            return m.group(1) if m else ""
    return ""


# ---------------------------------------------------------------- the decision

def decide(pr: dict, now: int, state: dict, load_ticket, review_left: int, skip=()) -> dict:
    """What to do with one open PR. Pure apart from load_ticket, which a test fakes.

    Returns {"action", "reason", "ticket"?}. Actions: skip, reopened, young, wait, outside,
    outside-filed, ladder, hold, merge, update, review, close-superseded, rework,
    close-requeue, close-comment.
    """
    key = f"{pr['slug']}#{pr['number']}"
    if key in skip or f"{pr['slug'].split('/')[-1]}#{pr['number']}" in skip:
        return {"action": "skip", "reason": "named by --skip"}
    # A REOPEN IS THE UNDO (PR #659 round 6, major). The close comment says
    # "Reopen this PR to undo", and state["closed"] was written and never read,
    # so the next hourly run closed a reopened PR again at the same head. A PR
    # open at the head pr-owner closed it at was reopened on purpose, by whoever
    # reopened it; it is theirs until a new push, then it is decided again.
    shut = (state.get("closed") or {}).get(key) or {}
    if shut.get("head") and shut["head"] == pr["head"]:
        return {"action": "reopened",
                "reason": f"pr-owner closed it at {pr['head'][:8]} at {iso(shut['at'])} and it was reopened; "
                          f"a reopen is the undo, so pr-owner leaves it until a new push"}
    # THE GATES COME BEFORE PROVENANCE (PR #659 round 3, minor). They act on
    # nothing and bind no ticket, so a fork reaches them safely, and before this
    # order a fork opened a minute ago was alerted on the next hourly tick.
    age = now - (pr["created"] or now)
    if age < AGE_S:
        return {"action": "young", "reason": f"open {hours(age)}, under the {hours(AGE_S)} age; whatever opened it still owns it"}
    quiet = now - (pr["pushed"] or pr["created"] or now)
    if quiet < QUIET_S:
        return {"action": "wait", "reason": f"pushed {hours(quiet)} ago, under {hours(QUIET_S)} of quiet; whoever pushed still owns it"}
    if pr.get("provenance") != ci_redrive().SAME_REPO:
        filed = (state.get("outside") or {}).get(key)
        if filed:
            return {"action": "outside-filed",
                    "reason": f"outside the fleet; its alert {filed.get('ticket') or ''} was filed at {iso(filed['at'])}".replace("  ", " ")}
        return {"action": "outside",
                "reason": f"head provenance is {pr.get('provenance') or 'unstated'}: its branch and title are its author's, so it binds no ticket and pr-owner does not act on it"}
    if pr.get("ladder"):
        return {"action": "ladder", "reason": pr["ladder"] + "; cap-ladder.py takes it, pr-owner writes nothing"}
    rv, rv_desc = pr.get("reviewer", ("unreviewed", ""))

    lv = pr.get("lessons")
    if lv and lv["batch"] and lv["on_base"] == lv["batch"]:
        return {"action": "close-superseded",
                "reason": f"every entry this batch adds to {LEDGER} is already on {pr['base']} ({lv['on_base']} of {lv['batch']})"}

    if pr["mergeable"] == "UNKNOWN":
        return {"action": "wait", "reason": "GitHub has not computed mergeability yet"}
    if pr["ci"] == "running":
        return {"action": "wait", "reason": "checks still running: " + ", ".join(pr["ci_names"][:4])}
    # NO CHECK IS NOT GREEN (see ci_state). main() reads the base's workflow files
    # for a "none" PR; without that read there is nothing true to say about its CI.
    no_ci = pr.get("no_ci")
    if pr["ci"] == "none" and no_ci is None:
        return {"action": "hold",
                "reason": f"no CI check at this head, and pr-owner could not tell whether {pr['base']} has a workflow file"}
    ci_ok = pr["ci"] == "green" or (pr["ci"] == "none" and no_ci is True)
    ci_said = ("CI green" if pr["ci"] == "green"
               else f"no CI check at this head and no workflow file on {pr['base']}, so the review is this repo's one check")
    if (rv == "approved" and ci_ok and pr["mergeable"] == "MERGEABLE"
            and pr["merge_state"] in MERGE_READY and not pr["draft"]):
        return {"action": "merge", "reason": f"approved ({rv_desc}), {ci_said}, mergeable, merge state {pr['merge_state']}"}
    if rv == "pending":
        return {"action": "wait", "reason": f"reviewer status pending: {rv_desc}"}

    red = []
    if pr["draft"]:
        red.append("draft")
    if pr["ci"] == "red":
        red.append("CI red: " + ", ".join(pr["ci_names"][:4]))
    if pr["ci"] == "none" and no_ci is False:
        red.append(f"no CI check reported at this head, though {pr['base']} has a workflow file")
    if pr["mergeable"] == "CONFLICTING" or pr["merge_state"] == "DIRTY":
        red.append("conflicts with " + pr["base"])
    if rv == "rejected":
        red.append(f"review: {rv_desc}")
    if rv == "cap":
        red.append(f"review cap: {rv_desc}")
    behind = False
    if not red and rv == "approved":
        gate = approved_gate(pr["merge_state"])
        if gate == 10:
            return {"action": "wait",
                    "reason": f"approved and {ci_said}, but GitHub says merge state {pr['merge_state']}; "
                              f"pr-verdict-lib.sh rework_gate calls that terminal, so it is never reworked or closed for it. "
                              f"pr-owner reads it again next hour; a mover for it is ASK-4061"}
        if gate != 30:
            return {"action": "hold", "reason": f"pr-verdict-lib.sh rework_gate could not answer (rc {gate}) for merge state {pr['merge_state']}"}
        # BEHIND IS UPDATED, NOT CLOSED (PR #659 round 7, minor). rework_gate's 30
        # is a rebase round, and with no open ticket the red table closed an
        # approved, green, conflict-free PR whose one defect was its base moving,
        # with a close comment naming no rebase actor. GitHub can do that rebase
        # itself: `gh pr update-branch`, once per head. If the head did not move,
        # the update failed, and the PR goes to the red table saying so.
        tried = (state.get("updates") or {}).get(key) or {}
        if pr["merge_state"] != "BEHIND":
            red.append(f"approved, but GitHub says merge state {pr['merge_state']} (rework_gate: a rebase round)")
        elif tried.get("head") == pr["head"]:
            red.append(f"approved and only BEHIND {pr['base']}, but update-branch was asked at {iso(tried['at'])} "
                       f"and the head did not move")
        else:
            behind = True
    if not red and rv == "unreviewed":
        past = (state.get("reviews") or {}).get(key) or {}
        if past.get("head") == pr["head"]:
            if now - past.get("at", now) < AGE_S:
                return {"action": "wait", "reason": f"a review was asked at this head at {iso(past['at'])}; waiting for its verdict"}
            red.append(f"a review was asked at this head at {iso(past['at'])} and no verdict landed")
        elif review_left <= 0:
            return {"action": "wait", "reason": f"{ci_said} and never reviewed; this run's one review is spent"}
        else:
            return {"action": "review", "reason": f"{ci_said}, no reviewer verdict at this head"}
    why = "; ".join(red) if red else f"approved, {ci_said}, conflict-free, BEHIND {pr['base']}"
    word = "behind" if behind else "red"

    ticket, err = resolve_ticket(pr, load_ticket)
    if err:
        return {"action": "hold", "reason": err}
    open_ticket = bool(ticket) and ticket["state_type"] not in ("completed", "canceled")
    if open_ticket and ticket["state_type"] == "started":
        lane_s = ticket["lane_hours"] * 3600
        if ticket.get("started") and now - ticket["started"] < lane_s:
            return {"action": "wait", "ticket": ticket,
                    "reason": f"{word} ({why}), but {ticket['id']} started {hours(now - ticket['started'])} ago, inside the {ticket['lane_hours']}h lane window"}
        if ticket.get("claim"):
            return {"action": "wait", "ticket": ticket, "reason": f"{word} ({why}), but {ticket['id']} has {ticket['claim']}"}
    if behind:
        return {"action": "update", "ticket": ticket, "reason": why}
    if open_ticket:
        if worker_branch_issue(pr["branch"]) == ticket["id"]:
            # A REWORK IS PROMISED ONLY TO A TICKET THE WORKER PICKS (ASK-4099). The
            # rework comment says "so the worker reworks it", and for a Triage
            # ticket nothing did: linear-worker.sh ready() returns False for it, and
            # linear-sync.py requeue leaves every state but started alone. Waiting a rework
            # round there is 48 hours on nobody, so it closes now with the resume
            # note, the route a lane branch takes for the same reason.
            queue = worker_queue_states()
            if not queue:
                return {"action": "hold", "ticket": ticket,
                        "reason": f"{why}; no QUEUE_STATES in linear-worker.sh, so pr-owner cannot tell "
                                  f"whether the worker picks {ticket['id']}"}
            if ticket["state_type"] not in queue and not (ticket["state_type"] == "started" and "backlog" in queue):
                return {"action": "close-requeue", "ticket": ticket,
                        "reason": f"{why}; {ticket['id']} is {ticket['state_name'] or ticket['state_type']}, "
                                  f"which linear-worker.sh does not pick (it picks {', '.join(queue)}), "
                                  f"so no rework round is asked"}
            strike = (state.get("strikes") or {}).get(key) or {}
            if strike.get("head") == pr["head"]:
                if now - strike.get("at", now) < AGE_S:
                    return {"action": "wait", "ticket": ticket,
                            "reason": f"rework asked at {iso(strike['at'])}; waiting one age for a push"}
                return {"action": "close-requeue", "ticket": ticket,
                        "reason": f"{why}; rework asked at {iso(strike['at'])} and still red at the same head"}
            return {"action": "rework", "ticket": ticket, "reason": why}
        return {"action": "close-requeue", "ticket": ticket, "reason": f"{why}; {ticket['id']} is open, on another branch"}
    tail = f"{ticket['id']} is {ticket['state_name'] or ticket['state_type']}" if ticket else "no ticket named in the branch or title"
    return {"action": "close-comment", "ticket": ticket, "reason": f"{why}; {tail}"}


# ---------------------------------------------------------------- state

def load_state(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        # An unreadable state file would forget every strike and rework a PR forever.
        raise SystemExit(f"REFUSED: state file {path} is unreadable ({exc}); not running on a blank memory")


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(state, indent=1, sort_keys=True) + "\n")
    os.replace(tmp, path)


def prune_state(state: dict, listed: dict, now: int) -> int:
    """Drop per-PR records whose PR left its repo's open list 30 days ago. Returns how many.

    THE STATE FILE STAYS BOUNDED (ASK-4099). Every map here gained a key per PR;
    strikes lost theirs on a close and the rest kept theirs for good, so the file
    grew with every PR the fleet ever had. A record is dropped when its repo was listed in full this run,
    its PR is not in that list, and the record is KEEP_DAYS old. Open PRs are
    never pruned, so a reopened PR keeps its undo for as long as it stays open; a
    PR closed by pr-owner keeps it for 30 days, which is what its close comment
    says. A repo that was not read, or whose list reached LIST_LIMIT, is
    never pruned: absent from a list nobody read is not gone. A repo dropped from the
    fleet keeps its records, a bounded set, since nothing new is written for it.
    """
    dropped = 0
    for name in PER_PR_MAPS:
        entries = state.get(name)
        if not isinstance(entries, dict):
            continue
        for key in list(entries):
            slug = key.rpartition("#")[0]
            at = (entries[key] or {}).get("at") if isinstance(entries[key], dict) else None
            if slug in listed and key not in listed[slug] and now - int(at or 0) >= KEEP_S:
                del entries[key]
                dropped += 1
    return dropped


# ---------------------------------------------------------------- acting

def latest_findings(slug: str, number: int) -> str:
    # Read only. The worker's review record names: <owner>_<repo>__pr-<n>-<stamp>.md.
    d = worker_state_dir() / "pr-reviews"
    try:
        files = sorted(d.glob(f"{slug.replace('/', '_')}__pr-{number}-*.md"),
                       key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return ""
    for f in files:
        try:
            text = f.read_text(errors="replace")
        except OSError:
            continue
        m = re.search(r"^FINDINGS:.*?^END FINDINGS", text, re.M | re.S)
        if m:
            return "\n".join(m.group(0).splitlines()[:40])
    return ""


def ticket_note(ticket: dict, line: str) -> tuple[bool, str]:
    """(ok, what). Requeue a started ticket (linear-sync's one state writer), else a progress note.

    A FAILED REQUEUE IS NOT OK (PR #659 round 4, minor). It fell back to a
    progress note and act() still said "rework asked": the ticket stayed In
    Progress, so no worker picked it up, while the PR comment said it went back to
    Backlog, and 48h later the PR closed as "still red". The note is still posted
    so the resume line lands, and the run counts a failure and exits 2, which
    launchd-health-check.py reads.
    """
    sync = str(SCRIPTS / "linear-sync.py")
    lost = ""
    if ticket["state_type"] == "started":
        rc, out, err = run([sys.executable, sync, "requeue", ticket["id"], "--exit", AGENT,
                            "--why", line, "--agent", AGENT])
        if rc == 0:
            return True, out.strip() or "requeued"
        lost = f"WARN requeue failed, {ticket['id']} is still {ticket['state_name'] or 'started'} ({' '.join((err or out).split())[-120:]}); "
    rc, out, err = run([sys.executable, sync, "progress", ticket["id"], line, "--agent", AGENT])
    if rc != 0:
        return False, lost + f"WARN note did not post: {' '.join((err or out).split())[-160:]}"
    return not lost, lost + "note posted"


def merge(pr: dict) -> tuple[bool, str]:
    """`gh pr merge --auto --squash <n>` from the repo's checkout. (ok, what happened).

    The gate's shape has no -R, so the checkout names the repo, as it does for
    automerge_arm. Before the merge, the PR is read from that same checkout: the
    same URL proves gh resolves this repo there, and the same head stands in for
    the --match-head-commit pin the gate does not allow. That pin was atomic and
    this read is about a second early; on a protected repo a head pushed in that
    second is held by GitHub, whose kipi/reviewer-approved is per head. After the
    merge, the PR is read back: --auto arms auto-merge on any state gh does not
    call mergeable now, and gh prints nothing either way when no terminal is
    attached, so the log says merged, armed, or neither merged nor armed (a failure).
    """
    n, cwd, env = str(pr["number"]), pr["path"], gh_env()

    def view(fields):
        rc, out, err = run(["gh", "pr", "view", n, "--json", fields], env=env, cwd=cwd)
        if rc != 0:
            raise RuntimeError(" ".join((err or out).split())[:160] or f"gh exited {rc}")
        got = json.loads(out or "{}")
        return got if isinstance(got, dict) else {}

    try:
        seen = view("url,headRefOid")
    except (RuntimeError, ValueError) as exc:
        return False, f"the pre-merge read from {cwd} failed ({exc}); not merged"
    if seen.get("url") != pr["url"]:
        return False, f"gh in {cwd} reads PR #{n} as {seen.get('url') or '?'}, not {pr['url']}; not merged"
    if seen.get("headRefOid") != pr["head"]:
        return False, (f"the head moved from {pr['head'][:8]} to {(seen.get('headRefOid') or '?')[:8]} since the read; "
                       f"not merged, and the new head is decided on its own")
    rc, out, err = gh_write(["pr", "merge", "--auto", "--squash", n], cwd=cwd, env=env)
    if rc != 0:
        return False, f"merge failed: {' '.join((err or out).split())[:200]}"
    try:
        after = view("state,autoMergeRequest")
    except (RuntimeError, ValueError) as exc:
        return False, f"the merge exited 0 but its read-back failed ({exc})"
    if after.get("state") == "MERGED":
        return True, "merged"
    if after.get("autoMergeRequest"):
        return True, "auto-merge armed; GitHub merges it when its required checks pass"
    return False, f"gh exited 0, but the PR is neither merged nor armed (state {after.get('state') or '?'})"


def act(pr: dict, d: dict, state: dict, now: int) -> tuple[bool, str]:
    """Apply one decision. (ok, what happened)."""
    slug, n, head, branch = pr["slug"], str(pr["number"]), pr["head"], pr["branch"]
    key = f"{slug}#{n}"
    short = head[:8]
    if d["action"] == "outside":
        notify = os.environ.get("KIPI_NOTIFY") or str(SCRIPTS / "slack-notify.sh")
        rc, out, err = run(["bash", notify, outside_alert(pr, d["reason"])])
        if rc != 0:
            return False, f"alert did not file: {' '.join((err or out).split())[-160:]}"
        ident = filed_ticket(out)
        if not ident:
            return False, (f"the alert sink exited 0 but named no ticket "
                           f"({' '.join((out or err).split())[-160:]}); not recorded, the next hourly run asks again")
        state.setdefault("outside", {})[key] = {"head": head, "at": now, "ticket": ident}
        save_state(state_path(), state)
        return True, f"alert filed on {ident} (once per PR)"
    if d["action"] == "merge":
        return merge(pr)
    if d["action"] == "update":
        # Recorded BEFORE the call, as a review is: an update that fails must not
        # be asked again every hour at the same head (decide() reads this record).
        state.setdefault("updates", {})[key] = {"head": head, "at": now}
        save_state(state_path(), state)
        rc, out, err = gh_write(["pr", "update-branch", n, "-R", slug])
        if rc != 0:
            return False, f"update-branch failed: {' '.join((err or out).split())[:160]}"
        return True, (f"update-branch asked; GitHub writes a new head, and pr-owner decides it again after "
                      f"{hours(QUIET_S)} of quiet (a new head needs its own review)")
    if d["action"] == "review":
        argv = ["bash", str(ROOT / "kipi"), "review", n, "--repo", pr["path"], "--post"]
        ticket, _ = resolve_ticket(pr, read_ticket)
        if ticket:
            argv += ["--issue", ticket["id"]]
        # The attempt is recorded BEFORE the run: a review that crashes must not be
        # asked again every hour on the same head (one review per head, then red).
        state.setdefault("reviews", {})[key] = {"head": head, "at": now}
        save_state(state_path(), state)
        log = state_path().parent / "reviews" / f"{slug.replace('/', '_')}-pr-{n}.log"
        rc, tail = run_logged(argv, log, timeout=2700)
        return rc == 0, "review posted" if rc == 0 else f"review exited {rc} (log {log}): {tail}"
    if d["action"] == "rework":
        ticket = d["ticket"]
        line = (f"Resume from branch {branch} at {short}. pr-owner (ASK-3962): PR #{n} is red ({d['reason']}). "
                f"It stays open once; still red at {short} after {hours(AGE_S)}, it closes with the branch kept.")
        # THE COMMENT SAYS WHAT ticket_note() DOES (PR #659 contract test). Only a
        # started ticket is requeued. A Backlog or Todo one is already in the
        # worker's queue and gets the resume note; "goes back to Backlog" on a Todo
        # ticket was a sentence nothing made true.
        where = (f"{ticket['id']} goes back to Backlog" if ticket["state_type"] == "started"
                 else f"{ticket['id']} stays {ticket['state_name'] or ticket['state_type']} and gets a resume note")
        body = (f"pr-owner (ASK-3962): this PR is red and nothing has pushed for {hours(now - (pr['pushed'] or now))}.\n\n"
                f"Why: {d['reason']}\n\n{where} so the worker reworks it on {branch}. "
                f"If the head is still {short} after {hours(AGE_S)}, this PR closes with the branch kept.")
        rc, out, err = gh_write(["pr", "comment", n, "-R", slug, "--body", body])
        if rc != 0:
            return False, f"comment failed: {' '.join(err.split())[:160]}"
        state.setdefault("strikes", {})[key] = {"head": head, "at": now, "why": d["reason"][:200]}
        save_state(state_path(), state)
        noted, what = ticket_note(ticket, line)
        return noted, f"rework asked; {what}"
    if d["action"] in ("close-superseded", "close-requeue", "close-comment"):
        ticket = d.get("ticket")
        findings = latest_findings(slug, pr["number"])
        body = (f"Closed by pr-owner (ASK-3962), the hourly owner of every open fleet PR.\n\n"
                f"Why: {d['reason']}.\n\n"
                f"Branch {branch} is kept at {short}. Nothing was deleted. Reopen this PR within {KEEP_DAYS} days to undo.")
        if d["action"] == "close-requeue":
            body += f"\n\n{ticket['id']} gets a resume note: resume from branch {branch} at {short}."
        if findings:
            body += "\n\nLast review findings:\n```\n" + findings + "\n```"
        rc, out, err = gh_write(["pr", "close", n, "-R", slug, "--comment", body])
        if rc != 0:
            return False, f"close failed: {' '.join(err.split())[:160]}"
        (state.setdefault("strikes", {})).pop(key, None)
        state.setdefault("closed", {})[key] = {"head": head, "at": now, "action": d["action"]}
        save_state(state_path(), state)
        what, noted = "closed, branch kept", True
        if ticket and d["action"] == "close-requeue":
            line = (f"Resume from branch {branch} at {short}. pr-owner (ASK-3962) closed PR #{n} ({d['reason']}). "
                    f"Branch kept; reopen the PR within {KEEP_DAYS} days to undo.")
            noted, note = ticket_note(ticket, line)
            what += "; " + note
        return noted, what
    return True, "nothing to do"


# ---------------------------------------------------------------- main

WRITES = ("outside", "merge", "update", "review", "rework", "close-superseded", "close-requeue", "close-comment")


def main(argv=None) -> int:
    """EXIT 3 FOR EVERY REFUSAL (PR #659 round 4, minor). fleet_repos, load_state
    and gh_write refuse with SystemExit("REFUSED: ..."), which Python exits as 1,
    the same code as a crash, while the docstring and main()'s own refusals say 3.
    launchd-health-check.py reads the code, so the two must not look alike."""
    try:
        return _run(argv)
    except SystemExit as exc:
        if isinstance(exc.code, str):
            print(exc.code, file=sys.stderr)
            return 3
        raise


def _run(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Give every open fleet PR an owner (ASK-3962).")
    ap.add_argument("--apply", action="store_true", help="act; without it, print and write nothing")
    ap.add_argument("--skip", action="append", default=[], metavar="REPO#N",
                    help="leave one PR alone this run (owner/repo#n or repo#n); repeatable")
    try:
        args = ap.parse_args(argv)
    except SystemExit as exc:
        return 0 if exc.code == 0 else 64  # -h printed its help and is done (PR #659 round 5, nit)

    floor = floor_desc()
    if not floor:
        print("REFUSED: no FLOOR_DESC in reviewer-floor.sh, so a never-reviewed PR cannot be told "
              "from a rejected one", file=sys.stderr)
        return 3
    if not archive_guard().is_file():
        print(f"REFUSED: the archive guard {archive_guard()} is missing, so the archived engagement "
              "(RULE-2026-10-23-B) cannot be told apart. Not sweeping.", file=sys.stderr)
        return 3

    mode = "apply" if args.apply else "dry"
    spath = state_path()
    lock = None
    if args.apply:
        spath.parent.mkdir(parents=True, exist_ok=True)
        lock = open(spath.with_name("lock"), "w")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print("another pr-owner run holds the lock; this run does nothing")
            return 0
    state = load_state(spath)
    now = now_s()

    rows, targets = fleet_repos(ROOT)
    if not rows:
        print("REFUSED: fleet_candidates returned no repo at all, not even home", file=sys.stderr)
        return 3
    counts = {k: 0 for k in ("skip", "reopened", "outside-filed", "ladder", "young", "wait", "hold") + WRITES}
    n_repos = n_excluded = n_unreadable = n_prs = n_failed = 0
    review_left = 1
    listed: dict = {}   # slug -> every open PR key, for repos listed in full (prune_state)
    no_ci_at: dict = {}  # (slug, base) -> no_workflows(), one read per base per run
    for name, path, _remote in rows:
        n_repos += 1
        try:
            denied = archived(path, name)
        except RuntimeError as exc:
            n_unreadable += 1
            print(f"UNREADABLE {name}: {exc}; not read")
            continue
        if denied:
            n_excluded += 1
            print(f"EXCLUDED {name}: the archive guard refuses it (RULE-2026-10-23-B); not read")
            continue
        if Path(path, ".kipi-no-dispatch").exists():
            n_excluded += 1
            print(f"EXCLUDED {name}: {path}/.kipi-no-dispatch is present (kill switch)")
            continue
        slug = slug_for(ROOT, path, targets)
        if not slug:
            n_unreadable += 1
            print(f"UNREADABLE {name}: no GitHub slug for {path}")
            continue
        try:
            denied = archived(path, slug)
        except RuntimeError as exc:
            n_unreadable += 1
            print(f"UNREADABLE {name} ({slug}): {exc}; not read")
            continue
        if denied:
            n_excluded += 1
            print(f"EXCLUDED {name} ({slug}): the archive guard refuses it; not read")
            continue
        try:
            raw = gh_json(["pr", "list", "-R", slug, "--state", "open", "--limit", str(LIST_LIMIT), "--json", PR_FIELDS])
        except (RuntimeError, ValueError) as exc:
            n_unreadable += 1
            print(f"UNREADABLE {name} ({slug}): gh pr list failed: {exc}")
            continue
        if len(raw or []) < LIST_LIMIT:
            listed[slug] = {f"{slug}#{int(r['number'])}" for r in raw or []}
        for item in sorted(raw or [], key=lambda r: int(r["number"])):
            n_prs += 1
            pr = normalize(slug, name, path, item)
            tag = f"{slug}#{pr['number']} ({pr['branch']})"
            if now - (pr["created"] or now) >= AGE_S:
                try:
                    if pr["provenance"] == ci_redrive().SAME_REPO:
                        detail = gh_json(["pr", "view", str(pr["number"]), "-R", slug, "--json", DETAIL_FIELDS])
                        pr = normalize(slug, name, path, {**item, **(detail or {})})
                        st = gh_json(["api", f"repos/{slug}/commits/{pr['head']}/status"])
                        pr["reviewer"] = reviewer_state((st or {}).get("statuses"), floor)
                        if pr["touches_ledger"]:
                            pr["lessons"] = lessons_verdict(slug, pr)
                        if pr["ci"] == "none":
                            if (slug, pr["base"]) not in no_ci_at:
                                no_ci_at[(slug, pr["base"])] = no_workflows(slug, pr["base"])
                            pr["no_ci"] = no_ci_at[(slug, pr["base"])]
                        pr["ladder"] = ladder_check(pr)
                    else:
                        # A fork's commits and nothing else: the 12h quiet gate needs
                        # its last push (round 3, minor). No status, no Linear.
                        detail = gh_json(["pr", "view", str(pr["number"]), "-R", slug, "--json", "commits"])
                        pr = normalize(slug, name, path, {**item, **(detail or {})})
                except (RuntimeError, ValueError) as exc:
                    counts["hold"] += 1
                    n_unreadable += 1
                    print(f"hold {tag}: could not read it ({exc})")
                    continue
            d = decide(pr, now, state, read_ticket, review_left, set(args.skip))
            counts[d["action"]] += 1
            if d["action"] == "hold":
                # A HOLD IS AN UNREAD PR (PR #659 round 5, minor). With Linear down
                # every red PR holds, and exit 0 told launchd-health-check.py the
                # run owned them. Same exit 2 as a GitHub read that failed.
                n_unreadable += 1
            if d["action"] == "review":
                review_left -= 1
            if d["action"] not in WRITES:
                print(f"{d['action']} {tag}: {d['reason']}")
                continue
            if mode == "dry":
                print(f"[dry] would {d['action']} {tag}: {d['reason']}")
                continue
            ok, what = act(pr, d, state, now)
            if not ok:
                n_failed += 1
            print(f"{d['action'].upper()} {tag}: {d['reason']} -> {what}")

    # A dry run prunes a copy, so it can say what --apply would drop and still write nothing.
    pruned = prune_state(state if args.apply else json.loads(json.dumps(state)), listed, now)
    if pruned:
        print(f"{'pruned' if args.apply else 'would prune'} {pruned} state entr{'y' if pruned == 1 else 'ies'}: "
              f"their PRs left a fully listed repo's open list at least {KEEP_DAYS} days ago")
    if args.apply:
        state["last_run"] = {"at": iso(now), "repos": n_repos, "prs": n_prs, "failed": n_failed,
                             "counts": {k: v for k, v in counts.items() if v}}
        save_state(spath, state)
    summary = ", ".join(f"{k} {v}" for k, v in counts.items() if v) or "nothing"
    print(f"-- {mode}: {n_repos} repo(s), {n_excluded} excluded, {n_unreadable} unreadable; "
          f"{n_prs} open PR(s): {summary}; {n_failed} failed")
    return 2 if (n_unreadable or n_failed) else 0


if __name__ == "__main__":
    sys.exit(main())
