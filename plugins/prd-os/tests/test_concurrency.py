"""Tests for scripts/concurrency.py and its integration into both runners.

Two layers:
  - Unit tests of the helper module (pure state-file reads).
  - Subprocess tests that call prd_runner / issue_runner and verify the
    cross-runner guard fires at the right entry points.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
CONCURRENCY_PATH = PLUGIN_ROOT / "scripts" / "concurrency.py"


@pytest.fixture
def concurrency_module():
    spec = importlib.util.spec_from_file_location(
        "prd_os_concurrency", CONCURRENCY_PATH
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["prd_os_concurrency"] = module
    spec.loader.exec_module(module)
    return module


def _bootstrap(repo: Path, write_config) -> None:
    write_config(
        repo,
        {
            "config_schema_version": 1,
            "prds_dir": ".prd-os/prds",
            "issues_dir": ".prd-os/issues",
            "findings_dir": ".prd-os/findings",
            "state_dir": ".claude/state",
        },
    )


def _write_issue_state(repo: Path, issue_id: str | None) -> Path:
    path = repo / ".claude/state/active-issue.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"issue_id": issue_id, "receipts": {}}))
    return path


def _write_prd_state(repo: Path, prd_id: str | None, status: str | None) -> Path:
    path = repo / ".claude/state/active-prd.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"prd_id": prd_id, "status": status}))
    return path


# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------


def test_active_issue_id_returns_none_when_no_file(tmp_path, concurrency_module):
    assert concurrency_module.active_issue_id(tmp_path / "missing.json") is None


def test_active_issue_id_returns_none_for_empty_state(tmp_path, concurrency_module):
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"issue_id": None}))
    assert concurrency_module.active_issue_id(path) is None


def test_active_issue_id_returns_id(tmp_path, concurrency_module):
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"issue_id": "issue-foo"}))
    assert concurrency_module.active_issue_id(path) == "issue-foo"


def test_active_issue_id_handles_corrupt_json(tmp_path, concurrency_module):
    path = tmp_path / "s.json"
    path.write_text("not json{")
    assert concurrency_module.active_issue_id(path) is None


def test_active_prd_returns_none_when_archived(tmp_path, concurrency_module):
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"prd_id": "prd-x", "status": "archived"}))
    assert concurrency_module.active_prd(path) is None


def test_active_prd_returns_info_for_draft(tmp_path, concurrency_module):
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"prd_id": "prd-x", "status": "draft"}))
    assert concurrency_module.active_prd(path) == {"prd_id": "prd-x", "status": "draft"}


def test_assert_no_active_issue_raises(tmp_path, concurrency_module):
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"issue_id": "issue-bar"}))
    with pytest.raises(concurrency_module.ConcurrencyError) as exc:
        concurrency_module.assert_no_active_issue(path, action="start PRD")
    assert "issue-bar" in str(exc.value)


def test_assert_no_active_issue_passes_when_cleared(tmp_path, concurrency_module):
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"issue_id": None}))
    concurrency_module.assert_no_active_issue(path, action="start PRD")


def test_assert_no_active_prd_raises_for_nonarchived(tmp_path, concurrency_module):
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"prd_id": "prd-live", "status": "in-review"}))
    with pytest.raises(concurrency_module.ConcurrencyError) as exc:
        concurrency_module.assert_no_active_prd(path, action="load issue")
    assert "prd-live" in str(exc.value)


def test_assert_no_active_prd_passes_for_archived(tmp_path, concurrency_module):
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"prd_id": "prd-done", "status": "archived"}))
    concurrency_module.assert_no_active_prd(path, action="load issue")


# ---------------------------------------------------------------------------
# Runner integration: PRD side
# ---------------------------------------------------------------------------


def test_prd_new_refuses_when_issue_active(fake_repo, write_config, run_prd_runner):
    _bootstrap(fake_repo, write_config)
    _write_issue_state(fake_repo, "issue-live")
    r = run_prd_runner(fake_repo, "new", "blocked-prd")
    assert r.returncode == 2
    assert "issue-live" in r.stderr
    assert "start PRD" in r.stderr
    # Spec file should NOT have been created.
    assert not (fake_repo / ".prd-os/prds").exists() or not any(
        p.suffix == ".md" for p in (fake_repo / ".prd-os/prds").iterdir()
    )


def test_prd_load_refuses_when_issue_active(fake_repo, write_config, run_prd_runner):
    _bootstrap(fake_repo, write_config)
    # Create a PRD first (no issue yet).
    assert run_prd_runner(fake_repo, "new", "prep-prd").returncode == 0
    state_path = fake_repo / ".claude/state/active-prd.json"
    prd_id = json.loads(state_path.read_text())["prd_id"]
    # Clear PRD state, activate an issue, then try to load the PRD.
    assert run_prd_runner(fake_repo, "clear").returncode == 0
    _write_issue_state(fake_repo, "issue-busy")
    r = run_prd_runner(fake_repo, "load", prd_id)
    assert r.returncode == 2
    assert "issue-busy" in r.stderr


def test_prd_new_allowed_after_issue_cleared(fake_repo, write_config, run_prd_runner):
    _bootstrap(fake_repo, write_config)
    _write_issue_state(fake_repo, "issue-will-clear")
    # Simulate clearing the issue (empty issue_id).
    _write_issue_state(fake_repo, None)
    r = run_prd_runner(fake_repo, "new", "after-clear")
    assert r.returncode == 0, r.stderr


# ---------------------------------------------------------------------------
# Runner integration: issue side
# ---------------------------------------------------------------------------


def test_issue_load_refuses_when_prd_active(
    fake_repo, write_config, run_runner, write_issue_spec
):
    _bootstrap(fake_repo, write_config)
    # Put an in-progress PRD into state.
    _write_prd_state(fake_repo, "prd-live-2026-04-16", "in-review")
    # Write an issue spec so the runner could otherwise load it.
    write_issue_spec(
        fake_repo / ".prd-os/issues",
        "issue-a",
        allowed_files=["src/a.py"],
    )
    r = run_runner(fake_repo, "load", "issue-a")
    assert r.returncode == 2
    assert "prd-live-2026-04-16" in r.stderr
    assert "load issue" in r.stderr


def test_issue_load_allowed_when_prd_archived(
    fake_repo, write_config, run_runner, write_issue_spec
):
    _bootstrap(fake_repo, write_config)
    _write_prd_state(fake_repo, "prd-old-2026-04-16", "archived")
    write_issue_spec(
        fake_repo / ".prd-os/issues",
        "issue-a",
        allowed_files=["src/a.py"],
    )
    r = run_runner(fake_repo, "load", "issue-a")
    assert r.returncode == 0, r.stderr


def test_issue_load_allowed_when_no_prd_state(
    fake_repo, write_config, run_runner, write_issue_spec
):
    _bootstrap(fake_repo, write_config)
    write_issue_spec(
        fake_repo / ".prd-os/issues",
        "issue-a",
        allowed_files=["src/a.py"],
    )
    r = run_runner(fake_repo, "load", "issue-a")
    assert r.returncode == 0, r.stderr
