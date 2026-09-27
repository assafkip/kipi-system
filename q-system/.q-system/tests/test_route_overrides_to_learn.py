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
    # Both Codex reviewers: the log line alone left the file where the pass
    # lists it. The empty file is moved aside and the pass says nothing this week.
    assert not list(inbox.glob("engagement-*.md")), "the empty file is still where the pass lists it"
    assert list((inbox / ".empty").glob("engagement-*.md")), "the empty file must be kept as evidence"
    passed = subprocess.run([sys.executable, str(SCRIPTS / "weekly-improve.py"), "--dry-run",
                             "--inbox", str(inbox), "--friction", str(tmp_path / "friction.jsonl")],
                            capture_output=True, text=True, env=env)
    inbox_section = passed.stdout.split("*Skill proposals inbox*", 1)[1]
    assert "nothing this week" in inbox_section and "engagement-" not in inbox_section


def test_learner_output_is_found_by_mtime_not_by_local_date(tmp_path):
    """Codex standard finding: the learner stamps UTC, the shell stamped local
    time. A pre-existing file with today's local date must NOT be classified;
    the file the learner wrote during the run must be, whatever its name."""
    db = tmp_path / "metrics.db"
    sqlite3.connect(str(db)).execute(
        "CREATE TABLE copy_edits (id INTEGER PRIMARY KEY, date TEXT, contact_name TEXT, action_type TEXT, "
        "original TEXT, edited TEXT, edit_summary TEXT)").connection.commit()
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    # An old-dated name: with today's name the learner would overwrite it and
    # it WOULD be the fresh output. The point is that classification never
    # reads the name; a find without -newer would sweep this file in.
    stale = inbox / "engagement-2000-01-01.md"
    stale.write_text("a real proposal from long ago\n", encoding="utf-8")
    os.utime(stale, (1_000_000_000, 1_000_000_000))  # older than the run
    log = tmp_path / "weekly.log"
    env = dict(os.environ, KIPI_WEEKLY_LOG=str(log), KIPI_PROPOSALS_INBOX=str(inbox), KIPI_METRICS_DB=str(db),
               KIPI_FRICTION_FILE=str(tmp_path / "friction.jsonl"), KIPI_DRAFTS_LEDGER=str(tmp_path / "ledger.jsonl"))
    subprocess.run(["bash", str(RUNNER)], capture_output=True, text=True, env=env)
    text = log.read_text(encoding="utf-8")
    assert stale.exists() and str(stale) not in text, "a pre-existing file was classified by its date"
    assert "EMPTY " in text, "the learner's fresh empty file was not found by mtime"


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


def test_runner_resolves_in_a_bare_environment(tmp_path):
    """a-scheduled-job-runs-in-a-bare-environment-not-your-shell: no profile,
    no HOME beyond a temp one, a minimal PATH. The dry-run must still resolve
    its own directory and print the order; the real run must still find
    python3 and log every step."""
    bare = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "KIPI_WEEKLY_LOG": str(tmp_path / "w.log"),
            "KIPI_PROPOSALS_INBOX": str(tmp_path / "inbox"), "KIPI_METRICS_DB": str(tmp_path / "m.db"),
            "KIPI_FRICTION_FILE": str(tmp_path / "f.jsonl"), "KIPI_DRAFTS_LEDGER": str(tmp_path / "l.jsonl"),
            "PYTEST_CURRENT_TEST": os.environ.get("PYTEST_CURRENT_TEST", "1")}
    dry = subprocess.run(["/bin/bash", str(RUNNER), "--dry-run"], capture_output=True, text=True, env=bare)
    assert dry.returncode == 0 and dry.stdout.count("would run: ") == 3, dry.stderr
    subprocess.run(["/bin/bash", str(RUNNER)], capture_output=True, text=True, env=bare)
    text = (tmp_path / "w.log").read_text(encoding="utf-8")
    assert text.count("START ") == 3 and text.count("END ") == 3, text[-400:]


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
