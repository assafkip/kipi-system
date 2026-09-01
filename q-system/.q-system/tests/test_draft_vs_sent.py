#!/usr/bin/env python3
"""RED FIRST. Issue mbl-draft-sent-pairing (prd-morning-brief-learns, Codex
finding-7). Pairing is by Gmail id only. Every run here uses a tmp_path ledger
and a tmp_path metrics.db (the fable-discipline lint refuses a live DB path in
a test), and the runner is injected; the live runner is refused under pytest.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
MODULE = SCRIPTS / "draft-vs-sent.py"


@pytest.fixture(scope="module")
def dvs():
    assert MODULE.is_file(), f"missing: {MODULE}"
    spec = importlib.util.spec_from_file_location("draft_vs_sent", MODULE)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _ledger(dvs, tmp_path):
    ledger = tmp_path / "drafts-ledger.jsonl"
    dvs.record_draft("m-111", "Marta Kowalski", "Hi Marta, draft one about the pilot.", "brief", ledger)
    dvs.record_draft("m-222", "Marta Kowalski", "Hi Marta, draft two about the pilot.", "q-create", ledger)
    return ledger


def _runner_with(sent: dict):
    def runner(prompt, tools):
        assert "m-111" in prompt and "m-222" in prompt, "every ledger id is looked up"
        return json.dumps(sent), None
    return runner


def test_two_drafts_same_subject_pair_only_by_id(dvs, tmp_path):
    ledger = _ledger(dvs, tmp_path)
    db = tmp_path / "metrics.db"
    sent = {"m-222": {"body": "Hi Marta, draft two about the pilot, now with the dates.", "to": ["marta@example.com"]}}
    result = dvs.pair(ledger, db, runner=_runner_with(sent))
    assert result["paired"] == 1 and result["unmatched"] == 1 and result["unmatched_ids"] == ["m-111"]
    rows = sqlite3.connect(str(db)).execute("SELECT action_type, original, edited FROM copy_edits").fetchall()
    assert len(rows) == 1 and rows[0][0].endswith("m-222")
    assert "draft two" in rows[0][1] and "now with the dates" in rows[0][2]


def test_identical_draft_and_sent_is_skipped_not_stored(dvs, tmp_path):
    ledger = _ledger(dvs, tmp_path)
    db = tmp_path / "metrics.db"
    sent = {"m-111": {"body": "Hi Marta, draft one about the pilot.", "to": ["marta@example.com"]},
            "m-222": {"body": "Hi Marta, draft two about the pilot.", "to": []}}
    result = dvs.pair(ledger, db, runner=_runner_with(sent))
    assert result["paired"] == 0 and result["identical"] == 2
    assert sqlite3.connect(str(db)).execute("SELECT COUNT(*) FROM copy_edits").fetchone()[0] == 0


def test_a_rerun_does_not_duplicate_rows(dvs, tmp_path):
    ledger = _ledger(dvs, tmp_path)
    db = tmp_path / "metrics.db"
    sent = {"m-222": {"body": "changed", "to": []}}
    dvs.pair(ledger, db, runner=_runner_with(sent))
    second = dvs.pair(ledger, db, runner=_runner_with(sent))
    assert second["paired"] == 0
    assert sqlite3.connect(str(db)).execute("SELECT COUNT(*) FROM copy_edits").fetchone()[0] == 1


def test_similarity_is_never_used(dvs, tmp_path):
    """A sent message whose body matches a draft but whose id is unknown must
    NOT pair: the id is the only key."""
    ledger = _ledger(dvs, tmp_path)
    db = tmp_path / "metrics.db"
    sent = {"m-999": {"body": "Hi Marta, draft one about the pilot.", "to": []}}
    result = dvs.pair(ledger, db, runner=_runner_with(sent))
    assert result["paired"] == 0 and result["unmatched"] == 2
    src = MODULE.read_text(encoding="utf-8")
    for banned in ("difflib.SequenceMatcher", "similar(", "fuzzy", "subject"):
        assert banned not in src.lower() or banned == "subject" and "subject, recipient or time similarity is never used" in src.lower(), banned


def test_record_draft_requires_an_id_and_appends(dvs, tmp_path):
    ledger = tmp_path / "l.jsonl"
    with pytest.raises(ValueError):
        dvs.record_draft("", "x", "body", "brief", ledger)
    dvs.record_draft("m-1", "x", "body", "brief", ledger)
    dvs.record_draft("m-2", "y", "body", "q-create", ledger)
    assert [r["draft_id"] for r in dvs.read_ledger(ledger)] == ["m-1", "m-2"]


def test_live_runner_is_refused_under_pytest(dvs, tmp_path):
    ledger = _ledger(dvs, tmp_path)
    with pytest.raises(RuntimeError, match="refused by draft-vs-sent"):
        dvs.pair(ledger, tmp_path / "metrics.db", runner=None)


def test_never_writes_exemplars(dvs):
    src = MODULE.read_text(encoding="utf-8")
    assert "exemplars.jsonl" in src and "NEVER q-consult/voice/exemplars.jsonl" in src
    assert "open(" not in src.replace("path.open(", "").replace(".open(\"a\"", ""), "the only file this writes is the ledger"


def test_this_file_runs_its_own_tests_under_python3():
    if os.environ.get("KIPI_SELFTEST_INNER"):
        pytest.skip("inner run")
    env = dict(os.environ, KIPI_SELFTEST_INNER="1")
    ok = subprocess.run([sys.executable, __file__], capture_output=True, text=True, env=env)
    assert ok.returncode == 0 and "passed" in ok.stdout, ok.stdout[-600:]
    none = subprocess.run([sys.executable, __file__, "-k", "no_such_test_zzz"], capture_output=True, text=True, env=env)
    assert none.returncode != 0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", *sys.argv[1:]]))
