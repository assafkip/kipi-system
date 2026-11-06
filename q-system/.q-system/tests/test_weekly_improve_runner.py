#!/usr/bin/env python3
"""Runner and plist tests for weekly-improve.sh (issue mbl-weekly-improve-runner,
trimmed by ASK-3402). This file was test_route_overrides_to_learn.py; the
learner and the draft producer are RETIRED 2026-10-30 (ASK-3402) because
nothing ever filled their inputs, so their tests went with them. Every path is
a tmp_path: the runner takes KIPI_WEEKLY_LOG and KIPI_STARVATION_LEDGER, and
--dry-run runs nothing. KIPI_STARVATION_NOTIFY is a stub, never the live
notifier.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
RUNNER = SCRIPTS / "weekly-improve.sh"
PLIST = SCRIPTS / "com.kipi.weekly-improve.plist"


def _env(tmp_path, **extra):
    stub = tmp_path / "notify.sh"
    stub.write_text(f'#!/bin/bash\necho "$1" >> "{tmp_path / "calls.txt"}"\n')
    return dict(os.environ, KIPI_WEEKLY_LOG=str(tmp_path / "w.log"),
                KIPI_PROPOSALS_INBOX=str(tmp_path / "inbox"),
                KIPI_FRICTION_FILE=str(tmp_path / "friction.jsonl"),
                KIPI_STARVATION_LEDGER=str(tmp_path / "starve.jsonl"),
                KIPI_STARVATION_NOTIFY=f"bash {stub}", **extra)


def test_runner_order_from_a_dry_run_trace(tmp_path):
    r = subprocess.run(["bash", str(RUNNER), "--dry-run"], capture_output=True, text=True,
                       env=dict(os.environ, KIPI_WEEKLY_LOG=str(tmp_path / "never.log")))
    assert r.returncode == 0
    order = [l.split("would run: ", 1)[1] for l in r.stdout.splitlines() if l.startswith("would run: ")]
    assert order == ["weekly-improve.py"], "the draft producer and the learner are retired (ASK-3402)"
    assert not (tmp_path / "never.log").exists(), "--dry-run must write nothing"


def test_the_retired_steps_are_not_run_or_named_as_steps():
    text = RUNNER.read_text(encoding="utf-8")
    steps = text.split("STEPS=(", 1)[1].split(")", 1)[0]
    assert "draft-vs-sent" not in steps and "route-overrides" not in steps
    assert not (SCRIPTS / "draft-vs-sent.py").exists() and not (SCRIPTS / "route-overrides-to-learn.py").exists()


def test_the_pass_is_logged_and_records_its_input_count(tmp_path):
    env = _env(tmp_path)
    subprocess.run(["bash", str(RUNNER)], capture_output=True, text=True, env=env)
    text = (tmp_path / "w.log").read_text(encoding="utf-8")
    assert "START weekly-improve.py" in text and "END weekly-improve.py rc=" in text
    rows = [json.loads(l) for l in (tmp_path / "starve.jsonl").read_text().splitlines()]
    assert [(r["loop"], r["inputs"]) for r in rows] == [("weekly-improve", 0)]
    assert "input missing" in text, "the pass names the missing input in its own output"


def test_three_starved_weekly_runs_alert_sana_once(tmp_path):
    """ASK-3402 alarm wired end to end: runner -> loop_starvation.py -> notifier."""
    env = _env(tmp_path)
    for _ in range(4):
        subprocess.run(["bash", str(RUNNER)], capture_output=True, text=True, env=env)
    calls = (tmp_path / "calls.txt").read_text().splitlines()
    assert len(calls) == 1 and "weekly-improve" in calls[0], calls


def test_runner_resolves_in_a_bare_environment(tmp_path):
    """a-scheduled-job-runs-in-a-bare-environment-not-your-shell: no profile,
    no HOME beyond a temp one, a minimal PATH. The dry-run must still resolve
    its own directory and print the order; the real run must still find
    python3 and log the step."""
    bare = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "KIPI_WEEKLY_LOG": str(tmp_path / "w.log"),
            "KIPI_PROPOSALS_INBOX": str(tmp_path / "inbox"),
            "KIPI_FRICTION_FILE": str(tmp_path / "f.jsonl"),
            "KIPI_STARVATION_LEDGER": str(tmp_path / "s.jsonl"),
            "KIPI_STARVATION_NOTIFY": "true",
            "PYTEST_CURRENT_TEST": os.environ.get("PYTEST_CURRENT_TEST", "1")}
    dry = subprocess.run(["/bin/bash", str(RUNNER), "--dry-run"], capture_output=True, text=True, env=bare)
    assert dry.returncode == 0 and dry.stdout.count("would run: ") == 1, dry.stderr
    subprocess.run(["/bin/bash", str(RUNNER)], capture_output=True, text=True, env=bare)
    text = (tmp_path / "w.log").read_text(encoding="utf-8")
    assert text.count("START ") == 1 and text.count("END ") == 1, text[-400:]
    assert (tmp_path / "s.jsonl").exists(), "the starvation record must run in a bare environment too"


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
