"""spill-02 reproducer: a `deferred` triage disposition auto-creates an OPEN
spillover item (so it cannot be deferred-and-forgotten), while `rejected` stays
terminal. Moving a finding back off `deferred` clears its spillover item.

Reproducer-first: before the hook exists, deferring a finding leaves the
spillover ledger empty and `gates run` green -- the exact silent-drop bug.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
PRD_RUNNER = PLUGIN_ROOT / "scripts" / "prd_runner.py"
FINDINGS_WRITER = PLUGIN_ROOT / "scripts" / "findings_writer.py"
PRD_ID = "prd-demo-2026-06-20"


def _run(script: Path, repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(script), "--repo-root", str(repo), *args],
        capture_output=True, text=True,
    )


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
    return r


def _seed_finding(repo: Path, finding_id: str = "finding-1") -> None:
    d = repo / ".prd-os" / "findings"
    d.mkdir(parents=True, exist_ok=True)
    rec = {
        "id": finding_id, "prd_id": PRD_ID, "source": "codex-review",
        "severity": "major", "disposition": "pending",
        "body": "obsidian export reads canonical without archive filter",
        "created_at": "2026-06-20T00:00:00Z",
    }
    (d / f"{PRD_ID}-findings.jsonl").write_text(json.dumps(rec) + "\n")


def _set(repo: Path, finding_id: str, disposition: str, rationale: str = "later") -> subprocess.CompletedProcess:
    args = ["set-disposition", PRD_ID, finding_id, disposition]
    if disposition in ("rejected", "deferred"):
        args += ["--rationale", rationale]
    return _run(FINDINGS_WRITER, repo, *args)


def _spill(repo: Path) -> list:
    r = _run(PRD_RUNNER, repo, "spillover", "list", "--json")
    return json.loads(r.stdout) if r.stdout.strip() else []


def test_deferred_creates_open_spillover_and_reddens_gate(repo):
    _seed_finding(repo)
    assert _run(PRD_RUNNER, repo, "gates", "run").returncode == 0  # clean first
    assert _set(repo, "finding-1", "deferred").returncode == 0
    items = [i for i in _spill(repo) if i.get("status") == "open"]
    assert items, "deferring a finding created no spillover item"
    assert "finding-1" in json.dumps(items)
    assert _run(PRD_RUNNER, repo, "gates", "run").returncode != 0  # now red


def test_rejected_creates_no_spillover(repo):
    _seed_finding(repo)
    assert _set(repo, "finding-1", "rejected", rationale="duplicate of finding-0").returncode == 0
    assert [i for i in _spill(repo) if i.get("status") == "open"] == []
    assert _run(PRD_RUNNER, repo, "gates", "run").returncode == 0


def test_redeferring_does_not_duplicate(repo):
    _seed_finding(repo)
    _set(repo, "finding-1", "deferred")
    _set(repo, "finding-1", "deferred")
    open_items = [i for i in _spill(repo) if i.get("status") == "open"]
    assert len(open_items) == 1


def test_moving_off_deferred_clears_spillover(repo):
    _seed_finding(repo)
    _set(repo, "finding-1", "deferred")
    assert _run(PRD_RUNNER, repo, "gates", "run").returncode != 0
    # operator decides to fix it in-scope -> accepted -> spillover clears
    assert _set(repo, "finding-1", "accepted").returncode == 0
    assert [i for i in _spill(repo) if i.get("status") == "open"] == []
    assert _run(PRD_RUNNER, repo, "gates", "run").returncode == 0
