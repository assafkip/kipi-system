"""ASK-1552: a new spillover row files one Linear issue at capture.

Founder, 2026-09-12: "Backlog where? In linear or is it going to disappear".
The ledger is untracked in git and nothing carried it to Linear, so capture now
means a ledger row AND a Linear issue through alert-to-linear.py.

Isolation: tmp repos, and the filer is the real alert-to-linear.py copied into
the tmp repo's q-system/.q-system/scripts/ (the production layout) with
KIPI_ALERT_CAPTURE set, so nothing reaches Linear.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
PRD_RUNNER = PLUGIN_ROOT / "scripts" / "prd_runner.py"
FINDINGS_WRITER = PLUGIN_ROOT / "scripts" / "findings_writer.py"
SKEL_SCRIPTS = PLUGIN_ROOT.parents[1] / "q-system" / ".q-system" / "scripts"
PRD_ID = "prd-demo-2026-09-12"
REFUSAL = ("a minor is fixed in this change or rejected with a reason; "
           "it is never queued (founder 2026-09-12)")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    (r / ".prd-os").mkdir(parents=True)
    (r / ".git").mkdir()
    (r / ".prd-os" / "config.json").write_text(json.dumps({
        "config_schema_version": 1,
        "prds_dir": ".prd-os/prds",
        "issues_dir": ".prd-os/issues",
        "findings_dir": ".prd-os/findings",
        "state_dir": ".claude/state",
    }))
    dest = r / "q-system" / ".q-system" / "scripts"
    dest.mkdir(parents=True)
    for name in ("alert-to-linear.py", "spillover-linear-check.py"):
        shutil.copy2(SKEL_SCRIPTS / name, dest / name)
    return r


def _run(script: Path, repo: Path, capture: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, KIPI_ALERT_CAPTURE=str(capture))
    return subprocess.run([sys.executable, str(script), "--repo-root", str(repo), *args],
                          capture_output=True, text=True, env=env, timeout=120)


def _ledger(repo: Path) -> dict:
    items: dict = {}
    path = repo / ".prd-os" / "spillover.jsonl"
    if path.exists():
        for raw in path.read_text().splitlines():
            if raw.strip():
                rec = json.loads(raw)
                items[rec["id"]] = rec
    return items


def _captured(capture: Path) -> list:
    return capture.read_text().splitlines() if capture.exists() else []


def _add(repo: Path, capture: Path, *extra: str, severity: str = "major") -> subprocess.CompletedProcess:
    return _run(PRD_RUNNER, repo, capture, "spillover", "add", "--source", "ASK-1552",
                "--desc", "ledger rows never reach Linear", "--id", "sp-cap00001",
                "--severity", severity, *extra)


@pytest.mark.parametrize("severity", ["minor", "low"])
def test_add_refuses_a_minor_or_low_and_writes_nothing(repo, tmp_path, severity):
    """Founder 2026-09-12: "New minor findings: fix or reject, never queue"."""
    cap = tmp_path / "capture.txt"
    res = _add(repo, cap, severity=severity)
    assert res.returncode == 2, res.stdout + res.stderr
    assert REFUSAL in res.stderr
    assert _ledger(repo) == {}, "a refused minor still reached the ledger"
    assert _captured(cap) == [], "a refused minor still reached Linear"


def test_add_with_no_severity_is_a_refused_minor(repo, tmp_path):
    """The CLI default is `minor`, so a bare add is the minor case."""
    cap = tmp_path / "capture.txt"
    res = _run(PRD_RUNNER, repo, cap, "spillover", "add", "--source", "ASK-1552",
               "--desc", "bare add", "--id", "sp-bare0001")
    assert res.returncode == 2 and REFUSAL in res.stderr
    assert _ledger(repo) == {}


@pytest.mark.parametrize("severity", ["medium", "blocker"])
def test_add_medium_and_blocker_still_file(repo, tmp_path, severity):
    cap = tmp_path / "capture.txt"
    res = _add(repo, cap, severity=severity)
    assert res.returncode == 0, res.stderr
    assert len(_captured(cap)) == 1
    assert _ledger(repo)["sp-cap00001"]["linear"]["state"] == "captured"


def test_add_files_exactly_one_issue_and_row_carries_the_link(repo, tmp_path):
    cap = tmp_path / "capture.txt"
    res = _add(repo, cap)
    assert res.returncode == 0, res.stderr
    lines = _captured(cap)
    assert len(lines) == 1, lines
    assert "sp-cap00001" in lines[0] and "ASK-1552" in lines[0]
    assert "major" in lines[0] and "ledger rows never reach Linear" in lines[0]
    rec = _ledger(repo)["sp-cap00001"]
    assert rec["status"] == "open"
    assert rec["linear"]["state"] == "captured" and rec["linear"]["exit"] == 0
    assert json.loads(res.stdout.strip().splitlines()[-1])["linear"]["state"] == "captured"


def test_add_rerun_does_not_file_a_second_issue(repo, tmp_path):
    cap = tmp_path / "capture.txt"
    assert _add(repo, cap).returncode == 0
    assert _add(repo, cap).returncode == 0
    assert len(_captured(cap)) == 1, "re-adding the same open row filed twice"
    assert _ledger(repo)["sp-cap00001"]["linear"]["state"] == "captured"


def test_filer_failure_keeps_the_row_and_marks_it_for_retry(repo, tmp_path):
    cap = tmp_path / "capture-dir"
    cap.mkdir()  # alert-to-linear cannot append to a directory: exit 1
    res = _add(repo, cap)
    assert res.returncode == 0, res.stderr   # capture never fails on the filer
    rec = _ledger(repo)["sp-cap00001"]
    assert rec["status"] == "open" and rec["description"] == "ledger rows never reach Linear"
    assert rec["linear"]["state"] == "failed" and rec["linear"]["exit"] == 1


def test_deferred_disposition_files_exactly_one_issue(repo, tmp_path):
    d = repo / ".prd-os" / "findings"
    d.mkdir(parents=True)
    (d / f"{PRD_ID}-findings.jsonl").write_text(json.dumps({
        "id": "finding-1", "prd_id": PRD_ID, "source": "codex-review",
        "severity": "major", "disposition": "pending",
        "body": "export reads canonical without archive filter",
        "created_at": "2026-09-12T00:00:00Z"}) + "\n")
    cap = tmp_path / "capture.txt"
    res = _run(FINDINGS_WRITER, repo, cap, "set-disposition", PRD_ID, "finding-1",
               "deferred", "--rationale", "next increment")
    assert res.returncode == 0, res.stderr
    sid = f"defer-{PRD_ID}-finding-1"
    lines = _captured(cap)
    assert len(lines) == 1 and sid in lines[0], lines
    rec = _ledger(repo)[sid]
    assert rec["status"] == "open" and rec["linear"]["state"] == "captured"


@pytest.mark.parametrize("severity", ["minor", "nit"])
def test_deferring_a_minor_finding_is_refused(repo, tmp_path, severity):
    """The only options for a minor are accepted (and fixed) or rejected with a
    rationale. prd-os findings grade minor-class work as `minor` or `nit`."""
    d = repo / ".prd-os" / "findings"
    d.mkdir(parents=True)
    rec = {"id": "finding-2", "prd_id": PRD_ID, "source": "codex-review",
           "disposition": "pending", "body": "nit: rename a local",
           "created_at": "2026-09-12T00:00:00Z"}
    rec["severity"] = severity
    fpath = d / f"{PRD_ID}-findings.jsonl"
    fpath.write_text(json.dumps(rec) + "\n")
    cap = tmp_path / "capture.txt"
    res = _run(FINDINGS_WRITER, repo, cap, "set-disposition", PRD_ID, "finding-2",
               "deferred", "--rationale", "later")
    assert res.returncode == 2, res.stdout + res.stderr
    assert REFUSAL in res.stderr
    assert json.loads(fpath.read_text().splitlines()[0])["disposition"] == "pending"
    assert _ledger(repo) == {} and _captured(cap) == []
    ok = _run(FINDINGS_WRITER, repo, cap, "set-disposition", PRD_ID, "finding-2",
              "rejected", "--rationale", "not worth a change")
    assert ok.returncode == 0, ok.stderr


def test_capture_link_is_not_a_tracker_ref_for_the_gate():
    """The alert ticket makes the row VISIBLE; it is not the promotion receipt
    the scopeless gate accepts for a blocking item. Minting that receipt by
    default would be "a check its own default satisfies" (see the comment on
    _spillover_has_tracker_ref), so gate semantics stay exactly as they were."""
    sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
    import prd_runner  # noqa: E402
    row = {"id": "sp-x", "severity": "major", "status": "open",
           "linear": {"state": "filed", "identifier": "ASK-9", "exit": 0}}
    assert not prd_runner._spillover_has_tracker_ref(row)
    assert prd_runner._spillover_blocks(row, None)
    assert prd_runner._spillover_has_tracker_ref({"linear": "ASK-9"})  # the old door


def test_the_two_plugin_copies_of_the_minor_rule_agree():
    """kipi-dsse keeps its own copy so it stays import-independent of prd-os."""
    import importlib.util as ilu
    sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
    import prd_runner  # noqa: E402
    spec = ilu.spec_from_file_location(
        "issue_findings_copy", PLUGIN_ROOT.parent / "kipi-dsse" / "scripts" / "issue_findings.py")
    dsse = ilu.module_from_spec(spec)
    spec.loader.exec_module(dsse)
    assert dsse.REFUSED_DEFER_SEVERITIES == prd_runner.SPILLOVER_REFUSED_SEVERITIES
    assert dsse.MINOR_REFUSAL == prd_runner.MINOR_REFUSAL == REFUSAL


def test_refusal_points_a_real_finding_at_severity(repo, tmp_path):
    """Review F4: the documented bare `add` defaults to minor and is refused; the
    refusal must tell an agent holding a real finding what to pass."""
    res = _add(repo, tmp_path / "c.txt", severity="minor")
    assert "--severity" in res.stderr


def test_add_output_does_not_deny_the_capture_ticket(repo, tmp_path):
    """Review F6: a blocking row with no DoR used to say "no Linear issue was
    created" in the same JSON that carried the capture link."""
    res = _add(repo, tmp_path / "c.txt", severity="major")
    out = json.loads(res.stdout.strip().splitlines()[-1])
    assert out["linear"]["state"] == "captured"
    assert "no Linear issue was created" not in res.stdout
