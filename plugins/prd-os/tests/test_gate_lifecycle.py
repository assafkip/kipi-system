"""Regression coverage for the PRD gate lifecycle boundary."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
PRD_RUNNER = PLUGIN_ROOT / "scripts" / "prd_runner.py"
MIGRATE = PLUGIN_ROOT / "scripts" / "migrate_gate_lifecycle.py"


def run(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PRD_RUNNER), "--repo-root", str(repo), *args],
        capture_output=True,
        text=True,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / ".prd-os").mkdir(parents=True)
    (root / ".git").mkdir()
    (root / ".prd-os" / "config.json").write_text(
        json.dumps(
            {
                "config_schema_version": 1,
                "prds_dir": ".prd-os/prds",
                "issues_dir": ".prd-os/issues",
                "findings_dir": ".prd-os/findings",
                "state_dir": ".claude/state",
            }
        )
    )
    return root


def write_gates(repo: Path, records: list[dict]) -> None:
    path = repo / ".prd-os" / "gates.jsonl"
    path.write_text("".join(json.dumps(record) + "\n" for record in records))


def test_list_filters_by_validated_lifecycle(repo):
    write_gates(
        repo,
        [
            {"gate_id": "current", "command": "true", "lifecycle": "regression"},
            {
                "gate_id": "receipt",
                "command": "false",
                "lifecycle": "historical-receipt",
            },
        ],
    )

    result = run(repo, "gates", "list", "--lifecycle", "regression")

    assert result.returncode == 0, result.stderr
    assert [record["gate_id"] for record in json.loads(result.stdout)] == ["current"]


def test_run_executes_only_regression_gates(repo):
    write_gates(
        repo,
        [
            {"gate_id": "receipt", "command": "false"},
            {"gate_id": "retired", "command": "false", "lifecycle": "retired"},
            {"gate_id": "external", "command": "false", "lifecycle": "external"},
            {"gate_id": "current", "command": "true", "lifecycle": "regression"},
        ],
    )

    result = run(repo, "gates", "run")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "current" in result.stdout
    assert "receipt" not in result.stdout
    assert "retired" not in result.stdout
    assert "external" not in result.stdout


def test_invalid_registry_lifecycle_fails_closed(repo):
    write_gates(
        repo,
        [{"gate_id": "bad", "command": "true", "lifecycle": "sometimes"}],
    )

    result = run(repo, "gates", "list")

    assert result.returncode == 2
    assert "invalid lifecycle" in result.stderr


def test_gate_register_validates_and_persists_lifecycle(repo):
    spec = importlib.util.spec_from_file_location("prd_runner_lifecycle", PRD_RUNNER)
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(PRD_RUNNER.parent))
    spec.loader.exec_module(module)
    cfg = module.load_config(repo)

    registered = module.gate_register(
        cfg,
        prd_id="prd-x",
        issue_id="issue-x",
        command="true",
        lifecycle="regression",
    )

    record = json.loads((repo / ".prd-os" / "gates.jsonl").read_text())
    assert registered["registered"] is True
    assert record["lifecycle"] == "regression"
    with pytest.raises(ValueError, match="invalid gate lifecycle"):
        module.gate_register(
            cfg,
            prd_id="prd-x",
            issue_id="issue-y",
            command="true",
            lifecycle="sometimes",
        )


def test_migration_classifies_every_record_without_deleting_receipts(repo):
    write_gates(
        repo,
        [
            {"gate_id": "old", "command": "true"},
            {"gate_id": "current", "command": "true"},
            {"gate_id": "remote", "command": "true"},
            {"gate_id": "gone", "command": "true"},
        ],
    )

    result = subprocess.run(
        [
            sys.executable,
            str(MIGRATE),
            "--registry",
            str(repo / ".prd-os" / "gates.jsonl"),
            "--regression",
            "current",
            "--external",
            "remote",
            "--retired",
            "gone",
            "--apply",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    records = [
        json.loads(line)
        for line in (repo / ".prd-os" / "gates.jsonl").read_text().splitlines()
    ]
    assert [record["gate_id"] for record in records] == [
        "old",
        "current",
        "remote",
        "gone",
    ]
    assert [record["lifecycle"] for record in records] == [
        "historical-receipt",
        "regression",
        "external",
        "retired",
    ]


def test_incremental_migration_preserves_existing_lifecycles(repo):
    write_gates(
        repo,
        [
            {"gate_id": "current", "command": "true", "lifecycle": "regression"},
            {"gate_id": "gone", "command": "true", "lifecycle": "retired"},
            {"gate_id": "remote", "command": "true"},
        ],
    )

    result = subprocess.run(
        [
            sys.executable,
            str(MIGRATE),
            "--registry",
            str(repo / ".prd-os" / "gates.jsonl"),
            "--external",
            "remote",
            "--apply",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    records = [
        json.loads(line)
        for line in (repo / ".prd-os" / "gates.jsonl").read_text().splitlines()
    ]
    assert [record["lifecycle"] for record in records] == [
        "regression",
        "retired",
        "external",
    ]
