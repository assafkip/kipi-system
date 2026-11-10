#!/usr/bin/env python3
"""Contract test for `linear-sync.py delegate` -- the verb that hands an issue to
the NATIVE Codex Linear agent instead of shelling a local reviewer (ASK-253).

WHY THIS EXISTS: the founder installed the Codex Linear agent on 2026-07-29 to
review Sana's work inside the issue. Per Linear's docs, an agent is given work by
DELEGATION, not assignment -- the human assignee stays the owner. Delegation was
proven by hand once (ASK-221, `delegateId: b2f81d11-...`); a verb makes it
repeatable. Nothing calls this verb yet, by design: the gate/verdict question for
`converge.sh` is a separate decision, so no paid agent session can be triggered
from here.

THE DEFECT CLASS THIS TEST IS BUILT AROUND is not "does the happy path work". It
is a mutation whose result is DISCARDED, so a rejected write still reports
success -- the `commentCreate` bug Codex found in this same file on 2026-07-29,
and `sp-8f879dc5` (slack-notify.sh always exits 0) before it. A delegate verb
with that bug tells the loop the reviewer was engaged while the issue sits
undelegated and nobody reviews anything. So every failure mode below asserts
non-zero AND the word BLOCK, never just the absence of a crash.

NO LIVE LINEAR. `graphql` is monkeypatched on the loaded module, so nothing here
touches the network, spends an AI credit, or mutates a permanent Linear object. A
test that delegates a real issue cannot be undone and would start a paid coding
session; that is a hard rule in this repo, not a nicety.

OBSERVED RED, not assumed. This file was written and run BEFORE cmd_delegate
existed, on branch sana/ask-253 at base eac5b667:

  FAIL: linear-sync.py has no cmd_delegate ... (exit 1)

The ref loader below is the same mechanism `test_linear_sync_comments.py` uses
(`KIPI_TEST_LINEAR_SYNC_REF=<git-ref>` loads linear-sync.py from that ref instead
of the working tree) and it keeps that RED reproducible after the fix lands:
`KIPI_TEST_LINEAR_SYNC_REF=eac5b667` must fail. It was NOT exercised in the run
that shipped this file -- the dispatch runner refuses an env-prefixed Bash
command -- so read it as the sibling's proven loader, not as a result measured
here.
"""
import contextlib
import importlib.util
import io
import os
import pathlib
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
_REF = os.environ.get("KIPI_TEST_LINEAR_SYNC_REF", "").strip()
if _REF:
    # Read-only: `git show` to a temp file. The working tree is never touched, so
    # this cannot disturb a session running in the same checkout.
    _repo = HERE.parents[2]
    _blob = subprocess.run(
        ["git", "-C", str(_repo), "show",
         f"{_REF}:q-system/.q-system/scripts/linear-sync.py"],
        capture_output=True, text=True)
    if _blob.returncode != 0:
        print(f"FAIL: cannot read linear-sync.py at ref {_REF}: {_blob.stderr.strip()}")
        sys.exit(1)
    _tmp = pathlib.Path(tempfile.mkdtemp()) / "linear-sync.py"
    _tmp.write_text(_blob.stdout)
    TARGET = _tmp
    print(f"module under test: ref {_REF} ({len(_blob.stdout.splitlines())} lines)")
else:
    TARGET = HERE / "linear-sync.py"

FAILURES = []
PASSES = []

# The real id, recorded on ASK-253 from the by-hand proof and re-read live from
# the schema probe on 2026-11-10. A made-up uuid here would let a verb that
# echoes back whatever it was handed pass the echo check (fixtures-from-producers).
CODEX_ID = "b2f81d11-5aa9-4989-bb7d-53ad90928236"
SANA_ID = "819c9810-0561-46c1-8ff0-8e402fe56d7e"

# Shape copied from the live `users` query, not invented: agents are ordinary
# User rows carrying `app: true`, and the humans in the workspace come back in
# the same list. `app` is what separates an agent from a person.
USERS_PAYLOAD = {"users": {"nodes": [
    {"id": CODEX_ID, "name": "Codex", "displayName": "codex",
     "active": True, "app": True},
    {"id": SANA_ID, "name": "Sana", "displayName": "sana",
     "active": True, "app": True},
    {"id": "d864082f-d345-42c2-82cf-c8f586af9f70", "name": "Linear",
     "displayName": "linear", "active": True, "app": True},
    {"id": "human-1", "name": "Assaf Kipnis", "displayName": "assaf",
     "active": True, "app": False},
]}}

ISSUE_PAYLOAD = {"issue": {"id": "uuid-1", "identifier": "ASK-253",
                           "title": "delegate to the native Codex agent",
                           "state": {"name": "Todo", "type": "unstarted"}}}


def ok(msg):
    PASSES.append(msg)
    print(f"  PASS {msg}")


def fail(msg):
    FAILURES.append(msg)
    print(f"  FAIL {msg}")


def load_module():
    """Load linear-sync.py by path. The filename has a hyphen, so `import` cannot
    reach it and importlib is the only way in."""
    spec = importlib.util.spec_from_file_location("linear_sync_under_test", TARGET)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Args:
    def __init__(self, issue="ASK-253", agent=None, clear=False):
        self.issue = issue
        self.agent = agent
        self.clear = clear


class Stub:
    """A graphql stub that RECORDS every call, so "sent no mutation" is an
    assertion against a call log rather than a hope. `update` is the payload the
    issueUpdate mutation returns; `raise_exc` makes the call raise instead."""

    def __init__(self, update=None, raise_exc=None, raise_on="issueUpdate"):
        self.calls = []
        self.update = update
        self.raise_exc = raise_exc
        self.raise_on = raise_on

    def __call__(self, query, variables):
        self.calls.append((query, variables))
        if self.raise_exc and self.raise_on in query:
            raise self.raise_exc
        if "issueUpdate" in query:
            return self.update
        if "users" in query:
            return USERS_PAYLOAD
        return ISSUE_PAYLOAD

    def mutations(self):
        return [(q, v) for q, v in self.calls if "issueUpdate" in q]


def ok_update(delegate):
    """What Linear returns on an accepted delegate write: success PLUS the issue's
    resulting delegate. The verb verifies that echo instead of trusting `success`,
    which is the only way it can tell a real write from an accepted no-op."""
    return {"issueUpdate": {"success": True,
                            "issue": {"id": "uuid-1", "identifier": "ASK-253",
                                      "delegate": delegate}}}


def run(mod, args, stub):
    mod.graphql = stub
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = mod.cmd_delegate(args)
    return rc, out.getvalue(), err.getvalue()


def main():
    if not TARGET.exists():
        print(f"FAIL: {TARGET} does not exist")
        return 1
    mod = load_module()

    if not hasattr(mod, "cmd_delegate"):
        print("FAIL: linear-sync.py has no cmd_delegate. Delegation to the native "
              "Codex Linear agent was proven by hand on 2026-07-29 and has no "
              "repeatable caller, so every review hand-off is a manual MCP call.")
        return 1
    ok("linear-sync.py exposes cmd_delegate")

    # --- DoR check 2: a stubbed success delegates and PRINTS the resolved id ----
    # The id is the output that matters. A line saying "delegated" with no id
    # cannot be checked against the agent the founder actually installed.
    stub = Stub(update=ok_update({"id": CODEX_ID, "name": "Codex"}))
    rc, out, err = run(mod, Args(agent="Codex"), stub)
    if rc != 0:
        fail(f"delegate --agent Codex exited {rc}, expected 0. stderr:\n{err}")
    elif CODEX_ID not in out:
        fail(f"delegate did not print the resolved delegate id. Got:\n{out}")
    else:
        ok("delegate --agent Codex exits 0 and prints the resolved delegate id")

    muts = stub.mutations()
    if len(muts) != 1:
        fail(f"expected exactly 1 issueUpdate, saw {len(muts)}")
    elif (muts[0][1].get("input") or {}).get("delegateId") != CODEX_ID:
        fail("the mutation did not carry the resolved delegateId. Sent: "
             f"{muts[0][1]}")
    else:
        ok("the mutation carries delegateId, the field the live schema declares")

    # --- the agent name is matched case-insensitively on name OR displayName ---
    # The founder types what he sees in Linear. `codex` and `Codex` are the same
    # agent, and a verb that refuses one of them is a verb nobody uses.
    stub = Stub(update=ok_update({"id": CODEX_ID, "name": "Codex"}))
    rc, out, _ = run(mod, Args(agent="codex"), stub)
    if rc != 0 or CODEX_ID not in out:
        fail(f"--agent codex (lowercase displayName) did not resolve. rc={rc} out:\n{out}")
    else:
        ok("--agent matches name or displayName, case-insensitively")

    # --- DoR check 3: --clear sends a NULL delegate ----------------------------
    # Asserted on the payload, not on the printed line: "cleared" is easy to
    # print and the only proof is what went over the wire.
    stub = Stub(update=ok_update(None))
    rc, out, err = run(mod, Args(clear=True), stub)
    if rc != 0:
        fail(f"delegate --clear exited {rc}, expected 0. stderr:\n{err}")
    else:
        ok("delegate --clear exits 0")
    muts = stub.mutations()
    if len(muts) != 1:
        fail(f"--clear sent {len(muts)} mutations, expected 1")
    else:
        sent = (muts[0][1].get("input") or {})
        if "delegateId" not in sent:
            fail(f"--clear omitted delegateId entirely, so Linear changes nothing "
                 f"and the issue stays delegated. Sent: {sent}")
        elif sent["delegateId"] is not None:
            fail(f"--clear sent a non-null delegateId: {sent}")
        else:
            ok("--clear sends delegateId: null")

    # --- DoR check 4a: success:false BLOCKS -----------------------------------
    # The commentCreate defect class. A rejected write that exits 0 tells the loop
    # the reviewer was engaged while the issue sits undelegated.
    stub = Stub(update={"issueUpdate": {"success": False, "issue": None}})
    rc, out, err = run(mod, Args(agent="Codex"), stub)
    if rc == 0:
        fail("a REJECTED issueUpdate exited 0, so a dropped delegation is "
             "indistinguishable from a delivered one")
    elif "BLOCK" not in err:
        fail(f"a rejected mutation did not say BLOCK. stderr:\n{err}")
    elif "delegated to" in out:
        fail(f"a rejected mutation still printed success. stdout:\n{out}")
    else:
        ok("a rejected issueUpdate BLOCKs and exits non-zero")

    # --- DoR check 4b: GraphQL errors BLOCK -----------------------------------
    stub = Stub(raise_exc=mod.LinearAPIError("delegateId is not a valid agent"))
    rc, out, err = run(mod, Args(agent="Codex"), stub)
    if rc == 0:
        fail("a Linear API error on the mutation exited 0")
    elif "BLOCK" not in err:
        fail(f"a Linear API error did not say BLOCK. stderr:\n{err}")
    else:
        ok("a GraphQL error on the mutation BLOCKs and exits non-zero")

    # --- an API error on the READ also BLOCKs, before any write ---------------
    stub = Stub(raise_exc=mod.LinearAPIError("rate limited"), raise_on="issue(")
    rc, out, err = run(mod, Args(agent="Codex"), stub)
    if rc == 0:
        fail("a failed issue read exited 0")
    elif stub.mutations():
        fail("a failed issue read still sent a mutation")
    else:
        ok("a failed issue read BLOCKs before any mutation")

    # --- a missing issue BLOCKs ----------------------------------------------
    class NoIssue(Stub):
        def __call__(self, query, variables):
            self.calls.append((query, variables))
            if "users" in query:
                return USERS_PAYLOAD
            if "issueUpdate" in query:
                return self.update
            return {"issue": None}

    stub = NoIssue()
    rc, out, err = run(mod, Args(agent="Codex"), stub)
    if rc == 0:
        fail("delegating a non-existent issue exited 0")
    elif "BLOCK" not in err:
        fail(f"a missing issue did not say BLOCK. stderr:\n{err}")
    elif stub.mutations():
        fail("a missing issue still sent a mutation")
    else:
        ok("a missing issue BLOCKs and sends no mutation")

    # --- DoR check 5: an unknown agent BLOCKs and sends NO mutation -----------
    # Asserted on the call log. The cost of getting this wrong is not a wrong
    # label: `issueUpdate` with a bad delegateId is a write, and a write that
    # lands on the wrong identity is what starts a paid session for the wrong
    # agent. Refusing BEFORE the write is the whole point.
    stub = Stub(update=ok_update({"id": "whatever", "name": "Whatever"}))
    rc, out, err = run(mod, Args(agent="Clawed"), stub)
    if rc == 0:
        fail("an unknown agent name exited 0")
    elif "BLOCK" not in err:
        fail(f"an unknown agent name did not say BLOCK. stderr:\n{err}")
    elif stub.mutations():
        fail(f"an unknown agent name still sent a mutation: {stub.mutations()}")
    else:
        ok("an unknown agent name BLOCKs and sends no mutation")

    # --- the refusal NAMES the agents that do exist --------------------------
    # A bare "unknown agent" leaves the caller guessing at a name it cannot see.
    if "Codex" not in err or "Sana" not in err:
        fail(f"the unknown-agent refusal does not list the available agents, so the "
             f"caller cannot fix the call. stderr:\n{err}")
    else:
        ok("the unknown-agent refusal lists the agents that do exist")

    # --- a HUMAN is not a delegate -------------------------------------------
    # `delegate` is Linear's agent hand-off; a person gets an assignee. Resolving
    # a human here would delegate an issue to someone who cannot act on it and
    # looks, on the board, exactly like a review that was requested.
    stub = Stub(update=ok_update({"id": "human-1", "name": "Assaf Kipnis"}))
    rc, out, err = run(mod, Args(agent="Assaf Kipnis"), stub)
    if rc == 0:
        fail("delegating to a HUMAN exited 0. delegate is the agent hand-off; a "
             "person gets an assignee, and a human delegate is a review nobody runs")
    elif stub.mutations():
        fail("a human delegate name still sent a mutation")
    else:
        ok("a human (app=false) is not accepted as a delegate")

    # --- success:true but the echo disagrees -> BLOCK -------------------------
    # The subtle half of the discarded-result class: Linear can accept the write
    # and the resulting delegate still not be the one asked for. Trusting
    # `success` alone cannot tell those apart.
    stub = Stub(update=ok_update({"id": SANA_ID, "name": "Sana"}))
    rc, out, err = run(mod, Args(agent="Codex"), stub)
    if rc == 0:
        fail("the mutation reported success while the echoed delegate was a "
             "DIFFERENT agent, and the verb exited 0")
    elif "BLOCK" not in err:
        fail(f"a mismatched delegate echo did not say BLOCK. stderr:\n{err}")
    else:
        ok("a delegate echo that disagrees with the request BLOCKs")

    # --- success:true with no echo at all -> BLOCK ---------------------------
    stub = Stub(update={"issueUpdate": {"success": True, "issue": None}})
    rc, out, err = run(mod, Args(agent="Codex"), stub)
    if rc == 0:
        fail("the mutation reported success with no issue echoed back, and the "
             "verb exited 0")
    elif "BLOCK" not in err:
        fail(f"a missing echo did not say BLOCK. stderr:\n{err}")
    else:
        ok("a success with no echoed issue BLOCKs")

    # --- --clear that did NOT clear -> BLOCK ---------------------------------
    stub = Stub(update=ok_update({"id": CODEX_ID, "name": "Codex"}))
    rc, out, err = run(mod, Args(clear=True), stub)
    if rc == 0:
        fail("--clear reported success while the issue is still delegated")
    elif "BLOCK" not in err:
        fail(f"a --clear that did not clear said no BLOCK. stderr:\n{err}")
    else:
        ok("--clear BLOCKs when the issue comes back still delegated")

    # --- neither --agent nor --clear is a usage refusal ----------------------
    stub = Stub(update=ok_update({"id": CODEX_ID, "name": "Codex"}))
    rc, out, err = run(mod, Args(), stub)
    if rc == 0:
        fail("delegate with neither --agent nor --clear exited 0")
    elif stub.mutations():
        fail("delegate with no target still sent a mutation")
    else:
        ok("delegate with neither --agent nor --clear refuses and sends nothing")

    # --- the verb is REGISTERED on the CLI, not just defined -----------------
    # A cmd_ function nothing routes to is dead code, and the only caller of this
    # verb is a human or a prompt typing the command.
    src = (HERE / "linear-sync.py").read_text()
    if 'add_parser("delegate"' not in src:
        fail("cmd_delegate is defined but never registered with add_parser, so "
             "`linear-sync.py delegate` is not a command")
    elif "func=cmd_delegate" not in src:
        fail("the delegate subparser does not route to cmd_delegate")
    else:
        ok("the delegate verb is registered on the CLI")

    # --- NOTHING calls it yet, which is the issue's blast-radius claim -------
    # The DoR says no caller, so no paid agent session can be started by this
    # change. That claim is checkable, so it is checked rather than asserted in
    # prose: if a future change wires the worker, this line turns red and the
    # wiring issue has to carry its own call-count bound.
    # LINE-level, and comment lines are dropped. A file-level grep red-flagged
    # verify-codex-review-live.sh, whose only hit is a header sentence recording
    # that the delegation path was rejected as a GATE. Prose about the verb is not
    # a caller, and a check that cannot tell those apart gets ignored.
    repo = HERE.parents[2]
    raw = subprocess.run(
        ["git", "-C", str(repo), "grep", "-n", "-e", "linear-sync.py delegate",
         "-e", "cmd_delegate", "--", ".", ":!*test_linear_sync_delegate.py"],
        capture_output=True, text=True).stdout.splitlines()
    unexpected = []
    for line in raw:
        path, _, rest = line.partition(":")
        _, _, text = rest.partition(":")
        if text.lstrip().startswith(("#", "//", "*")):
            continue
        if path.endswith("q-system/.q-system/scripts/linear-sync.py"):
            continue
        unexpected.append(line)
    if unexpected:
        fail("the delegate verb now has callers, so the 'no paid session can be "
             "triggered' blast-radius claim of ASK-253 no longer holds. The wiring "
             f"issue owes a bounded call count. Callers: {unexpected}")
    else:
        ok("no caller invokes delegate yet (ASK-253 blast radius holds)")

    print(f"\n== {len(PASSES)} passed, {len(FAILURES)} failed")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
