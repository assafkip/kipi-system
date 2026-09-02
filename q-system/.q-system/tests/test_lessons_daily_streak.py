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


# ---- issue lr-streak-noop-semantics (Codex finding-10) ----------------------

def _run_summary(tmp_path, summary_json: str):
    """Run the job with a distiller stub emitting `summary_json`. The propagate
    stub exits 99 so a run that wrongly reaches propagation is loud."""
    notify_log = tmp_path / "notify.log"
    env = dict(os.environ,
               KIPI_CLAUDE_BIN="/usr/bin/true",
               KIPI_DISTILL_CMD=f"printf '%s' '{summary_json}'",
               KIPI_PERSIST_CMD="true",
               KIPI_PROPAGATE_CMD="exit 99",
               KIPI_NOTIFY_CMD=f"echo \"$1\" >> '{notify_log}'",
               KIPI_LESSONS_LOG=str(tmp_path / "lessons-daily.log"),
               KIPI_STREAK_FILE=str(tmp_path / "streak.json"),
               KIPI_ESCALATIONS_FILE=str(tmp_path / "escalations.jsonl"),
               KIPI_STREAK_ESCALATE="3")
    return subprocess.run(["/bin/bash", str(JOB)], capture_output=True, text=True, env=env)


NOTHING = json.dumps({"published": [], "held": []})
HELD_ONLY = json.dumps({"published": [], "held": ["something-held"]})


def test_noop_runs_neither_reset_nor_increment_the_streak(tmp_path):
    """fail, fail, nothing-new, nothing-new, held-only, fail leaves the streak at 3."""
    _run(tmp_path, propagate_ok=False)
    _run(tmp_path, propagate_ok=False)
    assert _streak(tmp_path) == 2
    ledger = tmp_path / "escalations.jsonl"
    ledger.write_text('{"at": "2026-01-01T00:00:00+0000", "streak": 7, "threshold": 3, "action": "planted"}\n')
    before = (tmp_path / "streak.json").stat().st_mtime_ns
    ledger_before = (ledger.stat().st_mtime_ns, ledger.read_text())
    for summary in (NOTHING, NOTHING, HELD_ONLY):
        r = _run_summary(tmp_path, summary)
        assert r.returncode == 0, r.stderr[-300:]
    assert _streak(tmp_path) == 2, "a quiet run must not reset the streak"
    assert (tmp_path / "streak.json").stat().st_mtime_ns == before, "a quiet run must not rewrite the streak file"
    assert (ledger.stat().st_mtime_ns, ledger.read_text()) == ledger_before, "a quiet run must not rewrite or truncate an existing ledger"
    r, _ = _run(tmp_path, propagate_ok=False)
    assert r.returncode == 1 and _streak(tmp_path) == 3


def test_noop_runs_with_no_prior_streak_write_no_streak_file(tmp_path):
    for summary in (NOTHING, HELD_ONLY):
        r = _run_summary(tmp_path, summary)
        assert r.returncode == 0
    assert not (tmp_path / "streak.json").exists()
    assert not (tmp_path / "streak.json.lock").exists()


def test_the_rule_is_stated_next_to_the_branch():
    src = JOB.read_text(encoding="utf-8")
    rule = "only a real propagation attempt bumps the streak"
    lines = [l.lower() for l in src.splitlines()]
    rule_at = next((i for i, l in enumerate(lines) if rule in l), None)
    assert rule_at is not None, "the one-sentence rule must sit in the script"
    branch_at = next(i for i, l in enumerate(lines) if 'prop="no propagation (nothing published)"' in l)
    assert 0 < branch_at - rule_at <= 15, f"rule at line {rule_at + 1} is not next to the branch at line {branch_at + 1}"


# ---- issue lr-escalations-ledger-reader (Codex finding-8) --------------------

def _streak_py(tmp_path, *args):
    return subprocess.run([sys.executable, str(STREAK_PY), "--file", str(tmp_path / "streak.json"),
                           "--ledger", str(tmp_path / "escalations.jsonl"), *args],
                          capture_output=True, text=True)


def test_ledger_is_bounded_to_the_last_200_rows(tmp_path):
    for n in range(1, 251):
        assert _streak_py(tmp_path, "append-escalation", "--streak", str(n), "--threshold", "3").returncode == 0
    rows = [json.loads(l) for l in (tmp_path / "escalations.jsonl").read_text().splitlines()]
    assert len(rows) == 200 and rows[0]["streak"] == 51 and rows[-1]["streak"] == 250


def test_summary_reports_streak_and_recent_escalations(tmp_path):
    for _ in range(4):
        _streak_py(tmp_path, "bump", "--outcome", "fail")
    _streak_py(tmp_path, "append-escalation", "--streak", "3", "--threshold", "3")
    _streak_py(tmp_path, "append-escalation", "--streak", "4", "--threshold", "3")
    old = json.dumps({"at": "2020-01-01T00:00:00+0000", "streak": 9, "threshold": 3, "action": "old"})
    with open(tmp_path / "escalations.jsonl", "a") as fh:
        fh.write(old + "\n" + "{not json\n")
    r = _streak_py(tmp_path, "summary")
    assert r.returncode == 0 and r.stdout.strip() == "streak 4, 2 escalations in 30d (1 malformed ledger rows skipped)", r.stdout
    j = json.loads(_streak_py(tmp_path, "summary", "--json").stdout)
    assert j["streak"] == 4 and j["escalations_30d"] == 2 and j["malformed_rows"] == 1
    assert [row["streak"] for row in j["recent"]] == [3, 4]


def test_summary_with_nothing_on_disk_is_zero_not_an_error(tmp_path):
    r = _streak_py(tmp_path, "summary")
    assert r.returncode == 0 and r.stdout.strip() == "streak 0, 0 escalations in 30d"


def test_a_malformed_row_survives_the_next_append_and_stays_counted(tmp_path):
    """Codex (issue 3 standard review): an append that rewrites only the
    parseable rows silently deletes a bad line, so summary can never report it."""
    (tmp_path / "escalations.jsonl").write_text("{not json\n")
    assert _streak_py(tmp_path, "append-escalation", "--streak", "3", "--threshold", "3").returncode == 0
    rows = (tmp_path / "escalations.jsonl").read_text().splitlines()
    assert rows[0] == "{not json" and json.loads(rows[1])["streak"] == 3 and len(rows) == 2
    assert json.loads(_streak_py(tmp_path, "summary", "--json").stdout)["malformed_rows"] == 1


def test_retention_counts_raw_lines_so_a_bad_line_ages_out_not_vanishes(tmp_path):
    (tmp_path / "escalations.jsonl").write_text("{not json\n")
    for n in range(1, 200):
        _streak_py(tmp_path, "append-escalation", "--streak", str(n), "--threshold", "3")
    rows = (tmp_path / "escalations.jsonl").read_text().splitlines()
    assert len(rows) == 200 and rows[0] == "{not json", "199 appends keep the bad line as line 1 of 200"
    _streak_py(tmp_path, "append-escalation", "--streak", "200", "--threshold", "3")
    rows = (tmp_path / "escalations.jsonl").read_text().splitlines()
    assert len(rows) == 200 and json.loads(rows[0])["streak"] == 1, "the 200th append ages the bad line out"


def test_escalated_notify_line_carries_the_summary(tmp_path):
    lines = []
    for _ in range(4):
        _, notify_log = _run(tmp_path, propagate_ok=False)
        lines.append(notify_log.read_text().strip().splitlines()[-1])
    assert "streak 3, 1 escalations in 30d" in lines[2], lines[2]
    assert "streak 4, 2 escalations in 30d" in lines[3], lines[3]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", *sys.argv[1:]]))
