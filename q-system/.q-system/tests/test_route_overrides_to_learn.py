#!/usr/bin/env python3
"""RED FIRST. Issue mbl-weekly-improve-runner (prd-morning-brief-learns, Codex
finding-9). route-overrides-to-learn.py has existed since May with no test and
no trigger; this file is both halves' proof. Every path is a tmp_path: the
learner takes KIPI_METRICS_DB and KIPI_PROPOSALS_INBOX, the runner takes
KIPI_WEEKLY_LOG, and --dry-run runs nothing.
"""
from __future__ import annotations

import datetime as dt
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
LEARNER = SCRIPTS / "route-overrides-to-learn.py"
RUNNER = SCRIPTS / "weekly-improve.sh"
PLIST = SCRIPTS / "com.kipi.weekly-improve.plist"
EMPTY_MARKER = "No edited engagement actions in the metrics database."


def _learner(tmp_path, db=None):
    db = db or tmp_path / "metrics.db"
    inbox = tmp_path / "inbox"
    env = dict(os.environ, KIPI_METRICS_DB=str(db), KIPI_PROPOSALS_INBOX=str(inbox))
    r = subprocess.run([sys.executable, str(LEARNER)], capture_output=True, text=True, env=env)
    return r, inbox


def test_learner_over_an_empty_table_exits_2_and_the_file_is_reported_empty(tmp_path):
    db = tmp_path / "metrics.db"
    sqlite3.connect(str(db)).execute(
        "CREATE TABLE copy_edits (id INTEGER PRIMARY KEY, date TEXT, contact_name TEXT, action_type TEXT, "
        "original TEXT, edited TEXT, edit_summary TEXT)").connection.commit()
    r, inbox = _learner(tmp_path, db)
    assert r.returncode == 2, r.stdout + r.stderr
    files = list(inbox.glob("engagement-*.md"))
    assert len(files) == 1 and EMPTY_MARKER in files[0].read_text(encoding="utf-8")
    # The runner's checker: a dated file alone never counts as a proposal.
    log = tmp_path / "weekly.log"
    env = dict(os.environ, KIPI_WEEKLY_LOG=str(log), KIPI_PROPOSALS_INBOX=str(inbox),
               KIPI_METRICS_DB=str(db), KIPI_FRICTION_FILE=str(tmp_path / "friction.jsonl"),
               KIPI_DRAFTS_LEDGER=str(tmp_path / "ledger.jsonl"))
    subprocess.run(["bash", str(RUNNER)], capture_output=True, text=True, env=env)
    text = log.read_text(encoding="utf-8")
    assert "EMPTY " in text and "PROPOSAL " not in text


def test_learner_with_one_edit_writes_a_proposal(tmp_path):
    db = tmp_path / "metrics.db"
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE copy_edits (id INTEGER PRIMARY KEY, date TEXT, contact_name TEXT, action_type TEXT, "
                "original TEXT, edited TEXT, edit_summary TEXT)")
    con.execute("INSERT INTO copy_edits (date, contact_name, action_type, original, edited, edit_summary) VALUES "
                "('2026-09-01', 'rcpt:abc', 'draft-vs-sent:m-1', 'next week', 'Monday the 8th', 'diff projection')")
    con.commit()
    con.close()
    r, inbox = _learner(tmp_path, db)
    assert r.returncode == 0
    body = next(inbox.glob("engagement-*.md")).read_text(encoding="utf-8")
    assert EMPTY_MARKER not in body and "Monday the 8th" in body


def test_runner_order_from_a_dry_run_trace(tmp_path):
    r = subprocess.run(["bash", str(RUNNER), "--dry-run"], capture_output=True, text=True,
                       env=dict(os.environ, KIPI_WEEKLY_LOG=str(tmp_path / "never.log")))
    assert r.returncode == 0
    order = [l.split("would run: ", 1)[1] for l in r.stdout.splitlines() if l.startswith("would run: ")]
    assert order == ["draft-vs-sent.py", "route-overrides-to-learn.py", "weekly-improve.py"], order
    assert not (tmp_path / "never.log").exists(), "--dry-run must write nothing"


def test_every_step_is_logged_and_a_failing_producer_does_not_skip_the_pass(tmp_path):
    """The producer refuses under pytest (no runner injected), so it FAILS
    here on purpose; the learner and the pass must still run and log."""
    log = tmp_path / "weekly.log"
    env = dict(os.environ, KIPI_WEEKLY_LOG=str(log), KIPI_PROPOSALS_INBOX=str(tmp_path / "inbox"),
               KIPI_METRICS_DB=str(tmp_path / "metrics.db"), KIPI_FRICTION_FILE=str(tmp_path / "friction.jsonl"),
               KIPI_DRAFTS_LEDGER=str(tmp_path / "ledger.jsonl"))
    subprocess.run(["bash", str(RUNNER)], capture_output=True, text=True, env=env)
    text = log.read_text(encoding="utf-8")
    for step in ("draft-vs-sent.py", "route-overrides-to-learn.py", "weekly-improve.py"):
        assert f"START {step}" in text and re.search(rf"END {re.escape(step)} rc=\d+", text), step
    assert re.search(r"END draft-vs-sent\.py rc=[1-9]", text), "the producer was expected to fail under pytest"
    assert "END weekly-improve.py rc=" in text


def test_plist_template_placeholders_and_no_home_literal():
    text = PLIST.read_text(encoding="utf-8")
    for token in ("__KIPI_REPO__", "__HOME__", "__USER__"):
        assert token in text, token
    assert "/Users/" not in text
    assert "weekly-improve.sh" in text and "com.kipi.weekly-improve" in text
    assert "<key>Weekday</key><integer>1</integer>" in text


def test_runner_never_references_the_fleet_alert_notifier():
    assert "slack-notify" not in RUNNER.read_text(encoding="utf-8")


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
