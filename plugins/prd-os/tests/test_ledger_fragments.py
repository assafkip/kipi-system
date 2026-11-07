"""ledger_fragments: one row per file for receipts.jsonl and gates.jsonl (ASK-3829).

The two-branch and twenty-branch merge proofs live beside the close path in
plugins/kipi-dsse/scripts/test_ledger_fragments_close.py. This file pins the module itself and
the prd-os readers that fold through it.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import ledger_fragments  # noqa: E402

LEGACY = [{"issue_id": "old-1", "prd_id": "prd-a", "finding_id": "finding-1",
           "closed_at": "2026-09-01T00:00:00Z", "commit_sha": "a" * 40}]


def _rows(ledger):
    return [json.loads(t) for _s, _n, t in ledger_fragments.iter_lines(ledger) if t.strip()]


def _at(second):
    return datetime(2026, 11, 6, 0, 0, second, tzinfo=timezone.utc)


@pytest.fixture
def ledger(tmp_path):
    path = tmp_path / ".prd-os" / "receipts.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in LEGACY))
    return path


def test_fold_is_legacy_first_then_fragments_by_name_whatever_the_write_order(ledger):
    for second in (5, 1, 3):  # written out of order
        ledger_fragments.append_line(ledger, json.dumps({"issue_id": f"s{second}"}),
                                     kind="receipt", now=_at(second))
    assert [r["issue_id"] for r in _rows(ledger)] == ["old-1", "s1", "s3", "s5"]


def test_a_fragment_write_never_touches_the_legacy_bytes(ledger):
    before = ledger.read_bytes()
    landed = ledger_fragments.append_line(ledger, json.dumps({"issue_id": "x"}), kind="receipt")
    assert ledger.read_bytes() == before
    assert landed.parent == ledger_fragments.fragment_dir(ledger) == ledger.parent / "receipts.d"
    assert ledger_fragments.FRAGMENT_NAME_RE.match(landed.name), landed.name
    assert landed.read_text() == '{"issue_id": "x"}\n'


@pytest.mark.parametrize("line, why", [
    ('{"a": 1}\n{"b": 2}', "line break"),
    ("not json", "must be JSON"),
    ('["a list"]', "JSON object"),
])
def test_the_writer_refuses_anything_but_one_json_object(ledger, line, why):
    with pytest.raises(ValueError, match=why):
        ledger_fragments.append_line(ledger, line, kind="receipt")
    assert ledger_fragments.fragment_files(ledger) == []


def test_the_writer_refuses_a_kind_that_could_carry_a_path(ledger):
    with pytest.raises(ValueError, match="kind"):
        ledger_fragments.append_line(ledger, "{}", kind="../x")


def test_the_same_row_at_the_same_instant_is_one_file(ledger):
    a = ledger_fragments.append_line(ledger, '{"issue_id": "same"}', kind="receipt", now=_at(9))
    b = ledger_fragments.append_line(ledger, '{"issue_id": "same"}', kind="receipt", now=_at(9))
    assert a == b and len(ledger_fragments.fragment_files(ledger)) == 1


def test_a_name_held_by_other_bytes_is_never_overwritten(ledger, monkeypatch):
    first = ledger_fragments.append_line(ledger, '{"issue_id": "one"}', kind="receipt",
                                         now=_at(9))
    # Force a name collision: a second row whose hash prefix happens to match.
    real = ledger_fragments.hashlib.sha256
    monkeypatch.setattr(ledger_fragments.hashlib, "sha256",
                        lambda data: real(b'{"issue_id": "one"}\n'))
    with pytest.raises(FileExistsError):
        ledger_fragments.append_line(ledger, '{"issue_id": "two"}', kind="receipt", now=_at(9))
    assert first.read_text() == '{"issue_id": "one"}\n'


def test_hidden_temp_files_are_not_rows(ledger):
    d = ledger_fragments.fragment_dir(ledger)
    d.mkdir()
    (d / ".tmp-123.part").write_text('{"issue_id": "half"}\n')
    assert [r["issue_id"] for r in _rows(ledger)] == ["old-1"]


def test_missing_legacy_and_missing_dir_fold_to_nothing(tmp_path):
    ledger = tmp_path / ".prd-os" / "gates.jsonl"
    assert list(ledger_fragments.iter_lines(ledger)) == []
    assert ledger_fragments.has_rows(ledger) is False


# --- the one fallback: tracked legacy file, ignored fragments -------------------------------

def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


def _repo_with_gitignore(tmp_path, gitignore):
    repo = tmp_path / "r"
    (repo / ".prd-os").mkdir(parents=True)
    _git(repo, "init", "-q")
    (repo / ".gitignore").write_text(gitignore)
    ledger = repo / ".prd-os" / "receipts.jsonl"
    ledger.write_text(json.dumps(LEGACY[0]) + "\n")
    _git(repo, "add", "-f", ".gitignore", ".prd-os/receipts.jsonl")
    return ledger


def test_tracked_legacy_with_ignored_fragments_keeps_appending_and_says_so(tmp_path, capsys):
    """investigations and accountant, measured 2026-11-06: a fragment there would never be
    committed, and the worker deletes its worktree, so the receipt would be lost."""
    ledger = _repo_with_gitignore(tmp_path, "*.jsonl\n!.prd-os/receipts.jsonl\n")
    landed = ledger_fragments.append_line(ledger, '{"issue_id": "kept"}', kind="receipt")
    assert landed == ledger
    assert [r["issue_id"] for r in _rows(ledger)] == ["old-1", "kept"]
    assert ledger_fragments.fragment_files(ledger) == []
    assert "!.prd-os/receipts.d/*.jsonl" in capsys.readouterr().err


def test_tracked_legacy_with_trackable_fragments_writes_a_fragment(tmp_path):
    ledger = _repo_with_gitignore(
        tmp_path, "*.jsonl\n!.prd-os/receipts.jsonl\n!.prd-os/receipts.d/*.jsonl\n")
    before = ledger.read_bytes()
    landed = ledger_fragments.append_line(ledger, '{"issue_id": "frag"}', kind="receipt")
    assert landed.parent.name == "receipts.d" and ledger.read_bytes() == before


def test_an_untracked_legacy_file_never_triggers_the_fallback(tmp_path):
    """kipi-system's gates.jsonl: ignored and untracked, so nothing is lost by a fragment."""
    repo = tmp_path / "r"
    (repo / ".prd-os").mkdir(parents=True)
    _git(repo, "init", "-q")
    (repo / ".gitignore").write_text("*.jsonl\n")
    ledger = repo / ".prd-os" / "gates.jsonl"
    ledger.write_text('{"gate_id": "g"}\n')
    landed = ledger_fragments.append_line(ledger, '{"gate_id": "h"}', kind="gate")
    assert landed.parent.name == "gates.d"


# --- the prd-os readers fold legacy + fragments ---------------------------------------------

def _runner():
    import prd_runner
    return prd_runner


def test_archive_coverage_readers_see_fragments(ledger):
    pr = _runner()
    ledger_fragments.append_line(ledger, json.dumps(
        {"issue_id": "new-1", "prd_id": "prd-a", "finding_id": "finding-2",
         "closed_at": "2026-11-06T00:00:00Z"}), kind="receipt")
    assert pr._load_receipt_issue_ids(ledger) == {"old-1", "new-1"}
    assert pr._load_receipts_for_prd(ledger, "prd-a") == {"finding-1", "finding-2"}
    # A reopen recorded in a fragment beats the close in the legacy file.
    ledger_fragments.append_line(ledger, json.dumps(
        {"issue_id": "old-1", "prd_id": "prd-a", "finding_id": "finding-1",
         "reopened_at": "2026-11-06T00:00:01Z"}), kind="receipt")
    assert pr._load_receipts_for_prd(ledger, "prd-a") == {"finding-2"}


def _gate_repo(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".prd-os").mkdir(parents=True)
    (repo / ".git").mkdir()
    (repo / ".prd-os" / "config.json").write_text(json.dumps({
        "config_schema_version": 1, "issues_dir": ".prd-os/issues",
        "state_dir": ".claude/state"}))
    (repo / ".prd-os" / "gates.jsonl").write_text(json.dumps({
        "gate_id": "legacy-1", "prd_id": "p", "issue_id": "legacy", "command": "true",
        "lifecycle": "regression"}) + "\n")
    return repo


def test_gate_register_writes_a_fragment_and_dedups_across_both(tmp_path):
    pr = _runner()
    repo = _gate_repo(tmp_path)
    cfg = pr.load_config(repo)
    gates = repo / ".prd-os" / "gates.jsonl"
    legacy_before = gates.read_bytes()
    first = pr.gate_register(cfg, prd_id="p", issue_id="iss", command="true",
                             lifecycle="regression", protects="x")
    again = pr.gate_register(cfg, prd_id="p", issue_id="iss", command="true",
                             lifecycle="regression", protects="x")
    assert first["registered"] is True and again["registered"] is False
    assert gates.read_bytes() == legacy_before
    assert [g["issue_id"] for g in _rows(gates)] == ["legacy", "iss"]
    listed = subprocess.run([sys.executable, str(SCRIPTS / "prd_runner.py"), "--repo-root",
                             str(repo), "gates", "list"], capture_output=True, text=True)
    assert listed.returncode == 0, listed.stderr
    assert "legacy-1" in listed.stdout and first["gate_id"] in listed.stdout


def test_gates_run_names_the_fragment_that_holds_a_bad_row(tmp_path):
    repo = _gate_repo(tmp_path)
    d = repo / ".prd-os" / "gates.d"
    d.mkdir()
    bad = d / "20261106T000000000000Z-gate-0000000000000000.jsonl"
    bad.write_text("{not json\n")
    listed = subprocess.run([sys.executable, str(SCRIPTS / "prd_runner.py"), "--repo-root",
                             str(repo), "gates", "list"], capture_output=True, text=True)
    assert listed.returncode == 2
    assert f"{bad}:1: invalid JSONL" in listed.stderr, listed.stderr
