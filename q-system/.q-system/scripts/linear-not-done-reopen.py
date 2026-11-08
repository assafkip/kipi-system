#!/usr/bin/env python3
"""linear-not-done-reopen.py -- a Done ticket the worker held as NOT done goes back to Backlog (ASK-4020).

THE SHAPE, measured 2026-11-08 on ASK-297. The worker opened a client repo's PR #20 at
17:48:04Z, held the ticket at needs-scope at 17:48:26Z, and auto-merge landed the
PR at 17:48:31Z. Linear's GitHub integration closed the ticket Done at 17:48:33Z,
and at 17:53:38Z the worker logged "ASK-297 is NOT done: held at needs-scope". Done
hid it from linear-dor-drafter.py's needs-scope redraft, so the unfinished half had
no consumer, and the next merge on that branch can close it again.

THE WINDOW IS THE MERGING PR'S OPEN TIME, NOT THE MERGE. The ticket's DoR said "a
hold label applied after its last merge". On ASK-297 the label landed 4 seconds
BEFORE the merge, so that rule misses the ticket it was written for. A run that
holds the ticket happens while its PR is open, so:
  (a) a hold label still on the ticket, added after the merged PR was linked, or
  (b) a worker log line "<ID> is NOT done" after the PR was linked, with no later
      "start <ID> " line (a later run supersedes it),
means the merge carried half the work. A hold label added before the PR was linked
is a stale hold from an earlier round (ready() refuses a held ticket, so no run can
start under it); that ticket stays Done.

ONLY THE LOG FOR (b). The worker writes NOT done through say() (linear-worker.sh),
which tees to its log and never comments, so a comment scan would read nothing.

WHAT MOVES IT NEXT, named in the comment: needs-scope goes to linear-dor-drafter.py
(com.kipi.linear-dor, 03:00); blocked:capability is listed by stall-sweep.py until
ASK-3960 ships its consumer; no label returns it to the fleet worker's pool.

ONCE PER MERGE. The comment carries the merged PR's URL. If that marker is already
on the ticket, this job acted on that merge before and a later Done is respected.
Over 100 comments with no marker on page one: the marker may be on a later page, so
the job does not act (PR #661, Codex P1). Missing a rare ticket is recoverable; moving
a deliberately re-completed one back again is the defect this marker exists to stop.

STATE FIRST, THEN THE COMMENT, AND A FAILED COMMENT IS RETRIED. A marker on a ticket
that never moved would make every later run skip it, so the state moves first. If the
comment then fails, the ticket is in Backlog and no longer a candidate, so the comment
is kept in PENDING_PATH and posted at the start of the next run (PR #661, Codex P2).
This job is that file's only writer.

Exit codes:
  0  ok (report, or every planned reopen landed)
  2  usage
  3  no Linear key
  4  --apply refused under pytest
  6  a write was refused (others still attempted)
  9  incomplete: a Linear read failed; nothing written

Usage:
    python3 linear-not-done-reopen.py          # report only
    python3 linear-not-done-reopen.py --apply  # move to Backlog and comment
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import pathlib
import re
import sys
import tempfile
from datetime import datetime, timedelta, timezone

HERE = pathlib.Path(__file__).resolve().parent

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_NO_KEY = 3
EXIT_REFUSED_FIXTURE = 4
EXIT_WRITE_FAILED = 6
EXIT_INCOMPLETE = 9

HOLD_LABELS = ("needs-scope", "blocked:capability")
LOOKBACK_DAYS = 30
MAX_REOPENS = 10
MARKER = "kipi-not-done-reopen"
WORKER_LOG = "linear-worker.log"

# Job state lives outside every checkout (separate-worktrees.md).
EVIDENCE_PATH = pathlib.Path.home() / ".local" / "state" / "kipi" / "linear-not-done-reopen" / "last-run.json"
PENDING_PATH = EVIDENCE_PATH.with_name("pending-comments.json")

NOT_DONE = re.compile(r"^(\S+Z) (ASK-\d+) is NOT done\b")
START = re.compile(r"^(\S+Z) start (ASK-\d+) ")

NEXT = {
    "needs-scope": "linear-dor-drafter.py (com.kipi.linear-dor, 03:00) redrafts its Definition "
                   "of Ready and drops the label, then the fleet worker can pick it.",
    "blocked:capability": "stall-sweep.py (com.kipi.stall-sweep, hourly) lists it on ASK-3960, "
                          "which builds the consumer that re-tests a capability block.",
    None: "No hold label, so it is back in the fleet worker's pool (com.kipi.dispatch).",
}

TEAM_QUERY = 'query($k:String!){teams(filter:{key:{eq:$k}}){nodes{id}}}'
LABELLED_QUERY = """query($t:ID!,$s:DateTimeOrDuration!,$a:String){issues(filter:{team:{id:{eq:$t}},
 state:{type:{eq:"completed"}},completedAt:{gt:$s},
 labels:{name:{in:["needs-scope","blocked:capability"]}}},first:100,after:$a){
 nodes{identifier} pageInfo{hasNextPage endCursor}}}"""
ISSUE_QUERY = """query($id:String!){issue(id:$id){id identifier state{type} completedAt
 labels{nodes{id name}}
 attachments(first:50){nodes{url createdAt metadata}}
 history(first:100){nodes{createdAt addedLabelIds}}
 comments(first:100){nodes{body} pageInfo{hasNextPage}}}}"""
COMMENT_CREATE = """mutation($input:CommentCreateInput!){commentCreate(input:$input){success}}"""
ISSUE_UPDATE = """mutation($id:String!,$input:IssueUpdateInput!){issueUpdate(id:$id,input:$input){success}}"""


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


def read_log(lines) -> dict:
    """{identifier: {"not_done": [ts...], "start": [ts...]}} from the worker log."""
    out = {}
    for ln in lines:
        m = NOT_DONE.match(ln)
        kind = "not_done"
        if not m:
            m = START.match(ln)
            kind = "start"
        if not m:
            continue
        t = _ts(m.group(1))
        if t is not None:
            out.setdefault(m.group(2), {"not_done": [], "start": []})[kind].append(t)
    return out


def last_merge(issue: dict):
    """The latest merged PR attachment, or None when no merge closed it."""
    merged = []
    for a in ((issue.get("attachments") or {}).get("nodes") or []):
        m = a.get("metadata") or {}
        if "/pull/" in (a.get("url") or "") and str(m.get("status") or "").lower() == "merged":
            at, opened = _ts(m.get("mergedAt")), _ts(a.get("createdAt"))
            if at and opened:
                merged.append({"url": a["url"], "merged_at": at, "opened_at": opened})
    return max(merged, key=lambda r: r["merged_at"]) if merged else None


def decide(issue: dict, log: dict) -> dict:
    """{"reopen": bool, "why": str, "label": str|None, "merge": {...}|None}. Pure."""
    out = {"identifier": issue.get("identifier"), "reopen": False, "why": "", "label": None,
           "merge": None}
    if ((issue.get("state") or {}).get("type")) != "completed":
        out["why"] = "not completed"
        return out
    merge = last_merge(issue)
    if merge is None:
        out["why"] = "no merged PR closed it"
        return out
    out["merge"] = merge
    url = merge["url"]
    comments = issue.get("comments") or {}
    for c in (comments.get("nodes") or []):
        if f"<!-- {MARKER}: {url} -->" in (c.get("body") or ""):
            out["why"] = "already reopened once for this merge; a later Done is respected"
            return out
    if (comments.get("pageInfo") or {}).get("hasNextPage"):
        out["why"] = "over 100 comments and no marker on page one; the marker may be later, so no action"
        return out
    present = {(n.get("name") or ""): n.get("id") for n in ((issue.get("labels") or {}).get("nodes") or [])}
    held = [h for h in HOLD_LABELS if h in present]
    for h in held:
        added = [_ts(n.get("createdAt")) for n in ((issue.get("history") or {}).get("nodes") or [])
                 if present[h] in (n.get("addedLabelIds") or [])]
        added = [t for t in added if t is not None]
        if added and max(added) >= merge["opened_at"]:
            out.update(reopen=True, label=h,
                       why=f"{h} was added at {max(added).isoformat(timespec='seconds')}, after "
                           f"the PR was linked at {merge['opened_at'].isoformat(timespec='seconds')}")
            return out
    events = log.get(issue.get("identifier") or "") or {}
    nd = [t for t in events.get("not_done", []) if t >= merge["opened_at"]]
    if nd:
        last_nd = max(nd)
        if not [t for t in events.get("start", []) if t > last_nd]:
            out.update(reopen=True, label=held[0] if held else None,
                       why=f"the worker logged NOT done at {last_nd.isoformat(timespec='seconds')}, "
                           f"after the PR was linked")
            return out
    out["why"] = ("stale hold: added before the PR was linked" if held
                  else "no hold label and no NOT done after the PR was linked")
    return out


def reopen_comment(d: dict) -> str:
    """THE body. One producer, so the marker lookup reads what it writes."""
    m = d["merge"]
    return (f"<!-- {MARKER}: {m['url']} -->\n"
            f"**Back to Backlog: this merge carried only half the work.** Linear closed the "
            f"ticket Done when {m['url']} merged at {m['merged_at'].isoformat(timespec='seconds')}, "
            f"but {d['why']}.\n\n"
            f"Next step: {NEXT[d['label']]}\n\n"
            f"linear-not-done-reopen.py (com.kipi.linear-not-done-reopen, hourly, ASK-4020) "
            f"moved it. It acts once per merge: if this ticket really is done, set it Done "
            f"again and this job leaves it.")


# ---------------------------------------------------------------------------
# the network half
# ---------------------------------------------------------------------------

def _load_sync():
    spec = importlib.util.spec_from_file_location("linear_sync", HERE / "linear-sync.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def candidates(sync, team_id: str, log: dict, now: datetime) -> list:
    """Completed tickets with a hold label, plus every ticket the log calls NOT done."""
    since = (now - timedelta(days=LOOKBACK_DAYS)).isoformat()
    names, after = set(), None
    while True:
        page = sync.graphql(LABELLED_QUERY, {"t": team_id, "s": since, "a": after})["issues"]
        names |= {n["identifier"] for n in page["nodes"]}
        if not page["pageInfo"]["hasNextPage"]:
            break
        after = page["pageInfo"]["endCursor"]
    cutoff = now - timedelta(days=LOOKBACK_DAYS)
    names |= {i for i, ev in log.items() if any(t >= cutoff for t in ev["not_done"])}
    return sorted(names)


def read_pending(path: pathlib.Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def write_pending(path: pathlib.Path, pending: dict) -> None:
    """Atomic, one writer (this job)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".pending.", suffix=".json")
    with os.fdopen(fd, "w") as fh:
        json.dump(pending, fh, indent=2, sort_keys=True)
    os.replace(tmp, path)


def post_comment(sync, issue_id: str, body: str) -> bool:
    res = sync.graphql(COMMENT_CREATE, {"input": {"issueId": issue_id, "body": body}}) or {}
    return bool((res.get("commentCreate") or {}).get("success"))


def retry_pending(sync, path: pathlib.Path) -> tuple:
    """(posted ids, still pending ids). Runs before any new reopen."""
    pending = read_pending(path)
    posted = []
    for ident, row in sorted(pending.items()):
        try:
            if post_comment(sync, row["issue_id"], row["body"]):
                posted.append(ident)
        except Exception:  # noqa: BLE001 - stays pending; the next run retries
            pass
    for ident in posted:
        pending.pop(ident, None)
    if posted:
        write_pending(path, pending)
    return posted, sorted(pending)


def apply_one(sync, issue: dict, d: dict, backlog_id: str, pending_path: pathlib.Path) -> str:
    """State first, then the comment: a failed comment must not leave a marker on a
    ticket that never moved, or the next run would skip it for good. A comment that
    fails after the move is kept in pending_path for the next run."""
    res = sync.graphql(ISSUE_UPDATE, {"id": issue["id"], "input": {"stateId": backlog_id}}) or {}
    if not (res.get("issueUpdate") or {}).get("success"):
        raise RuntimeError(f"{d['identifier']}: issueUpdate(stateId) refused; still Done")
    body = reopen_comment(d)
    try:
        ok = post_comment(sync, issue["id"], body)
    except Exception:  # noqa: BLE001 - same handling as a refused comment
        ok = False
    if not ok:
        pending = read_pending(pending_path)
        pending[d["identifier"]] = {"issue_id": issue["id"], "body": body}
        write_pending(pending_path, pending)
        raise RuntimeError(f"{d['identifier']}: moved to Backlog; comment refused, kept for the next run")
    return "reopened"


def write_evidence(path: pathlib.Path, payload: dict) -> None:
    """One writer, atomic rename. Audit only: no job reads it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".last-run.", suffix=".json")
    with os.fdopen(fd, "w") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True, default=str)
    os.replace(tmp, path)


def main(argv: list) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--team", default=os.environ.get("KIPI_LINEAR_TEAM", "ASK"))
    ap.add_argument("--log", default=None, help="worker log (default: $KIPI_STATE_DIR/linear-worker.log)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--apply", action="store_true", help="write (default: report only)")
    try:
        args = ap.parse_args(argv)
    except SystemExit:
        return EXIT_USAGE
    if args.apply and os.environ.get("PYTEST_CURRENT_TEST"):
        print("linear-not-done-reopen: REFUSED --apply under pytest.", file=sys.stderr)
        return EXIT_REFUSED_FIXTURE

    state_dir = os.environ.get("KIPI_STATE_DIR") or str(pathlib.Path.home() / ".config" / "kipi")
    log_path = pathlib.Path(args.log or os.path.join(state_dir, WORKER_LOG))
    try:
        with open(log_path, encoding="utf-8", errors="replace") as fh:
            log = read_log(fh)
    except FileNotFoundError:
        log = {}  # no worker on this machine: case (b) has nothing to read
    sync = _load_sync()
    try:
        sync.linear_api_key()
    except Exception as exc:
        print(f"linear-not-done-reopen: no Linear key configured ({exc})", file=sys.stderr)
        return EXIT_NO_KEY

    now = datetime.now(timezone.utc)
    try:
        team_id = sync.graphql(TEAM_QUERY, {"k": args.team})["teams"]["nodes"][0]["id"]
        idents = candidates(sync, team_id, log, now)
        issues = []
        for ident in idents:
            issue = (sync.graphql(ISSUE_QUERY, {"id": ident}) or {}).get("issue")
            if issue:
                issues.append(issue)
    except Exception as exc:
        print(f"linear-not-done-reopen: a read failed ({exc}); nothing written. Exit 9.", file=sys.stderr)
        return EXIT_INCOMPLETE

    decisions = [decide(i, log) for i in issues]
    plan = [(i, d) for i, d in zip(issues, decisions) if d["reopen"]][:MAX_REOPENS]
    done, failed = [], []
    retried, still_pending = [], []
    if args.apply:
        retried, still_pending = retry_pending(sync, PENDING_PATH)
    if args.apply and plan:
        backlog_id = sync.requeue_state_id(team_id)
        if not backlog_id:
            failed.append({"id": "*", "error": "team has no Backlog or Todo state"})
        else:
            for issue, d in plan:
                try:
                    done.append({"id": d["identifier"],
                                 "did": apply_one(sync, issue, d, backlog_id, PENDING_PATH)})
                except Exception as exc:
                    failed.append({"id": d["identifier"], "error": str(exc)[:200]})

    result = {"ts": now.isoformat(timespec="seconds"), "applied": bool(args.apply),
              "candidates": len(issues),
              "reopen": [{"id": d["identifier"], "why": d["why"], "merge": d["merge"]["url"]}
                         for _, d in plan],
              "stays_done": [{"id": d["identifier"], "why": d["why"]} for d in decisions if not d["reopen"]],
              "done": done, "failed": failed,
              "pending_posted": retried, "pending_left": still_pending}
    if args.apply:
        try:
            write_evidence(EVIDENCE_PATH, result)
        except OSError as exc:
            print(f"linear-not-done-reopen: evidence not written ({exc})", file=sys.stderr)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
    else:
        print(f"linear-not-done-reopen: {len(issues)} candidate(s); {len(plan)} to reopen.")
        for r in result["reopen"]:
            print(f"  REOPEN {r['id']}: {r['why']} ({r['merge']})")
        for f in failed:
            print(f"  FAILED {f['id']}: {f['error']}")
    return EXIT_WRITE_FAILED if (failed or still_pending) else EXIT_OK


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
