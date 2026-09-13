"""ASK-1552: a `deferred` disposition on the DSSE issue path files one Linear
issue for the spillover row it creates, the same as `spillover add`.

Founder, 2026-09-12: "Backlog where? In linear or is it going to disappear".
The row is written first through this plugin's existing ledger append; the
Linear link is appended after. Isolation: tmp repo, the real alert-to-linear.py
copied into the production layout, KIPI_ALERT_CAPTURE set.
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
ISSUE_FINDINGS = PLUGIN_ROOT / "scripts" / "issue_findings.py"
SKEL_SCRIPTS = PLUGIN_ROOT.parents[1] / "q-system" / ".q-system" / "scripts"
ISSUE_ID = "c2w-linear"
SID = f"defer-{ISSUE_ID}-finding-9"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    (r / "issues" / "findings").mkdir(parents=True)
    (r / ".git").mkdir()
    (r / "issues" / "findings" / f"{ISSUE_ID}-findings.jsonl").write_text(json.dumps({
        "id": "finding-9", "issue_id": ISSUE_ID, "source": "codex-adversarial",
        "severity": "major", "disposition": "pending",
        "body": "exporter drops non-ascii slugs", "out_of_scope": False,
        "affected_path": "q-consult/pipeline/exporters.py",
        "created_at": "2026-09-12T00:00:00Z"}) + "\n")
    dest = r / "q-system" / ".q-system" / "scripts"
    dest.mkdir(parents=True)
    for name in ("alert-to-linear.py", "spillover-linear-check.py"):
        shutil.copy2(SKEL_SCRIPTS / name, dest / name)
    return r


def _defer(repo: Path, capture: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(repo), KIPI_ALERT_CAPTURE=str(capture))
    return subprocess.run(
        [sys.executable, str(ISSUE_FINDINGS), "set-disposition", ISSUE_ID, "finding-9",
         "deferred", "--rationale", "later"],
        capture_output=True, text=True, env=env, cwd=str(repo), timeout=120)


def _ledger(repo: Path) -> dict:
    items: dict = {}
    for raw in (repo / ".prd-os" / "spillover.jsonl").read_text().splitlines():
        if raw.strip():
            rec = json.loads(raw)
            items[rec["id"]] = rec
    return items


def test_dsse_deferred_files_exactly_one_issue_and_links_the_row(repo, tmp_path):
    cap = tmp_path / "capture.txt"
    out = _defer(repo, cap)
    assert out.returncode == 0, out.stderr
    lines = cap.read_text().splitlines() if cap.exists() else []
    assert len(lines) == 1 and SID in lines[0], lines
    rec = _ledger(repo)[SID]
    assert rec["status"] == "open" and rec["linear"]["state"] == "captured"

    # A second defer is idempotent: no second row, no second issue.
    assert _defer(repo, cap).returncode == 0
    assert len(cap.read_text().splitlines()) == 1


def test_dsse_filer_failure_keeps_the_row(repo, tmp_path):
    cap = tmp_path / "capture-dir"
    cap.mkdir()
    out = _defer(repo, cap)
    assert out.returncode == 0, out.stderr
    rec = _ledger(repo)[SID]
    assert rec["status"] == "open"
    assert rec["linear"]["state"] == "failed" and rec["linear"]["exit"] == 1


@pytest.mark.parametrize("severity", ["minor", "low"])
def test_dsse_deferring_a_minor_is_refused(repo, tmp_path, severity):
    """Founder 2026-09-12: "New minor findings: fix or reject, never queue"."""
    fpath = repo / "issues" / "findings" / f"{ISSUE_ID}-findings.jsonl"
    rec = json.loads(fpath.read_text().splitlines()[0])
    rec["severity"] = severity
    fpath.write_text(json.dumps(rec) + "\n")
    cap = tmp_path / "capture.txt"
    out = _defer(repo, cap)
    assert out.returncode == 2, out.stdout + out.stderr
    assert ("a minor is fixed in this change or rejected with a reason; "
            "it is never queued (founder 2026-09-12)") in out.stderr
    assert json.loads(fpath.read_text().splitlines()[0])["disposition"] == "pending"
    assert not (repo / ".prd-os" / "spillover.jsonl").exists()
    assert not cap.exists()
