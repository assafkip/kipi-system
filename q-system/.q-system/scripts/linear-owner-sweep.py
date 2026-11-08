#!/usr/bin/env python3
"""Every open fleet ticket has an owner label (ASK-4010).

THE RULING. Founder, 2026-11-08, verbatim: "every single piece must have sauna as
an owner is still enforced in pros [...] Everything must be enforced with code. We
cannot have these things get stuck again on rules that are not being enforced and
then tickets don't get done because they're waiting for someone that doesn't exist."

THE DEFECT, MEASURED 2026-11-08 on team ASK: 2374 open tickets, 88 with no owner:*
label. 42 sat in a fleet project (all kipi-system, all machine-filed job inflow),
44 had no project, 2 sat in projects outside the fleet. linear-worker.sh ready()
refuses a ticket without owner:sana, so all 88 were invisible to every worker.

WHY NOTHING CAUGHT THEM. linear-route.py adds owner:sana only to a DoR ticket that
has a project and is not job inflow. Its job-inflow skip was ASK-1887's "Not doing"
line ("they need a liveness check before a worker run, not a label"); the 2026-11-08
ruling supersedes that line for the owner label. Chief's triage has an `unowned`
rule, but chief's triage bot belongs to the chief rebuild and was not draining these.
A sweep over the board catches every entry path, including ones not built yet.

WHAT IT DOES. One pass over the open board:
  * a ticket with any owner:* label is left alone. owner:assaf is counted and never
    relabelled; this sweep files nothing about it (ASK-3961 owns that population);
  * a ticket with no owner:* label, in a fleet project (a registry row's board name)
    or with no project at all, gets ONE comment naming the next consumer, then
    owner:sana. The project-unset population is the skeleton's (ASK-839,
    linear_registry.skeleton_project), so it is the fleet's;
  * a ticket in a project no row of the registry copy it read names is counted and
    listed by id, never labelled. "Outside" is a fact about that copy, not the
    project: on 2026-11-08 origin's copy lacked infohawk, a fleet project (PR #654
    review). So the job runs from the shared checkout, whose copy is current
    (job-checkouts.json, ASK-3967), and the drift itself is ASK-4024.

COMMENT FIRST, THEN THE LABEL. The comment carries SWEEP_MARKER and is looked up
before it is posted. A label write that fails after its comment landed is retried
next night with no second comment. A comment that fails stops that ticket before
its label, because a label with no recorded reason is a silent change of owner.

THE FIXTURE CHOKEPOINT. --apply refuses under pytest, the same rail
linear-route.py and linear-triage-health.py carry. A suite can never relabel a
real ticket.

Usage:
    python3 linear-owner-sweep.py                 # report only
    python3 linear-owner-sweep.py --json          # the same, as JSON
    python3 linear-owner-sweep.py --apply         # write, every ticket in scope

EXIT CODES
  0  measured, and every write it attempted landed
  2  usage error
  3  no Linear API key configured
  4  refused: --apply under pytest
  6  at least one write did not land (named in the output)
  9  incomplete: the board walk failed or the registry could not be read; nothing written
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import pathlib
import sys
import tempfile
from datetime import datetime, timezone

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import linear_registry  # noqa: E402  (after sys.path, by design)

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_NO_KEY = 3
EXIT_REFUSED_FIXTURE = 4
EXIT_WRITE_FAILED = 6
EXIT_INCOMPLETE = 9

OWNER_PREFIX = "owner:"
OWNER_LABEL = "owner:sana"
FOUNDER_LABEL = "owner:assaf"
SWEEP_MARKER = "kipi-owner-sweep"
CLOSED_STATE_TYPES = ("completed", "canceled")
ALERT_MARKER = "kipi-alert-fingerprint"
DOR_HEADING = "Definition of Ready"

# Job state lives outside every checkout (separate-worktrees.md: "A job writes its
# state and output under ~/.config/kipi/ or ~/.local/state/kipi/").
EVIDENCE_PATH = pathlib.Path.home() / ".local" / "state" / "kipi" / "linear-owner-sweep" / "last-run.json"

TEAM_QUERY = 'query($k:String!){teams(filter:{key:{eq:$k}}){nodes{id}}}'
BOARD_QUERY = """query($t:ID!,$a:String){issues(filter:{team:{id:{eq:$t}},
 state:{type:{nin:["completed","canceled"]}}},first:250,after:$a){
 nodes{id identifier title description state{type} project{name} labels{nodes{id name}}}
 pageInfo{hasNextPage endCursor}}}"""
TEAM_LABELS_QUERY = """query($t:String!){team(id:$t){labels(first:250){nodes{id name}}}}"""
# The re-read before a write: labels to see an owner that arrived after the walk,
# comments to find this job's own marker. 100 is a page, not a promise; the
# truncation flag rides along so "no marker on page one" is never read as "none".
ISSUE_QUERY = """query($id:String!){issue(id:$id){id identifier state{type}
 labels{nodes{id name}} comments(first:100){nodes{body} pageInfo{hasNextPage}}}}"""
COMMENT_CREATE = """mutation($input:CommentCreateInput!){commentCreate(input:$input){success}}"""
ISSUE_UPDATE = """mutation($id:String!,$input:IssueUpdateInput!){issueUpdate(id:$id,input:$input){success}}"""


class WriteRefused(RuntimeError):
    """A write that did not land, with the step that refused it."""


# ---------------------------------------------------------------------------
# the pure half
# ---------------------------------------------------------------------------

def label_names(issue: dict) -> list:
    return [(n.get("name") or "") for n in ((issue.get("labels") or {}).get("nodes") or [])]


def has_owner(names) -> bool:
    # Case-folded: Linear stores owner:sana lowercase on this board, and a human
    # typing Owner:Sana still means an owner (alert-to-linear.py:816 hit the same).
    return any(n.strip().lower().startswith(OWNER_PREFIX) for n in names)


def project_of(issue: dict):
    return ((issue.get("project") or {}).get("name") or "").strip() or None


def fleet_projects(registry_path: str) -> tuple:
    """(board names every registry row carries, ok). Read through linear_registry,
    the one reader of instance-registry.json, never a second parse of its rows.

    Every row counts, not only rows whose checkout is on this machine: a fleet
    project with its checkout elsewhere is still the fleet's ticket.
    """
    try:
        with open(registry_path) as fh:
            reg = json.load(fh)
    except Exception:
        return frozenset(), False
    names = {linear_registry.linear_project(r) for r in linear_registry._rows(reg)}
    names.discard("")
    return frozenset(names), bool(names)


def classify(issue: dict, fleet: frozenset) -> str:
    """'closed' | 'founder' | 'owned' | 'sweep' | 'outside'. One class each."""
    if ((issue.get("state") or {}).get("type")) in CLOSED_STATE_TYPES:
        return "closed"
    names = label_names(issue)
    if any(n.strip().lower() == FOUNDER_LABEL for n in names):
        return "founder"
    if has_owner(names):
        return "owned"
    proj = project_of(issue)
    if proj is None or proj in fleet:
        return "sweep"
    return "outside"


def next_step(issue: dict) -> str:
    """The consumer that takes this ticket after it has an owner. Named, never vague.

    Each branch names the script and the job that runs it, per the 2026-11-08
    ruling "There is no someone": a handoff that names no consumer is the defect.
    """
    desc = issue.get("description") or ""
    if project_of(issue) is None:
        if DOR_HEADING in desc:
            return ("It has no project, so ready() refuses it in every repo. "
                    "linear-route.py (run by com.kipi.linear-triage-health at 09:00) "
                    "sets the project from the Files: line of its Definition of Ready.")
        # PR #654 review, minor: a clause here once said the run evidence keeps the
        # ticket visible. No script reads last-run.json, so it named no consumer.
        return ("It has no project and no Definition of Ready, so nothing picks this up "
                "until ASK-3959 ships the router that stamps a project at creation.")
    if ALERT_MARKER in desc:
        return ("It is a fleet alert, so linear-alert-triage.py (com.kipi.linear-alert-triage, "
                "02:30) decides promote or close.")
    if DOR_HEADING in desc:
        return ("It has a project and a Definition of Ready, so the fleet worker "
                "(com.kipi.dispatch, linear-worker.sh ready()) can pick it on its next tick.")
    return ("linear-dor-drafter.py (com.kipi.linear-dor, 03:00) drafts its Definition "
            "of Ready, then the fleet worker (com.kipi.dispatch) can pick it.")


def sweep_comment(issue: dict) -> str:
    """THE body this job writes. One producer, so the marker lookup reads what it writes."""
    return (f"<!-- {SWEEP_MARKER}: {OWNER_LABEL} -->\n"
            f"**Owner set: {OWNER_LABEL}.** This ticket had no owner:* label, and every "
            f"open fleet ticket has one (founder ruling 2026-11-08, ASK-4010). "
            f"linear-owner-sweep.py (com.kipi.linear-owner-sweep, nightly) added it.\n\n"
            f"Next step: {next_step(issue)}\n\n"
            f"To give it another owner, put that owner:* label on it. This sweep only "
            f"acts on tickets that carry none.")


def plan(issues: list, fleet: frozenset) -> dict:
    """The whole decision for one board walk. Pure: no network, no clock."""
    out = {"sweep": [], "founder": [], "outside": {}, "owned": 0, "closed": 0}
    for issue in issues:
        kind = classify(issue, fleet)
        if kind == "sweep":
            out["sweep"].append(issue)
        elif kind == "founder":
            out["founder"].append(issue.get("identifier"))
        elif kind == "outside":
            out["outside"].setdefault(project_of(issue), []).append(issue.get("identifier"))
        else:
            out[kind] += 1
    return out


def marker_present(comment_nodes: list) -> bool:
    needle = f"<!-- {SWEEP_MARKER}:"
    return any(needle in (n.get("body") or "") for n in comment_nodes)


# ---------------------------------------------------------------------------
# the network half
# ---------------------------------------------------------------------------

def _load_sync():
    """linear-sync.py owns the transport, including the KIPI_LINEAR_API_URL seam."""
    spec = importlib.util.spec_from_file_location("linear_sync", HERE / "linear-sync.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def fetch_board(sync, team_key: str) -> tuple:
    """(open issues, team_id). Raises on a broken walk rather than reporting a short board."""
    team_id = sync.graphql(TEAM_QUERY, {"k": team_key})["teams"]["nodes"][0]["id"]
    issues, after = [], None
    while True:
        page = sync.graphql(BOARD_QUERY, {"t": team_id, "a": after})["issues"]
        issues += page["nodes"]
        if not page["pageInfo"]["hasNextPage"]:
            break
        after = page["pageInfo"]["endCursor"]
    return issues, team_id


def owner_label_id(sync, team_id: str) -> str:
    nodes = ((((sync.graphql(TEAM_LABELS_QUERY, {"t": team_id}) or {}).get("team") or {})
              .get("labels") or {}).get("nodes") or [])
    for n in nodes:
        if (n.get("name") or "").strip().lower() == OWNER_LABEL:
            return n.get("id") or ""
    return ""


def apply_one(sync, issue: dict, label_id: str) -> str:
    """Write one ticket. Returns what happened; raises WriteRefused on a refused write."""
    fresh = ((sync.graphql(ISSUE_QUERY, {"id": issue["id"]}) or {}).get("issue")) or {}
    if not fresh:
        raise WriteRefused(f"{issue.get('identifier')}: re-read returned nothing")
    if ((fresh.get("state") or {}).get("type")) in CLOSED_STATE_TYPES:
        return "closed-since-walk"
    if has_owner(label_names(fresh)):
        return "owned-since-walk"
    comments = (fresh.get("comments") or {})
    nodes = comments.get("nodes") or []
    did = []
    if not marker_present(nodes):
        if (comments.get("pageInfo") or {}).get("hasNextPage"):
            # Over 100 comments and no marker on page one: the marker may still be
            # on a later page. Labelling without a second comment is the safe half.
            did.append("comment-skipped-truncated")
        else:
            res = (sync.graphql(COMMENT_CREATE, {"input": {
                "issueId": fresh["id"], "body": sweep_comment(issue)}}) or {})
            if not (res.get("commentCreate") or {}).get("success"):
                raise WriteRefused(f"{issue.get('identifier')}: commentCreate refused; "
                                   f"label not written, next run retries both")
            did.append("commented")
    # addedLabelIds is applied server-side and leaves every other label in place,
    # so there is no read-modify-write window (linear-alert-triage.py, PR #268 R3).
    res = (sync.graphql(ISSUE_UPDATE, {"id": fresh["id"],
                                       "input": {"addedLabelIds": [label_id]}}) or {})
    if not (res.get("issueUpdate") or {}).get("success"):
        raise WriteRefused(f"{issue.get('identifier')}: issueUpdate(addedLabelIds) refused; "
                           f"next run retries the label without a second comment")
    did.append(f"labelled {OWNER_LABEL}")
    return ", ".join(did)


def write_evidence(path: pathlib.Path, payload: dict) -> None:
    """One writer, atomic rename, so a reader never sees half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".last-run.", suffix=".json")
    with os.fdopen(fd, "w") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
    os.replace(tmp, path)


def main(argv: list) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--team", default=os.environ.get("KIPI_LINEAR_TEAM", "ASK"))
    ap.add_argument("--registry", default=None,
                    help="instance-registry.json (default: the skeleton's)")
    ap.add_argument("--json", action="store_true", help="print the result as JSON")
    ap.add_argument("--apply", action="store_true", help="write (default: report only)")
    try:
        args = ap.parse_args(argv)
    except SystemExit:
        return EXIT_USAGE

    if args.apply and os.environ.get("PYTEST_CURRENT_TEST"):
        print("linear-owner-sweep: REFUSED --apply under pytest.", file=sys.stderr)
        return EXIT_REFUSED_FIXTURE

    fleet, reg_ok = fleet_projects(args.registry or linear_registry.default_registry_path())
    if not reg_ok:
        # Without the registry, "fleet project" and "outside project" cannot be told
        # apart. Labelling on a guess would hand another system's tickets to Sana.
        print("linear-owner-sweep: instance-registry.json unreadable; nothing classified, "
              "nothing written. Exit 9.", file=sys.stderr)
        return EXIT_INCOMPLETE

    sync = _load_sync()
    try:
        sync.linear_api_key()
    except Exception as exc:
        print(f"linear-owner-sweep: no Linear key configured ({exc})", file=sys.stderr)
        return EXIT_NO_KEY
    try:
        issues, team_id = fetch_board(sync, args.team)
    except Exception as exc:
        print(f"linear-owner-sweep: board walk failed ({exc}); nothing written. Exit 9.",
              file=sys.stderr)
        return EXIT_INCOMPLETE

    p = plan(issues, fleet)
    written, failed = [], []
    if args.apply and p["sweep"]:
        label_id = owner_label_id(sync, team_id)
        if not label_id:
            failed.append({"id": "*", "error": f"team has no {OWNER_LABEL} label"})
        else:
            for issue in p["sweep"]:
                try:
                    written.append({"id": issue["identifier"],
                                    "did": apply_one(sync, issue, label_id)})
                except Exception as exc:
                    # One refused write must not abandon the rest of the population.
                    failed.append({"id": issue.get("identifier"), "error": str(exc)[:200]})

    result = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "applied": bool(args.apply),
        "open": len(issues),
        "ownerless_in_scope": len(p["sweep"]),
        "ownerless_ids": [i.get("identifier") for i in p["sweep"]],
        "founder_owned": len(p["founder"]),
        "founder_ids": p["founder"],
        "outside_fleet": p["outside"],
        "written": written,
        "failed": failed,
    }
    if args.apply:
        try:
            write_evidence(EVIDENCE_PATH, result)
        except OSError as exc:
            print(f"linear-owner-sweep: run evidence not written ({exc})", file=sys.stderr)
            failed.append({"id": "*", "error": "run evidence not written"})

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        outside = sum(len(v) for v in p["outside"].values())
        print(f"linear-owner-sweep: {len(issues)} open; {len(p['sweep'])} with no owner "
              f"label in the fleet's scope; {len(p['founder'])} {FOUNDER_LABEL} (counted, "
              f"left as is); {outside} ownerless outside the fleet's projects.")
        for proj, ids in sorted(p["outside"].items()):
            print(f"  outside {proj}: {', '.join(ids)}")
        for row in written:
            print(f"  WROTE {row['id']}: {row['did']}")
        for row in failed:
            print(f"  FAILED {row['id']}: {row['error']}", file=sys.stderr)
        if not args.apply:
            for issue in p["sweep"]:
                print(f"  would label {issue.get('identifier')} ({project_of(issue) or 'no project'})")
            print("report only. --apply to write.")
    return EXIT_WRITE_FAILED if failed else EXIT_OK


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
