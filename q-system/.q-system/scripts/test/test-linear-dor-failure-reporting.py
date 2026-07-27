#!/usr/bin/env python3
"""Test paired with the linear-dor-drafter.py script: its failures reach Linear.

This test is the executable check for ASK-183 bar 2 of the job-migration
standard: "failures and findings reach Linear, not only a log."

The drafter script returns 0 on every path so launchd does not mark the job
failed. That also means launchd-health-check.py, which keys on a non-zero
LastExitStatus, sees nothing here. Every failure the script can have (no claude
binary, unusable model output, a Linear write refused, Linear unreachable) went to
stderr and stopped at ~/.config/kipi/linear-dor.err -- a file that did not exist
on 2026-07-26, because the script had never once run under its own scheduler.

The executable blocker for that gap is report_failures() in linear-dor-drafter.py
plus this test file, registered in capability-manifest.json so capability-gate.py
runs it. The checks below are the blocker: the report reaches Linear, one permanent
issue takes a comment per failing run instead of forking, a CLOSED permanent issue
is reopened rather than commented into the void, an unreachable Linear pings the
founder and carries the failures to the next run, and every distinct root cause
arrives as a distinct line.

Hermetic by construction: no check reads where `claude` happens to live on the
host, no check touches the live state file or the live ledger. A unit test that
asserts the environment goes red on a healthy machine (PR #12 review, minor 3).

Run: python3 test-linear-dor-failure-reporting.py   (exit 0 = pass)
"""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

DRAFTER = Path(__file__).resolve().parents[1] / "linear-dor-drafter.py"
_spec = importlib.util.spec_from_file_location("dor", DRAFTER)
dor = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dor)

failures = []


def check(name, got, want):
    if got != want:
        failures.append(f"{name}: got {got!r}, want {want!r}")
    else:
        print(f"  ok: {name}")


class FakeLinear:
    """Stands in for linear-sync.py. Records every write it is asked to make.

    `issue_state` is the state TYPE the permanent failure issue is in remotely
    ("backlog" / "started" / "completed" / "canceled"), or None to model an issue
    that no longer exists. fetch_remote_state cannot report it -- its query filters
    on project and does not select state -- so the drafter has to ask separately,
    and this fake is the thing that answers.
    """

    ISSUE_CREATE = "mutation issueCreate"
    COMMENT_CREATE = "mutation commentCreate"

    def __init__(self, existing_keys=None, unreachable=False,
                 report_unreachable=False, issue_state="started",
                 reopen_succeeds=True, draftable=()):
        self.existing_keys = existing_keys or {}
        self.unreachable = unreachable
        self.report_unreachable = report_unreachable
        self.issue_state = issue_state
        self.reopen_succeeds = reopen_succeeds
        self.draftable = list(draftable)
        self.created = []
        self.comments = []
        self.state_moves = []
        self.ledger_appends = []

    # -- the surface linear-dor-drafter.py uses -----------------------------
    def graphql(self, query, variables):
        if self.unreachable:
            raise RuntimeError("network: connection refused")
        if "teams(" in query:
            return {"teams": {"nodes": [{"id": "team-1"}]}}
        if "states(" in query:
            return {"team": {"states": {"nodes": [
                {"id": "st-done", "name": "Done", "type": "completed", "position": 4},
                {"id": "st-todo", "name": "Todo", "type": "unstarted", "position": 2},
                {"id": "st-backlog", "name": "Backlog", "type": "backlog", "position": 1},
            ]}}}
        if "issues(" in query:
            return {"issues": {"nodes": self.draftable,
                               "pageInfo": {"hasNextPage": False}}}
        if "issue(id:" in query.replace(" ", ""):
            if self.issue_state is None:
                return {"issue": None}
            return {"issue": {"id": "iss-1", "identifier": "ASK-999",
                              "state": {"name": "x", "type": self.issue_state}}}
        if "stateId" in query:
            self.state_moves.append(variables)
            return {"issueUpdate": {"success": self.reopen_succeeds}}
        if query is self.ISSUE_CREATE:
            self.created.append(variables["input"])
            return {"issueCreate": {"issue": {"id": "iss-1", "identifier": "ASK-999"}}}
        if query is self.COMMENT_CREATE:
            self.comments.append(variables["input"])
            return {"commentCreate": {"comment": {"id": "c-1"}}}
        if "IssueUpdateInput" in query:
            return {"issueUpdate": {"success": True, "issue": {"identifier": "ASK-1"}}}
        raise AssertionError(f"unexpected query: {query[:60]}")

    def fetch_remote_state(self, team_key, repo):
        if self.unreachable or self.report_unreachable:
            raise RuntimeError("network: connection refused")
        return "team-1", {"id": "proj-1"}, dict(self.existing_keys)

    def read_ledger(self):
        return {}

    def append_ledger(self, records):
        self.ledger_appends.extend(records)
        return len(records)


CLOSED_KEY = {dor.FAILURE_KEY: {"linear_id": "iss-1", "identifier": "ASK-999"}}
FAILS = ["ASK-1: claude call failed (TimeoutExpired after 5s)",
         "ASK-2: claude exited rc=1 with 0 chars of output"]

SANDBOX = Path(tempfile.mkdtemp(prefix="linear-dor-test-"))

# Every founder ping in this file goes through the real subprocess call the
# drafter makes -- a stub on dor.notify would prove the drafter has a function,
# not that the ping leaves the process. This script stands in for
# slack-notify.sh and records what it was handed.
PINGS = SANDBOX / "pings.txt"
_ping_script = SANDBOX / "fake-slack-notify.sh"
_ping_script.write_text(f'printf "%s\\n" "$1" >> {PINGS}\n')
_ping_script.chmod(0o755)
dor.NOTIFY_SCRIPT = _ping_script


def pings():
    return PINGS.read_text().splitlines() if PINGS.exists() else []


# --- the launchd-PATH regression -------------------------------------------
# 2026-07-27, first real kickstart of com.kipi.linear-dor: 8 of 8 drafts died on
# FileNotFoundError while launchd recorded LastExitStatus=0. The plist runs
# `/bin/bash -lc`; `-l` sources BASH login files, the founder's shell is zsh, so
# ~/.local/bin never entered PATH. Interactive runs inherited PATH and passed.
# claude_binary() resolves the binary instead of trusting the scheduler.
#
# These checks use a binary this test PLANTS. Asserting the host's own install
# location was the bug in the first version: any claude installed via nvm/volta/
# asdf failed a check about code that was fine (PR #12 review, minor 3).
_fake_bin = SANDBOX / "claude"
_fake_bin.write_text("exit 0\n")
_fake_bin.chmod(0o755)
_not_executable = SANDBOX / "claude-not-exec"
_not_executable.write_text("exit 0\n")
_not_executable.chmod(0o644)

_real_which, _real_fallbacks = dor.shutil.which, dor.CLAUDE_FALLBACKS
try:
    # An empty PATH is what launchd effectively handed it. The fallbacks carry it.
    dor.shutil.which = lambda _name: None
    dor.CLAUDE_FALLBACKS = (_fake_bin,)
    check("with PATH blind, the fallbacks still find it", dor.claude_binary(), str(_fake_bin))

    # The escape hatch for an install outside the hardcoded list (nvm, volta, asdf).
    os.environ[dor.CLAUDE_BIN_ENV] = str(_fake_bin)
    dor.CLAUDE_FALLBACKS = (Path("/nonexistent/claude"),)
    check("the env override resolves an install the list never heard of",
          dor.claude_binary(), str(_fake_bin))

    os.environ[dor.CLAUDE_BIN_ENV] = str(_not_executable)
    check("a non-executable override is ignored, not returned",
          dor.claude_binary(), None)
    os.environ.pop(dor.CLAUDE_BIN_ENV)

    # And with nothing anywhere, a draft is a reported failure, never a crash.
    _body, _reason = dor.draft_one({"identifier": "ASK-1", "title": "t", "description": ""}, 5)
    check("no binary anywhere is a clean None, not an exception", _body, None)
    check("...and the reason names the missing binary",
          "no claude binary" in _reason, True)
finally:
    dor.shutil.which, dor.CLAUDE_FALLBACKS = _real_which, _real_fallbacks
    os.environ.pop(dor.CLAUDE_BIN_ENV, None)

# --- one cause per line: four root causes must not collapse into one --------
# PR #12 review, minor 4: every failure reached Linear as the identical string
# "draft failed (claude call or output rejected)", so the operator got a count
# and never a cause. The FileNotFoundError this whole PR exists because of was
# indistinguishable from a timeout.
_good_dor = ("- **Outcome:** x\n- **Files:** y\n- **Check:** z\n"
             "- **Blast radius:** w\n- **Not doing:** v\n\n**Energy:** Admin · **Time Est:** 30 min")


class _Res:
    def __init__(self, rc, out):
        self.returncode, self.stdout, self.stderr = rc, out, ""


_real_run = dor.subprocess.run
_reasons = []
try:
    dor.shutil.which = lambda _name: str(_fake_bin)
    _issue = {"identifier": "ASK-1", "title": "t", "description": ""}

    def _raises(*_a, **_k):
        raise subprocess.TimeoutExpired(cmd="claude", timeout=5)

    dor.subprocess.run = _raises
    _reasons.append(dor.draft_one(_issue, 5)[1])

    dor.subprocess.run = lambda *_a, **_k: _Res(1, "")
    _reasons.append(dor.draft_one(_issue, 5)[1])

    dor.subprocess.run = lambda *_a, **_k: _Res(0, "the model wrote prose instead " * 5)
    _reasons.append(dor.draft_one(_issue, 5)[1])

    dor.subprocess.run = lambda *_a, **_k: _Res(0, _good_dor)
    _ok_body, _ok_reason = dor.draft_one(_issue, 5)
finally:
    dor.subprocess.run = _real_run
    dor.shutil.which = _real_which

check("a timeout names itself", "TimeoutExpired" in _reasons[0], True)
check("a non-zero exit names its code", "rc=1" in _reasons[1], True)
check("a rejected body says what was missing", "Energy" in _reasons[2], True)
check("three distinct causes produce three distinct lines", len(set(_reasons)), 3)
check("a good draft returns a body and no reason", (bool(_ok_body), _ok_reason),
      (True, ""))

# --- THE RULE: a run with failures files them to Linear ---------------------
ls = FakeLinear()
check("a failing run creates one issue", dor.report_failures(ls, FAILS), "created")
check("exactly one issue was created", len(ls.created), 1)
check(
    "the issue carries the dedup key",
    f"<!-- kipi-key: {dor.FAILURE_KEY} -->" in ls.created[0]["description"],
    True,
)
check(
    "the issue body names the real failures",
    all(f in ls.created[0]["description"] for f in FAILS),
    True,
)
check("the create is recorded in the ledger", len(ls.ledger_appends), 1)

# --- no fork: the second failing run comments, never creates again ----------
ls = FakeLinear(existing_keys=CLOSED_KEY, issue_state="started")
check("a recurrence comments instead", dor.report_failures(ls, FAILS), "commented")
check("no second issue is created", len(ls.created), 0)
check("one comment was posted", len(ls.comments), 1)
check("an open issue is left alone", len(ls.state_moves), 0)
check(
    "the comment names the real failures",
    all(f in ls.comments[0]["body"] for f in FAILS),
    True,
)

# --- THE DETECTOR MUST NOT SWITCH ITSELF OFF --------------------------------
# PR #12 review, major 1: the dedup key survives the issue being closed, and
# fetch_remote_state cannot see state. So the first time the operator did the
# right thing -- fix the cause, close the issue -- every later failing night
# became a comment on a Done issue. Nothing open on the board, forever.
for closed in ("completed", "canceled"):
    ls = FakeLinear(existing_keys=CLOSED_KEY, issue_state=closed)
    check(f"a {closed} issue is reopened, not commented into the void",
          dor.report_failures(ls, FAILS), "reopened")
    check(f"...the {closed} issue was actually moved", len(ls.state_moves), 1)
    check(f"...to an open state, not any state ({closed})",
          ls.state_moves[0].get("s") in ("st-todo", "st-backlog"), True)
    check(f"...and the failures still landed on it ({closed})", len(ls.comments), 1)

ls = FakeLinear(existing_keys=CLOSED_KEY, issue_state="completed", reopen_succeeds=False)
_before = len(pings())
check("a reopen Linear refuses is reported as such, not as success",
      dor.report_failures(ls, FAILS), "reopen-failed")
check("...the detail still reaches the issue", len(ls.comments), 1)
check("...and the founder is told the board has nothing open",
      len(pings()) > _before, True)

# A ledger entry pointing at an issue that no longer exists must not be a dead
# end: file a fresh one rather than commenting into a 404.
ls = FakeLinear(existing_keys=CLOSED_KEY, issue_state=None)
check("a vanished issue is replaced, not commented on",
      dor.report_failures(ls, FAILS), "created")
check("...exactly one replacement", len(ls.created), 1)

# --- a clean run reports nothing -------------------------------------------
ls = FakeLinear()
check("a clean run files nothing", dor.report_failures(ls, []), "none")
check("no writes on a clean run", (len(ls.created), len(ls.comments)), (0, 0))

# --- the reporter must never become the failure -----------------------------
ls = FakeLinear(unreachable=True)
_before = len(pings())
try:
    verdict = dor.report_failures(ls, FAILS)
except Exception as exc:  # noqa: BLE001 - that is exactly the bug under test
    verdict = f"RAISED {type(exc).__name__}"
check("an unreachable Linear is swallowed, not raised", verdict, "unreachable")
check("...and it is not silent: the founder gets the one ping", len(pings()), _before + 1)
check("...the ping carries the count", "2 failure" in pings()[-1], True)

# --- WIRING: main() must actually call it on a run where drafts fail --------
# The helper existing is not the contract. The contract is that a real nightly
# run in which every draft fails ends with those failures on the Linear issue.
DRAFTABLE = [{"id": "x", "identifier": "ASK-1", "title": "t", "description": "",
              "project": None, "state": {"name": "Backlog", "type": "backlog"}}]
STATE_FILE = SANDBOX / "state.json"

_real_linear, _real_draft, _real_argv = dor._linear, dor.draft_one, sys.argv
_real_state, _real_fetch = dor.STATE, dor.fetch_draftable


def run_main(fake, draftable, reason="claude call failed (TimeoutExpired after 300s)"):
    global dor
    dor.STATE = STATE_FILE
    dor._linear = lambda: fake
    dor.draft_one = lambda issue, timeout: (None, reason)  # noqa: ARG005
    dor.fetch_draftable = lambda ls_, tid: list(draftable)  # noqa: ARG005
    sys.argv = ["linear-dor-drafter.py", "--limit", "1", "--apply"]
    return dor.main()


try:
    wired = FakeLinear()
    rc = run_main(wired, DRAFTABLE)
    check("main() still exits 0 for launchd", rc, 0)
    check("main() filed the failing run to Linear", len(wired.created), 1)
    check(
        "the filed issue names the failed identifier",
        "ASK-1" in (wired.created[0]["description"] if wired.created else ""),
        True,
    )
    check(
        "the filed issue names the CAUSE, not just the count",
        "TimeoutExpired" in (wired.created[0]["description"] if wired.created else ""),
        True,
    )

    # --- the failures survive a night when Linear is down -------------------
    # PR #12 review, major 2: the failure list was dropped to stderr, the run
    # exited 0, and the only record was a state file with no reader anywhere in
    # the repo. Now the state file IS read -- by the next run.
    STATE_FILE.unlink(missing_ok=True)
    down = FakeLinear(report_unreachable=True)
    _before = len(pings())
    rc = run_main(down, DRAFTABLE)
    saved = json.loads(STATE_FILE.read_text())
    check("a night Linear is down still exits 0", rc, 0)
    check("...the founder is pinged", len(pings()), _before + 1)
    check("...the unfiled failures are held, not dropped",
          len(saved.get("pending_failures") or []), 1)
    check("...and the held failure keeps its cause",
          "TimeoutExpired" in (saved.get("pending_failures") or [""])[0], True)

    # Next night: nothing new fails, and the held failure still reaches Linear.
    back_up = FakeLinear()
    rc = run_main(back_up, [])
    saved = json.loads(STATE_FILE.read_text())
    check("the next run files what the down night could not", len(back_up.created), 1)
    check("...naming the issue from the earlier run",
          "ASK-1" in back_up.created[0]["description"], True)
    check("...marked as carried so the report does not lie about when it happened",
          "carried" in back_up.created[0]["description"], True)
    check("...and the queue is cleared once it lands",
          saved.get("pending_failures"), [])
finally:
    dor._linear, dor.draft_one, sys.argv = _real_linear, _real_draft, _real_argv
    dor.STATE, dor.fetch_draftable = _real_state, _real_fetch

if failures:
    print("\nFAIL:")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("\nall linear-dor failure-reporting checks passed")
