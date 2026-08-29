#!/usr/bin/env python3
r"""Triage the fleet-alert bucket: the missing consumer between alert-to-linear.py
and linear-worker.sh.

THE GAP THIS CLOSES (measured 2026-08-29, ASK-1127).
alert-to-linear.py files a ticket. TWO independent readers then refuse it:

  linear-dor-drafter.py  is_alert_ticket()  -> selection_mode() returns None
  linear-worker.sh:568   is_fleet_alert()   -> ready() returns False

Both refusals are correct in isolation and were added together on purpose
(ASK-839): a raw alert line is a notification, not a spec, and drafting a DoR
onto one only makes it READY-SHAPED. What was never built is the third thing --
anything that moves a ticket OUT of that bucket. terminal-states.json registered
the exit as `terminal: true` with the rationale "the consumer of an alert is the
operator who reads it". The same file's own doc block forbids exactly that:
"A human is never a valid consumer -- the founder does not read or work on code."
And there is no operator to read it: the ASK team has two members, Codex and the
founder. `owner:sana` is a routing label the worker consumes, not a person with a
seat who sees a backlog. So the declared consumer is the empty set, and the
measured effect is silence -- 151 open alert tickets on 2026-08-29, of which 55
in kipi-system, covering a RED main and a disk at 98%.

WHY PROMOTION AND NOT AUTO-DOR.
Emitting a DoR from the filer (the obvious fix) is INERT: linear-worker.sh
refuses at is_fleet_alert() on line 568, before line 571 ever reads the
description for a DoR. It would only work by also deleting that exclusion, which
reverts a measured decision and dumps every unscoped notification into the
executable queue. So the transition is explicit and per-ticket: a promotion
DECIDES that this particular alert is real, scoped work, and only then converts
it.

WHAT PROMOTION IS, MECHANICALLY.
Strip the `<!-- kipi-alert-fingerprint: ... -->` comment, drop `needs-triage`,
append a real `## Definition of Ready`. After that the issue is an ordinary
issue and BOTH consumers accept it with no change to either -- the load path is
already proven by ASK-1119, which is exactly this shape and sits in the worker's
ready set today. Zero edits to linear-worker.sh or linear-dor-drafter.py is the
point, not an accident: a fix that needs the two refusals loosened would be a
fix that re-opens the flood ASK-839 measured.

DEDUP IS NOT AFFECTED, AND THAT WAS CHECKED RATHER THAN ASSUMED.
alert-to-linear.py keys repeat-detection on a LOCAL state file
(_read_state(fp) -> {fp}.json -> prior["issue_id"]), never on the description.
Stripping the marker therefore cannot resurrect the four-tickets-per-alert flood
that fingerprinting was built to stop. The value is preserved in a
`<!-- kipi-alert-promoted: <fp> -->` line so the provenance survives the
promotion; that key is NOT `kipi-alert-fingerprint`, and both readers match the
whole key exactly (worker: `name.strip() == ALERT_MARKER`; drafter:
`re.escape("kipi-alert-fingerprint") + r"\s*:"`), so the audit line cannot
re-trip either filter.

NEVER DELETE. A ticket that is not worth working is CLOSED with the reason
written on it as a comment, which is reversible and auditable. There is no verb
in this script that removes an issue.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent

ALERT_MARKER = "kipi-alert-fingerprint"
PROMOTED_MARKER = "kipi-alert-promoted"
TRIAGE_LABEL = "needs-triage"
OWNER_LABEL = "owner:sana"
DOR_HEADING = "## Definition of Ready"
TEAM_KEY = "ASK"

# Same shape both existing readers use. Kept here rather than imported because
# linear-worker.sh's copy lives inside a bash heredoc and cannot be imported at
# all -- so the invariant is pinned by test_linear_alert_triage.py asserting this
# module and the worker agree on the same fixtures, not by a shared symbol.
ALERT_RE = re.compile(r"<!--\s*" + re.escape(ALERT_MARKER) + r"\s*:")
# Non-greedy to the FIRST close, so a description containing two HTML comments
# does not have everything between them eaten.
ALERT_COMMENT_RE = re.compile(
    r"[ \t]*<!--\s*" + re.escape(ALERT_MARKER) + r"\s*:(?P<fp>.*?)-->[ \t]*\n?",
    re.DOTALL)


def is_alert_ticket(description: str) -> bool:
    return bool(ALERT_RE.search(description or ""))


def alert_fingerprint(description: str) -> str:
    m = ALERT_COMMENT_RE.search(description or "")
    return m.group("fp").strip() if m else ""


def strip_alert_marker(description: str) -> str:
    """Remove every alert-fingerprint comment. Plural on purpose: a ticket that
    was commented onto by a repeat can legitimately carry more than one, and
    leaving the second behind would leave the issue still refused while the run
    reported it promoted."""
    return ALERT_COMMENT_RE.sub("", description or "")


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ISSUES_Q = """query($f:IssueFilter,$a:String){issues(filter:$f,first:100,after:$a){
  pageInfo{hasNextPage endCursor}
  nodes{id identifier title description url createdAt
        state{name type} project{name} labels{nodes{id name}}}}}"""

ISSUE_Q = """query($id:String!){issue(id:$id){id identifier title description url
  state{name type} project{name} labels{nodes{id name}}}}"""

UPDATE_M = """mutation($id:String!,$input:IssueUpdateInput!){
  issueUpdate(id:$id,input:$input){success issue{identifier}}}"""

COMMENT_M = """mutation($input:CommentCreateInput!){
  commentCreate(input:$input){success}}"""

STATES_Q = """query($k:String!){teams(filter:{key:{eq:$k}}){nodes{
  states{nodes{id name type}}}}}"""


def fetch_open(ls, project: str | None) -> list:
    f = {"team": {"key": {"eq": TEAM_KEY}},
         "state": {"type": {"nin": ["completed", "canceled"]}}}
    out, after = [], None
    while True:
        page = (ls.graphql(ISSUES_Q, {"f": f, "a": after}) or {}).get("issues") or {}
        out += page.get("nodes") or []
        if not (page.get("pageInfo") or {}).get("hasNextPage"):
            break
        after = page["pageInfo"]["endCursor"]
    if project:
        out = [i for i in out if ((i.get("project") or {}).get("name") or "") == project]
    return out


def label_ids(issue: dict, name: str) -> list:
    return [l["id"] for l in ((issue.get("labels") or {}).get("nodes") or [])
            if l.get("name") == name and l.get("id")]


def reread(ls, identifier: str) -> dict | None:
    """The issue as Linear holds it NOW.

    Same reason the drafter has one (reread_before_write): selection and write are
    separated by a decision, and building the payload from the pre-decision copy
    silently overwrites anything edited in between. None is a refusal to write,
    not an empty issue.
    """
    try:
        return (ls.graphql(ISSUE_Q, {"id": identifier}) or {}).get("issue")
    except Exception as exc:  # noqa: BLE001 - a failed freshness check must not write
        print(f"  {identifier}: could not re-read before write: {str(exc)[:120]}",
              file=sys.stderr)
        return None


def promote_body(desc: str, dor: str, fp: str, why: str) -> str:
    body = strip_alert_marker(desc).rstrip()
    dor = dor.strip()
    if not dor.startswith("#"):
        dor = f"{DOR_HEADING}\n\n{dor}"
    parts = [body, "", dor, "",
             f"---", f"Promoted from a fleet alert by linear-alert-triage.py. {why}".rstrip()]
    if fp:
        # Provenance survives the promotion. Deliberately a DIFFERENT comment key
        # from the one both consumers match, so the audit line cannot re-refuse
        # the issue it is documenting.
        parts.append(f"<!-- {PROMOTED_MARKER}: {fp} -->")
    return "\n".join(parts).rstrip() + "\n"


def do_promote(ls, issue: dict, dor: str, why: str, apply: bool) -> str:
    ident = issue["identifier"]
    fresh = reread(ls, ident) if apply else issue
    if fresh is None:
        return f"{ident}: SKIPPED (could not re-read)"
    desc = fresh.get("description") or ""
    if not is_alert_ticket(desc):
        return f"{ident}: SKIPPED (no alert marker; already promoted or never an alert)"
    fp = alert_fingerprint(desc)
    new = promote_body(desc, dor, fp, why)
    # ONE mutation for description + label drop. As two calls a failure between
    # them leaves a ticket carrying a DoR and still wearing needs-triage, which
    # reads as triaged to a human and as untriaged to every filter.
    payload = {"description": new, "removedLabelIds": label_ids(fresh, TRIAGE_LABEL)}
    if not apply:
        return (f"{ident}: WOULD PROMOTE (strip marker {fp[:12] or '-'}, "
                f"drop {TRIAGE_LABEL}, +{len(dor)} chars of DoR)")
    res = ls.graphql(UPDATE_M, {"id": ident, "input": payload})
    if not (((res or {}).get("issueUpdate") or {}).get("success")):
        raise RuntimeError(f"{ident}: issueUpdate.success=false")
    return f"{ident}: PROMOTED"


def do_close(ls, issue: dict, reason: str, apply: bool) -> str:
    ident = issue["identifier"]
    if not apply:
        return f"{ident}: WOULD CLOSE ({reason[:70]})"
    # Comment FIRST, then close. The reverse order leaves a closed issue with no
    # recorded rationale if the second call fails, and a silent close is exactly
    # the "never silently delete" rule this script exists under.
    ls.graphql(COMMENT_M, {"input": {"issueId": issue["id"],
               "body": f"Triaged by linear-alert-triage.py: not worth executing.\n\n{reason}"}})
    teams = (ls.graphql(STATES_Q, {"k": TEAM_KEY}) or {}).get("teams") or {}
    states = (((teams.get("nodes") or [{}])[0]).get("states") or {}).get("nodes") or []
    done = [s for s in states if s.get("type") == "canceled"] or \
           [s for s in states if s.get("type") == "completed"]
    if not done:
        raise RuntimeError("no canceled/completed state on the team")
    res = ls.graphql(UPDATE_M, {"id": ident, "input": {"stateId": done[0]["id"]}})
    if not (((res or {}).get("issueUpdate") or {}).get("success")):
        raise RuntimeError(f"{ident}: close failed")
    return f"{ident}: CLOSED ({done[0]['name']})"


def write_run_evidence(line: str) -> None:
    """The liveness artifact terminal-states.json points at.

    A launchd job that exits 0 with no output is indistinguishable from one that
    did nothing -- which is how com.kipi.linear-dor read as dead for this whole
    investigation until its log turned up under ~/.config/kipi/ instead of
    ~/Library/Logs/kipi/. This job states what it did, every run, in the one place
    the contract names.
    """
    path = Path(os.path.expanduser("~/.config/kipi/linear-alert-triage.out"))
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(f"alert-triage {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}: {line}\n")
    except OSError:
        pass


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("verb", choices=["list", "promote", "close"])
    ap.add_argument("ids", nargs="*", help="issue identifiers, e.g. ASK-1121")
    ap.add_argument("--project", help="only this project")
    ap.add_argument("--dor", help="Definition of Ready body (promote)")
    ap.add_argument("--dor-file", help="read the DoR body from a file (promote)")
    ap.add_argument("--why", default="", help="one line of triage rationale")
    ap.add_argument("--reason", help="why this is not worth executing (close)")
    ap.add_argument("--apply", action="store_true", help="write to Linear")
    a = ap.parse_args()

    ls = _load("linear_sync", "linear-sync.py")
    try:
        ls.linear_api_key()
    except Exception as exc:  # noqa: BLE001
        print(f"no Linear key configured ({exc})", file=sys.stderr)
        return 2

    if a.verb == "list":
        issues = [i for i in fetch_open(ls, a.project)
                  if is_alert_ticket(i.get("description"))]
        for i in sorted(issues, key=lambda x: x["identifier"]):
            labs = ",".join(sorted(l["name"] for l in (i["labels"]["nodes"])))
            print(f'{i["identifier"]}\t{(i.get("project") or {}).get("name")}\t'
                  f'{labs}\t{i["title"][:88]}')
        line = (f"{len(issues)} open alert ticket(s)"
                + (f" in {a.project}" if a.project else " fleet-wide"))
        print(line)
        write_run_evidence(line)
        return 0

    if not a.ids:
        print("no issue ids given", file=sys.stderr)
        return 2

    dor = a.dor or ""
    if a.dor_file:
        dor = Path(a.dor_file).read_text(encoding="utf-8")
    if a.verb == "promote" and not dor.strip():
        print("promote needs --dor or --dor-file", file=sys.stderr)
        return 2
    if a.verb == "close" and not (a.reason or "").strip():
        print("close needs --reason (never a silent close)", file=sys.stderr)
        return 2

    rc, done = 0, []
    for ident in a.ids:
        issue = reread(ls, ident)
        if issue is None:
            print(f"{ident}: NOT FOUND", file=sys.stderr)
            rc = 1
            continue
        try:
            if a.verb == "promote":
                out = do_promote(ls, issue, dor, a.why, a.apply)
            else:
                out = do_close(ls, issue, a.reason, a.apply)
            print(out)
            done.append(out)
        except Exception as exc:  # noqa: BLE001 - one bad issue must not stop the batch
            print(f"{ident}: FAILED {str(exc)[:160]}", file=sys.stderr)
            rc = 1
    if a.apply and done:
        write_run_evidence("; ".join(done))
    return rc


if __name__ == "__main__":
    sys.exit(main())
