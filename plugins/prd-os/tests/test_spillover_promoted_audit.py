#!/usr/bin/env python3
"""`promoted` stops being an exit that proves nothing. sp-0d76a138.

## The defect

`_spillover_open` filters `status == "open"`, so the moment a row is promoted it
stops blocking `gates run` AND stops blocking archive. `spillover-promote.py`
says in its own docstring that "promoting is not fixing, and a status that
claimed otherwise would let the pile launder itself clean" -- and then nothing
ever re-read the Linear issue. Creating the issue was what cleared the gate. The
one exit that is not evidence-bound was the one that fires automatically.

## What was measured before building this

Run live against Linear, 2026-08-17, all 17 promoted rows:

    WOULD RESOLVE: 2
      sp-32e6595c  ASK-700
      sp-9633b3e9  ASK-785
    STILL OPEN: 15
      sp-0803593f  ASK-784  ... (state: In Progress)
      sp-174d7fae  ASK-788  ... (state: Backlog)
      ... 13 more, every one Backlog or In Progress
    UNVERIFIABLE: 0

That measurement is why the audit resolves rather than blocks. Flipping
`promoted` back to blocking would have turned the standing gate red on 15 items
at once, and a gate that is red for months teaches everyone to step over it.
The flip is captured as its own item, with this number attached.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
RUNNER = REPO / "plugins" / "prd-os" / "scripts" / "prd_runner.py"

sys.path.insert(0, str(RUNNER.parent))
import prd_runner  # noqa: E402


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    """A ledger of this test's own. Never the repo's."""
    prd = tmp_path / ".prd-os"
    (prd / "issues").mkdir(parents=True)
    (prd / "config.json").write_text(json.dumps({"version": 1}))
    cfg = prd_runner.load_config(tmp_path, strict=False)
    rows = [
        {"id": "sp-closed", "status": "promoted", "linear_ref": "ASK-700",
         "description": "its issue really did close", "severity": "major"},
        {"id": "sp-stillopen", "status": "promoted", "linear_ref": "ASK-780",
         "description": "its issue is sitting in Backlog", "severity": "major"},
        {"id": "sp-noref", "status": "promoted",
         "description": "promoted with no linear_ref at all", "severity": "major"},
        {"id": "sp-untouched", "status": "open",
         "description": "an ordinary open item", "severity": "major"},
    ]
    prd_runner._spillover_path(cfg).parent.mkdir(parents=True, exist_ok=True)
    prd_runner._spillover_path(cfg).write_text("".join(json.dumps(r) + "\n" for r in rows))
    return cfg


def _states(monkeypatch, mapping):
    """Stub the tracker. Replaces the function, so the pytest chokepoint inside
    the real one is replaced with it -- that guard exists for the test that
    FORGETS to stub, not for this one."""
    def fake(identifier):
        if identifier not in mapping:
            raise prd_runner.LinearRefError(f"no such issue {identifier}")
        return mapping[identifier]
    monkeypatch.setattr(prd_runner, "_linear_issue_state", fake)


class Args:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _statuses(cfg):
    return {r["id"]: r.get("status") for r in prd_runner._read_spillover(cfg).values()}


def test_a_promoted_row_whose_issue_closed_is_resolved(ledger, monkeypatch, capsys):
    """FIRES. The whole point: something finally re-checks."""
    _states(monkeypatch, {"ASK-700": {"name": "Done", "type": "completed"},
                          "ASK-780": {"name": "Backlog", "type": "backlog"}})
    assert prd_runner._spillover_promoted_audit(ledger, Args(dry_run=False)) == 0
    assert _statuses(ledger)["sp-closed"] == "resolved"


def test_a_promoted_row_whose_issue_is_still_open_is_left_alone(ledger, monkeypatch):
    """STAYS PUT. The sweep must not launder an item whose work never happened."""
    _states(monkeypatch, {"ASK-700": {"name": "Done", "type": "completed"},
                          "ASK-780": {"name": "Backlog", "type": "backlog"}})
    prd_runner._spillover_promoted_audit(ledger, Args(dry_run=False))
    after = _statuses(ledger)
    assert after["sp-stillopen"] == "promoted"
    assert after["sp-noref"] == "promoted"
    assert after["sp-untouched"] == "open"


def test_a_canceled_issue_never_resolves_an_item(ledger, monkeypatch):
    """A canceled issue shipped NO FIX.

    The nastiest available false positive: `canceled` is a terminal state and
    reads like closure. `_verify_resolution_ref` already refuses it, which is
    exactly why this audit reuses that function instead of asking Linear itself
    whether the issue is 'done'. A second opinion about what closed means is how
    the two answers drift.
    """
    _states(monkeypatch, {"ASK-700": {"name": "Canceled", "type": "canceled"},
                          "ASK-780": {"name": "Backlog", "type": "backlog"}})
    prd_runner._spillover_promoted_audit(ledger, Args(dry_run=False))
    assert _statuses(ledger)["sp-closed"] == "promoted"


def test_an_unreachable_tracker_resolves_nothing(ledger, monkeypatch, capsys):
    """Offline is a REPORT, never a resolution.

    Forced rather than hoped for. An unforced version would pass against a sweep
    that simply found nothing to do.
    """
    def boom(identifier):
        # The PRODUCTION outage type, not an invented one. The first version
        # raised RuntimeError, which only the generic except catches — so the
        # test passed while real outages (LinearUnreachableError from
        # _linear_issue_state's transport handlers) were being filed under
        # STILL OPEN (Codex review PR #213; fixtures-from-producers).
        raise prd_runner.LinearUnreachableError(
            "cannot reach Linear to verify %s: network is down" % identifier)
    monkeypatch.setattr(prd_runner, "_linear_issue_state", boom)
    prd_runner._spillover_promoted_audit(ledger, Args(dry_run=False))
    assert _statuses(ledger)["sp-closed"] == "promoted"
    out = capsys.readouterr().out
    # THREE, not two. The first version of this assertion said two and was
    # wrong: `sp-noref` is unverifiable for its own reason (no linear_ref was
    # ever recorded), independent of the network. Both causes land in the same
    # bucket and both must, because both mean "nothing proved this closed".
    assert "UNVERIFIABLE: 3" in out, out
    assert "tracker unreachable" in out and "no linear_ref recorded" in out
    assert "RESOLVED: 0" in out


def test_dry_run_writes_nothing(ledger, monkeypatch, capsys):
    _states(monkeypatch, {"ASK-700": {"name": "Done", "type": "completed"},
                          "ASK-780": {"name": "Backlog", "type": "backlog"}})
    before = prd_runner._spillover_path(ledger).read_text()
    prd_runner._spillover_promoted_audit(ledger, Args(dry_run=True))
    assert prd_runner._spillover_path(ledger).read_text() == before
    assert "WOULD RESOLVE: 1" in capsys.readouterr().out


def test_the_resolution_records_what_proved_it(ledger, monkeypatch):
    """A resolved row must carry the evidence, not just the verdict.

    The whole complaint about `promoted` was a status that asserted something
    nothing had checked. Replacing it with a `resolved` that asserts something
    nothing recorded would be the same defect one square over.
    """
    _states(monkeypatch, {"ASK-700": {"name": "Done", "type": "completed"},
                          "ASK-780": {"name": "Backlog", "type": "backlog"}})
    prd_runner._spillover_promoted_audit(ledger, Args(dry_run=False))
    rec = prd_runner._read_spillover(ledger)["sp-closed"]
    assert rec["resolution_ref"] == "ASK-700"
    assert rec["resolution_tracker"] == "linear"
    assert rec["resolution_verified_state"] == "Done"
    assert "promoted-audit" in rec["resolution_evidence"]
    assert rec["resolved_at"]


def test_the_linear_call_refuses_to_run_from_inside_a_test():
    """The chokepoint, asserted rather than assumed.

    This audit turns one command into seventeen outbound requests, and adding an
    outbound call to shared code retroactively puts every older suite that
    reaches it on the live path. The failure is invisible while the network
    happens to be up and the token happens to be valid.
    """
    assert os.environ.get("PYTEST_CURRENT_TEST")
    with pytest.raises(prd_runner.LinearRefError, match="from inside a test"):
        prd_runner._linear_issue_state("ASK-1")


def test_the_subcommand_is_reachable_from_the_cli(tmp_path):
    """Wiring, not just a function. A sweep nobody can invoke is not a sweep."""
    prd = tmp_path / ".prd-os"
    (prd / "issues").mkdir(parents=True)
    (prd / "config.json").write_text(json.dumps({"version": 1}))
    (prd / "spillover.jsonl").write_text("")
    out = subprocess.run(
        [sys.executable, str(RUNNER), "--repo-root", str(tmp_path),
         "spillover", "promoted-audit", "--dry-run"],
        capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "promoted rows audited: 0" in out.stdout


def test_an_all_unverifiable_sweep_exits_nonzero(ledger, monkeypatch, capsys):
    """The audit RAN but audited nothing; an unattended job must not report
    success with the tracker fully down (Codex PR #213 r3)."""
    def boom(identifier):
        raise prd_runner.LinearUnreachableError("cannot reach Linear: down")
    monkeypatch.setattr(prd_runner, "_linear_issue_state", boom)
    rc = prd_runner._spillover_promoted_audit(ledger, Args(dry_run=False))
    assert rc == 1
    assert "3 of 3 rows unverifiable" in capsys.readouterr().err


def test_a_partial_outage_exits_nonzero_and_keeps_the_resolved_work(ledger, monkeypatch, capsys):
    """One row resolves, one lookup 500s: the work is kept AND the sweep
    reports its own ill health (Codex PR #213 r5: partial outages returned
    success, so the daily detector discarded unreachable rows)."""
    calls = {}
    def split(identifier):
        calls[identifier] = True
        if identifier == "ASK-780":
            raise prd_runner.LinearUnreachableError("Linear returned HTTP 500")
        return {"name": "Done", "type": "completed"}
    monkeypatch.setattr(prd_runner, "_linear_issue_state", split)
    rc = prd_runner._spillover_promoted_audit(ledger, Args(dry_run=False))
    assert rc == 1
    out = capsys.readouterr()
    assert "transport failure" in out.err
    statuses = _statuses(ledger)
    resolved = [k for k, v in statuses.items() if v == "resolved"]
    assert resolved, "the reachable closed row must still resolve"
