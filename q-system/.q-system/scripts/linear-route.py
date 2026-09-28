#!/usr/bin/env python3
"""Route the DoR tickets no dispatcher can reach, and MARK the ones nothing can route (ASK-1887).

THE DEFECT
----------
`linear-worker.sh`'s `ready()` needs three things at once: `owner:sana`, a project
that matches this checkout, and a Definition of Ready. Measured 2026-09-19 against
team ASK: 102 non-alert tickets carried the DoR, were not held, and still failed
`ready()` -- 49 with `owner:sana` and no project, 37 with neither, 16 on
`kipi-system` with an empty label set. Median age 12 days, oldest 47.
`linear-triage-health.py` has counted the class the whole time (311 unrouted
against an alert line of 50) and alerted about it. Nothing acted. This is the
paired action.

WHY A BOARD SWEEP AND NOT A FILER PATCH
---------------------------------------
Every issue-creating script in this repo already sets `projectId` when its lookup
resolves one: alert-to-linear.py:1020, fleet-health-daily.py:2298,
linear-dor-drafter.py:1158, linear-job-migration.py:206, linear-sync.py:977,
spillover-promote.py:553. ASK-1886 -- the ticket whose filing caused ASK-1887 --
came from none of them. A Claude Code session filed it through the Linear MCP with
a full DoR, no owner label and no project, and it would have sat forever. Hardening
the six filers judges only the entry paths we built a judge for. Reading the board
covers every entry path there will ever be, including the next one.

A GUESS IS WORSE THAN A GAP
---------------------------
Routing a ticket to a project makes it eligible for an autonomous run in that
repo. A wrong route puts a worker in the wrong repo. So this script routes ONLY on
an unambiguous path-to-registry match and refuses everything else, which is
ASK-1887's own blast-radius rule: an unknown target stays unrouted and gets a mark
saying so, never a guess.

That is also why Jev is not the router here. Measured 2026-09-19 over 816 tickets
that already carried a project: 0.779 accuracy over all of them, 0.885 at a 0.95
confidence floor, and the 54 wrong ones at that floor are systematic rather than
random (26 kipi-system tickets sent to cole-GTM). Good enough to SUGGEST beside a
deterministic pass, not good enough to dispatch on.

THE RULES, strongest first
--------------------------
    R1  an absolute path under a registry row's `path`            -> that row
    R2  a relative path whose first segment is a row's q-dir      -> that row
    R3  a relative path that is skeleton-managed and exists there -> the skeleton
    --  no rule fires, or two paths name two different rows       -> UNROUTABLE

R3 asks `kipi-update.sh` which subtrees an INSTANCE owns, rather than holding its
own copy of that list. `q-system/my-project/` and `q-system/canonical/` are
authored per instance, so a path inside one names no repo; everything else under
`q-system/` is skeleton-managed, because `kipi update`'s rsync --delete overwrites
it in every instance (RULE-2026-06-30-A). A copied list agrees on the day it is
written and then diverges silently, which this repo has paid for twice already
(ASK-729, ASK-840).

THE OWNER LABEL, AND THE POPULATION IT SKIPS
--------------------------------------------
A DoR ticket with no owner label gets `owner:sana` -- but only once it has a
project, and never when the ticket is machine-filed job inflow. ASK-1887's
"Not doing" line is explicit: the launchd job tickets name `com.cole.*` and
`com.alice.*` jobs that may be paused or retired, and they need a liveness check
before a worker run, not a label. That population is read from the marker its own
filer stamps (`<!-- kipi-key: fleet-health/... -->`, `<!-- kipi-key:
job-migration/... -->`), never from title prose a human can edit.

AN UNREADABLE REGISTRY IS UNKNOWN, NOT UNROUTABLE
-------------------------------------------------
Every project resolves to nothing when the registry cannot be read, so classifying
that as "nothing routes" would mark the entire board unroutable in one run. Same
posture, same reason, as `linear-route-reachability-check.py` beside it.

Usage:
    python3 linear-route.py                 # read-only report
    python3 linear-route.py --json          # the same, as JSON
    python3 linear-route.py --apply --limit 20   # write, bounded
"""
from __future__ import annotations

import argparse
import dataclasses
import importlib.util
import json
import os
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import linear_registry  # noqa: E402  (after sys.path, by design)

# Every way a write can fail, as a CLOSED vocabulary. The alert one job up is
# built from these strings, so an unnamed failure class would reach Sana as the
# wrong cause -- which is exactly what "refused by Linear" said about the first
# two, neither of which ever reached the network (PR #461 review, minor).
WRITE_FAILURE_KINDS = ("no-such-project", "no-such-label", "linear-refused-project",
                       "linear-refused-label", "linear-refused-comment")
LOCAL_FAILURE_KINDS = ("no-such-project", "no-such-label")


class WriteRefused(RuntimeError):
    """A write that did not land, carrying WHY in a form a report can read."""

    def __init__(self, kind: str, message: str):
        if kind not in WRITE_FAILURE_KINDS:
            raise ValueError(f"unknown write-failure kind {kind!r}")
        super().__init__(message)
        self.kind = kind


EXIT_OK = 0
EXIT_NO_KEY = 3
EXIT_REFUSED_FIXTURE = 4
EXIT_INCOMPLETE = 9

OWNER_LABEL = "owner:sana"
FOUNDER_LABEL = "owner:assaf"
HELD_LABELS = ("needs-scope", "blocked:capability")
OPEN_STATE_TYPES = ("backlog", "unstarted")
ALERT_MARKER = "kipi-alert-fingerprint"
KEY_MARKER = "kipi-key"
# The mark this script writes when no rule fires. Read back on the next run so a
# marked ticket is never re-marked: the mark is a record, not a running commentary.
UNROUTABLE_MARKER = "route-unknown"
# kipi-key prefixes whose issues are machine-filed job inflow (ASK-1887 Not-doing).
JOB_INFLOW_PREFIXES = ("fleet-health/", "job-migration/")

# The comments come back WITH the board walk, because the mark this script writes
# is a comment and a reader that does not fetch comments cannot see it (PR #461
# review, major). 50 is a page, not a guarantee: `pageInfo.hasNextPage` rides
# along so a truncated read can be named rather than mistaken for "unmarked".
COMMENT_PAGE = 50
BOARD_QUERY = """query($t:ID!,$a:String){issues(filter:{team:{id:{eq:$t}}},first:250,after:$a){
 nodes{id identifier title description state{name type} project{name}
       labels{nodes{id name}}
       comments(first:%d){nodes{body} pageInfo{hasNextPage}}}
 pageInfo{hasNextPage endCursor}}}""" % COMMENT_PAGE
TEAM_QUERY = 'query($k:String!){teams(filter:{key:{eq:$k}}){nodes{id}}}'
PROJECTS_QUERY = """query($t:String!){team(id:$t){projects(first:250){nodes{id name}}}}"""
TEAM_LABELS_QUERY = """query($t:String!){team(id:$t){labels(first:250){nodes{id name}}}}"""
ISSUE_UPDATE = """mutation($id:String!,$input:IssueUpdateInput!){
 issueUpdate(id:$id,input:$input){success issue{identifier}}}"""
COMMENT_CREATE = """mutation($input:CommentCreateInput!){
 commentCreate(input:$input){success comment{id}}}"""


# ---------------------------------------------------------------------------
# facts
# ---------------------------------------------------------------------------

_OWNED_RE = re.compile(r"^INSTANCE_OWNED_SUBTREES=\(\n(.*?)^\)", re.S | re.M)


def _parse_instance_owned(updater_path: str) -> list:
    """The subtrees `kipi update` never copies into an instance, parsed from it.

    Same regex `fleet-reach-audit.py` and `kipi-update-preserve-scan.py` use. An
    empty parse returns [] and the caller degrades to `ok=False`, because a
    silently-empty list would make every path under `q-system/` look
    skeleton-managed -- a routing rule that fires on `q-system/canonical/` would
    send instance-authored work to the skeleton.
    """
    try:
        text = pathlib.Path(updater_path).read_text()
    except OSError:
        return []
    match = _OWNED_RE.search(text)
    if not match:
        return []
    return [line.strip() for line in match.group(1).splitlines() if line.strip()]


@dataclasses.dataclass
class RoutingFacts:
    """Everything the rules read, from ONE registry read and ONE updater read."""

    ok: bool
    rows_by_project: dict          # board project -> {"path", "q_dir"}
    instance_owned: list           # subtrees an instance authors, relative to q-system/
    skeleton_project: str
    skeleton_path: str

    @classmethod
    def load(cls, registry_path: str, updater_path: str | None = None) -> "RoutingFacts":
        try:
            with open(registry_path) as fh:
                reg = json.load(fh)
        except Exception:
            return cls(False, {}, [], "", "")

        skel_row = reg.get("skeleton") if isinstance(reg, dict) else None
        skel_path = (skel_row or {}).get("path") or ""
        if updater_path is None:
            updater_path = os.path.join(skel_path, "kipi-update.sh")
        owned = _parse_instance_owned(updater_path)

        rows = {}
        for entry in linear_registry._rows(reg):
            project = linear_registry.linear_project(entry)
            path = entry.get("path")
            if not project or not path:
                continue
            rows[project] = {"path": path, "q_dir": entry.get("instance_q_dir") or ""}

        # An empty owned-list is UNKNOWN, not "nothing is instance-owned": R3
        # would then claim every path under q-system/ for the skeleton.
        return cls(bool(rows) and bool(owned), rows,
                   owned, linear_registry.linear_project(skel_row or {}), skel_path)


# ---------------------------------------------------------------------------
# selection
# ---------------------------------------------------------------------------

def labels_of(issue: dict) -> set:
    return {n.get("name") for n in ((issue.get("labels") or {}).get("nodes") or [])}


def project_of(issue: dict):
    return (issue.get("project") or {}).get("name")


def comment_keys(description: str) -> list:
    """(key, value) for every WHOLE HTML-comment key in the body.

    Parsed as a whole key, never as a bare substring, for the reason ASK-839
    recorded one file over: a substring test counts an issue that merely
    DISCUSSES a marker as carrying it, and this ticket's own body names both
    markers below.
    """
    out = []
    for chunk in (description or "").split("<!--")[1:]:
        head = chunk.split("-->", 1)[0]
        name, sep, rest = head.partition(":")
        out.append((name.strip(), rest.strip() if sep else ""))
    return out


def is_fleet_alert(issue: dict) -> bool:
    return any(key == ALERT_MARKER for key, _ in comment_keys(issue.get("description")))


def is_job_inflow(issue: dict) -> bool:
    """Machine-filed launchd job inflow, read from the marker its filer stamps."""
    for key, value in comment_keys(issue.get("description")):
        if key == KEY_MARKER and value.startswith(JOB_INFLOW_PREFIXES):
            return True
    return False


def _comment_bodies(issue: dict) -> tuple:
    node = issue.get("comments") or {}
    return (tuple((n.get("body") or "") for n in (node.get("nodes") or [])),
            bool((node.get("pageInfo") or {}).get("hasNextPage")))


def is_marked_unroutable(issue: dict) -> bool:
    """Read the mark where the mark is WRITTEN, plus where a person may paste it.

    `apply_row` writes `UNROUTABLE_MARKER` as a COMMENT. Until PR #461's review
    this function read only the description, so it never found its own mark: the
    daily --apply tick re-commented every unroutable ticket and each re-mark ate
    one of the run's 10 write slots. The description is still read because a
    human who pastes the marker into the body has marked it too.

    A TRUNCATED comment page with no marker on it counts as MARKED. The asymmetry
    is deliberate and inverts `already_flagged()` in linear-triage-health.py:
    there the expensive outcome is a missed flag, here it is a duplicate comment
    every morning. `measure()` counts these under `mark_unknown` so the skip is
    named rather than silent.
    """
    bodies, truncated = _comment_bodies(issue)
    for text in (issue.get("description"), *bodies):
        if any(key == UNROUTABLE_MARKER for key, _ in comment_keys(text)):
            return True
    return truncated


def mark_read_incomplete(issue: dict) -> bool:
    """True when the comment page ran out before the marker was found."""
    bodies, truncated = _comment_bodies(issue)
    if not truncated:
        return False
    return not any(key == UNROUTABLE_MARKER
                   for text in (issue.get("description"), *bodies)
                   for key, _ in comment_keys(text))


def is_pending(issue: dict) -> bool:
    """Carries a DoR, is open and unheld, and still cannot be picked up.

    The population `ready()` refuses for a reason a ROUTER can fix: a missing
    project or a missing owner label. An issue whose project simply names no
    checkout is the sibling check's population
    (`linear-route-reachability-check.py`), not this one.
    """
    labels = labels_of(issue)
    if FOUNDER_LABEL in labels:
        return False
    if any(held in labels for held in HELD_LABELS):
        return False
    if (issue.get("state") or {}).get("type") not in OPEN_STATE_TYPES:
        return False
    if "Definition of Ready" not in (issue.get("description") or ""):
        return False
    if is_fleet_alert(issue):
        return False
    return not project_of(issue) or OWNER_LABEL not in labels


# ---------------------------------------------------------------------------
# path extraction
# ---------------------------------------------------------------------------

_FILES_FIELD = re.compile(r"^\s*[-*]?\s*\*\*Files:?\*\*", re.I)
_NEXT_FIELD = re.compile(r"^\s*[-*]?\s*\*\*[A-Z]", re.I)
_BACKTICKED = re.compile(r"`([^`\n]+)`")


def _looks_like_a_path(token: str) -> bool:
    """A conservative filter. A wrong ACCEPT here becomes a wrong route."""
    token = token.strip()
    if not token or " " in token or "(" in token or ")" in token:
        return False
    if token.startswith("http://") or token.startswith("https://"):
        return False
    return "/" in token or bool(re.search(r"\.[A-Za-z0-9]{1,6}$", token))


def dor_file_paths(description: str) -> list:
    """The backticked paths on the DoR's **Files:** field, in order.

    Bounded to that field on purpose: **Check:** routinely names a command that
    RUNS a script in another repo, and **Blast radius:** names paths the work must
    not touch. Reading those as routing evidence is how a ticket gets sent
    somewhere it was explicitly told not to go.
    """
    lines = (description or "").splitlines()
    collected, inside = [], False
    for line in lines:
        if inside:
            if not line.strip() or _NEXT_FIELD.match(line):
                break
            collected.append(line)
            continue
        if _FILES_FIELD.match(line):
            inside = True
            collected.append(line)
    out = []
    for line in collected:
        for token in _BACKTICKED.findall(line):
            token = token.strip()
            if _looks_like_a_path(token) and token not in out:
                out.append(token)
    return out


# ---------------------------------------------------------------------------
# the rules
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class Decision:
    project: str | None
    rule: str | None
    reason: str


def _expand(path: str) -> str:
    return os.path.expanduser(path)


def _match_absolute(path: str, facts: RoutingFacts):
    """R1. Longest row path wins, so a nested checkout beats its parent."""
    real = os.path.realpath(_expand(path))
    best = None
    for project, row in facts.rows_by_project.items():
        root = os.path.realpath(row["path"])
        if real == root or real.startswith(root + os.sep):
            if best is None or len(root) > best[1]:
                best = (project, len(root))
    return best[0] if best else None


def _match_q_dir(path: str, facts: RoutingFacts):
    """R2. `q-consult/...` names the consulting instance and nothing else.

    THE PREFIX ALONE IS NOT ENOUGH, and the mutation test is what said so. The
    first version matched the q-dir name and stopped there, so moving a row's
    `path` to a directory that does not exist still routed tickets to it -- a
    rule reading the registry's NAMES while ignoring the field that says where
    the checkout is. The file has to be there, which also makes a stale q-dir on
    a retired row route nothing instead of routing wrongly.
    """
    head = path.split("/", 1)[0]
    if not head:
        return None
    for project, row in facts.rows_by_project.items():
        if row["q_dir"] and row["q_dir"] == head \
                and os.path.exists(os.path.join(row["path"], path)):
            return project
    return None


def _is_instance_owned(path: str, facts: RoutingFacts) -> bool:
    relative = path[len("q-system/"):] if path.startswith("q-system/") else path
    return any(relative == sub or relative.startswith(sub + "/")
               for sub in facts.instance_owned)


def _match_skeleton(path: str, facts: RoutingFacts):
    """R3. Skeleton-managed, and the file is actually there."""
    if not facts.skeleton_path or not facts.skeleton_project:
        return None
    if _is_instance_owned(path, facts):
        return None
    if not os.path.exists(os.path.join(facts.skeleton_path, path)):
        return None
    return facts.skeleton_project


def _route_one(path: str, facts: RoutingFacts) -> Decision:
    if os.path.isabs(_expand(path)):
        hit = _match_absolute(path, facts)
        if hit:
            return Decision(hit, "R1", f"{path} is inside that checkout")
        return Decision(None, None, f"{path} is absolute and under no registry row")
    hit = _match_q_dir(path, facts)
    if hit:
        return Decision(hit, "R2", f"{path} starts with that instance's q-dir")
    if _is_instance_owned(path, facts):
        return Decision(None, None,
                        f"{path} is in an instance-owned subtree; every instance "
                        "authors its own, so the path names no repo")
    hit = _match_skeleton(path, facts)
    if hit:
        return Decision(hit, "R3", f"{path} is skeleton-managed and present there")
    return Decision(None, None, f"no rule fired for {path}")


def route_paths(paths: list, facts: RoutingFacts) -> Decision:
    """One decision for the whole **Files:** list. Disagreement refuses."""
    if not facts.ok:
        return Decision(None, None,
                        "UNKNOWN: instance-registry.json or kipi-update.sh could "
                        "not be read; nothing classified")
    if not paths:
        return Decision(None, None, "the DoR names no files")
    hits, misses = [], []
    for path in paths:
        decision = _route_one(path, facts)
        (hits if decision.project else misses).append(decision)
    named = sorted({d.project for d in hits})
    if len(named) > 1:
        return Decision(None, None,
                        "the DoR's files disagree: " + ", ".join(named))
    if named:
        return hits[0]
    return misses[0] if misses else Decision(None, None, "no path resolved")


# ---------------------------------------------------------------------------
# the plan
# ---------------------------------------------------------------------------

def plan_actions(issues: list, facts: RoutingFacts) -> list:
    """One row per pending issue: what a run WOULD write, and why. Pure."""
    rows = []
    for issue in issues:
        if not is_pending(issue):
            continue
        decision = route_paths(dor_file_paths(issue.get("description")), facts)
        current = project_of(issue)
        labels = labels_of(issue)
        set_project = decision.project if (not current and decision.project) else None
        will_have_project = bool(current or set_project)
        # The label follows the project, never leads it. Adding owner:sana to a
        # project-less ticket manufactures more of the 49-ticket class this
        # script exists to drain.
        add_label = (OWNER_LABEL if (will_have_project
                                     and OWNER_LABEL not in labels
                                     and not is_job_inflow(issue)) else None)
        rows.append({
            "id": issue.get("id"),
            "identifier": issue.get("identifier"),
            "title": issue.get("title") or "",
            "project": current,
            "set_project": set_project,
            "add_label": add_label,
            "mark_unroutable": bool(not will_have_project
                                    and not is_marked_unroutable(issue)),
            "mark_unknown": bool(not will_have_project
                                 and mark_read_incomplete(issue)),
            "rule": decision.rule,
            "reason": decision.reason,
            "label_ids": sorted({n["id"] for n in
                                 ((issue.get("labels") or {}).get("nodes") or [])
                                 if n.get("id")}),
        })
    return rows


def rows_with_work(rows: list) -> list:
    return [r for r in rows
            if r["set_project"] or r["add_label"] or r["mark_unroutable"]]


def measure(issues: list, facts: RoutingFacts) -> dict:
    rows = plan_actions(issues, facts)
    routable = [r for r in rows if r["set_project"] or r["project"]]
    return {
        "registry_ok": facts.ok,
        "pending": len(rows),
        "routable": len(routable),
        "unroutable": len(rows) - len(routable),
        # Named on purpose: these tickets were skipped because their comment page
        # ran out, not because they are fine. An unnamed skip is a silent one.
        "mark_unknown": sum(1 for r in rows if r["mark_unknown"]),
        "with_work": len(rows_with_work(rows)),
        "by_rule": {rule: sum(1 for r in rows if r["rule"] == rule)
                    for rule in sorted({r["rule"] for r in rows if r["rule"]})},
    }


def select_to_write(rows: list, limit: int) -> list:
    """Which rows this run may WRITE. Never a display concern.

    Split out for the reason `select_to_flag` in linear-triage-health.py was:
    when the cap lives inside the print loop, the run flags N and prints "and
    more", and the sentence reads as a work report.
    """
    if limit < 0:
        raise ValueError("limit must be >= 0")
    return rows[:limit] if limit else list(rows)


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
    """(issues, team_id). Raises on a broken walk rather than reporting a short board."""
    team_id = sync.graphql(TEAM_QUERY, {"k": team_key})["teams"]["nodes"][0]["id"]
    issues, after = [], None
    while True:
        page = sync.graphql(BOARD_QUERY, {"t": team_id, "a": after})["issues"]
        issues += page["nodes"]
        if not page["pageInfo"]["hasNextPage"]:
            break
        after = page["pageInfo"]["endCursor"]
    return issues, team_id


def _name_id_map(sync, query: str, team_id: str, field: str) -> dict:
    nodes = (((sync.graphql(query, {"t": team_id}) or {}).get("team") or {})
             .get(field) or {}).get("nodes") or []
    return {(n.get("name") or "").strip().lower(): n.get("id") for n in nodes}


def unroutable_comment(reason: str) -> str:
    """THE body of the mark. One producer, so a reader can be fed by it.

    Extracted from `apply_row` for the reason PR #461's review found: the test
    that claimed a marked ticket is never re-marked pasted its own hand-written
    body, agreed with itself, and agreed with nothing the script writes.
    """
    return (f"<!-- {UNROUTABLE_MARKER}: {reason} -->\n\n"
            f"**Not routable from this ticket's own Definition of Ready.** "
            f"{reason}.\n\n"
            f"Routing is deterministic on purpose (ASK-1887): a wrong project "
            f"sends an autonomous worker into the wrong repo, so an unknown "
            f"target is marked rather than guessed. To route it, name a file "
            f"path in the DoR's **Files:** field that lives in exactly one "
            f"checkout, or set the project by hand.")


def apply_row(sync, row: dict, projects: dict, labels: dict) -> list:
    """Write one row. Returns the list of writes that LANDED.

    Every mutation's `success` is read. A discarded return value turns a rejected
    write into a reported one, and here that means a ticket the report calls
    routed which the picker still refuses -- the silent-redispatch shape
    linear-sync.py's cmd_label already records.

    Every failure raises `WriteRefused` carrying a KIND, because the operator's
    only visible line is built from it: before PR #461's review a local lookup
    miss, which never reached the network, was reported to Sana as a write
    "refused by Linear".
    """
    done = []
    if row["set_project"]:
        pid = projects.get(row["set_project"].lower())
        if not pid:
            raise WriteRefused("no-such-project",
                               f"no board project named {row['set_project']!r}")
        res = (sync.graphql(ISSUE_UPDATE, {"id": row["id"],
                                           "input": {"projectId": pid}}) or {})
        if not (res.get("issueUpdate") or {}).get("success"):
            raise WriteRefused("linear-refused-project",
                               f"issueUpdate(project) refused for {row['identifier']}")
        done.append(f"project={row['set_project']}")
    if row["add_label"]:
        lid = labels.get(row["add_label"].lower())
        if not lid:
            raise WriteRefused("no-such-label",
                               f"no team label named {row['add_label']!r}")
        # READ-MODIFY-WRITE: issueUpdate takes labelIds as the COMPLETE set, so
        # sending only the new id strips every label already on the issue.
        res = (sync.graphql(ISSUE_UPDATE, {
            "id": row["id"],
            "input": {"labelIds": sorted(set(row["label_ids"]) | {lid})}}) or {})
        if not (res.get("issueUpdate") or {}).get("success"):
            raise WriteRefused("linear-refused-label",
                               f"issueUpdate(labels) refused for {row['identifier']}")
        done.append(f"label={row['add_label']}")
    if row["mark_unroutable"]:
        res = (sync.graphql(COMMENT_CREATE,
                            {"input": {"issueId": row["id"],
                                       "body": unroutable_comment(row["reason"])}}) or {})
        if not (res.get("commentCreate") or {}).get("success"):
            raise WriteRefused("linear-refused-comment",
                               f"commentCreate refused for {row['identifier']}")
        done.append("marked-unroutable")
    return done


def render(m: dict, rows: list) -> str:
    if not m["registry_ok"]:
        return ("linear-route: UNKNOWN -- instance-registry.json or kipi-update.sh "
                "could not be read. Nothing classified; this is not a pass.")
    lines = [f"linear-route: {m['pending']} pending (DoR, unheld, not pickable); "
             f"{m['routable']} routable, {m['unroutable']} unroutable, "
             f"{m['with_work']} with a write to make."]
    if m["by_rule"]:
        lines.append("  routed by: " + ", ".join(f"{k}={v}" for k, v in m["by_rule"].items()))
    for row in rows_with_work(rows):
        acts = [a for a in (
            f"project={row['set_project']}" if row["set_project"] else "",
            f"label={row['add_label']}" if row["add_label"] else "",
            "mark-unroutable" if row["mark_unroutable"] else "") if a]
        lines.append(f"  {row['identifier']}: {', '.join(acts)}  ({row['reason']})")
    return "\n".join(lines)


def main(argv: list) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--team", default=os.environ.get("KIPI_LINEAR_TEAM", "ASK"))
    ap.add_argument("--registry", default=None,
                    help="instance-registry.json (default: the skeleton's)")
    ap.add_argument("--json", action="store_true", help="print the measurement as JSON")
    ap.add_argument("--apply", action="store_true",
                    help="write the routing (default: report only)")
    ap.add_argument("--limit", type=int, default=0, metavar="N",
                    help="write at most N issues this run (0 = no cap)")
    args = ap.parse_args(argv)

    if args.limit < 0:
        print("--limit must be >= 0", file=sys.stderr)
        return EXIT_INCOMPLETE

    # THE FIXTURE CHOKEPOINT, the same one alert-to-linear.py and
    # linear-triage-health.py carry. A suite written tomorrow must not be able to
    # relabel a real issue, and the refusal lives here rather than in each test.
    if args.apply and os.environ.get("PYTEST_CURRENT_TEST"):
        print("linear-route: REFUSED under pytest.", file=sys.stderr)
        return EXIT_REFUSED_FIXTURE

    registry = args.registry or linear_registry.default_registry_path()
    facts = RoutingFacts.load(registry)
    sync = _load_sync()
    try:
        sync.linear_api_key()
    except Exception as exc:
        print(f"no Linear key configured ({exc})", file=sys.stderr)
        return EXIT_NO_KEY
    try:
        issues, team_id = fetch_board(sync, args.team)
    except Exception as exc:
        print(f"board walk failed ({exc}); nothing measured", file=sys.stderr)
        return EXIT_INCOMPLETE

    rows = plan_actions(issues, facts)
    m = measure(issues, facts)

    written, failed = [], []
    if args.apply and facts.ok:
        projects = _name_id_map(sync, PROJECTS_QUERY, team_id, "projects")
        labels = _name_id_map(sync, TEAM_LABELS_QUERY, team_id, "labels")
        for row in select_to_write(rows_with_work(rows), args.limit):
            try:
                written.append({"id": row["identifier"],
                                "did": apply_row(sync, row, projects, labels)})
            except Exception as exc:
                # One refused write must not abandon the rest: the population is
                # the point, and a run that stops on issue 3 of 90 reports a
                # drain that did not happen.
                failed.append({"id": row["identifier"], "error": str(exc)[:200],
                               "kind": getattr(exc, "kind", "unknown")})
    m["written"] = len(written)
    m["write_failures"] = len(failed)
    # The KINDS travel with the count. The caller's alert line is built from
    # them, and a count on its own can only be described by guessing a cause.
    m["write_failure_kinds"] = sorted({f["kind"] for f in failed})

    if args.json:
        print(json.dumps({**m, "writes": written, "failures": failed}, indent=2))
    else:
        print(render(m, rows))
        for row in written:
            print(f"  WROTE {row['id']}: {', '.join(row['did'])}")
        for row in failed:
            print(f"  FAILED {row['id']}: {row['error']}", file=sys.stderr)
        if not args.apply:
            print("report only. --apply to write.")
    return EXIT_INCOMPLETE if failed else EXIT_OK


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
