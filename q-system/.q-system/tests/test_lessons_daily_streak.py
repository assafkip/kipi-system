#!/usr/bin/env python3
"""RED FIRST. Issue lr-propagation-streak-escalation (prd-lessons-rail-and-up-rail,
plan 3b). Six identical alarms in five weeks produced no action; the fix is a
streak that changes the line and a logged action. Every seam of
lessons-daily.sh is stubbed through env: no claude, no distiller, no git
commit, no kipi-update.sh, no Slack. The script's own log, streak file and
escalations ledger live in tmp_path.
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
JOB = SCRIPTS / "lessons-daily.sh"
STREAK_PY = SCRIPTS / "lessons_streak.py"
SUMMARY = json.dumps({"published": ["a-lesson"], "held": []})


def _run(tmp_path, propagate_ok: bool, threshold=3):
    notify_log = tmp_path / "notify.log"
    env = dict(os.environ,
               KIPI_CLAUDE_BIN="/usr/bin/true",
               KIPI_DISTILL_CMD=f"printf '%s' '{SUMMARY}'",
               KIPI_PERSIST_CMD="true",
               KIPI_PROPAGATE_CMD="true" if propagate_ok else "false",
               KIPI_NOTIFY_CMD=f"echo \"$1\" >> '{notify_log}'",
               KIPI_LESSONS_LOG=str(tmp_path / "lessons-daily.log"),
               KIPI_STREAK_FILE=str(tmp_path / "streak.json"),
               KIPI_ESCALATIONS_FILE=str(tmp_path / "escalations.jsonl"),
               KIPI_STREAK_ESCALATE=str(threshold))
    r = subprocess.run(["/bin/bash", str(JOB)], capture_output=True, text=True, env=env)
    return r, notify_log


def _streak(tmp_path):
    p = tmp_path / "streak.json"
    return json.loads(p.read_text())["streak"] if p.exists() else None


def test_the_nth_failure_reads_differently_and_records_one_escalation_row(tmp_path):
    lines = []
    for n in range(1, 5):
        r, notify_log = _run(tmp_path, propagate_ok=False)
        assert r.returncode == 1, "a failed propagation still exits 1 (the Linear wire)"
        lines.append(notify_log.read_text().strip().splitlines()[-1])
        assert _streak(tmp_path) == n
    assert "streak" not in lines[0] and "streak" not in lines[1], "below the threshold the line is the ordinary one"
    assert "streak 3" in lines[2] and "streak 4" in lines[3], lines
    assert lines[2] != lines[0], "night 3 must not read like night 1"
    rows = [json.loads(l) for l in (tmp_path / "escalations.jsonl").read_text().splitlines()]
    assert [row["streak"] for row in rows] == [3, 4], "one row per escalating run, none below the threshold"
    assert "ESCALATION streak=3" in (tmp_path / "lessons-daily.log").read_text()


def test_success_resets_the_streak(tmp_path):
    _run(tmp_path, propagate_ok=False)
    _run(tmp_path, propagate_ok=False)
    assert _streak(tmp_path) == 2
    r, _ = _run(tmp_path, propagate_ok=True)
    assert r.returncode == 0 and _streak(tmp_path) == 0
    assert "streak reset after 2" in (tmp_path / "lessons-daily.log").read_text()
    r, _ = _run(tmp_path, propagate_ok=False)
    assert _streak(tmp_path) == 1, "a failure after a reset starts a new streak, not the old one"


def test_a_missing_or_corrupt_streak_file_counts_from_zero(tmp_path):
    (tmp_path / "streak.json").write_text("{not json")
    r, _ = _run(tmp_path, propagate_ok=False)
    assert r.returncode == 1 and _streak(tmp_path) == 1


def test_nothing_new_touches_no_streak_and_exits_0(tmp_path):
    env = dict(os.environ, KIPI_CLAUDE_BIN="/usr/bin/true",
               KIPI_DISTILL_CMD="printf '%s' '{\"published\": [], \"held\": []}'",
               KIPI_LESSONS_LOG=str(tmp_path / "l.log"), KIPI_STREAK_FILE=str(tmp_path / "streak.json"))
    r = subprocess.run(["/bin/bash", str(JOB)], capture_output=True, text=True, env=env)
    assert r.returncode == 0 and not (tmp_path / "streak.json").exists()


def test_production_defaults_are_untouched():
    src = JOB.read_text(encoding="utf-8")
    assert "bash kipi-update.sh" in src and "slack-notify.sh" in src and "lessons-distill.py" in src
    assert 'STREAK_ESCALATE="${KIPI_STREAK_ESCALATE:-3}"' in src


def test_twenty_concurrent_bumps_lose_nothing(tmp_path):
    """Codex finding-9: a scheduled run overlapping a manual run must not lose
    an increment or leave a half-written file."""
    import concurrent.futures
    f = tmp_path / "streak.json"
    cmd = [sys.executable, str(STREAK_PY), "--file", str(f), "bump", "--outcome", "fail"]

    def one(_):
        return subprocess.run(cmd, capture_output=True, text=True).returncode

    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as ex:
        rcs = list(ex.map(one, range(20)))
    assert rcs == [0] * 20
    assert json.loads(f.read_text())["streak"] == 20
    assert not list(tmp_path.glob("streak.json.*")) or list(tmp_path.glob("streak.json.*")) == [tmp_path / "streak.json.lock"], \
        "no temp file may survive a completed bump"


def test_reset_reports_the_previous_streak_from_the_same_locked_call(tmp_path):
    """Codex standard review: a `read` followed by a separate `ok` bump lets a
    concurrent failure land between them. The reset must return what it reset."""
    f = tmp_path / "streak.json"
    for _ in range(3):
        subprocess.run([sys.executable, str(STREAK_PY), "--file", str(f), "bump", "--outcome", "fail"], check=True, capture_output=True)
    out = subprocess.run([sys.executable, str(STREAK_PY), "--file", str(f), "bump", "--outcome", "ok"], capture_output=True, text=True, check=True).stdout
    assert out == "0\t3\n", out
    src = JOB.read_text(encoding="utf-8")
    assert "streak read" not in src, "the job must not read-then-reset in two calls"


def test_reader_never_sees_a_partial_file(tmp_path):
    f = tmp_path / "streak.json"
    subprocess.run([sys.executable, str(STREAK_PY), "--file", str(f), "bump", "--outcome", "fail"], check=True)
    txt = f.read_text()
    assert txt.endswith("\n") and json.loads(txt)["streak"] == 1


def test_only_lessons_streak_writes_the_streak_file():
    """Single-writer chokepoint: the job never writes the streak file or the
    ledger itself; every write goes through lessons_streak.py."""
    src = JOB.read_text(encoding="utf-8")
    assert 'lessons_streak.py' in src
    for bad in ('> "$STREAK_FILE"', '>> "$STREAK_FILE"', '>> "$ESCALATIONS"', '> "$ESCALATIONS"', "streak_write"):
        assert bad not in src, bad
    writers = subprocess.run(["grep", "-rl", "lessons-propagation-streak", str(SCRIPTS)], capture_output=True, text=True).stdout.split()
    assert sorted(Path(w).name for w in writers) == ["lessons-daily.sh", "lessons_streak.py"], writers


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
