"""A receipt says what KIND of problem its work fixed (ASK-1968).

Measured 2026-09-20: a receipt row read alone abstained on 81 of 100 when asked
what problem the work fixed, because every field is an id or a timestamp. The
finding body that answers it is free text and cannot enter the ledger, which is
committed to a public repo. So the finding carries an optional `finding_class`
from one fixed list, and close copies it onto the receipt.

Fixtures come from producers: the finding is written by findings_writer.py and
the receipt by issue_runner.py close, both run as subprocesses in a virgin repo.
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

DSSE = Path(__file__).resolve().parent
PRDOS = DSSE.parents[1] / "prd-os/scripts"
LEDGER_CHECK = DSSE.parents[2] / "q-system/.q-system/scripts/receipts-ledger-check.py"

sys.path.insert(0, str(DSSE))
from test_computed_receipts import (  # noqa: E402
    _check_off_deliverables,
    _issue,
    _review_artifact,
    _run,
)


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_repo(tmp_path: Path, finding: dict) -> Path:
    """The same producer chain as test_computed_receipts._make_repo, with the
    finding's writer input as the one variable."""
    repo = tmp_path / "repo"
    repo.mkdir()
    for cmd in (["init", "-q"], ["config", "user.email", "t@t.co"],
                ["config", "user.name", "t"]):
        subprocess.run(["git", *cmd], cwd=repo, capture_output=True)
    (repo / "README.md").write_text("# t\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, capture_output=True)

    assert _run(repo, PRDOS / "prd_os_init.py").returncode == 0
    created = _run(repo, PRDOS / "prd_runner.py", "new", "probe", "--title", "T")
    assert created.returncode == 0, created.stderr
    prd_id = json.loads(created.stdout)["created"]
    spec = repo / ".prd-os/prds" / f"{prd_id}.md"
    manifest = json.dumps([{
        "id": "probe-1", "title": "Probe", "allowed_files": ["README.md"],
        "required_checks": ["python3 -c \"print('ok')\""], "acceptance": "a",
        "finding_id": "finding-1",
        "bypass_check": "python3 -c \"print('no bypass')\"",
    }], indent=2)
    body = spec.read_text()
    at = body.index("\n## Issues") + len("\n## Issues")
    spec.write_text(body[:at] + "\n\n```json\n" + manifest + "\n```\n" + body[at:])

    assert _run(repo, PRDOS / "prd_runner.py", "advance", "draft").returncode == 0
    add = _run(repo, PRDOS / "findings_writer.py", "add", prd_id,
               "--source", "claude-review", stdin=json.dumps([finding]))
    assert add.returncode == 0, add.stderr
    assert _run(repo, PRDOS / "findings_writer.py", "set-disposition", prd_id,
                "finding-1", "accepted", "--reason-code", "valid-fix-now",
                "--actor", "t").returncode == 0
    for stage in ("in-review", "approved"):
        assert _run(repo, PRDOS / "prd_runner.py", "advance", stage).returncode == 0
    assert _run(repo, PRDOS / "prd_split.py").returncode == 0
    assert _run(repo, PRDOS / "prd_runner.py", "clear").returncode == 0
    assert _issue(repo, "load", "probe-1").returncode == 0
    assert _issue(repo, "approve").returncode == 0
    return repo


def _close(repo: Path) -> dict:
    assert _issue(repo, "verify").returncode == 0
    assert _issue(repo, "triage").returncode == 0
    for kind in ("standard", "adversarial"):
        assert _issue(repo, "record-review", kind).returncode == 0
        assert _issue(repo, "complete-review", kind, "--verdict", "approve",
                      "--evidence-file", _review_artifact(repo, kind)).returncode == 0
    _check_off_deliverables(repo)
    proc = _issue(repo, "close")
    assert proc.returncode == 0, f"close refused: {proc.stderr}"
    rows = [json.loads(line) for line in
            (repo / ".prd-os/receipts.jsonl").read_text().splitlines() if line.strip()]
    assert len(rows) == 1, rows
    return rows[0]


def test_a_classed_finding_gives_a_receipt_with_the_same_class(tmp_path):
    receipt = _close(_make_repo(tmp_path, {
        "severity": "major", "body": "probe", "finding_class": "wiring"}))
    assert receipt.get("finding_class") == "wiring", receipt


def test_an_unclassed_finding_gives_a_receipt_with_no_class_key(tmp_path):
    receipt = _close(_make_repo(tmp_path, {"severity": "major", "body": "probe"}))
    assert "finding_class" not in receipt, receipt


@pytest.mark.parametrize("value", ["bogus", "some free text", 7])
def test_the_writer_refuses_a_class_off_the_list(tmp_path, value):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, capture_output=True)
    assert _run(repo, PRDOS / "prd_os_init.py").returncode == 0
    proc = _run(repo, PRDOS / "findings_writer.py", "add", "p", "--source", "manual",
                stdin=json.dumps([{"severity": "minor", "body": "b",
                                   "finding_class": value}]))
    assert proc.returncode == 2, proc.stdout
    assert "finding_class" in proc.stderr, proc.stderr
    assert not (repo / ".prd-os/findings/p-findings.jsonl").exists()


def test_the_ledger_gate_and_the_writer_hold_the_same_list():
    """The gate cannot import the writer (it runs at commit time from
    q-system/, where a missing plugin would turn it into a crash), so the list
    lives twice. This is the divergence check that fails when they drift."""
    writer = _load(PRDOS / "findings_writer.py", "fw_ask1968")
    gate = _load(LEDGER_CHECK, "rlc_ask1968")
    assert writer.FINDING_CLASSES, "derivation floor: the writer list is empty"
    assert set(writer.FINDING_CLASSES) == set(gate.FINDING_CLASSES)
