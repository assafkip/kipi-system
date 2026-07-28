#!/usr/bin/env python3
"""Collapse the job-migration duplicate family into one surviving issue.

WHY THIS EXISTS
---------------
32 open issues read "Migrate com.<x> to Linear-tracked execution". Same shape,
same fix, 32 different targets. They are one change, not 32, and while they sit
apart the board reads as 2 months of work that is actually one.

WHAT COLLAPSE MEANS HERE -- and what it is NOT
----------------------------------------------
NOT "close 32 issues". Closing them would delete the record of which job each
one named, and a family fix that silently drops one job's name is exactly how a
job stays dark. Collapse means:

  1. ONE survivor whose body enumerates EVERY member's job label. The union,
     never a sample.
  2. Every absorbed issue gets a comment naming the survivor, written BEFORE
     it is closed. A close with no pointer is an orphan.
  3. Closed as `canceled` (Linear's "not planned"), never `completed`: nobody
     did this work yet, and a Done that claims otherwise outlives the board.
     Reopening restores it and the pointer is still there.

SCAR THIS CARRIES
-----------------
linear-triage.py --apply died mid-run on 2026-07-28 after commenting on 74
issues and closing 32, with its --out file written only at the end -- so the
audit trail of what it had touched did not exist (sp-b5dcf944). This appends
its record per-issue, BEFORE the write it describes, so a crash leaves a log
that over-reports rather than under-reports. Over-reporting is recoverable by
reading the issue; under-reporting is not recoverable at all.

Idempotent: an issue already carrying the marker is skipped, so a partial run
is resumed by re-running.

Usage:  linear-collapse-jobmigration.py [--apply] [--survivor ASK-n]
        Dry by default. Prints exactly what it would do.
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import importlib.util

_spec = importlib.util.spec_from_file_location(
    "linear_sync", os.path.join(os.path.dirname(os.path.abspath(__file__)), "linear-sync.py"))
ls = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ls)

MARKER = "<!-- kipi-collapse: job-migration -->"
TEAM_KEY = "ASK"

ISSUES_Q = """
query($t: String!, $a: String) {
  issues(filter: {team: {key: {eq: $t}}, state: {type: {nin: ["completed","canceled"]}}},
         first: 250, after: $a) {
    nodes { id identifier title
            state { id name type }
            comments { nodes { id body } } }
    pageInfo { hasNextPage endCursor }
  }
}
"""

TITLE_RE = re.compile(r"^Migrate\s+(\S+)\s+to Linear-tracked execution\s*$", re.I)


def log(path, rec):
    """Append-as-you-go. Written BEFORE the API call it describes."""
    with open(path, "a") as fh:
        fh.write(json.dumps(rec) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write to Linear")
    ap.add_argument("--survivor", help="identifier to keep (default: lowest number)")
    ap.add_argument("--out", default="q-system/output/collapse-jobmigration-%s.jsonl"
                    % datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    args = ap.parse_args()

    team = ls.graphql('query{teams(filter:{key:{eq:"%s"}}){nodes{id}}}' % TEAM_KEY, {})
    team_id = team["teams"]["nodes"][0]["id"]

    issues, after = [], None
    while True:
        p = ls.graphql(ISSUES_Q, {"t": TEAM_KEY, "a": after})["issues"]
        issues += p["nodes"]
        if not p["pageInfo"]["hasNextPage"]:
            break
        after = p["pageInfo"]["endCursor"]

    fam = []
    for i in issues:
        m = TITLE_RE.match(i["title"].strip())
        if m:
            fam.append((int(i["identifier"].split("-")[1]), i, m.group(1)))
    fam.sort()

    if not fam:
        print("no job-migration issues found; nothing to do")
        return 0

    if args.survivor:
        keep = next((f for f in fam if f[1]["identifier"] == args.survivor), None)
        if not keep:
            print("survivor %s is not in the family" % args.survivor)
            return 1
    else:
        keep = fam[0]
    absorbed = [f for f in fam if f[1]["identifier"] != keep[1]["identifier"]]

    print("family: job-migration, %d issue(s)" % len(fam))
    print("survivor: %s  %s" % (keep[1]["identifier"], keep[1]["title"]))
    print("absorbing: %d" % len(absorbed))
    for _, i, job in absorbed:
        print("   %-9s %s" % (i["identifier"], job))

    # The survivor body enumerates EVERY job label -- the union, asserted here
    # rather than trusted, because a dropped member is the whole failure mode.
    jobs = [j for _, _, j in fam]
    assert len(jobs) == len(fam), "job list is not 1:1 with the family"
    body_lines = [
        MARKER,
        "",
        "**Collapsed family: %d `Migrate com.<x> to Linear-tracked execution` issues "
        "became this one.** Same shape, same fix, %d targets. Absorbed issues are "
        "closed as not-planned with a comment pointing here; reopening any of them "
        "restores it." % (len(fam), len(fam)),
        "",
        "## Every job this must cover (%d)" % len(jobs),
        "",
    ]
    body_lines += ["- `%s`" % j for j in sorted(jobs)]
    body_lines += [
        "",
        "**The `com.cole.*` jobs are PAUSED ON PURPOSE** pending exactly this "
        "migration. They are not rot and must not be retired -- the fix is the "
        "migration, not a cleanup.",
        "",
        "## Definition of Ready",
        "",
        "**Outcome:** every job above runs under Linear-tracked execution, and "
        "none is silently dropped.",
        "",
        "**Files:** the launchd plists for the jobs above, plus whatever single "
        "mechanism performs the migration. Name it explicitly before starting.",
        "",
        "**Check:** the migration is demonstrated on ONE job end to end with real "
        "output first; then the remaining %d are driven by the same mechanism and "
        "the count of migrated jobs is asserted to equal %d. A partial pass that "
        "reports success is the failure mode." % (len(jobs) - 1, len(jobs)),
        "",
        "**Blast radius:** these are the founder's scheduled jobs. A migration "
        "that half-lands leaves a job neither on the old path nor the new one, "
        "which is a silently dark job -- the exact failure the launchd watchdog "
        "exists to catch.",
        "",
        "**Not doing:** retiring, un-pausing, or changing what any job DOES.",
    ]
    survivor_body = "\n".join(body_lines)

    if not args.apply:
        print("\n--- DRY RUN, nothing written. Survivor body preview: ---")
        print(survivor_body[:1200])
        print("\n(run with --apply to write)")
        return 0

    close_id = None
    states = ls.graphql(ls.TEAM_STATES_QUERY, {"teamId": team_id})
    for s in (((states or {}).get("team") or {}).get("states") or {}).get("nodes") or []:
        if s.get("type") == "canceled":
            close_id = s["id"]
            break
    if not close_id:
        print("REFUSING: no canceled-type state on this team, so absorbed issues "
              "cannot be closed as not-planned. Nothing written.")
        return 1

    log(args.out, {"ts": datetime.now(timezone.utc).isoformat(), "event": "start",
                   "survivor": keep[1]["identifier"], "family_size": len(fam),
                   "jobs": sorted(jobs)})

    ls.graphql(ls.ISSUE_UPDATE, {"id": keep[1]["id"],
                                 "input": {"description": survivor_body}})
    print("survivor %s updated with all %d job labels" % (keep[1]["identifier"], len(jobs)))
    log(args.out, {"event": "survivor-updated", "id": keep[1]["identifier"]})

    done = skipped = 0
    for _, i, job in absorbed:
        if any(MARKER in (c.get("body") or "") for c in i["comments"]["nodes"]):
            print("  skip %s (already collapsed)" % i["identifier"])
            skipped += 1
            continue
        # Record BEFORE the write, so a crash over-reports rather than under-reports.
        log(args.out, {"event": "absorbing", "id": i["identifier"], "job": job,
                       "into": keep[1]["identifier"]})
        ls.graphql(ls.COMMENT_CREATE, {"input": {"issueId": i["id"], "body":
            "%s\n\nCollapsed into **%s**, which now carries every job in this "
            "family including `%s`. Same shape, same fix, one issue instead of "
            "%d.\n\nClosed as not-planned, not as done -- the work has not "
            "happened. Reopening restores this issue and this pointer stays."
            % (MARKER, keep[1]["identifier"], job, len(fam))}})
        ls.graphql(ls.ISSUE_UPDATE, {"id": i["id"], "input": {"stateId": close_id}})
        print("  %-9s -> commented + closed (%s)" % (i["identifier"], job))
        done += 1

    log(args.out, {"event": "done", "absorbed": done, "skipped": skipped})
    print("\ncollapsed %d, skipped %d, survivor %s. Record: %s"
          % (done, skipped, keep[1]["identifier"], args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
