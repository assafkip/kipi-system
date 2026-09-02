#!/usr/bin/env python3
"""RED FIRST. Issue mbl-off-switches (prd-morning-brief-learns, Codex
finding-17): every new job and writer has an off state, and the off state is
proven a NO-OP by the absence of the artifact the on state would produce. A
test that only sets its own precondition cannot see missing wiring (lesson),
so each case here asserts what did NOT happen: no request, no file, no send.

Runs LAST in the PRD; imports every module by path with tmp_path homes.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
ROOT = HERE.parent.parent.parent
NOW = dt.datetime(2026, 9, 8, 7, 0, tzinfo=dt.timezone.utc)


def _load(stem, path):
    spec = importlib.util.spec_from_file_location(stem, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_board_with_no_page_id_file_is_off_and_makes_no_request(tmp_path):
    board = _load("notion_board_off", SCRIPTS / "notion_board.py")
    calls = []

    def opener(req, timeout):
        calls.append(req.full_url)
        return io.BytesIO(b'{"results": [], "has_more": false}')
    (tmp_path / "notion-token").write_text("t")
    out = board.collect(NOW, {"owed": (["ASK-1  x"], None)}, opener=opener,
                        token_file=tmp_path / "notion-token", page_file=tmp_path / "absent")
    assert out is None, "off must be None (no section), not an empty section"
    assert calls == [], f"the off state reached the network: {calls}"


def test_weekly_runner_dry_run_writes_nothing(tmp_path):
    env = dict(os.environ, KIPI_WEEKLY_LOG=str(tmp_path / "weekly.log"), KIPI_PROPOSALS_INBOX=str(tmp_path / "inbox"))
    r = subprocess.run(["bash", str(SCRIPTS / "weekly-improve.sh"), "--dry-run"], capture_output=True, text=True, env=env)
    assert r.returncode == 0
    assert sorted(p.name for p in tmp_path.iterdir()) == [], f"dry-run created files: {list(tmp_path.iterdir())}"


def test_weekly_pass_with_no_friction_file_sends_nothing(tmp_path, capsys):
    weekly = _load("weekly_improve_off", SCRIPTS / "weekly-improve.py")
    rc = weekly.main(["--friction", str(tmp_path / "absent.jsonl"), "--inbox", str(tmp_path / "no-inbox")])
    out = capsys.readouterr().out
    assert "nothing this week" in out
    assert '"refused": true' in out and '"delivered": false' in out, "under pytest a send must be refused, and refused is not delivered"
    assert rc == 1, "a refused send is not a success exit"
    assert not (tmp_path / "absent.jsonl").exists(), "the consumer must not create the ledger"


def test_producer_import_creates_no_salt_and_no_ledger(tmp_path, monkeypatch):
    dvs = _load("draft_vs_sent_off", SCRIPTS / "draft-vs-sent.py")
    monkeypatch.setattr(dvs, "SALT_FILE", tmp_path / "draft-salt")
    monkeypatch.setattr(dvs, "LEDGER", tmp_path / "ledger.jsonl")
    assert dvs.read_ledger() == []
    assert not (tmp_path / "draft-salt").exists() and not (tmp_path / "ledger.jsonl").exists()


def test_improve_ground_is_importable_without_side_effects(tmp_path):
    before = sorted(p.name for p in tmp_path.iterdir())
    ig = _load("improve_ground_off", ROOT / "plugins" / "kipi-core" / "skills" / "improve" / "scripts" / "improve_ground.py")
    report = ig.corpus_report([tmp_path / "absent"])
    assert report[0]["status"] == "missing"
    assert sorted(p.name for p in tmp_path.iterdir()) == before, "import or report created files"


def test_unknown_terms_with_no_inputs_is_an_error_not_a_pull(tmp_path):
    ut = _load("unknown_terms_off", SCRIPTS / "unknown_terms.py")
    rows, err = ut.collect(NOW, {}, canonical_dir=tmp_path)
    assert rows == [] and err and "not collected" in err
    src = (SCRIPTS / "unknown_terms.py").read_text(encoding="utf-8")
    assert "run_claude" not in src and "urllib" not in src


def test_every_new_script_declares_its_off_switch_in_its_docstring():
    """The switch must be written where an operator reads it."""
    expectations = {
        "notion_board.py": "OFF",
        "weekly-improve.py": "trigger",
        "friction-note.sh": "instance",
        "draft-vs-sent.py": "refused",
    }
    for name, token in expectations.items():
        text = (SCRIPTS / name).read_text(encoding="utf-8")
        assert token in text, f"{name} does not say how it is switched off ({token!r} missing)"


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
