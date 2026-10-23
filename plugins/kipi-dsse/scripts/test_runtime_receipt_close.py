"""DSSE close refuses a runtime-control issue without a runtime receipt.

RCA 2026-10-02: a gate "proven" by reading its source never fired on the real
caller. An issue whose title claims a gate / cap / meter / budget / ledger /
guard / limit / rate / quota fix closes only with a receipt of a real call.
Fixtures come from producers: the repo is built by prd_split + issue_runner.
"""
import json
import sys
from pathlib import Path

DSSE = Path(__file__).resolve().parent
sys.path.insert(0, str(DSSE))
from test_computed_receipts import (  # noqa: E402
    _check_off_deliverables, _issue, _make_repo, _review_artifact, _run)


def _ready(tmp_path: Path, title: str) -> Path:
    repo = _make_repo(tmp_path, check="python3 -c \"print('ok')\"")
    spec = repo / ".prd-os/issues/probe-1.md"
    spec.write_text(spec.read_text().replace("title: Probe", f"title: {title}", 1))
    assert _issue(repo, "verify").returncode == 0
    assert _issue(repo, "triage").returncode == 0
    for kind in ("standard", "adversarial"):
        assert _issue(repo, "record-review", kind).returncode == 0
        assert _issue(repo, "complete-review", kind, "--verdict", "approve",
                      "--evidence-file", _review_artifact(repo, kind)).returncode == 0
    _check_off_deliverables(repo)
    return repo


def _rows(repo: Path) -> list:
    f = repo / ".prd-os/receipts.jsonl"
    return [json.loads(l) for l in f.read_text().splitlines() if l.strip()] if f.exists() else []


def test_a_cap_issue_does_not_close_without_a_runtime_receipt(tmp_path):
    repo = _ready(tmp_path, "Cap the reviewer rounds")
    proc = _issue(repo, "close")
    assert proc.returncode == 2, proc.stdout
    assert "--runtime-receipt" in proc.stderr, proc.stderr
    assert _rows(repo) == []


def test_a_source_only_receipt_does_not_close_it(tmp_path):
    repo = _ready(tmp_path, "Cap the reviewer rounds")
    r = tmp_path / "grep.json"
    r.write_text(json.dumps({"command": "grep -n MAX_ROUNDS reviewer.py",
                             "output": "3:MAX_ROUNDS = 2", "ran_at": "2026-01-01T00:00:00Z"}))
    proc = _issue(repo, "close", "--runtime-receipt", str(r))
    assert proc.returncode == 2 and "only reads source" in proc.stderr, proc.stderr


def test_a_real_receipt_closes_and_lands_on_the_receipt_row(tmp_path):
    repo = _ready(tmp_path, "Cap the reviewer rounds")
    out = tmp_path / "real.json"
    cap = _run(repo, DSSE / "runtime_receipt.py", "capture", "--out", str(out), "--",
               sys.executable, "-c", "print('rounds used: 2 of 2')")
    assert cap.returncode == 0, cap.stderr
    proc = _issue(repo, "close", "--runtime-receipt", str(out))
    assert proc.returncode == 0, proc.stderr
    (row,) = _rows(repo)
    assert row["runtime_receipt"]["claim_terms"] == ["cap"]


def test_an_ordinary_issue_closes_without_one(tmp_path):
    repo = _ready(tmp_path, "Probe")
    proc = _issue(repo, "close")
    assert proc.returncode == 0, proc.stderr
    assert "runtime_receipt" not in _rows(repo)[0]
