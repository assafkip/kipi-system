#!/usr/bin/env python3
"""ASK-3402 cross-cutting alarm. Every path is a tmp_path file; the notifier is
a stub that appends to a tmp file, so nothing touches the live ledger or Linear.
Run through pytest with the repo's addopts, never as loose scratch code.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "scripts" / "loop_starvation.py"


def _env(tmp_path, threshold=None, notify_rc=0):
    calls = tmp_path / "calls.txt"
    stub = tmp_path / "notify.sh"
    stub.write_text(f'#!/bin/bash\necho "$1" >> "{calls}"\nexit {notify_rc}\n')
    env = dict(os.environ, KIPI_STARVATION_LEDGER=str(tmp_path / "ledger.jsonl"),
               KIPI_STARVATION_NOTIFY=f"bash {stub}")
    env.pop("KIPI_STARVATION_THRESHOLD", None)
    if threshold:
        env["KIPI_STARVATION_THRESHOLD"] = str(threshold)
    return env, calls


def _rec(env, loop, n, *extra):
    return subprocess.run([sys.executable, str(SCRIPT), "record", loop, str(n), *extra],
                          capture_output=True, text=True, env=env)


def _n_calls(calls):
    return len(calls.read_text().splitlines()) if calls.exists() else 0


def test_three_zero_runs_alert_once_and_a_fourth_does_not_repeat(tmp_path):
    env, calls = _env(tmp_path)
    for _ in range(2):
        assert _rec(env, "weekly-improve", 0).returncode == 0
    assert _n_calls(calls) == 0, "two zero runs are below the threshold"
    _rec(env, "weekly-improve", 0)
    assert _n_calls(calls) == 1
    assert "weekly-improve" in calls.read_text() and "loop_starvation.py" in calls.read_text(), "names loop and emitter"
    _rec(env, "weekly-improve", 0)
    _rec(env, "weekly-improve", 0)
    assert _n_calls(calls) == 1, "state change only: no second alert while still starved"


def test_a_nonzero_run_resets_the_counter_and_the_next_starvation_alerts_again(tmp_path):
    env, calls = _env(tmp_path)
    for _ in range(3):
        _rec(env, "L", 0)
    assert _n_calls(calls) == 1
    _rec(env, "L", 5)
    _rec(env, "L", 0)
    _rec(env, "L", 0)
    assert _n_calls(calls) == 1, "counter reset: two zeros after input is below threshold"
    _rec(env, "L", 0)
    assert _n_calls(calls) == 2


def test_loops_are_counted_separately(tmp_path):
    env, calls = _env(tmp_path)
    for loop in ("a", "b", "a", "b", "a"):
        _rec(env, loop, 0)
    assert _n_calls(calls) == 1 and "a" in calls.read_text().split("loop starved: ")[1].split()[0]


def test_a_failed_filing_is_retried_on_the_next_zero_run(tmp_path):
    env, calls = _env(tmp_path, notify_rc=1)
    for _ in range(4):
        _rec(env, "L", 0)
    assert _n_calls(calls) == 2, "alerted flag is only set when the notifier exited 0"


def test_threshold_override_and_the_threshold_mutant(tmp_path):
    env, calls = _env(tmp_path, threshold=2)
    _rec(env, "L", 0)
    _rec(env, "L", 0)
    assert _n_calls(calls) == 1, "env override of 2 fires on the second zero"
    # Mutant: the same sequence with the off-by-one the check must catch. If the
    # comparison were `> threshold` the second zero would not fire; prove the
    # module's own comparison is `>=` by loading it and flipping it.
    src = SCRIPT.read_text()
    assert "len(run) >= threshold" in src
    mutant = tmp_path / "mut.py"
    mutant.write_text(src.replace("len(run) >= threshold", "len(run) > threshold"))
    spec = importlib.util.spec_from_file_location("mut", mutant)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    env2, calls2 = _env(tmp_path / "m" if (tmp_path / "m").mkdir() is None else tmp_path, threshold=2)
    os.environ.update({k: env2[k] for k in ("KIPI_STARVATION_LEDGER", "KIPI_STARVATION_NOTIFY")})
    try:
        mod.record("L", 0, 2)
        mod.record("L", 0, 2)
    finally:
        os.environ.pop("KIPI_STARVATION_LEDGER")
        os.environ.pop("KIPI_STARVATION_NOTIFY")
    assert _n_calls(calls2) == 0, "mutant (> instead of >=) does not fire at 2: the real test above would be red"


def test_ledger_rows_are_append_only_records(tmp_path):
    env, _ = _env(tmp_path)
    _rec(env, "L", 0)
    _rec(env, "L", 3)
    rows = [json.loads(l) for l in (tmp_path / "ledger.jsonl").read_text().splitlines()]
    assert [r["inputs"] for r in rows] == [0, 3] and all({"loop", "at", "inputs", "alerted"} <= set(r) for r in rows)


def test_lessons_daily_is_wired_to_candidates_never_to_scanned():
    """PR #572 review: `scanned` is zero on a quiet night by design, so wiring it
    files a ticket for routine operation. ASK-3516 wires the intake count instead."""
    text = (HERE.parent / "scripts" / "lessons-daily.sh").read_text(encoding="utf-8")
    assert 'record lessons-daily "$CAND"' in text and "d.get('candidates')" in text
    assert "record lessons-daily \"$SCANNED" not in text and "normal quiet night" in text


def test_a_corrupt_friction_ledger_is_not_counted_as_zero(tmp_path):
    bad = tmp_path / "f.jsonl"
    bad.write_text("{not json\n")
    r = subprocess.run([sys.executable, str(HERE.parent / "scripts" / "weekly-improve.py"), "--count-inputs", "--friction", str(bad)],
                       capture_output=True, text=True)
    assert r.returncode == 1 and r.stdout.strip() == ""
