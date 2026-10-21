#!/usr/bin/env python3
"""Fail when a dispatchable Linear issue sits on a project no checkout backs (ASK-1951).

THE DEFECT THIS METERS
----------------------
`linear-worker.sh`'s `ready()` requires `project_of(i) == REPO_PROJECT`, and
REPO_PROJECT comes from instance-registry.json. So a Linear project with no
registry row matches NO checkout: a ticket on it has an owner label, a Definition
of Ready and a project, every existing count reads it as routed, and no worker in
the fleet will ever pick it up. ASK-1887 is a ticket missing a field; this is a
ticket carrying the field with a value nothing can consume. Both end as work that
no worker takes and no count flags.

Measured 2026-09-20 (the filing): 469 issues with a DoR + `owner:sana` + a
project, 15 of them on `lane-h-digest-repeats`, a project with no registry row and
no directory anywhere. Re-measured 2026-09-26 against the live board: 398 in
shape, 13 unreachable -- 7 lane-h survivors (8 of the original 15 were closed or
lost `owner:sana` in between) plus 6 on `Chief`, which ASK-1951 named as the
near-miss holding zero at the time. The class grew while the ticket sat, which is
the argument for a meter rather than a one-off sweep.

EXIT CODES
----------
    0  nothing unreachable, or every unreachable issue is acknowledged, or the
       registry could not be read (UNKNOWN, see below)
    2  at least one unacknowledged unreachable issue
    5  as 2, AND --notify was asked for and the send failed. Worst-first: the
       finding is still true, but nobody was told, and that is the state a
       launchd job must not record as a measured red. Same code and same reason
       as EXIT_ALERT_FAILED in linear-triage-health.py, the caller beside it.

WHAT ACKNOWLEDGED MEANS, AND WHY IT IS NOT A BYPASS
---------------------------------------------------
An acknowledgement is ASK-1887's rule that an unknown target gets a MARK and
never a guess. It does NOT clear the finding: the acknowledged population is
printed on its own line on every run, with its projects, so a queue silenced by
acknowledging still reads as a queue. What it removes is the ALARM, the way
`needs-scope` removes an issue from the dispatch queue without deleting it. An
unacknowledged unreachable issue is the new occurrence this script exists to
catch.

TWO ACCEPTED MARKS, AND WHY THE COMMENT IS THE PRIMARY ONE.

    <!-- route-unreachable-ack -->   in any comment on the issue
    route:unreachable                as a label

The comment marker is primary because the label could not be created: measured
2026-09-26, `issueLabelCreate` on team ASK returns 403 FORBIDDEN, "You are not
allowed to create labels in this team", for the API key every script here uses.
A mechanism the runner cannot execute is not a mechanism, so the acknowledgement
moved to the channel it CAN write -- the same per-issue marker-comment pattern
linear-triage-health.py already uses for dormancy (DORMANT_MARKER). The label is
still honored, at no cost, because labels arrive in the board fetch already and
the founder may create it by hand later.

The comment read is per-issue, so it costs one API call per UNREACHABLE issue and
nothing for a clean board. That is self-limiting in the right direction: the cost
rises only with the population the check exists to drive to zero.

AN UNREADABLE REGISTRY IS UNKNOWN, NOT UNREACHABLE
--------------------------------------------------
Every project resolves to nothing when the registry cannot be read, so treating
that as failure fires a false alarm on the whole board at once -- the failure
mode ASK-1951 exists to remove, pointed the other way. The script says UNKNOWN
and exits 0. Same reason `registry_ok` is carried explicitly in the resolver.

THE RESOLVER IS IMPORTED, NEVER RETYPED
---------------------------------------
Project-name and local-checkout resolution come from `linear_registry.py`, the
same module `linear-worker.sh` reads. A second copy of that derivation would
agree today and diverge silently later, which is the defect class this repo has
already paid for twice (ASK-729, ASK-840).

Usage:
    python3 linear-route-reachability-check.py            # human report, exit 0/2
    python3 linear-route-reachability-check.py --json     # machine report
    python3 linear-route-reachability-check.py --notify    # + one line to Sana
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import linear_registry  # noqa: E402  (after sys.path, by design)

EXIT_OK = 0
EXIT_UNREACHABLE = 2
# 5, matching EXIT_ALERT_FAILED in linear-triage-health.py. The two scripts feed
# one launchd surface, so one number must not mean two things across them.
EXIT_ALERT_FAILED = 5

ACK_LABEL = "route:unreachable"
# Stamped into a comment by whoever records the routing reason. Matched as a WHOLE
# HTML comment key, never as a bare substring: a bare-name match would count an
# issue whose body merely DISCUSSES this mechanism as acknowledged, which is the
# exact defect ASK-839 fixed in the alert-fingerprint matcher one file over.
ACK_MARKER = "route-unreachable-ack"

ISSUE_COMMENTS_QUERY = """query($id:String!){issue(id:$id){
 identifier comments(first:100){nodes{body}}}}"""
HELD_LABELS = ("needs-scope", "blocked:capability")
ALERT_MARKER = "kipi-alert-fingerprint"
OPEN_STATE_TYPES = ("backlog", "unstarted")

# The whole team, closed rows included, because the state filter below is what
# decides open-ness and a second filter in the query would hide its own effect.
BOARD_QUERY = """query($t:ID!,$a:String){issues(filter:{team:{id:{eq:$t}}},first:250,after:$a){
 nodes{id identifier title description state{name type} project{name}
       labels{nodes{name}}} pageInfo{hasNextPage endCursor}}}"""

TEAM_QUERY = 'query($k:String!){teams(filter:{key:{eq:$k}}){nodes{id}}}'


def _load_sync():
    """linear-sync.py owns the transport, including the KIPI_LINEAR_API_URL seam.

    Loaded by path because the filename has a hyphen. The seam is what lets the
    test drive this script against a fixture board instead of the live one, the
    same way test-worker-project-scope.sh drives the real picker.
    """
    spec = importlib.util.spec_from_file_location("linear_sync", HERE / "linear-sync.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def is_fleet_alert(issue: dict) -> bool:
    """A fleet alert is a notification, not dispatch work (ASK-839).

    Matched on the WHOLE comment key alert-to-linear.py stamps, not the bare
    name: the bare-name test matched any issue whose body merely DISCUSSES the
    marker, which silently swept in the tickets ABOUT this mechanism.
    """
    for chunk in (issue.get("description") or "").split("<!--")[1:]:
        head = chunk.split("-->", 1)[0]
        name, sep, _rest = head.partition(":")
        if sep and name.strip() == ALERT_MARKER:
            return True
    return False


def labels_of(issue: dict) -> set:
    return {n["name"] for n in ((issue.get("labels") or {}).get("nodes") or [])}


def project_of(issue: dict):
    return (issue.get("project") or {}).get("name")


def is_dispatchable_shape(issue: dict) -> bool:
    """The population `linear-worker.sh` would dispatch if the project resolved.

    Mirrors `ready_ignoring_project` in linear-worker.sh:632. It is a MIRROR, not
    an import, because that predicate lives inside a bash heredoc and cannot be
    imported. test-linear-route-reachability.sh closes the gap the honest way:
    it runs the real worker and this script over ONE fixture board and fails if
    their unreachable sets differ, so a change to either side that splits the
    predicate goes red instead of quiet.
    """
    labels = labels_of(issue)
    if "owner:assaf" in labels:
        return False
    if "owner:sana" not in labels:
        return False
    if any(h in labels for h in HELD_LABELS):
        return False
    if (issue.get("state") or {}).get("type") not in OPEN_STATE_TYPES:
        return False
    if is_fleet_alert(issue):
        return False
    return "Definition of Ready" in (issue.get("description") or "")


def fetch_board(sync, team_key: str) -> list:
    tid = sync.graphql(TEAM_QUERY, {"k": team_key})["teams"]["nodes"][0]["id"]
    issues, after = [], None
    while True:
        page = sync.graphql(BOARD_QUERY, {"t": tid, "a": after})["issues"]
        issues += page["nodes"]
        if not page["pageInfo"]["hasNextPage"]:
            break
        after = page["pageInfo"]["endCursor"]
    return issues


def has_marker_comment(sync, identifier: str, marker: str = ACK_MARKER) -> bool:
    """True when any comment on the issue carries the whole marker key.

    Parsed the same way is_fleet_alert parses its own: split on the comment open,
    take the key before the colon, compare the WHOLE key. `<!-- x -->` with no
    colon is accepted too, since a bare marker needs no payload.

    A failed lookup returns False, which classifies the issue as UNACKNOWLEDGED.
    Failing toward the alarm is deliberate: the alternative is an API hiccup
    silently marking work as seen.
    """
    try:
        node = sync.graphql(ISSUE_COMMENTS_QUERY, {"id": identifier})["issue"]
    except Exception:
        return False
    for body in [(n.get("body") or "") for n in (node.get("comments") or {}).get("nodes") or []]:
        for chunk in body.split("<!--")[1:]:
            head = chunk.split("-->", 1)[0]
            key = head.partition(":")[0].strip()
            if key == marker:
                return True
    return False


def measure(issues: list, facts: dict, sync=None) -> dict:
    """Split the dispatchable population by whether its project resolves.

    `sync` is the transport used for the per-issue acknowledgement read. Passing
    None skips that read entirely, so the label remains the only accepted mark --
    which is what the unit-shaped cases want and what keeps a measure() call from
    making network requests it was not asked to make.
    """
    local = linear_registry.local_by_project(facts)
    shaped = [i for i in issues if is_dispatchable_shape(i)]
    result = {
        "registry_ok": bool(facts.get("ok")),
        "local_projects": sorted(local),
        "shaped": len(shaped),
        "unset_project": sorted(i["identifier"] for i in shaped if not project_of(i)),
        "unreachable": [],
        "acknowledged": [],
    }
    if not facts.get("ok"):
        # UNKNOWN. Every project would read as unreachable, so classify nothing.
        return result
    for i in shaped:
        proj = project_of(i)
        if not proj or proj in local:
            continue
        row = {"id": i["identifier"], "project": proj,
               "reason": ("project has a registry row with no directory here"
                          if proj in _registry_projects(facts)
                          else "no instance-registry.json row names this project")}
        # Label first because it is already in hand; the comment read only runs
        # for an issue the label did not answer, so an acknowledged board costs
        # no extra calls at all.
        acked = ACK_LABEL in labels_of(i)
        if not acked and sync is not None:
            acked = has_marker_comment(sync, i["identifier"])
        result["acknowledged" if acked else "unreachable"].append(row)
    result["unreachable"].sort(key=lambda r: (r["project"], r["id"]))
    result["acknowledged"].sort(key=lambda r: (r["project"], r["id"]))
    return result


def _registry_projects(facts: dict) -> set:
    """Board names the registry DECLARES, whether or not the directory exists.

    Separating "no row at all" from "row whose checkout is missing here" is what
    makes the printed reason actionable: the first needs a routing decision, the
    second needs a clone. `local_repos` only carries rows whose directory exists,
    so a declared-but-absent row is the set difference -- and today that set is
    empty, which the test pins rather than assumes.
    """
    return {r["project"] for r in facts.get("all_projects") or []}


def render(m: dict) -> str:
    lines = []
    if not m["registry_ok"]:
        lines.append("route-reachability: UNKNOWN -- instance-registry.json unreadable. "
                     "Nothing classified; this is not a pass.")
        return "\n".join(lines)
    lines.append(f"route-reachability: {m['shaped']} dispatchable-shaped issue(s); "
                 f"{len(m['unreachable'])} unacknowledged unreachable, "
                 f"{len(m['acknowledged'])} acknowledged.")
    for bucket, title in (("unreachable", "UNREACHABLE (no checkout backs the project)"),
                          ("acknowledged", f"ACKNOWLEDGED ({ACK_MARKER} / {ACK_LABEL})")):
        rows = m[bucket]
        if not rows:
            continue
        lines.append(f"  {title}:")
        byproj = {}
        for r in rows:
            byproj.setdefault(r["project"], []).append(r)
        for proj in sorted(byproj):
            ids = " ".join(r["id"] for r in byproj[proj])
            lines.append(f"    {proj} ({len(byproj[proj])}): {ids}")
            lines.append(f"      reason: {byproj[proj][0]['reason']}")
    if m["unset_project"]:
        lines.append(f"  (separately, {len(m['unset_project'])} dispatchable-shaped "
                     "issue(s) carry no project at all -- ASK-1887 owns those)")
    return "\n".join(lines)


def notify(line: str) -> int:
    """Sana's Linear triage, never a founder page (founder-notifications.md).

    KIPI_NOTIFY is the stub seam every sibling here exposes, and it is part of
    test isolation rather than a nicety: on 2026-08-01 a suite reporting 14/14
    green reached the real notifier and paged the founder twice.
    """
    script = os.environ.get("KIPI_NOTIFY") or str(HERE / "slack-notify.sh")
    if not os.path.exists(script):
        return 0
    return subprocess.run(["bash", script, line], check=False).returncode


def main(argv: list) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--team", default=os.environ.get("KIPI_LINEAR_TEAM", "ASK"))
    ap.add_argument("--registry", default=None,
                    help="instance-registry.json (default: the skeleton's)")
    ap.add_argument("--json", action="store_true", help="print the measurement as JSON")
    ap.add_argument("--notify", action="store_true",
                    help="file one line into Sana's Linear triage when red")
    args = ap.parse_args(argv)

    registry = args.registry or linear_registry.default_registry_path()
    facts = linear_registry.registry_facts(registry)
    facts["all_projects"] = _declared_rows(registry)
    sync = _load_sync()
    m = measure(fetch_board(sync, args.team), facts, sync)

    print(json.dumps(m, indent=2) if args.json else render(m))
    if m["unreachable"]:
        if args.notify:
            rc = notify(f"route-reachability: {len(m['unreachable'])} owner:sana DoR "
                        f"issue(s) on a Linear project no checkout backs "
                        f"({', '.join(sorted({r['project'] for r in m['unreachable']}))})")
            # A NONZERO HERE IS A DELIVERY FAILURE AND MUST REACH THE EXIT CODE.
            # Dropping it made a failed send and a delivered one byte-identical,
            # which is the Codex major from PR #204 in the sibling file this one
            # is wired into, reproduced one directory over (PR #449 review).
            # `notify()` never raises by design, so its return value is the only
            # signal there is.
            if rc != 0:
                print(f"alert FAILED (exit {rc}): the finding was measured and "
                      "nobody was told.", file=sys.stderr)
                return EXIT_ALERT_FAILED
        return EXIT_UNREACHABLE
    return EXIT_OK


def _declared_rows(registry_path: str) -> list:
    """Every row's board name, directory present or not. Read from the same file."""
    try:
        with open(registry_path) as fh:
            reg = json.load(fh)
    except Exception:
        return []
    out = []
    for e in linear_registry._rows(reg):
        proj = linear_registry.linear_project(e)
        if proj:
            out.append({"project": proj, "path": e.get("path") or ""})
    return out


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
