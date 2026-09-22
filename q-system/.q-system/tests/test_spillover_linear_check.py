"""Pins spillover-linear-check.py (ASK-1552): a captured finding cannot sit where
Sana does not see it.

Founder, 2026-09-12: "Backlog where? In linear or is it going to disappear".
Measured that day: `.prd-os/spillover.jsonl` is untracked in git in every repo
that has one and nothing carried it to Linear. These tests pin the daily check
that retries the Linear link for new rows and says so, loudly, when rows stay
unlinked.

Isolation: every ledger is a tmp file, and every Linear write goes through
KIPI_ALERT_CAPTURE (alert-to-linear's own capture hatch), so no test can file a
real ticket. The one test that needs a real `filed ASK-n` line gets it from the
PRODUCER (alert-to-linear.file_alert against a fake Linear client), never from a
string typed here.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
CHECK = SCRIPTS / "spillover-linear-check.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _row(sid: str, created_at: str, status: str = "open", **extra) -> dict:
    rec = {"id": sid, "source": "ASK-1552", "severity": "medium",
           "description": f"finding {sid} needs a Linear issue",
           "status": status, "created_at": created_at, "owner": "sana"}
    rec.update(extra)
    return rec


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    (r / ".prd-os").mkdir(parents=True)
    (r / ".git").mkdir()
    return r


def _seed(repo: Path, rows: list) -> None:
    path = repo / ".prd-os" / "spillover.jsonl"
    with path.open("a") as fh:
        for rec in rows:
            fh.write(json.dumps(rec) + "\n")


def _ledger(repo: Path) -> dict:
    items: dict = {}
    for raw in (repo / ".prd-os" / "spillover.jsonl").read_text().splitlines():
        if raw.strip():
            rec = json.loads(raw)
            items[rec["id"]] = rec
    return items


def _check(repo: Path, capture: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, KIPI_ALERT_CAPTURE=str(capture))
    return subprocess.run([sys.executable, str(CHECK), *args, str(repo)],
                          capture_output=True, text=True, env=env, timeout=120)


def _captured(capture: Path) -> list:
    return capture.read_text().splitlines() if capture.exists() else []


def test_check_files_new_unlinked_rows_and_skips_pre_cutoff(repo, tmp_path):
    _seed(repo, [
        _row("sp-old00001", "2026-01-01T00:00:00Z"),            # pre-existing backlog
        _row("sp-new00001", _now()),
        _row("sp-new00002", _now()),
        _row("sp-done0001", _now(), status="resolved"),         # not open
    ])
    cap = tmp_path / "capture.txt"
    res = _check(repo, cap)
    assert res.returncode == 0, res.stdout + res.stderr

    lines = _captured(cap)
    assert len(lines) == 2, lines
    assert any("sp-new00001" in ln for ln in lines)
    assert any("sp-new00002" in ln for ln in lines)
    assert not any("sp-old00001" in ln for ln in lines), "pre-cutoff row was filed"

    items = _ledger(repo)
    assert items["sp-new00001"]["linear"]["state"] == "captured"
    assert items["sp-new00002"]["linear"]["state"] == "captured"
    assert "linear" not in items["sp-old00001"]
    assert items["sp-done0001"]["status"] == "resolved"
    # The pre-existing backlog is printed as its own number, not folded in.
    assert "pre-existing unlinked backlog" in res.stdout
    assert "pre_cutoff_unlinked=1" in res.stdout


def test_rerun_never_double_files(repo, tmp_path):
    _seed(repo, [_row("sp-new00003", _now())])
    cap = tmp_path / "capture.txt"
    assert _check(repo, cap).returncode == 0
    assert len(_captured(cap)) == 1
    again = _check(repo, cap)
    assert again.returncode == 0
    assert len(_captured(cap)) == 1, "second run filed the same row again"
    assert "filed_now=0" in again.stdout


def test_rows_left_unlinked_raise_exactly_one_summary_alert(repo, tmp_path):
    _seed(repo, [_row(f"sp-lim0000{i}", _now()) for i in range(3)])
    cap = tmp_path / "capture.txt"
    res = _check(repo, cap, "--limit", "1")
    assert res.returncode == 0, res.stdout + res.stderr
    lines = _captured(cap)
    rows_filed = [ln for ln in lines if ln.startswith("spillover sp-")]
    summaries = [ln for ln in lines if ln.startswith("spillover-linear-check:")]
    assert len(rows_filed) == 1
    assert len(summaries) == 1, lines
    assert "still_unlinked=2" in res.stdout

    # Dedup on the Linear side: tomorrow's summary for the SAME condition must
    # carry the same alert-to-linear fingerprint, so it counts on one ticket.
    res2 = _check(repo, cap, "--limit", "1")
    summaries = [ln for ln in _captured(cap) if ln.startswith("spillover-linear-check:")]
    assert len(summaries) == 2
    atl = _load("atl_for_fp", SCRIPTS / "alert-to-linear.py")
    assert atl.fingerprint(summaries[0]) == atl.fingerprint(summaries[1]), res2.stdout


def test_no_summary_alert_when_every_new_row_is_linked(repo, tmp_path):
    """Negative control for the summary test above: without it, a check that
    alerted on every run would pass that test too."""
    _seed(repo, [_row("sp-new00009", _now())])
    cap = tmp_path / "capture.txt"
    assert _check(repo, cap).returncode == 0
    assert not [ln for ln in _captured(cap) if ln.startswith("spillover-linear-check:")]


def test_filer_failure_keeps_rows_marks_retry_and_fails_loudly(repo, tmp_path):
    _seed(repo, [_row("sp-fail0001", _now())])
    cap = tmp_path / "capture-is-a-directory"
    cap.mkdir()  # the filer cannot append to a directory: a real exit 1
    res = _check(repo, cap)
    # The rows could not be filed AND the summary could not be sent: a job
    # that cannot alert must not exit 0 (launchd-health reads the exit code).
    assert res.returncode != 0, res.stdout + res.stderr
    rec = _ledger(repo)["sp-fail0001"]
    assert rec["status"] == "open"
    assert rec["linear"]["state"] == "failed"
    assert rec["linear"]["exit"] == 1

    # Next run with a working filer retries the failed row.
    cap2 = tmp_path / "capture.txt"
    assert _check(repo, cap2).returncode == 0
    assert _ledger(repo)["sp-fail0001"]["linear"]["state"] == "captured"


def test_parser_reads_identifier_from_the_producer_lines(tmp_path, monkeypatch):
    """The `filed ASK-n` and `repeat #n on ASK-n` lines come from alert-to-linear
    itself, run against a fake Linear client, so a format change there turns
    this red instead of silently leaving every row unlinked."""
    atl = _load("atl_producer", SCRIPTS / "alert-to-linear.py")
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from test_alert_to_linear import FakeLinear  # the suite's own fake client

    fake = FakeLinear()
    monkeypatch.setattr(atl, "_state_dir", lambda: str(tmp_path))
    monkeypatch.setattr(atl, "_load_linear", lambda: fake)
    check = _load("slc_parser", CHECK)
    msg = check.message_for(_row("sp-prod0001", _now()))

    code, line = atl.file_alert(msg, now=1000.0)
    link = check.parse_filer_output(code, f"alert-to-linear: {line}\n", "")
    assert link["state"] == "filed" and link["identifier"] == "ASK-101", line

    code, line = atl.file_alert(msg, now=1001.0)
    assert fake.created == 1
    link = check.parse_filer_output(code, f"alert-to-linear: {line}\n", "")
    assert link["state"] == "filed" and link["identifier"] == "ASK-101", line


def test_distinct_rows_never_collapse_into_one_ticket():
    """alert-to-linear strips paths, digits and hex before fingerprinting, so two
    rows whose descriptions differ only by a path would share one ticket. The
    per-row key keeps them apart while a re-file of the SAME row still dedups."""
    atl = _load("atl_fp2", SCRIPTS / "alert-to-linear.py")
    check = _load("slc_fp2", CHECK)
    a = _row("sp-aaaa1111", _now(), description="stale read in q-consult/a.py")
    b = _row("sp-bbbb2222", _now(), description="stale read in q-consult/b.py")
    assert atl.fingerprint(check.message_for(a)) != atl.fingerprint(check.message_for(b))
    assert atl.fingerprint(check.message_for(a)) == atl.fingerprint(check.message_for(dict(a)))


# --- PR #344 review round 1 --------------------------------------------------

def test_check_never_files_a_new_minor_row(repo, tmp_path):
    """F3. Pre-sync instances still write minors; RULE-2026-09-12-A says a minor
    is never queued, so the check counts them and files nothing."""
    _seed(repo, [_row("sp-min00001", _now(), severity="minor"),
                 _row("sp-nit00001", _now(), severity="nit"),
                 _row("sp-med00001", _now(), severity="medium")])
    cap = tmp_path / "capture.txt"
    res = _check(repo, cap)
    assert res.returncode == 0, res.stdout + res.stderr
    lines = _captured(cap)
    assert len(lines) == 1 and "sp-med00001" in lines[0], lines
    assert "new_minor_skipped=2" in res.stdout


def test_check_closes_the_ticket_of_a_row_that_left_the_ledger(repo, tmp_path):
    """F2. A resolved or voided row's capture ticket must not stay open forever."""
    link = {"state": "captured", "identifier": None, "exit": 0, "at": _now()}
    _seed(repo, [_row("sp-void0001", _now(), status="resolved",
                      void_reason="not real after all", linear=link),
                 _row("sp-open0001", _now(), linear=dict(link))])
    cap = tmp_path / "capture.txt"
    res = _check(repo, cap)
    assert res.returncode == 0, res.stdout + res.stderr
    closes = [ln for ln in _captured(cap) if ln.startswith("spillover-close ")]
    assert len(closes) == 1 and "sp-void0001" in closes[0], _captured(cap)
    assert "closed_now=1" in res.stdout
    assert _ledger(repo)["sp-void0001"]["linear"]["closed_at"]
    assert "closed_at" not in _ledger(repo)["sp-open0001"]["linear"]
    # Idempotent: the second run closes nothing.
    again = _check(repo, cap)
    assert len([ln for ln in _captured(cap) if ln.startswith("spillover-close ")]) == 1
    assert "closed_now=0" in again.stdout


class _CloseLinear:
    """Fake linear-sync surface for the close path: one open issue."""

    def __init__(self, state_type="unstarted"):
        self.state_type, self.updates, self.comments = state_type, [], []

    def graphql(self, query, variables):
        if "issueUpdate" in query:
            self.updates.append(variables)
            return {"issueUpdate": {"success": True}}
        if "commentCreate" in query:
            self.comments.append(variables)
            return {"commentCreate": {"success": True}}
        if "issue(id" in query:
            return {"issue": {"id": "uuid-7", "identifier": variables["id"],
                              "state": {"type": self.state_type},
                              "team": {"states": {"nodes": [
                                  {"id": "st-done", "type": "completed"},
                                  {"id": "st-cancel", "type": "canceled"},
                                  {"id": "st-todo", "type": "unstarted"}]}}}}
        raise AssertionError(query)


def test_close_record_cancels_a_voided_row_and_completes_a_fixed_one(monkeypatch):
    monkeypatch.delenv("KIPI_ALERT_CAPTURE", raising=False)
    check = _load("slc_close", CHECK)
    base = {"state": "filed", "identifier": "ASK-7", "exit": 0}
    voided = _row("sp-v", _now(), status="resolved", void_reason="dup", linear=base)
    fixed = _row("sp-f", _now(), status="resolved", resolution_ref="ASK-9", linear=base)
    fake = _CloseLinear()
    assert check.close_record(voided, Path("."), ln=fake)["close"] == "canceled"
    assert fake.updates[-1]["input"]["stateId"] == "st-cancel"
    assert check.close_record(fixed, Path("."), ln=fake)["close"] == "completed"
    assert fake.updates[-1]["input"]["stateId"] == "st-done"
    assert len(fake.comments) == 2
    done = _CloseLinear(state_type="completed")
    assert check.close_record(fixed, Path("."), ln=done)["close"] == "already-closed"
    assert done.updates == []


def test_promotion_adopts_the_capture_ticket_instead_of_filing_a_second(tmp_path):
    """F1. A blocking row with no DoR files a capture ticket; promoting it later
    must put the DoR on THAT ticket, not open a second permanent issue."""
    sys.path.insert(0, str(SCRIPTS))
    import test_spillover_promote_selection as sel  # the promoter's own stub

    class AdoptLinear(sel.RecordingLinear):
        def __init__(self, board=None):
            super().__init__(board)
            self.updated = None

        def graphql(self, query, variables):
            if "issueUpdate" in query:
                self.updated = variables
                for issue in self.board:
                    if issue["identifier"] == variables["id"]:
                        issue["description"] = variables["input"]["description"]
                return {"issueUpdate": {"success": True,
                                        "issue": {"identifier": variables["id"]}}}
            return super().graphql(query, variables)

    root = tmp_path
    (root / ".prd-os").mkdir()
    (root / ".prd-os" / "spillover.jsonl").write_text(json.dumps({
        "id": "sp-test01", "status": "open", "severity": "major", "source": "ASK-451",
        "description": "the conveyor is dead",
        "linear": {"state": "filed", "identifier": "ASK-7001", "exit": 0}}) + "\n")
    mod = sel.load_promote()
    stub = AdoptLinear(board=[{"identifier": "ASK-7001",
                               "description": "Filed automatically by the fleet alert path."}])
    mod.linear_module = lambda: stub
    dor = root / "dor.md"
    dor.write_text(sel.DOR)
    old_argv, old_env = sys.argv, dict(os.environ)
    sys.argv = ["spillover-promote.py", "sp-test01", "--title", "conveyor",
                "--dor-file", str(dor), "--repo-root", str(root)]
    os.environ["KIPI_LINEAR_PROJECT"] = "kipi-system"
    try:
        rc = mod.main()
    finally:
        sys.argv = old_argv
        os.environ.clear()
        os.environ.update(old_env)
    assert rc == 0
    assert stub.created is None, "promotion filed a SECOND issue for one finding"
    assert stub.updated and stub.updated["id"] == "ASK-7001"
    body = stub.updated["input"]["description"]
    assert body.startswith(mod.promotion_marker("sp-test01")) and "Definition of Ready" in body
    rows = [json.loads(x) for x in (root / ".prd-os" / "spillover.jsonl").read_text().splitlines()]
    assert rows[-1]["status"] == "promoted" and rows[-1]["linear_ref"] == "ASK-7001"
