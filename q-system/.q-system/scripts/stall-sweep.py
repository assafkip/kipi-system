#!/usr/bin/env python3
"""stall-sweep.py -- every work item idle 24h names its next consumer, or turns red (ASK-4019).

Founder, 2026-11-08: "make sure that we still don't have tickets, PRs or any work
that goes to someone and stalls or stalls anywhere."

WHY A SWEEP AND NOT MORE CONSUMERS. The 2026-11-08 dead-end audit walked 56 exit
sites and found 22 with no consumer. Each fix closes one site; nothing noticed the
next one. This job does not move anything. It lists what has not moved in 24 hours
and asks one question of each item: which code moves it next? An item with no
answer is a gap, and a gap gets exactly one owner:sana ticket.

THE POPULATION
  * tickets: team ASK, state Todo or In Progress (state types unstarted, started),
    updatedAt 24h or more ago. Chief is skipped: the chief rebuild owns it (audit C6).
    A project no registry row names is a gap, not a skip (PR #654 round 3: the owner
    sweep leaves those tickets, so this is where they get a consumer). The archived
    engagement (RULE-2026-10-23-B) is skipped, tickets and repo: the founder's hook
    ps-archive-deny.sh is asked, the way pr-owner.py asks it, and a missing hook
    refuses the run. A gap ticket listing its work would steer an agent at the clean
    room.
  * PRs: open PRs in every fleet repo except assafkip/chief, with no commit, review
    or check run in 24h.
  * worker attempts that started and never ended: a started ticket. The worker log
    has no machine-readable end record, so the end state that can be read is the
    ticket's (state, attempts-ledger row, tree claim, open PR), which is what
    linear-sync.py started_hold_reason already decides. It is asked, not copied.
    The attempts ledger is a set of counters with no start/end pair, so it cannot
    answer this on its own. An interactive lane holds no claim and writes no ledger
    row; its lane marker (ASK-4095) is read first, through linear-sync.py lane_marker.

WHERE IT RUNS. Pinned (job-checkouts.json), from its own tree at origin/main. Its
registry is that tree's instance-registry.json, the copy the pinned dispatcher reads
(kipi-dispatch.sh), so a project the dispatcher cannot see is reported as the gap it
is, never named as reachable. A row only the shared checkout carries is ASK-3967's.

THE CONSUMER, IN ready()'s ORDER (linear-worker.sh). A label ready() refuses maps
through hold-label-consumers.json (ASK-4011), the one table of hold labels. Every
other reason maps through REASONS below. Reachability is repo-preflight.sh, run once
per project, the same gate the worker runs (linear-worker.sh, ASK-840). That gate
fails closed, so a refusal is a gap only once it has held 24h (refusals.json); a
token blip is never a ticket. An alert goes to the alert lane first, as in ready(),
and is judged by linear-alert-triage.py promotion_refusal itself.

ONE TICKET PER GAP, NOT PER ITEM. On 2026-11-08, 44 idle tickets had no project. One
ticket each is 44 tickets for one missing router, and volume from one detector is a
signal about the detector. So a gap is a reason. A reason whose consumer is being
built (a registry `missing` row, or REASONS) already has its ticket: the sweep keeps
one marker comment there listing the items. A reason with no builder gets one filed
ticket (kipi-key stall-sweep/<reason>), never a duplicate. The comment is rewritten
only when the item set changes, so an hourly run is not an hourly write.

Exit codes:
  0  every idle item names a consumer, or its gap has an open ticket after this run
  1  red and unhanded: a gap with no open ticket (cap hit, write refused, or its
     ticket was Canceled, which is a recorded decision and is respected)
  2  usage
  3  no Linear key
  4  --apply refused under pytest
  9  incomplete: a read failed. A failed board walk, registry or archive hook
     writes nothing. Any other failed read is listed, and its items are skipped,
     never filed: "could not look" is not "nothing moves it"

Usage:
    python3 stall-sweep.py            # report only
    python3 stall-sweep.py --json     # the same, as JSON
    python3 stall-sweep.py --apply    # file gap tickets and gap comments
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone

HERE = pathlib.Path(__file__).resolve().parent
QDIR = HERE.parent
sys.path.insert(0, str(HERE))

import linear_registry  # noqa: E402  (after sys.path, by design)

EXIT_OK = 0
EXIT_RED = 1
EXIT_USAGE = 2
EXIT_NO_KEY = 3
EXIT_REFUSED_FIXTURE = 4
EXIT_INCOMPLETE = 9

IDLE_HOURS = 24
# Per run. A first run on a board that has never been swept must not mint a wall.
MAX_NEW_TICKETS = 3
MAX_COMMENT_WRITES = 12
# A comment lists this many items; the count above it is always the full number.
MAX_LISTED = 40

OWNER_LABEL = "owner:sana"
FOUNDER_LABEL = "owner:assaf"
OWNER_PREFIX = "owner:"
# linear-filer-label-lint.py: an automated filer marks its own output.
TRIAGE_LABEL = "needs-triage"
HOME_PROJECT = "kipi-system"
CHIEF_PROJECT = "Chief"
CHIEF_REPO = "assafkip/chief"
ALERT_MARKER = "kipi-alert-fingerprint"
DOR_HEADING = "Definition of Ready"
LANE_HOLD = "triage:held"
KEY_PREFIX = "stall-sweep/"
COMMENT_MARKER = "kipi-stall-sweep"
OPEN_TYPES = ("backlog", "unstarted", "started", "triage")

REGISTRY_REL = "hold-label-consumers.json"
# The labels ready() refuses, in ready()'s own order. parked is absent: since #663
# (ASK-4031) ready() sorts an expired park last instead of refusing it.
READY_LABEL_ORDER = ("owner:assaf", "owner:sana", "needs-scope", "blocked:capability")

# Job state lives outside every checkout (separate-worktrees.md).
EVIDENCE_PATH = pathlib.Path.home() / ".local" / "state" / "kipi" / "stall-sweep" / "last-run.json"
# {project: {"since", "why"}}: when each project's preflight refusal began. One
# writer, this script under --apply. PR #689 review, major 1: repo-preflight.sh
# fails closed, so an expired gh token or one GitHub 5xx refuses every project,
# and filed at once that is a permanent ticket for a project never unreachable.
REFUSALS_PATH = EVIDENCE_PATH.parent / "refusals.json"

# linear-sync.py words that mean "could not look", never "nothing moves it" (PR #689
# review, major 2). test_a_read_failure_inside_started_hold_reason_is_unread_not_a_gap
# pins both against the real module with real ledger files.
# No row, and no ledger file at all, are both facts: the fleet never ran it (PR #689
# review r2, minor 2). A torn ledger or a non-object is a failed read.
NO_HISTORY_PREFIXES = ("no worker history:", "no attempts ledger here")
PR_UNREAD_PREFIX = "its PRs could not be read"

# Every reason that is not a hold label. `builder` is the ticket building the
# missing consumer, or None when nothing is, in which case the sweep files one.
REASONS = {
    "no-project": {
        "builder": "ASK-3959",
        "what": "No project and no Definition of Ready, so no repo's worker sees it and "
                "linear-dor-drafter.py skips it (no project). ASK-3959 builds the router.",
    },
    "outside-fleet-project": {
        "builder": None,
        "what": "Its project has no instance-registry.json row, so no fleet worker, drafter "
                "or owner sweep reaches it. Register the project or move the ticket.",
    },
    "unreachable-project": {
        "builder": None,
        "what": "Its project has no checkout the fleet worker may enter: no local checkout, "
                "or repo-preflight.sh has refused it for 24h or more. No rotation reaches it.",
    },
    "started-no-history": {
        "builder": None,
        "what": "Started, but the attempts ledger has no row for it, so the worker never "
                "releases it (linear-sync.py worker_history). Chief's stale_in_progress is "
                "the only by-age exit and it is cap-starved (audit row 36).",
    },
    "started-held": {
        "builder": None,
        "what": "Started and held by linear-sync.py started_hold_reason for a reason no "
                "job acts on.",
    },
    "lane-marker-unreadable": {
        "builder": None,
        "what": "Its lane marker (~/.config/kipi/lanes, lane-mark.py) cannot be read or names "
                "no expiry. linear-sync.py lane_marker fails closed on it, so the redrives "
                "hold the ticket with no end, and no lane is behind it.",
    },
    "alert-lane-refused": {
        "builder": None,
        "what": "A fleet alert that linear-alert-triage.py promotion_refusal refuses (each "
                "item names its refusal), and ready() refuses every alert (audit row 50).",
    },
    "other-owner": {
        "builder": None,
        "what": "Carries an owner:* label no fleet job works, and no owner:sana, so ready() "
                "refuses it and linear-owner-sweep.py leaves it (it has an owner).",
    },
    "pr-outside-pr-owner": {
        "builder": None,
        "what": "Open PR with no commit, review or check run in 24h, in a repo outside the "
                "dispatcher's set, so pr-owner.py never reads it (audit row 54).",
    },
    "pr-no-owner": {
        "builder": "ASK-3962",
        "what": "Open PR with no commit, review or check run in 24h. No PR owner registry "
                "names what moves it; ASK-3962 builds pr-owner.py.",
    },
}

TEAM_QUERY = 'query($k:String!){teams(filter:{key:{eq:$k}}){nodes{id}}}'
BOARD_QUERY = """query($t:ID!,$a:String){issues(filter:{team:{id:{eq:$t}},
 state:{type:{in:["unstarted","started"]}}},first:100,after:$a){
 nodes{id identifier title description updatedAt startedAt state{type name}
 project{name} labels{nodes{name}}}
 pageInfo{hasNextPage endCursor}}}"""
TEAM_LABELS_QUERY = """query($t:String!){team(id:$t){labels(first:250){nodes{id name}}}}"""
PROJECT_QUERY = 'query($n:String!){projects(filter:{name:{eq:$n}}){nodes{id name}}}'
KEYED_QUERY = """query($t:ID!,$k:String!){issues(filter:{team:{id:{eq:$t}},
 description:{contains:$k}},first:20){nodes{id identifier state{type} createdAt}}}"""
BUILDER_QUERY = """query($id:String!){issue(id:$id){id identifier state{type}
 comments(first:100){nodes{id body} pageInfo{hasNextPage}}}}"""
COMMENT_CREATE = """mutation($input:CommentCreateInput!){commentCreate(input:$input){success}}"""
COMMENT_UPDATE = """mutation($id:String!,$input:CommentUpdateInput!){commentUpdate(id:$id,input:$input){success}}"""

GITHUB_SLUG = re.compile(r"github\.com[:/]([^/\s]+)/([^/\s]+?)(?:\.git)?/?$")
PR_FIELDS = "number,url,headRefName,createdAt,commits,reviews,statusCheckRollup"
PR_LIMIT = 30


# ---------------------------------------------------------------------------
# the pure half
# ---------------------------------------------------------------------------

def _ts(stamp):
    if not stamp:
        return None
    try:
        return datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def idle_hours(stamps, now: datetime):
    """Hours since the newest of `stamps`, or None when none parses."""
    seen = [t for t in (_ts(s) for s in stamps) if t is not None]
    if not seen:
        return None
    return (now - max(seen)).total_seconds() / 3600.0


def label_names(issue: dict) -> set:
    return {(n.get("name") or "").strip() for n in ((issue.get("labels") or {}).get("nodes") or [])}


def project_of(issue: dict):
    return ((issue.get("project") or {}).get("name") or "").strip() or None


def is_alert(issue: dict) -> bool:
    """The writer's structural form, as linear-worker.sh is_fleet_alert reads it."""
    for chunk in (issue.get("description") or "").split("<!--")[1:]:
        head = chunk.split("-->", 1)[0].strip()
        if head.split(":", 1)[0].strip() == ALERT_MARKER:
            return True
    return False


def named(text: str) -> tuple:
    return ("consumer", text)


def gap(reason: str, builder, what: str, why=None) -> tuple:
    """`why`, when given, is this item's own cause, shown on its line in the gap comment."""
    val = {"reason": reason, "builder": builder, "what": what}
    if why:
        val["why"] = why
    return ("gap", val)


def from_registry_row(label: str, row: dict) -> tuple:
    """A hold-label row to a verdict. A person is never a consumer (the table's rule)."""
    if row.get("consumer"):
        c = row["consumer"]
        return named(f"{pathlib.Path(c['path']).name} ({c['job']})")
    if row.get("outside_consumer"):
        c = row["outside_consumer"]
        return named(f"{c['repo']} {c['path']} ({c['job']})")
    m = row.get("missing") or {}
    return gap(f"label-{label.replace(':', '-')}", m.get("ticket"), m.get("what") or "")


def classify_ticket(issue: dict, ctx: dict) -> tuple:
    """("consumer", text) | ("gap", {...}) | ("skip", why). Pure; ctx is precomputed.

    ctx keys: rows (hold-label table rows), fleet (board names), home (the skeleton's
    board name), refusal {project: "" reachable | why not}, started {identifier:
    (class, text)} for started tickets, lanes {identifier: ("live" | "unreadable",
    text)} from lane_classes, refused_hours {project: hours refused}, alert_refusal
    (linear-alert-triage.py promotion_refusal, or None when it could not be loaded).
    """
    labels = label_names(issue)
    proj = project_of(issue)
    if proj == CHIEF_PROJECT:
        return ("skip", "Chief: the chief rebuild owns it (audit C6)")
    if proj is not None and proj in ctx.get("archived", ()):
        return ("skip", "the archived engagement (RULE-2026-10-23-B)")
    # Before every label: a live lane moves the ticket whatever it carries. A lane
    # writes no attempts-ledger row, so without this its started ticket reads as
    # started-no-history and files a ticket to build a consumer that is already on it.
    lane = (ctx.get("lanes") or {}).get(issue.get("identifier"))
    if lane:
        if lane[0] == "live":
            return named(f"the interactive lane that holds it ({lane[1]})")
        return gap("lane-marker-unreadable", None, REASONS["lane-marker-unreadable"]["what"])
    if proj is not None and proj not in ctx["fleet"]:
        return gap("outside-fleet-project", None, REASONS["outside-fleet-project"]["what"])
    rows = ctx["rows"]
    owners = {l for l in labels if l.lower().startswith(OWNER_PREFIX)}
    # ready() refuses an alert before it reads any label (linear-worker.sh
    # is_fleet_alert), so an alert's only consumer is the alert lane. PR #689 review,
    # minor 3: walked after the labels, an alert with needs-scope named the DoR
    # drafter, which refuses alerts too. The lane is asked, never copied.
    if is_alert(issue):
        if LANE_HOLD in labels and LANE_HOLD in rows:
            return from_registry_row(LANE_HOLD, rows[LANE_HOLD])
        refuse = ctx.get("alert_refusal")
        if refuse is None:
            return ("skip", "alert: linear-alert-triage.py promotion_refusal not read this run")
        if not owners and (rows.get(OWNER_LABEL) or {}).get("consumer"):
            # The owner sweep labels an ownerless ticket owner:sana first, so the lane
            # is asked about the ticket as the owner sweep will leave it.
            nodes = list(((issue.get("labels") or {}).get("nodes")) or []) + [{"name": OWNER_LABEL}]
            why = refuse(dict(issue, labels={"nodes": nodes}))
            if why is None:
                first = from_registry_row(OWNER_LABEL, rows[OWNER_LABEL])[1]
                return named(f"{first}, then linear-alert-triage.py (com.kipi.linear-alert-triage)")
        else:
            why = refuse(issue)
            if why is None:
                return named("linear-alert-triage.py (com.kipi.linear-alert-triage)")
        # PR #689 review r2, minor 3: a hold label whose row is a known gap keeps that
        # row's builder (ASK-3960, ASK-3961), and every other refusal carries the
        # lane's own words to the item line, so the gap ticket names the real blocker.
        for label in READY_LABEL_ORDER:
            row = rows.get(label) or {}
            if row.get("missing") and row.get("refused_when") == "present" and label in labels:
                return from_registry_row(label, row)
        return gap("alert-lane-refused", None, REASONS["alert-lane-refused"]["what"], why=why)
    for label in READY_LABEL_ORDER:
        row = rows.get(label)
        if row is None:
            continue
        hit = (label in labels) if row.get("refused_when") == "present" else (label not in labels)
        if not hit:
            continue
        if label == OWNER_LABEL and owners - {FOUNDER_LABEL}:
            # Owned, just not by Sana: the owner sweep only labels a ticket with none.
            return gap("other-owner", REASONS["other-owner"]["builder"],
                       REASONS["other-owner"]["what"])
        return from_registry_row(label, row)
    desc = issue.get("description") or ""
    if proj is None:
        if DOR_HEADING in desc:
            return named("linear-route.py (com.kipi.linear-triage-health) sets the project "
                         "from its Definition of Ready")
        return gap("no-project", REASONS["no-project"]["builder"], REASONS["no-project"]["what"])
    if proj != ctx["home"]:
        refusal = ctx["refusal"].get(proj)
        if refusal is None or refusal:
            hours = (ctx.get("refused_hours") or {}).get(proj)
            if hours is None or hours < IDLE_HOURS:
                return ("skip", f"{proj}: refused under {IDLE_HOURS}h, so it may be a blip "
                                f"({refusal or 'not preflighted'})")
            return gap("unreachable-project", None, REASONS["unreachable-project"]["what"])
    if (issue.get("state") or {}).get("type") == "started":
        cls, text = ctx["started"].get(issue.get("identifier"), ("unread", ""))
        if cls == "unread":
            # Never a gap: a failed read is not "nothing moves it". The run already
            # reports itself incomplete (exit 9).
            return ("skip", "started: hold reason not read this run")
        if cls == "released":
            if DOR_HEADING not in desc:
                return named("linear-dor-drafter.py (com.kipi.linear-dor)")
            return named("linear-worker.sh started_open() (com.kipi.dispatch)")
        if cls == "claim":
            return named(f"the live worker run on its tree ({text})")
        if cls == "pr":
            return named(f"its open PR, which the PR half of this sweep tracks ({text})")
        if cls == "history":
            return gap("started-no-history", None, REASONS["started-no-history"]["what"])
        return gap("started-held", None, REASONS["started-held"]["what"])
    if DOR_HEADING not in desc:
        return named("linear-dor-drafter.py (com.kipi.linear-dor)")
    return named("linear-worker.sh ready() (com.kipi.dispatch)")


def pr_last_activity(pr: dict) -> list:
    """The three signals the DoR names: commit, review, check run. Never a comment:
    a redrive that posts "still failing" every tick is not progress."""
    stamps = [pr.get("createdAt")]
    commits = pr.get("commits") or []
    if commits:
        stamps.append((commits[-1] or {}).get("committedDate"))
    stamps += [(r or {}).get("submittedAt") for r in (pr.get("reviews") or [])]
    for c in pr.get("statusCheckRollup") or []:
        stamps.append((c or {}).get("completedAt") or (c or {}).get("startedAt"))
    return stamps


def classify_pr(pr: dict, owned) -> tuple:
    """`owned`: the slugs pr-owner.py moves, or None while pr-owner.py is not on this tree.

    WHY NOT "sana/ HAS A MOVER". A sana/ head has redrives, but a capped-out or
    escalated one is skipped by both (audit rows 22, 26), so that claim is false
    often enough to hide the PRs that matter. pr-owner.py (ASK-3962) is the by-age
    exit for every open PR in the dispatcher's set, whatever its branch, so its set
    is the answer, read from pr-owner.py itself so the two cannot drift.
    """
    if owned is None:
        return gap("pr-no-owner", REASONS["pr-no-owner"]["builder"], REASONS["pr-no-owner"]["what"])
    if (pr.get("repo") or "").lower() in owned:
        return named("pr-owner.py (com.kipi.pr-owner, hourly)")
    return gap("pr-outside-pr-owner", None, REASONS["pr-outside-pr-owner"]["what"])


def plan(tickets: list, prs: list, ctx: dict, now: datetime) -> dict:
    """The whole decision for one run. Pure: no network, no clock of its own."""
    out = {"named": [], "gaps": {}, "skipped": 0, "fresh": 0}
    items = []
    for t in tickets:
        h = idle_hours([t.get("updatedAt")], now)
        if h is None or h < IDLE_HOURS:
            out["fresh"] += 1
            continue
        items.append((f"ticket {t.get('identifier')}", t.get("title") or "", h,
                      classify_ticket(t, ctx)))
    for pr in prs:
        h = idle_hours(pr_last_activity(pr), now)
        if h is None or h < IDLE_HOURS:
            out["fresh"] += 1
            continue
        items.append((f"PR {pr.get('repo')}#{pr.get('number')}", pr.get("headRefName") or "",
                      h, classify_pr(pr, ctx.get("pr_owned"))))
    for ref, title, h, (kind, val) in items:
        line = f"{ref} ({title[:60]}), idle {int(h)}h"
        if kind == "skip":
            out["skipped"] += 1
        elif kind == "consumer":
            out["named"].append(f"{line}: {val}")
        else:
            g = out["gaps"].setdefault(val["reason"], {"builder": val["builder"],
                                                       "what": val["what"], "items": [],
                                                       "refs": []})
            # The digest is over refs, so a cause on the line never rewrites the comment.
            g["items"].append(f"{line}: {val['why'][:120]}" if val.get("why") else line)
            g["refs"].append(ref)
    for g in out["gaps"].values():
        g["items"].sort()
        g["refs"].sort()
    out["status"] = "red" if out["gaps"] else "green"
    return out


def set_digest(refs: list) -> str:
    # Over the item REFS, never the lines: a line carries "idle Nh", which ticks every
    # run, and a digest over it would rewrite the comment hourly for an unchanged set.
    return hashlib.sha1("\n".join(sorted(refs)).encode()).hexdigest()[:12]


def gap_comment(reason: str, g: dict, ticket: str) -> str:
    """THE body on a gap ticket. One producer, so the marker lookup reads what it writes."""
    shown = g["items"][:MAX_LISTED]
    more = len(g["items"]) - len(shown)
    lines = "\n".join(f"- {i}" for i in shown) + (f"\n- and {more} more" if more > 0 else "")
    return (f"<!-- {COMMENT_MARKER}: {reason} set={set_digest(g['refs'])} -->\n"
            f"**Stalled 24h or more with no consumer: {len(g['items'])}.** "
            f"stall-sweep.py (com.kipi.stall-sweep, hourly) lists them here and rewrites "
            f"this comment when the set changes.\n\n"
            f"Why nothing moves them: {g['what']}\n\n"
            f"This ticket ({ticket}) builds the consumer. When it ships, the sweep stops "
            f"listing them.\n\n{lines}")


def gap_issue_payload(reason: str, g: dict, team_id: str, label_ids: list, project_id) -> dict:
    """A filed gap ticket. No Definition of Ready on purpose: a DoR a script writes is
    hollow. It is in kipi-system, so linear-dor-drafter.py drafts one at 03:00 and
    the fleet worker builds the consumer."""
    body = (f"<!-- kipi-key: {KEY_PREFIX}{reason} -->\n\n"
            f"stall-sweep.py found work idle 24h or more that no consumer moves "
            f"(ASK-4019). Reason `{reason}`: {g['what']}\n\n"
            f"Outcome: a job that moves this class of item, so the sweep stops listing "
            f"it. The current items are in the {COMMENT_MARKER} comment below, rewritten "
            f"when the set changes.\n\n"
            f"Next step: linear-dor-drafter.py (com.kipi.linear-dor, 03:00) drafts the "
            f"Definition of Ready, then the fleet worker (com.kipi.dispatch) can pick it.")
    payload = {"title": f"Stall sweep: {len(g['items'])} item(s) idle 24h with no consumer ({reason})"[:250],
               "description": body, "teamId": team_id, "labelIds": label_ids}
    if project_id:
        payload["projectId"] = project_id
    return payload


def marker_comment(nodes: list, reason: str):
    needle = f"<!-- {COMMENT_MARKER}: {reason} "
    for n in nodes:
        if needle in (n.get("body") or ""):
            return n
    return None


def pick_keyed(nodes: list):
    """(open issue, canceled issue) among the keyed tickets, newest first."""
    nodes = sorted(nodes, key=lambda n: n.get("createdAt") or "", reverse=True)
    opened = next((n for n in nodes if (n.get("state") or {}).get("type") in OPEN_TYPES), None)
    canceled = next((n for n in nodes if (n.get("state") or {}).get("type") == "canceled"), None)
    return opened, canceled


def repo_slug(remote: str):
    m = GITHUB_SLUG.search((remote or "").strip())
    return f"{m.group(1)}/{m.group(2)}" if m else None


def track_refusals(prev, refusal: dict, now: datetime) -> tuple:
    """(new state, {project: hours refused}) from the last state and this run's refusals.

    The clock runs while a project stays refused, whatever the reason: an expired
    token that turns into a hook-parity gap is still a project nobody enters. It
    stops when the project is seen reachable. A project not preflighted this run
    keeps its clock, because not checked is not recovered, but only while it was
    seen refused within IDLE_HOURS (PR #689 review r2, minor 1): a project with no
    idle ticket is never preflighted, so a carried row froze its `since`, and the
    next one-hour blip read as 121h and filed at once. A row that cannot be read,
    or was not seen lately, starts the clock now: the gap waits, it is never minted.
    """
    prev = prev if isinstance(prev, dict) else {}

    def recent(row) -> bool:
        seen = _ts(row.get("last_seen")) if isinstance(row, dict) else None
        return seen is not None and timedelta(0) <= now - seen <= timedelta(hours=IDLE_HOURS)

    prev = {p: r for p, r in prev.items() if recent(r)}
    state = {p: r for p, r in prev.items() if p not in refusal}
    hours = {}
    stamp = now.isoformat(timespec="seconds")
    for proj, why in refusal.items():
        if not why:
            continue
        row = prev.get(proj)
        since = _ts(row.get("since")) if row else None
        if since is None or since > now:
            since = now
        state[proj] = {"since": since.isoformat(timespec="seconds"), "last_seen": stamp, "why": why}
        hours[proj] = (now - since).total_seconds() / 3600.0
    return state, hours


def preflight_refusal(rc: int, output: str) -> str:
    """"" when the gate lets a dispatcher in, else the failed check names, as the
    worker reports them (linear-worker.sh REFUSED_IN)."""
    if rc == 0:
        return ""
    names = [ln[5:].split(":", 1)[0] for ln in output.splitlines() if ln.startswith("FAIL ")]
    return "preflight refuses: " + (",".join(names) or "refused")


# ---------------------------------------------------------------------------
# the network half
# ---------------------------------------------------------------------------

def _load_sync():
    """linear-sync.py owns the transport and started_hold_reason."""
    spec = importlib.util.spec_from_file_location("linear_sync", HERE / "linear-sync.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def fetch_board(sync, team_key: str) -> tuple:
    team_id = sync.graphql(TEAM_QUERY, {"k": team_key})["teams"]["nodes"][0]["id"]
    issues, after = [], None
    while True:
        page = sync.graphql(BOARD_QUERY, {"t": team_id, "a": after})["issues"]
        issues += page["nodes"]
        if not page["pageInfo"]["hasNextPage"]:
            break
        after = page["pageInfo"]["endCursor"]
    return issues, team_id


def started_classes(sync, issues: list, state_dir: str) -> dict:
    """{identifier: (class, text)} for started tickets, asked of started_hold_reason.

    The class is read by equality with the same module's own answers where it can
    be: "" released it, worker_history's text is no history, live_claim's text is a
    live run, open_prs' line is an open PR. Two answers mean "could not look" and
    are "unread", skipped and reported, never a gap (PR #689 review, major 2): a
    worker_history answer that is neither no row nor no ledger file (a torn ledger,
    a non-object), and a failed PR read, which started_hold_reason folds into prose.
    """
    out = {}
    for i in issues:
        if (i.get("state") or {}).get("type") != "started":
            continue
        ident = i.get("identifier") or ""
        why = sync.started_hold_reason(i, state_dir=state_dir)
        if why == "":
            out[ident] = ("released", "")
        elif why == sync.worker_history(state_dir, ident):
            out[ident] = ("history" if why.startswith(NO_HISTORY_PREFIXES) else "unread", why)
        elif why == sync.live_claim(os.path.join(state_dir, "worktrees"), ident):
            out[ident] = ("claim", why)
        elif why.startswith("open PR "):
            out[ident] = ("pr", why[len("open PR "):])
        elif why.startswith(PR_UNREAD_PREFIX):
            out[ident] = ("unread", why)
        else:
            out[ident] = ("held", why)
    return out


def _load_alert_triage():
    """linear-alert-triage.py, for promotion_refusal: the alert lane's own refusal."""
    spec = importlib.util.spec_from_file_location("alert_triage_for_stall_sweep",
                                                  HERE / "linear-alert-triage.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


LANE_LIVE_PREFIX = "lane marker: "


def lane_classes(sync, identifiers) -> dict:
    """{identifier: ("live" | "unreadable", text)} for tickets a lane marker names.

    Asked of linear-sync.py lane_marker, the reader the redrives use (ASK-4095), so
    the sweep and the redrives agree on which lanes are live. "" (no marker, or an
    expired one) is no lane. Its live answer opens with LANE_LIVE_PREFIX and every
    fail-closed answer does not; test_lane_answers_are_read_from_the_real_lane_marker
    pins that split against the function itself, with real marker files.
    """
    out = {}
    for ident in identifiers:
        why = sync.lane_marker(ident)
        if why:
            out[ident] = ("live" if why.startswith(LANE_LIVE_PREFIX) else "unreadable", why)
    return out


class ArchiveGuardMissing(RuntimeError):
    """No hook to ask, so nothing may be read: the same refusal pr-owner.py makes."""


def archive_guard() -> pathlib.Path:
    # HOME is the seam, not a KIPI_* knob: a variable would be a documented way to
    # aim the guard at /bin/true (pr-owner.py, rearm-degraded-approvals.sh).
    return pathlib.Path.home() / ".claude" / "hooks" / "ps-archive-deny.sh"


def archived(path: str, label: str, run=subprocess.run) -> bool:
    """Ask the founder's hook, never a copy of its pattern. Any doubt is a deny."""
    guard = archive_guard()
    if not guard.is_file():
        raise ArchiveGuardMissing(f"{guard} is missing")
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": f"ls {path} {label}"}})
    env = {k: v for k, v in os.environ.items() if k != "ALLOW_PS_ARCHIVE"}
    try:
        p = run(["bash", str(guard)], input=payload, capture_output=True, text=True,
                timeout=30, env=env)
    except (OSError, subprocess.TimeoutExpired):
        return True
    return '"permissionDecision":"deny"' in (p.stdout or "").replace(" ", "")


def pr_owner_set():
    """The slugs pr-owner.py moves, or None while it (and its job) are not on this tree."""
    if not ((HERE / "pr-owner.py").is_file() and (HERE / "com.kipi.pr-owner.plist").is_file()):
        return None
    spec = importlib.util.spec_from_file_location("pr_owner_for_stall_sweep", HERE / "pr-owner.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    try:
        rows, targets = mod.fleet_repos(mod.ROOT)
    except SystemExit as exc:  # pr-owner refuses with SystemExit; here that is a failed read
        raise RuntimeError(str(exc)) from None
    out = set()
    for _name, path, _remote in rows:
        if (pathlib.Path(path) / ".kipi-no-dispatch").exists():
            continue  # pr-owner skips a repo behind its kill switch
        slug = mod.slug_for(mod.ROOT, path, targets)
        if slug:
            out.add(slug.lower())
    return out


def reachability(facts: dict, projects: set, run=subprocess.run) -> dict:
    """{project: "" | why not}, repo-preflight.sh once per project (worker parity)."""
    local = linear_registry.local_by_project(facts)
    out = {}
    for proj in sorted(projects):
        row = local.get(proj)
        if row is None:
            out[proj] = "no local checkout"
            continue
        p = run(["bash", str(HERE / "repo-preflight.sh"), row["path"], row.get("remote") or ""],
                capture_output=True, text=True)
        out[proj] = preflight_refusal(p.returncode, (p.stdout or "") + (p.stderr or ""))
    return out


def fleet_repos(facts: dict, run=subprocess.run, is_archived=None) -> tuple:
    """(github slugs to list PRs in, rows with no readable remote). chief excluded,
    and the archived engagement is never read."""
    slugs, unread = set(), []
    for row in facts.get("local_repos") or []:
        if is_archived is not None and is_archived(row["path"], row.get("project") or ""):
            continue
        remote = row.get("remote") or ""
        if not remote:
            p = run(["git", "-C", row["path"], "remote", "get-url", "origin"],
                    capture_output=True, text=True)
            remote = (p.stdout or "").strip() if p.returncode == 0 else ""
        slug = repo_slug(remote)
        if slug is None:
            unread.append(row.get("project") or row.get("path"))
        elif slug.lower() != CHIEF_REPO:
            slugs.add(slug)
    return sorted(slugs), unread


def fetch_prs(slug: str, run=subprocess.run) -> list:
    p = run(["gh", "pr", "list", "-R", slug, "--state", "open", "--limit", str(PR_LIMIT),
             "--json", PR_FIELDS], capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or "gh failed").strip()[:200])
    prs = json.loads(p.stdout or "[]")
    if len(prs) >= PR_LIMIT:
        # A full page is not "all of them"; the run reports itself incomplete.
        raise RuntimeError(f"{slug}: {PR_LIMIT}+ open PRs, page may be truncated")
    for pr in prs:
        pr["repo"] = slug
    return prs


def label_ids(sync, team_id: str, names: list) -> list:
    nodes = ((((sync.graphql(TEAM_LABELS_QUERY, {"t": team_id}) or {}).get("team") or {})
              .get("labels") or {}).get("nodes") or [])
    by = {(n.get("name") or "").strip().lower(): n.get("id") for n in nodes}
    return [by[n] for n in names if by.get(n)]


def gap_ticket(sync, team_id: str, reason: str, g: dict, budget: dict, ids: dict) -> tuple:
    """(ticket identifier or "", what happened). Files at most budget['new'] tickets."""
    if g["builder"]:
        b = ((sync.graphql(BUILDER_QUERY, {"id": g["builder"]}) or {}).get("issue")) or {}
        if (b.get("state") or {}).get("type") in OPEN_TYPES:
            return b.get("identifier") or g["builder"], "builder"
        # The builder closed while the gap is still live: the sweep owns it now.
    nodes = (((sync.graphql(KEYED_QUERY, {"t": team_id, "k": f"kipi-key: {KEY_PREFIX}{reason} "})
               or {}).get("issues") or {}).get("nodes") or [])
    opened, canceled = pick_keyed(nodes)
    if opened:
        return opened["identifier"], "keyed"
    if canceled:
        return "", f"declined: {canceled['identifier']} was Canceled; respected, nothing filed"
    if budget["new"] <= 0:
        return "", f"not filed: {MAX_NEW_TICKETS} new tickets this run already"
    if ids.get("labels") is None:
        ids["labels"] = label_ids(sync, team_id, [OWNER_LABEL, TRIAGE_LABEL])
        proj = ((sync.graphql(PROJECT_QUERY, {"n": HOME_PROJECT}) or {}).get("projects") or {})
        ids["project"] = ((proj.get("nodes") or [{}])[0] or {}).get("id")
    if len(ids["labels"]) != 2:
        return "", f"not filed: team lacks {OWNER_LABEL} or {TRIAGE_LABEL}"
    res = sync.graphql(sync.ISSUE_CREATE, {"input": gap_issue_payload(
        reason, g, team_id, ids["labels"], ids["project"])}) or {}
    node = (res.get("issueCreate") or {}).get("issue") or {}
    if not node.get("identifier"):
        return "", "not filed: issueCreate returned no issue"
    budget["new"] -= 1
    return node["identifier"], "filed"


def upsert_comment(sync, ticket: str, reason: str, g: dict, budget: dict) -> str:
    issue = ((sync.graphql(BUILDER_QUERY, {"id": ticket}) or {}).get("issue")) or {}
    comments = issue.get("comments") or {}
    found = marker_comment(comments.get("nodes") or [], reason)
    body = gap_comment(reason, g, ticket)
    if found and f"set={set_digest(g['refs'])} -->" in (found.get("body") or ""):
        return "unchanged"
    if budget["comments"] <= 0:
        return "comment deferred: write cap"
    if found:
        res = sync.graphql(COMMENT_UPDATE, {"id": found["id"], "input": {"body": body}}) or {}
        ok = (res.get("commentUpdate") or {}).get("success")
    elif (comments.get("pageInfo") or {}).get("hasNextPage"):
        # 100+ comments and no marker on page one: it may be on page two. A second
        # marker comment is the duplicate this job promises never to write.
        return "comment skipped: marker may be past page one"
    else:
        res = sync.graphql(COMMENT_CREATE, {"input": {"issueId": issue["id"], "body": body}}) or {}
        ok = (res.get("commentCreate") or {}).get("success")
    budget["comments"] -= 1
    return "comment written" if ok else "comment refused"


def write_json(path: pathlib.Path, payload: dict) -> None:
    """One writer (this script under --apply), atomic rename. last-run.json is audit
    only, no job reads it; refusals.json is read back by the next run of this script."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.stem}.", suffix=".json")
    with os.fdopen(fd, "w") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
    os.replace(tmp, path)


def load_json(path: pathlib.Path) -> dict:
    """{} when missing, torn or not an object: the refusal clocks then start now."""
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def main(argv: list) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--team", default=os.environ.get("KIPI_LINEAR_TEAM", "ASK"))
    ap.add_argument("--registry", default=None, help="instance-registry.json (default: the skeleton's)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--apply", action="store_true", help="write (default: report only)")
    try:
        args = ap.parse_args(argv)
    except SystemExit:
        return EXIT_USAGE
    if args.apply and os.environ.get("PYTEST_CURRENT_TEST"):
        print("stall-sweep: REFUSED --apply under pytest.", file=sys.stderr)
        return EXIT_REFUSED_FIXTURE

    reg_path = args.registry or linear_registry.default_registry_path()
    overlay = os.environ.get("KIPI_DISPATCH_TARGETS") or str(
        pathlib.Path.home() / ".config" / "kipi" / "dispatch-targets.json")
    facts = linear_registry.registry_facts(reg_path, overlay_path=overlay)
    try:
        hold = json.loads((QDIR / REGISTRY_REL).read_text())["labels"]
        with open(reg_path) as fh:
            reg = json.load(fh)
        fleet = {linear_registry.linear_project(r) for r in linear_registry._rows(reg)} - {""}
    except (OSError, ValueError, KeyError) as exc:
        print(f"stall-sweep: a registry is unreadable ({exc}); nothing classified. Exit 9.",
              file=sys.stderr)
        return EXIT_INCOMPLETE
    if not facts["ok"]:
        print("stall-sweep: instance-registry.json unreadable; nothing classified. Exit 9.",
              file=sys.stderr)
        return EXIT_INCOMPLETE

    sync = _load_sync()
    try:
        sync.linear_api_key()
    except Exception as exc:
        print(f"stall-sweep: no Linear key configured ({exc})", file=sys.stderr)
        return EXIT_NO_KEY
    incomplete = []
    try:
        tickets, team_id = fetch_board(sync, args.team)
    except Exception as exc:
        print(f"stall-sweep: board walk failed ({exc}); nothing written. Exit 9.", file=sys.stderr)
        return EXIT_INCOMPLETE

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=IDLE_HOURS)
    idle = [t for t in tickets if (_ts(t.get("updatedAt")) or now) <= cutoff]
    state_dir = os.environ.get("KIPI_STATE_DIR") or str(pathlib.Path.home() / ".config" / "kipi")
    try:
        started = started_classes(sync, idle, state_dir)
    except Exception as exc:
        incomplete.append(f"started tickets: {str(exc)[:160]}")
        started = {}
    unread_started = sorted(k for k, (cls, _) in started.items() if cls == "unread")
    if unread_started:
        incomplete.append(f"started tickets not read ({len(unread_started)}), skipped: "
                          + ", ".join(unread_started[:20]))
    lanes = lane_classes(sync, [t.get("identifier") or "" for t in idle])
    try:
        alert_refusal = _load_alert_triage().promotion_refusal
    except Exception as exc:
        incomplete.append(f"linear-alert-triage.py: {str(exc)[:160]}")
        alert_refusal = None
    local = linear_registry.local_by_project(facts)
    # Both readers of the archive hook sit under one handler (PR #689 review, minor 4):
    # with no idle ticket in a project, fleet_repos is the only one that asks it.
    try:
        arch = {p for p in {project_of(t) for t in idle} - {None}
                if archived((local.get(p) or {}).get("path") or p, p)}
        slugs, unlisted = fleet_repos(facts, is_archived=archived)
    except ArchiveGuardMissing as exc:
        print(f"stall-sweep: REFUSED, {exc}; the archived engagement cannot be told apart, "
              f"so nothing is read. Exit 9.", file=sys.stderr)
        return EXIT_INCOMPLETE
    projects = {project_of(t) for t in idle} - {None, CHIEF_PROJECT, facts["skeleton_project"]} - arch
    refusal = reachability(facts, projects & fleet)
    refusal_state, refused_hours = track_refusals(load_json(REFUSALS_PATH), refusal, now)

    try:
        owned = pr_owner_set()
    except Exception as exc:
        incomplete.append(f"pr-owner.py set: {str(exc)[:160]}")
        owned = None
    prs = []
    for slug in slugs:
        try:
            prs += fetch_prs(slug)
        except Exception as exc:
            incomplete.append(f"PRs {slug}: {str(exc)[:160]}")

    ctx = {"rows": hold, "fleet": fleet, "home": facts["skeleton_project"] or HOME_PROJECT,
           "refusal": refusal, "refused_hours": refused_hours, "started": started,
           "lanes": lanes, "alert_refusal": alert_refusal, "archived": arch, "pr_owned": owned}
    p = plan(tickets, prs, ctx, now)

    handed, unhanded = {}, {}
    if args.apply and p["gaps"]:
        budget = {"new": MAX_NEW_TICKETS, "comments": MAX_COMMENT_WRITES}
        ids = {}
        for reason, g in sorted(p["gaps"].items()):
            try:
                ticket, how = gap_ticket(sync, team_id, reason, g, budget, ids)
                if not ticket:
                    unhanded[reason] = how
                    continue
                handed[reason] = f"{ticket} ({how}); " + upsert_comment(sync, ticket, reason, g, budget)
            except Exception as exc:
                # One refused write must not abandon the other gaps.
                unhanded[reason] = f"write failed: {str(exc)[:160]}"

    result = {"ts": now.isoformat(timespec="seconds"), "applied": bool(args.apply),
              "status": p["status"], "tickets_read": len(tickets), "prs_read": len(prs),
              "fresh": p["fresh"], "skipped": p["skipped"], "named": p["named"],
              "gaps": p["gaps"], "handed": handed, "unhanded": unhanded,
              "repos_unlisted": unlisted, "refusals": refusal_state, "incomplete": incomplete}
    if args.apply:
        for path, payload in ((REFUSALS_PATH, refusal_state), (EVIDENCE_PATH, result)):
            try:
                write_json(path, payload)
            except OSError as exc:
                print(f"stall-sweep: {path.name} not written ({exc})", file=sys.stderr)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"stall-sweep: {p['status'].upper()}. {len(p['named'])} idle item(s) name a "
              f"consumer; {sum(len(g['items']) for g in p['gaps'].values())} in "
              f"{len(p['gaps'])} gap(s); {p['skipped']} outside scope.")
        for reason, g in sorted(p["gaps"].items()):
            where = handed.get(reason) or unhanded.get(reason) or (
                f"builder {g['builder']}" if g["builder"] else "no ticket yet (report only)")
            print(f"  GAP {reason}: {len(g['items'])} -> {where}")
        for line in incomplete:
            print(f"  INCOMPLETE {line}")
    if incomplete:
        return EXIT_INCOMPLETE
    if args.apply and unhanded:
        return EXIT_RED
    if not args.apply and any(not g["builder"] for g in p["gaps"].values()):
        return EXIT_RED
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
