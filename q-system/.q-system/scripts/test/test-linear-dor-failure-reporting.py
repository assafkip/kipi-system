#!/usr/bin/env python3
"""Test paired with the linear-dor-drafter.py script: its failures reach Linear.

This test is the executable check for ASK-183 bar 2 of the job-migration
standard: "failures and findings reach Linear, not only a log."

The drafter returns 0 on every path so launchd does not mark the job failed. That
also means launchd-health-check.py, which keys on a non-zero LastExitStatus, sees
nothing here. Its failures (claude unavailable, unusable model output, Linear write
rejected, Linear unreachable) went to stderr and stopped at
~/.config/kipi/linear-dor.err. Observed 2026-07-26: that file did not exist.

The executable blocker for that gap is report_failures() in linear-dor-drafter.py
plus this test file, registered in capability-manifest.json so capability-gate.py
runs it. The checks below are the blocker: the report reaches Linear, one
permanent issue takes a comment per failing run instead of forking, and an
unreachable Linear returns rather than raising.

Run: python3 test-linear-dor-failure-reporting.py   (exit 0 = pass)
"""

import importlib.util
import sys
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
    """Stands in for linear-sync.py. Records every write it is asked to make."""

    ISSUE_CREATE = "mutation issueCreate"
    COMMENT_CREATE = "mutation commentCreate"

    def __init__(self, existing_keys=None, unreachable=False):
        self.existing_keys = existing_keys or {}
        self.unreachable = unreachable
        self.created = []
        self.comments = []
        self.ledger_appends = []

    # -- the surface linear-dor-drafter.py uses -----------------------------
    def graphql(self, query, variables):
        if self.unreachable:
            raise RuntimeError("network: connection refused")
        if "teams(" in query:
            return {"teams": {"nodes": [{"id": "team-1"}]}}
        if "issues(" in query:
            return {"issues": {"nodes": [], "pageInfo": {"hasNextPage": False}}}
        if query is self.ISSUE_CREATE:
            self.created.append(variables["input"])
            return {"issueCreate": {"issue": {"id": "iss-1", "identifier": "ASK-999"}}}
        if query is self.COMMENT_CREATE:
            self.comments.append(variables["input"])
            return {"commentCreate": {"comment": {"id": "c-1"}}}
        if "issueUpdate" in query:
            return {"issueUpdate": {"success": True, "issue": {"identifier": "ASK-1"}}}
        raise AssertionError(f"unexpected query: {query[:60]}")

    def fetch_remote_state(self, team_key, repo):
        if self.unreachable:
            raise RuntimeError("network: connection refused")
        return "team-1", {"id": "proj-1"}, dict(self.existing_keys)

    def read_ledger(self):
        return {}

    def append_ledger(self, records):
        self.ledger_appends.extend(records)
        return len(records)


FAILS = ["ASK-1: claude failed (TimeoutExpired)", "ASK-2: unusable output (rc=1, 0 chars)"]

# --- THE RULE: a run with failures files them to Linear ---------------------
ls = FakeLinear()
check("a failing run creates one issue", dor.report_failures(ls, FAILS, apply=True), "created")
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
ls = FakeLinear(existing_keys={dor.FAILURE_KEY: {"linear_id": "iss-1", "identifier": "ASK-999"}})
check("a recurrence comments instead", dor.report_failures(ls, FAILS, apply=True), "commented")
check("no second issue is created", len(ls.created), 0)
check("one comment was posted", len(ls.comments), 1)
check(
    "the comment names the real failures",
    all(f in ls.comments[0]["body"] for f in FAILS),
    True,
)

# --- a clean run reports nothing -------------------------------------------
ls = FakeLinear()
check("a clean run files nothing", dor.report_failures(ls, [], apply=True), "none")
check("no writes on a clean run", (len(ls.created), len(ls.comments)), (0, 0))

# --- a dry run stays dry ----------------------------------------------------
ls = FakeLinear()
check("without --apply nothing is written", dor.report_failures(ls, FAILS, apply=False), "dry")
check("dry run made no writes", (len(ls.created), len(ls.comments)), (0, 0))

# --- the reporter must never become the failure -----------------------------
ls = FakeLinear(unreachable=True)
try:
    verdict = dor.report_failures(ls, FAILS, apply=True)
except Exception as exc:  # noqa: BLE001 - that is exactly the bug under test
    verdict = f"RAISED {type(exc).__name__}"
check("an unreachable Linear is swallowed, not raised", verdict, "unreachable")

# --- WIRING: main() must actually call it on a run where drafts fail --------
# The helper existing is not the contract. The contract is that a real nightly
# run in which every draft fails ends with those failures on the Linear issue.
wired = FakeLinear()
_real_linear, _real_draft, _real_argv = dor._linear, dor.draft_one, sys.argv
_real_state = dor.STATE
try:
    import tempfile

    tmp = Path(tempfile.mkdtemp()) / "state.json"
    dor.STATE = tmp
    dor._linear = lambda: wired
    dor.draft_one = lambda issue, timeout: None  # every claude call fails
    dor.fetch_draftable = lambda ls_, tid: [  # noqa: ARG005
        {"id": "x", "identifier": "ASK-1", "title": "t", "description": "",
         "project": None, "state": {"name": "Backlog", "type": "backlog"}},
    ]
    sys.argv = ["linear-dor-drafter.py", "--limit", "1", "--apply"]
    rc = dor.main()
finally:
    dor._linear, dor.draft_one, sys.argv = _real_linear, _real_draft, _real_argv
    dor.STATE = _real_state

check("main() still exits 0 for launchd", rc, 0)
check("main() filed the failing run to Linear", len(wired.created), 1)
check(
    "the filed issue names the failed identifier",
    "ASK-1" in (wired.created[0]["description"] if wired.created else ""),
    True,
)

if failures:
    print("\nFAIL:")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("\nall linear-dor failure-reporting checks passed")
