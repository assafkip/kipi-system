#!/usr/bin/env python3
"""linear-sync.py requeue and started_hold_reason, the two halves of ASK-3825.

RULE-2026-11-06-B: "A ticket the worker picks up returns to Backlog when its run
fails, caps or parks." requeue_issue is the ONE writer of that move (the worker
and linear-triage-health.py both call it), and started_hold_reason is the ONE
rule for "a started ticket nobody is working" (the worker picker, the DoR
drafter and linear-triage-health.py all ask it). This file pins each edge of
both directly. The end-to-end paths are in test-worker-state-round-trip.sh and
tests/test_linear_triage_health.py.

NO NETWORK. The module's own `graphql` is replaced with a recorder, so every
Linear call the code makes is visible here and none leaves the machine.

NEGATIVE SELF-TEST (last case): requeue against a mutant that drops the
started-state check must move a Done issue, or the "never touches Done" case
proves nothing.

Run: python3 q-system/.q-system/scripts/test/test-linear-requeue.py
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
SYNC = os.path.join(HERE, "..", "linear-sync.py")
NOW = datetime(2026, 11, 6, 12, 0, 0, tzinfo=timezone.utc)

PASS, FAIL = 0, 0


def ok(name):
    global PASS
    PASS += 1
    print(f"  ok   {name}")


def bad(name, detail=""):
    global FAIL
    FAIL += 1
    print(f"  FAIL {name}\n     {detail}")


def check(cond, name, detail=""):
    if cond:
        ok(name)
    else:
        bad(name, detail)


def load(path=SYNC, name="ls_requeue_test"):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Recorder:
    """Answers the queries requeue makes, records every mutation."""

    def __init__(self, state="started", update_ok=True, comment_ok=True, states=None,
                 attachments=None, fail_attachments=False):
        self.state = state
        self.update_ok, self.comment_ok = update_ok, comment_ok
        self.states = states if states is not None else [
            {"id": "st-todo", "name": "Todo", "type": "unstarted", "position": 1},
            {"id": "st-backlog", "name": "Backlog", "type": "backlog", "position": 2},
            {"id": "st-progress", "name": "In Progress", "type": "started", "position": 3},
        ]
        self.attachments = attachments or []
        self.fail_attachments = fail_attachments
        self.mutations = []

    def __call__(self, query, variables):
        if "issueUpdate" in query:
            self.mutations.append(("update", variables["input"]))
            return {"issueUpdate": {"success": self.update_ok}}
        if "commentCreate" in query:
            self.mutations.append(("comment", variables["input"]["body"]))
            return {"commentCreate": {"success": self.comment_ok, "comment": {"id": "c"}}}
        if "states(first" in query:
            return {"team": {"states": {"nodes": self.states}}}
        if "attachments(" in query:
            if self.fail_attachments:
                raise RuntimeError("fixture: attachments unavailable")
            return {"issue": {"attachments": {"nodes": self.attachments}}}
        names = {"started": "In Progress", "backlog": "Backlog", "completed": "Done",
                 "canceled": "Canceled"}
        return {"issue": {"id": "uuid-1", "identifier": "ASK-1",
                          "state": {"name": names[self.state], "type": self.state},
                          "team": {"id": f"team-{id(self)}"}}}


def with_recorder(rec, mod=None):
    mod = mod or load()
    mod.graphql = rec
    return mod


print("== requeue_issue")

rec = Recorder()
outcome, msg = with_recorder(rec).requeue_issue("ASK-1", "fail", "rc=1, attempt 1 of 3", "sana")
updates = [m for m in rec.mutations if m[0] == "update"]
comments = [m for m in rec.mutations if m[0] == "comment"]
if outcome == "moved" and updates == [("update", {"stateId": "st-backlog"})]:
    ok("a started issue moves to the Backlog state, not Todo (Backlog is what every drain reads)")
else:
    bad("a started issue moves to Backlog", f"{outcome} {msg} {rec.mutations}")
if len(comments) == 1 and "\n" not in comments[0][1] \
        and "Back to Backlog from In Progress. Exit: fail (rc=1, attempt 1 of 3)." in comments[0][1]:
    ok("one comment, one line, naming the exit and its reason")
else:
    bad("one one-line comment names the exit", f"{comments}")
if rec.mutations and rec.mutations[0][0] == "update":
    ok("the state moves BEFORE the comment, so a comment never claims a move that failed")
else:
    bad("state first, comment second", f"{rec.mutations}")

for state in ("backlog", "completed", "canceled"):
    rec = Recorder(state=state)
    outcome, msg = with_recorder(rec).requeue_issue("ASK-1", "cap", "x")
    if outcome == "unchanged" and rec.mutations == []:
        ok(f"a {state} issue is left alone: nothing written ({msg})")
    else:
        bad(f"a {state} issue is left alone", f"{outcome} {rec.mutations}")

rec = Recorder(update_ok=False)
outcome, msg = with_recorder(rec).requeue_issue("ASK-1", "fail")
if outcome == "failed" and not [m for m in rec.mutations if m[0] == "comment"]:
    ok("a refused state write is a failure, and no comment claims it moved")
else:
    bad("a refused state write fails without a comment", f"{outcome} {rec.mutations}")

rec = Recorder(comment_ok=False)
outcome, msg = with_recorder(rec).requeue_issue("ASK-1", "fail")
if outcome == "failed" and "moved to Backlog, but the comment" in msg:
    ok("a refused comment is reported as a failure that names the half that landed")
else:
    bad("a refused comment is a failure", f"{outcome} {msg}")

rec = Recorder(states=[{"id": "st-progress", "name": "In Progress", "type": "started"}])
outcome, msg = with_recorder(rec).requeue_issue("ASK-1", "park")
if outcome == "failed" and rec.mutations == []:
    ok("a team with no Backlog or Todo state fails loudly and writes nothing")
else:
    bad("no Backlog state fails", f"{outcome} {rec.mutations}")

rec = Recorder()
with_recorder(rec).requeue_issue("ASK-1", "park", "line one\nline two\n\nline three")
body = [m for m in rec.mutations if m[0] == "comment"][0][1]
if "\n" not in body and "line one line two line three" in body:
    ok("a multi-line reason is folded, so a caller cannot break the one-line contract")
else:
    bad("a multi-line reason is folded", repr(body))

print("== started_hold_reason")


def started(hours, ident="ASK-1"):
    stamp = (NOW - timedelta(hours=hours)).isoformat().replace("+00:00", "Z")
    return {"id": "uuid-" + ident, "identifier": ident,
            "state": {"name": "In Progress", "type": "started"}, "startedAt": stamp}


# The worker's state dir: worktrees/ for claims, the attempts ledger beside it.
# ASK-1 has a ledger row, so the fleet has run it (PR #611 review, finding 1).
trees = tempfile.mkdtemp()
os.makedirs(os.path.join(trees, "worktrees"))
LEDGER = os.path.join(trees, "linear-worker-attempts.json")
with open(LEDGER, "w") as fh:
    json.dump({"ASK-1": {"rounds": 1}}, fh)
mod = with_recorder(Recorder())
cases = [
    ("abandoned 30 days, no claim, no PR", started(24 * 30), ""),
    ("23 hours: inside the lane window", started(23), "inside the 24h window"),
    ("exactly 24 hours: the window is inclusive of its end", started(24), ""),
]
for label, node, want in cases:
    got = mod.started_hold_reason(node, NOW, trees)
    if (want == "" and got == "") or (want and want in got):
        ok(f"{label} -> {got or 'eligible'}")
    else:
        bad(label, f"got {got!r}, want {want!r}")

node = started(24 * 30)
node["startedAt"] = None
got = mod.started_hold_reason(node, NOW, trees)
check("no startedAt" in got, "no startedAt holds the ticket (fail closed)", got)

node = started(24 * 30)
node["state"] = {"name": "Backlog", "type": "backlog"}
got = mod.started_hold_reason(node, NOW, trees)
check(got == "not in a started state", "a Backlog issue is not a started one", got)

mod = with_recorder(Recorder(attachments=[
    {"url": "https://github.com/x/r/pull/9", "metadata": {"status": "open", "branch": "sana/ASK-1"}},
    {"url": "https://github.com/x/r/pull/8", "metadata": {"status": "closed", "branch": "lane"}},
    {"url": "https://linear.app/doc", "metadata": {"status": "open", "branch": "lane"}},
]))
got = mod.started_hold_reason(started(24 * 30), NOW, trees)
check(got == "open PR https://github.com/x/r/pull/9 on sana/ASK-1",
      "an open PR on the worker's own branch holds it; a closed PR and a non-PR attachment do not", got)

mod = with_recorder(Recorder(attachments=[
    {"url": "https://github.com/x/r/pull/8", "metadata": {"status": "closed", "branch": "lane"}},
    {"url": "https://github.com/x/r/pull/6", "metadata": {"status": "merged", "branch": "lane"}},
    {"url": "https://linear.app/doc", "metadata": {"status": "open", "branch": "lane"}},
]))
got = mod.started_hold_reason(started(24 * 30), NOW, trees)
check(got == "", "closed and merged PRs and a non-PR attachment do not hold it", got)

mod = with_recorder(Recorder(attachments=[
    {"url": "https://github.com/x/r/pull/7", "metadata": {"status": "draft"}}]))
got = mod.started_hold_reason(started(24 * 30), NOW, trees)
check("open PR https://github.com/x/r/pull/7 on an unknown branch" in got, "an unknown status on an unknown branch holds it (fail closed)", got)

mod = with_recorder(Recorder(fail_attachments=True))
got = mod.started_hold_reason(started(24 * 30), NOW, trees)
check("could not be read" in got, "an unreadable PR list holds it", got)

# Claims, in the shape linear-claim.py writes, at the path the worker claims in.
mod = with_recorder(Recorder())
claim_dir = os.path.join(trees, "worktrees", "ask-1")
os.makedirs(claim_dir)
claim = os.path.join(claim_dir, ".linear-claims.json")
dead = subprocess.Popen(["true"])
dead.wait()
for label, body, want in [
    ("a live holder holds it", {"agent": "sana", "session": "s1", "holder_pid": os.getpid()},
     "a live claim by sana"),
    ("a dead holder does not", {"agent": "sana", "session": "s1", "holder_pid": dead.pid}, ""),
    ("a claim with no holder pid is respected", {"agent": "sana", "session": "s1"},
     "a live claim by sana"),
]:
    with open(claim, "w") as fh:
        json.dump(body, fh)
    got = mod.started_hold_reason(started(24 * 30), NOW, trees)
    if (want == "" and got == "") or (want and want in got):
        ok(f"claim: {label} -> {got or 'eligible'}")
    else:
        bad(f"claim: {label}", f"got {got!r}")
with open(claim, "w") as fh:
    fh.write("{not json")
got = mod.started_hold_reason(started(24 * 30), NOW, trees)
check("not valid JSON" in got, "a corrupt claim file holds it (fail closed)", got)
with open(claim, "w") as fh:
    fh.write("")
got = mod.started_hold_reason(started(24 * 30), NOW, trees)
check(got == "", "an empty claim file (a released claim) does not", got)

print("== worker history (the positive release signal)")
mod = with_recorder(Recorder())
os.remove(claim)
got = mod.started_hold_reason(started(24 * 30, ident="ASK-2"), NOW, trees)
check("no worker history" in got,
      "a month-old started ticket the fleet never ran is held (a lane or a person started it)", got)
empty_state = tempfile.mkdtemp()
got = mod.started_hold_reason(started(24 * 30), NOW, empty_state)
check("no attempts ledger here" in got, "no ledger file proves nothing, so it holds", got)
with open(LEDGER, "w") as fh:
    fh.write("{torn")
got = mod.started_hold_reason(started(24 * 30), NOW, trees)
check("unreadable" in got, "a corrupt ledger holds it (fail closed)", got)
with open(LEDGER, "w") as fh:
    json.dump({"ASK-1": {}}, fh)
got = mod.started_hold_reason(started(24 * 30), NOW, trees)
check("no worker history" in got, "an empty row is no history", got)
with open(LEDGER, "w") as fh:
    json.dump({"ASK-1": {"rounds": 1}}, fh)
got = mod.started_hold_reason(started(24 * 30), NOW, trees)
check(got == "", "with a row back, the same ticket is released", got)

print("== negative self-test")
src = open(SYNC).read()
anchor = '''    if (state.get("type") or "") != "started":
        return "unchanged",'''
if anchor not in src:
    bad("mutation anchor present", "the started-state check moved; update this self-test")
else:
    mut_path = os.path.join(tempfile.mkdtemp(), "linear-sync.py")
    with open(mut_path, "w") as fh:
        fh.write(src.replace(anchor, '''    if False:
        return "unchanged",'''))
    rec = Recorder(state="completed")
    outcome, _ = with_recorder(rec, load(mut_path, "ls_requeue_mutant")).requeue_issue("ASK-1", "cap")
    if outcome == "moved" and rec.mutations:
        ok("mutant killed: without the started check a Done issue is moved, so the case above can fail")
    else:
        bad("mutant survived", f"{outcome} {rec.mutations}")

print()
print(f"  {PASS} passed, {FAIL} failed")
sys.exit(0 if FAIL == 0 else 1)
