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
from collections import namedtuple
import subprocess
import json
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent

ALERT_MARKER = "kipi-alert-fingerprint"
PROMOTED_MARKER = "kipi-alert-promoted"
HELD_LABEL = "triage:held"

# WHETHER A WRITE HAPPENED IS DATA, NOT A SUBSTRING (codex round 5, major 1).
#
# do_promote and do_hold each have a legitimate refuse path (the issue is no
# longer an alert, or it could not be re-read). Both returned a plain string, and
# run_triage counted "the call did not raise" as success. So a batch that skipped
# every issue reported "N promoted", exited 0, and told launchd-health-check the
# night went fine while nothing was written. That is the SAME silent-success
# defect fixed one round earlier for total model failure: I fixed the symptom
# (model unreachable) and left the class (a non-write counted as a write).
#
# The status now travels WITH the line, so a caller cannot forget to ask.
Outcome = namedtuple("Outcome", "wrote line")
TRIAGE_LABEL = "needs-triage"
OWNER_LABEL = "owner:sana"
DOR_HEADING = "## Definition of Ready"
# Any level of heading whose text is "Definition of Ready". Mirrors the drafter.
DOR_HEADING_RE = re.compile(r"(?mi)^[ \t]{0,3}#{1,6}[ \t]+definition of ready\b")
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

LABELS_Q = """query{issueLabels(first:250){nodes{id name}}}"""

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
    # THE HEADING MUST ACTUALLY BE THERE (codex round 4, major 1).
    #
    # The first cut tested `dor.startswith("#")`, reasoning that a body already
    # starting with a heading carried its own. It does not follow: a model that
    # opens with "## Problem" satisfies that test and ships NO Definition of Ready.
    # The result is the worst of both states, because promotion has already
    # stripped the alert marker: the issue is out of the triage pool AND
    # linear-worker.sh still refuses it, since ready() wants the literal
    # "Definition of Ready". Promoted and unselectable is a new dead end, which is
    # the exact failure mode this whole issue exists to remove.
    #
    # Test for the HEADING, not for "starts with a hash". Same distinction
    # linear-dor-drafter.py's find_dor_heading draws, and for the same reason:
    # structure, not a character.
    if not DOR_HEADING_RE.search(dor):
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
        return Outcome(False, f"{ident}: SKIPPED (could not re-read)")
    desc = fresh.get("description") or ""
    if not is_alert_ticket(desc):
        return Outcome(False, f"{ident}: SKIPPED (no alert marker; already promoted or never an alert)")
    fp = alert_fingerprint(desc)
    new = promote_body(desc, dor, fp, why)
    # ONE mutation for description + label drop. As two calls a failure between
    # them leaves a ticket carrying a DoR and still wearing needs-triage, which
    # reads as triaged to a human and as untriaged to every filter.
    payload = {"description": new, "removedLabelIds": label_ids(fresh, TRIAGE_LABEL)}
    if not apply:
        return Outcome(True, f"{ident}: WOULD PROMOTE (strip marker "
                       f"{fp[:12] or '-'}, drop {TRIAGE_LABEL}, +{len(dor)} chars)")
    res = ls.graphql(UPDATE_M, {"id": ident, "input": payload})
    if not (((res or {}).get("issueUpdate") or {}).get("success")):
        raise RuntimeError(f"{ident}: issueUpdate.success=false")
    return Outcome(True, f"{ident}: PROMOTED")


def do_close(ls, issue: dict, reason: str, apply: bool) -> str:
    ident = issue["identifier"]
    if not apply:
        return Outcome(True, f"{ident}: WOULD CLOSE ({reason[:70]})")
    # Comment FIRST, then close, and REFUSE TO CLOSE IF THE COMMENT DID NOT LAND.
    #
    # Ordering alone was not enough and that was a real defect (codex review of
    # PR #268, major 2): the first cut sent the comment and discarded the result,
    # so `commentCreate.success=false` still fell through to the close and the run
    # printed "CLOSED" -- a silent close wearing an audit trail it did not have.
    # Getting the ORDER right and then not reading the first write's result is the
    # whole failure: an unrecorded close is exactly what this script forbids, and
    # a wrong success line is worse than a failure, because nobody goes looking.
    res = ls.graphql(COMMENT_M, {"input": {"issueId": issue["id"],
              "body": f"Triaged by linear-alert-triage.py: not worth executing.\n\n{reason}"}})
    if not (((res or {}).get("commentCreate") or {}).get("success")):
        raise RuntimeError(
            f"{ident}: refusing to close -- the rationale comment did not post, "
            "and a close with no recorded reason is exactly what this script forbids")
    teams = (ls.graphql(STATES_Q, {"k": TEAM_KEY}) or {}).get("teams") or {}
    states = (((teams.get("nodes") or [{}])[0]).get("states") or {}).get("nodes") or []
    done = [s for s in states if s.get("type") == "canceled"] or \
           [s for s in states if s.get("type") == "completed"]
    if not done:
        raise RuntimeError("no canceled/completed state on the team")
    res = ls.graphql(UPDATE_M, {"id": ident, "input": {"stateId": done[0]["id"]}})
    if not (((res or {}).get("issueUpdate") or {}).get("success")):
        raise RuntimeError(f"{ident}: close failed")
    return Outcome(True, f"{ident}: CLOSED ({done[0]['name']})")


# THE UNATTENDED LANE (codex review of PR #268, major 1).
#
# The first cut of this file shipped promote/close as hand-run verbs and nothing
# else. That is the SAME defect this script was written to fix, one layer over: a
# consumer that no scheduler invokes does not exist operationally, and the 151
# tickets stay exactly where they were. The reviewer was right and the finding is
# recorded here rather than in a commit message, because the shape is easy to
# re-introduce.
#
# WHY PROMOTE-OR-HOLD AND NEVER AUTO-CLOSE. Promotion is reversible: the issue
# stays open and visible, and a wrong promotion costs one dispatch. A close is the
# direction you cannot see afterwards, so it stays an explicit verb a person or an
# agent runs deliberately. An unattended job that closes permanent Linear objects
# on a model's say-so is precisely the "wrong behavior unattended that a human must
# clean up" this repo grades as major.
#
# WHY HOLD IS MARKED. Without a marker every held ticket is re-evaluated every
# night forever, so the nightly cost grows with the size of the bucket rather than
# with its inflow. The marker is a comment key, like the other two, and it does not
# collide with either refusal predicate.
# HOLD IS A LABEL, NOT A BODY EDIT (codex round 3, major 1; confirmed by a Fable
# escalation and then by measurement).
#
# The first cut appended a marker to the description. do_hold re-read the issue,
# checked it was still an alert, and then wrote description = stale_body + marker.
# A promotion landing inside that window was CLOBBERED: its Definition of Ready
# deleted and the issue excluded from triage forever. Adding a fourth point-in-time
# check would not fix it, and this repo already wrote that lesson down in ASK-1126:
# a point-in-time check cannot make a shared mutable resource safe, and there is
# always a next window. I then wrote exactly that bug, twice.
#
# A label is applied by Linear as a SERVER-SIDE DELTA at write time
# (addedLabelIds/removedLabelIds), so it commutes with a concurrent description
# write and touches no description bytes. The race is removed by construction
# rather than guarded. Same reasoning linear-dor-drafter.py gives for using
# removedLabelIds over a full labelIds replacement.
#
# MEASURED before choosing: exactly two call sites sent a description
# (do_promote and do_hold). do_close writes none. So dropping hold's write leaves
# ONE description writer, which is the condition under which this closes the class
# rather than relocating it. do_promote keeps its own re-read guard, and its worst
# case is a DoR overwritten by another DoR, never a DoR deleted.
#
# The label is the SOLE source of held-ness. Nothing writes a hold marker into the
# body any more; two sources of one fact is how they drift.

TRIAGE_PROMPT = """You are triaging ONE fleet alert ticket in a software repo.

Decide whether it describes real, scoped engineering work someone should execute.

Reply with EITHER:
  PROMOTE
  <a Definition of Ready: Problem, Approach, Reproducer, Acceptance criteria as
   markdown checkboxes. Ground every claim in the alert text below. Do not invent
   measurements. Start directly with the body, no preamble.>
OR:
  HOLD
  <one line saying why this is not executable as written>

The first line must be exactly PROMOTE or HOLD and nothing else.

Project: {project}
Title: {title}

Alert body:
{description}
"""


def is_held(issue: dict) -> bool:
    """Held-ness lives in the label set, never in the description."""
    return HELD_LABEL in {l.get("name") for l in
                          ((issue.get("labels") or {}).get("nodes") or [])}


def held_label_id(ls) -> str:
    """Resolve the hold label. Raises rather than returning None.

    A label id that does not resolve makes issueUpdate error, not silently no-op,
    and an unattended job that cannot record a hold must say so loudly instead of
    reporting HELD every night while marking nothing.
    """
    data = ls.graphql(LABELS_Q, {}) or {}
    for node in ((data.get("issueLabels") or {}).get("nodes") or []):
        if node.get("name") == HELD_LABEL:
            return node["id"]
    raise RuntimeError(
        f"no {HELD_LABEL!r} label exists on this workspace; create it once, "
        "then this job can record holds")


def claude_binary() -> str | None:
    for cand in (os.environ.get("KIPI_CLAUDE_BIN"), "claude",
                 os.path.expanduser("~/.claude/local/claude"),
                 "/opt/homebrew/bin/claude", "/usr/local/bin/claude"):
        if not cand:
            continue
        try:
            if subprocess.run([cand, "--version"], capture_output=True,
                              timeout=20, stdin=subprocess.DEVNULL).returncode == 0:
                return cand
        except (OSError, subprocess.TimeoutExpired):
            continue
    return None


def decide(issue: dict, timeout: int = 300) -> tuple[str, str] | None:
    """(verdict, body) or None when the model could not be reached.

    ANTHROPIC_MODEL is pinned. An unpinned headless `claude -p` job rides whatever
    the default is; the fleet has already paid for that once (a batch lane burned
    3% of a weekly budget in an hour on the wrong model). A scheduled job that
    picks its own model is a cost defect waiting for a quiet night.
    """
    binary = claude_binary()
    if not binary:
        return None
    prompt = TRIAGE_PROMPT.format(
        project=(issue.get("project") or {}).get("name") or "unassigned",
        title=issue.get("title") or "",
        description=(issue.get("description") or "(empty)")[:4000])
    env = {**os.environ, "ANTHROPIC_MODEL": os.environ.get(
        "KIPI_TRIAGE_MODEL", "claude-opus-5")}
    # NO TOOLS. THE PROMPT CONTAINS UNTRUSTED TEXT (codex round 6, major).
    #
    # The alert body is machine-written from fleet events and is not authored by
    # anyone we trust to be addressing the model. This job runs unattended, at
    # 02:30, against the PRIMARY checkout. The first cut passed that text with
    # --permission-mode acceptEdits, copied from linear-dor-drafter.py without
    # asking what it was for: a prompt-injected alert could have edited files in
    # the repo, with nobody watching and the only record a triage line.
    #
    # This call is text in, one verdict out. It needs no tools at all, so it gets
    # none: `--tools ""` disables the entire built-in set. That is a capability
    # bound, not a filter, so it does not depend on recognising an attack.
    #
    # linear-dor-drafter.py has the SAME exposure on the same kind of input and
    # is already running nightly. Filed separately rather than fixed here.
    try:
        res = subprocess.run([binary, "-p", prompt, "--tools", ""],
                             capture_output=True, text=True, timeout=timeout,
                             stdin=subprocess.DEVNULL, env=env)
    except (OSError, subprocess.TimeoutExpired):
        return None
    out = (res.stdout or "").strip()
    if res.returncode != 0 or not out:
        return None
    out = re.sub(r"^```[a-z]*\n|\n```$", "", out).strip()
    head, _, rest = out.partition("\n")
    verdict = head.strip().upper()
    # Parsed strictly. A model that answered in prose has NOT made a decision, and
    # guessing one from fuzzy text is how an unattended job promotes garbage.
    if verdict not in ("PROMOTE", "HOLD"):
        return None
    return verdict, rest.strip()


def do_hold(ls, issue: dict, reason: str, apply: bool) -> str:
    ident = issue["identifier"]
    if not apply:
        return Outcome(True, f"{ident}: WOULD HOLD ({reason[:70]})")
    fresh = reread(ls, ident)
    if fresh is None:
        return Outcome(False, f"{ident}: SKIPPED (could not re-read)")
    desc = (fresh.get("description") or "").rstrip()

    # STILL AN ALERT? (codex review of PR #268 round 2, major 2.) do_promote has
    # always re-checked this; do_hold did not, and the omission is the whole bug: a
    # rival run (or a hand promotion) can promote this issue during the model call,
    # and holding it afterwards stamps a worker-READY issue as excluded-from-triage.
    # It then sits eligible for dispatch and invisible to every future pass at once.
    # The guard belongs on BOTH write paths or it belongs on neither; one function
    # having it was the reason it looked correct.
    if not is_alert_ticket(desc):
        return Outcome(False, f"{ident}: SKIPPED (no longer an alert; promoted while this ran)")

    # COMMENT FIRST, AND READ ITS RESULT, THEN THE MARKER (round 2, major 3).
    # This is the identical defect just fixed in do_close, in a function written in
    # the same commit -- fixing the instance and not the class. The marker is the
    # irreversible half here: it removes the issue from every future nightly pass,
    # so writing it before a rationale that never landed produces a permanent,
    # unexplained exclusion that reports HELD. Rationale first; no rationale, no
    # marker, and the issue simply stays in the pool for tomorrow.
    res = ls.graphql(COMMENT_M, {"input": {"issueId": fresh["id"], "body":
        f"Held by linear-alert-triage.py: not executable as written.\n\n{reason}\n\n"
        f"This is NOT a close. Remove the {HELD_LABEL} label to put it back in "
        "the nightly triage pool, or promote it by hand with a real DoR."}})
    if not (((res or {}).get("commentCreate") or {}).get("success")):
        raise RuntimeError(
            f"{ident}: refusing to hold -- the rationale comment did not post, and a "
            "hold marker with no recorded reason is a permanent silent exclusion")

    # addedLabelIds, never a description write. See the HELD_LABEL note above.
    upd = ls.graphql(UPDATE_M, {"id": ident,
                                "input": {"addedLabelIds": [held_label_id(ls)]}})
    if not (((upd or {}).get("issueUpdate") or {}).get("success")):
        raise RuntimeError(f"{ident}: hold label write failed")
    return Outcome(True, f"{ident}: HELD")


def run_triage(ls, project: str | None, limit: int, apply: bool) -> int:
    """One bounded unattended pass. Returns a process exit code."""
    # AN UNROUTABLE ISSUE IS NEVER PROMOTED. Same rule linear-dor-drafter.py
    # applies: a project is how linear-worker.sh decides which checkout can serve
    # an issue, so with none set in_this_repo() is false in every repo at once.
    # Promoting one moves it from "not ready" to "ready and reachable by nobody",
    # which is the UNREACHABLE bucket ASK-839 measured. The first state is honest.
    pool = [i for i in fetch_open(ls, project)
            if is_alert_ticket(i.get("description")) and not is_held(i)
            and ((i.get("project") or {}).get("name") or "").strip()]
    pool.sort(key=lambda i: i.get("createdAt") or "")
    batch = pool[:limit]
    wrote = failed = skipped = 0
    for issue in batch:
        d = decide(issue)
        if d is None:
            failed += 1
            print(f"  {issue['identifier']}: no decision (model unreachable or unparseable)",
                  file=sys.stderr)
            continue
        verdict, body = d
        try:
            if verdict == "PROMOTE" and body:
                out = do_promote(ls, issue, body, "Triaged unattended.", apply)
            else:
                out = do_hold(ls, issue, body or "no reason given", apply)
            print(out.line)
            # .wrote, never "the call returned without raising". A refuse path is
            # not a success, and counting it as one is what made a fully-skipped
            # night report exit 0.
            if out.wrote:
                wrote += 1
            else:
                skipped += 1
        except Exception as exc:  # noqa: BLE001 - one bad issue must not stop the batch
            failed += 1
            print(f"  {issue['identifier']}: FAILED {str(exc)[:160]}", file=sys.stderr)
    line = (f"triage pass: {wrote} written, {skipped} skipped, {failed} failed; "
            f"{len(pool) - len(batch)} still queued"
            + (f" in {project}" if project else " fleet-wide"))
    print(line)
    write_run_evidence(line)
    # TOTAL failure is not a quiet night (codex round 3, major 2). The first cut
    # returned 0 unconditionally, with a comment justifying it: launchd treats
    # non-zero as a crash and launchd-health-check.py keys on LastExitStatus. That
    # reasoning is right for a PARTIAL failure and wrong for a complete one. With
    # the model unreachable every night, the job would report success forever while
    # triaging nothing, which is the same invisible-silence defect this whole issue
    # is about (ASK-1127) and the same one ASK-1123 found in the watchdog.
    #
    # So: partial failures stay exit 0 (one bad issue is not an outage), an empty
    # batch stays exit 0 (nothing to do is success), and a non-empty batch where
    # NOTHING succeeded exits 1 so the health check sees it.
    if batch and not wrote:
        print(f"  NOTHING WAS WRITTEN this pass ({failed} failed, {skipped} skipped "
              f"of {len(batch)}); reporting a failed run so launchd-health-check "
              "does not read it as a quiet night", file=sys.stderr)
        return 1
    # A MOSTLY-FAILED PASS IS NOT A GOOD NIGHT EITHER (codex round 6, minor).
    # One write out of eight exited 0, so a job degrading badly looked identical
    # to a healthy one. A single bad issue still must not page, which is why this
    # is a majority test and not "any failure".
    if failed > wrote:
        print(f"  DEGRADED: {failed} failure(s) against {wrote} write(s); more went "
              "wrong than right, so this pass is reported as failed",
              file=sys.stderr)
        return 1
    return 0


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
    ap.add_argument("verb", choices=["list", "promote", "close", "triage"])
    ap.add_argument("ids", nargs="*", help="issue identifiers, e.g. ASK-1121")
    ap.add_argument("--project", help="only this project")
    ap.add_argument("--dor", help="Definition of Ready body (promote)")
    ap.add_argument("--dor-file", help="read the DoR body from a file (promote)")
    ap.add_argument("--why", default="", help="one line of triage rationale")
    ap.add_argument("--reason", help="why this is not worth executing (close)")
    ap.add_argument("--apply", action="store_true", help="write to Linear")
    ap.add_argument("--limit", type=int, default=5, help="issues per triage pass")
    a = ap.parse_args()

    ls = _load("linear_sync", "linear-sync.py")
    try:
        ls.linear_api_key()
    except Exception as exc:  # noqa: BLE001
        print(f"no Linear key configured ({exc})", file=sys.stderr)
        return 2

    if a.verb == "triage":
        return run_triage(ls, a.project, a.limit, a.apply)

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
            print(out.line)
            done.append(out.line)
        except Exception as exc:  # noqa: BLE001 - one bad issue must not stop the batch
            print(f"{ident}: FAILED {str(exc)[:160]}", file=sys.stderr)
            rc = 1
    if a.apply and done:
        write_run_evidence("; ".join(done))
    return rc


if __name__ == "__main__":
    sys.exit(main())
