#!/usr/bin/env python3
"""A test never writes the live attempts ledger (ASK-4052).

RED FIRST. On main attempts-ledger.py writes wherever it is pointed, so a write to
<temp HOME>/.config/kipi/linear-worker-attempts.json under pytest succeeds.

NEVER A LIVE PATH. Every case points HOME at tmp_path, and no case names the real
account home, so even on main nothing here touches the founder's ledger.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
LEDGER = HERE.parent / "scripts" / "attempts-ledger.py"
NAME = "linear-worker-attempts.json"


def run(home, path, *args, pytest_var=True, kipi_test=None):
    env = {k: v for k, v in os.environ.items() if k not in ("PYTEST_CURRENT_TEST", "KIPI_TEST")}
    env["HOME"] = str(home)
    if pytest_var:
        env["PYTEST_CURRENT_TEST"] = os.environ.get("PYTEST_CURRENT_TEST") or "x"
    if kipi_test is not None:
        env["KIPI_TEST"] = kipi_test
    return subprocess.run([sys.executable, str(LEDGER), str(path), *args],
                          capture_output=True, text=True, env=env)


def live(home):
    p = home / ".config" / "kipi" / NAME
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def test_a_write_to_the_ledger_under_home_is_refused_under_pytest(tmp_path):
    p = live(tmp_path)
    r = run(tmp_path, p, "bump-attempt", "ASK-1", "a test forgot KIPI_STATE_DIR")
    assert r.returncode == 5, r.stderr
    assert "KIPI_STATE_DIR" in r.stderr and not p.exists()


def test_kipi_test_alone_refuses_too(tmp_path):
    """The shell suites carry KIPI_TEST=1 from capability-gate.py, not pytest's variable."""
    p = live(tmp_path)
    r = run(tmp_path, p, "claim-flag", "ASK-1", "drift_paged", pytest_var=False, kipi_test="1")
    assert r.returncode == 5 and not p.exists()


def test_a_state_dir_path_is_written(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    p = state / NAME
    r = run(tmp_path, p, "bump-attempt", "ASK-1", "fixture")
    assert r.returncode == 0, r.stderr
    assert json.loads(p.read_text())["ASK-1"]["count"] == 1


def test_reads_stay_allowed(tmp_path):
    p = live(tmp_path)
    p.write_text(json.dumps({"ASK-1": {"count": 2}}))
    r = run(tmp_path, p, "get", "ASK-1", "count")
    assert r.returncode == 0 and r.stdout.strip() == "2"


def test_production_writes_the_live_path(tmp_path):
    """Neither variable set: the guard is silent, so production is unchanged."""
    p = live(tmp_path)
    r = run(tmp_path, p, "bump-attempt", "ASK-1", "a real run", pytest_var=False)
    assert r.returncode == 0, r.stderr
    assert json.loads(p.read_text())["ASK-1"]["count"] == 1


def test_the_shell_suites_get_kipi_test_from_their_runner():
    src = (HERE.parent / "scripts" / "capability-gate.py").read_text()
    assert 'KIPI_TEST="1"' in src
