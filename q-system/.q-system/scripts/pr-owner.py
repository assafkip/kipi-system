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
  * kipi/reviewer-approved green and GitHub says mergeable and clean:
    `gh pr merge --squash --match-head-commit <sha>`.
  * CI green and never reviewed: `kipi review <n> --repo <path> --post`, at most one
    per run, at most one per head.
  * red (CI failure, conflict, REQUEST CHANGES or BLOCK or no verdict, review cap,
    draft, approved but not mergeable):
      - open ticket whose worker branch sana/<id> this is: rework. A PR comment,
        the ticket back to Backlog with "resume from branch X at sha Y", the PR left
        open once. Still red at the same head one age (48h) later: close.
      - open ticket on any other branch: close, then the same resume note.
      - no ticket, or a closed one: close with a comment.
  * checks still running, or GitHub has not computed mergeability: wait.
A close never deletes the branch. Reopening the PR undoes it.

A LIVE LANE IS NEVER CLOSED. A ticket started inside linear-sync.py's
STARTED_STALE_HOURS window, or with a live worker claim, holds its PR. Same rule
as linear-worker.sh lane_hold, same race (ASK-3826 trap 1): the orchestrator moves
a lane's ticket to In Progress by hand, and a lane reworking an old PR can go hours
before its first push.

ONE WRITER. The state file ~/.local/state/kipi/pr-owner/state.json (strikes and
review attempts, per PR and head) is written only here, under a lock, as a temp
file plus rename. Linear writes go through linear-sync.py requeue and progress,
the same two writers wip_release uses.

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
import importlib.util
import json
import os
import re
import subprocess
import sys
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

REVIEWER_CONTEXT = "kipi/reviewer-approved"
# Engine slots, not CI. Each is a verdict, read separately below.
ENGINE_CONTEXTS = ("kipi/reviewer-approved", "kipi/codex-approved")
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


# THE ONE DOOR FOR A GITHUB WRITE. A close or merge that deletes the branch loses
# the only copy of the work, and the destructive-op hook does not see a gh call
# made from Python. So the refusal lives at the chokepoint, not in each caller.
def gh_write(argv):
    if argv[:2] in (["pr", "close"], ["pr", "merge"]) and ("--delete-branch" in argv or "-d" in argv):
        raise SystemExit("REFUSED: pr-owner never deletes a branch: " + " ".join(argv))
    return run(["gh"] + argv)


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
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": f"ls {path} {label}"}})
    env = {k: v for k, v in os.environ.items() if k != "ALLOW_PS_ARCHIVE"}
    try:
        p = subprocess.run(["bash", str(archive_guard())], input=payload, capture_output=True,
                           text=True, timeout=30, env=env)
    except (OSError, subprocess.TimeoutExpired):
        return True  # a guard that cannot answer is a deny: never read what may be the archive
    return '"permissionDecision":"deny"' in p.stdout.replace(" ", "")


# ---------------------------------------------------------------- reading a PR

PR_FIELDS = ("number,title,url,headRefName,headRefOid,baseRefName,createdAt,isDraft,"
             "mergeable,mergeStateStatus,statusCheckRollup")
# Read per aged PR, never in the list. Measured 2026-11-08, first live dry run:
# `commits` in a 200-PR list traverses the authors connection and GitHub refuses the
# whole query ("requesting up to 1,000,000 possible nodes"), so every repo read as
# unreadable and the run owned nothing.
DETAIL_FIELDS = "commits,files"


def ci_state(rollup) -> tuple[str, list]:
    """("green"|"running"|"red", names). Engine verdict contexts are not CI."""
    red, running = [], []
    for c in rollup or []:
        name = c.get("name") or c.get("context") or "?"
        if name in ENGINE_CONTEXTS:
            continue
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
    return "green", []


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


# ---------------------------------------------------------------- the decision

def decide(pr: dict, now: int, state: dict, load_ticket, review_left: int, skip=()) -> dict:
    """What to do with one open PR. Pure apart from load_ticket, which a test fakes.

    Returns {"action", "reason", "ticket"?}. Actions: skip, young, wait, hold,
    merge, review, close-superseded, rework, close-requeue, close-comment.
    """
    key = f"{pr['slug']}#{pr['number']}"
    if key in skip or f"{pr['slug'].split('/')[-1]}#{pr['number']}" in skip:
        return {"action": "skip", "reason": "named by --skip"}
    age = now - (pr["created"] or now)
    if age < AGE_S:
        return {"action": "young", "reason": f"open {hours(age)}, under the {hours(AGE_S)} age; whatever opened it still owns it"}
    quiet = now - (pr["pushed"] or pr["created"] or now)
    if quiet < QUIET_S:
        return {"action": "wait", "reason": f"pushed {hours(quiet)} ago, under {hours(QUIET_S)} of quiet; whoever pushed still owns it"}
    rv, rv_desc = pr.get("reviewer", ("unreviewed", ""))

    lv = pr.get("lessons")
    if lv and lv["batch"] and lv["on_base"] == lv["batch"]:
        return {"action": "close-superseded",
                "reason": f"every entry this batch adds to {LEDGER} is already on {pr['base']} ({lv['on_base']} of {lv['batch']})"}

    if pr["mergeable"] == "UNKNOWN":
        return {"action": "wait", "reason": "GitHub has not computed mergeability yet"}
    if rv == "approved" and pr["mergeable"] == "MERGEABLE" and pr["merge_state"] in MERGE_READY and not pr["draft"]:
        return {"action": "merge", "reason": f"approved ({rv_desc}), mergeable, merge state {pr['merge_state']}"}
    if pr["ci"] == "running":
        return {"action": "wait", "reason": "checks still running: " + ", ".join(pr["ci_names"][:4])}
    if rv == "pending":
        return {"action": "wait", "reason": f"reviewer status pending: {rv_desc}"}

    red = []
    if pr["draft"]:
        red.append("draft")
    if pr["ci"] == "red":
        red.append("CI red: " + ", ".join(pr["ci_names"][:4]))
    if pr["mergeable"] == "CONFLICTING" or pr["merge_state"] == "DIRTY":
        red.append("conflicts with " + pr["base"])
    if rv == "rejected":
        red.append(f"review: {rv_desc}")
    if rv == "cap":
        red.append(f"review cap: {rv_desc}")
    if not red and rv == "approved":
        red.append(f"approved, but GitHub says merge state {pr['merge_state']}")
    if not red and rv == "unreviewed":
        past = (state.get("reviews") or {}).get(key) or {}
        if past.get("head") == pr["head"]:
            if now - past.get("at", now) < AGE_S:
                return {"action": "wait", "reason": f"a review was asked at this head at {iso(past['at'])}; waiting for its verdict"}
            red.append(f"a review was asked at this head at {iso(past['at'])} and no verdict landed")
        elif review_left <= 0:
            return {"action": "wait", "reason": "CI green and never reviewed; this run's one review is spent"}
        else:
            return {"action": "review", "reason": "CI green, no reviewer verdict at this head"}
    why = "; ".join(red)

    ticket, err = resolve_ticket(pr, load_ticket)
    if err:
        return {"action": "hold", "reason": err}
    if ticket and ticket["state_type"] not in ("completed", "canceled"):
        if ticket["state_type"] == "started":
            lane_s = ticket["lane_hours"] * 3600
            if ticket.get("started") and now - ticket["started"] < lane_s:
                return {"action": "wait", "ticket": ticket,
                        "reason": f"red ({why}), but {ticket['id']} started {hours(now - ticket['started'])} ago, inside the {ticket['lane_hours']}h lane window"}
            if ticket.get("claim"):
                return {"action": "wait", "ticket": ticket, "reason": f"red ({why}), but {ticket['id']} has {ticket['claim']}"}
        if worker_branch_issue(pr["branch"]) == ticket["id"]:
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


def ticket_note(ticket: dict, line: str) -> str:
    """Requeue a started ticket (one line, linear-sync's one state writer), else a progress note."""
    sync = str(SCRIPTS / "linear-sync.py")
    if ticket["state_type"] == "started":
        rc, out, err = run([sys.executable, sync, "requeue", ticket["id"], "--exit", AGENT,
                            "--why", line, "--agent", AGENT])
        if rc == 0:
            return out.strip() or "requeued"
    rc, out, err = run([sys.executable, sync, "progress", ticket["id"], line, "--agent", AGENT])
    return "note posted" if rc == 0 else f"WARN note did not post: {' '.join((err or out).split())[-160:]}"


def act(pr: dict, d: dict, state: dict, now: int) -> tuple[bool, str]:
    """Apply one decision. (ok, what happened)."""
    slug, n, head, branch = pr["slug"], str(pr["number"]), pr["head"], pr["branch"]
    key = f"{slug}#{n}"
    short = head[:8]
    if d["action"] == "merge":
        rc, out, err = gh_write(["pr", "merge", n, "-R", slug, "--squash", "--match-head-commit", head])
        return rc == 0, "merged" if rc == 0 else f"merge failed: {' '.join(err.split())[:160]}"
    if d["action"] == "review":
        argv = ["bash", str(ROOT / "kipi"), "review", n, "--repo", pr["path"], "--post"]
        ticket, _ = resolve_ticket(pr, read_ticket)
        if ticket:
            argv += ["--issue", ticket["id"]]
        # The attempt is recorded BEFORE the run: a review that crashes must not be
        # asked again every hour on the same head (one review per head, then red).
        state.setdefault("reviews", {})[key] = {"head": head, "at": now}
        save_state(state_path(), state)
        rc, out, err = run(argv, timeout=2700)
        return rc == 0, "review posted" if rc == 0 else f"review exited {rc}: {' '.join((err or out).split())[-160:]}"
    if d["action"] == "rework":
        ticket = d["ticket"]
        line = (f"Resume from branch {branch} at {short}. pr-owner (ASK-3962): PR #{n} is red ({d['reason']}). "
                f"It stays open once; still red at {short} after {hours(AGE_S)}, it closes with the branch kept.")
        body = (f"pr-owner (ASK-3962): this PR is red and nothing has pushed for {hours(now - (pr['pushed'] or now))}.\n\n"
                f"Why: {d['reason']}\n\n{ticket['id']} goes back to Backlog so the worker reworks it on {branch}. "
                f"If the head is still {short} after {hours(AGE_S)}, this PR closes with the branch kept.")
        rc, out, err = gh_write(["pr", "comment", n, "-R", slug, "--body", body])
        if rc != 0:
            return False, f"comment failed: {' '.join(err.split())[:160]}"
        state.setdefault("strikes", {})[key] = {"head": head, "at": now, "why": d["reason"][:200]}
        save_state(state_path(), state)
        return True, f"rework asked; {ticket_note(ticket, line)}"
    if d["action"] in ("close-superseded", "close-requeue", "close-comment"):
        ticket = d.get("ticket")
        findings = latest_findings(slug, pr["number"])
        body = (f"Closed by pr-owner (ASK-3962), the hourly owner of every open fleet PR.\n\n"
                f"Why: {d['reason']}.\n\n"
                f"Branch {branch} is kept at {short}. Nothing was deleted. Reopen this PR to undo.")
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
        what = "closed, branch kept"
        if ticket and d["action"] == "close-requeue":
            line = (f"Resume from branch {branch} at {short}. pr-owner (ASK-3962) closed PR #{n} ({d['reason']}). "
                    f"Branch kept; reopen the PR to undo.")
            what += "; " + ticket_note(ticket, line)
        return True, what
    return True, "nothing to do"


# ---------------------------------------------------------------- main

WRITES = ("merge", "review", "rework", "close-superseded", "close-requeue", "close-comment")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Give every open fleet PR an owner (ASK-3962).")
    ap.add_argument("--apply", action="store_true", help="act; without it, print and write nothing")
    ap.add_argument("--skip", action="append", default=[], metavar="REPO#N",
                    help="leave one PR alone this run (owner/repo#n or repo#n); repeatable")
    try:
        args = ap.parse_args(argv)
    except SystemExit:
        return 64

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
    counts = {k: 0 for k in ("skip", "young", "wait", "hold") + WRITES}
    n_repos = n_excluded = n_unreadable = n_prs = n_failed = 0
    review_left = 1
    for name, path, _remote in rows:
        n_repos += 1
        if archived(path, name):
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
        if archived(path, slug):
            n_excluded += 1
            print(f"EXCLUDED {name} ({slug}): the archive guard refuses it; not read")
            continue
        try:
            raw = gh_json(["pr", "list", "-R", slug, "--state", "open", "--limit", "200", "--json", PR_FIELDS])
        except (RuntimeError, ValueError) as exc:
            n_unreadable += 1
            print(f"UNREADABLE {name} ({slug}): gh pr list failed: {exc}")
            continue
        for item in sorted(raw or [], key=lambda r: int(r["number"])):
            n_prs += 1
            pr = normalize(slug, name, path, item)
            tag = f"{slug}#{pr['number']} ({pr['branch']})"
            if now - (pr["created"] or now) >= AGE_S:
                try:
                    detail = gh_json(["pr", "view", str(pr["number"]), "-R", slug, "--json", DETAIL_FIELDS])
                    pr = normalize(slug, name, path, {**item, **(detail or {})})
                    st = gh_json(["api", f"repos/{slug}/commits/{pr['head']}/status"])
                    pr["reviewer"] = reviewer_state((st or {}).get("statuses"), floor)
                    if pr["touches_ledger"]:
                        pr["lessons"] = lessons_verdict(slug, pr)
                except (RuntimeError, ValueError) as exc:
                    counts["hold"] += 1
                    n_unreadable += 1
                    print(f"hold {tag}: could not read its head ({exc})")
                    continue
            d = decide(pr, now, state, read_ticket, review_left, set(args.skip))
            counts[d["action"]] += 1
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
