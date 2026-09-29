"""The hard per-run cap in the voiceloop wrapper (ASK-2011, Step 5).

Every assertion about what a capped run looks like reads the REAL capture in
`fixtures/claude-p-cap-hits-capture.json` (producer: `capture_cap_hits.py` beside
it, two live Haiku calls on 2026-09-29). Nothing here invents a cap document: the
whole question this step answers is what the CLI actually does when it stops a run,
and an invented fixture would test the assumption instead of the CLI.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from voiceloop import prompt_render, usage_ledger  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "fixtures", "claude-p-cap-hits-capture.json")


@pytest.fixture(scope="module")
def captured():
    with open(FIXTURE, encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    """No test may read the machine's live ledger or caps file."""
    monkeypatch.setenv(usage_ledger.LEDGER_ENV, str(tmp_path / "ledger.jsonl"))
    monkeypatch.setenv(usage_ledger.CAPS_ENV, str(tmp_path / "caps.json"))
    monkeypatch.delenv(usage_ledger.TURNS_ENV, raising=False)
    monkeypatch.delenv(usage_ledger.BUDGET_ENV, raising=False)


# --------------------------------------------------------- what the CLI does

@pytest.mark.parametrize("case,subtype", [("turn_cap", "error_max_turns"),
                                          ("budget_cap", "error_max_budget_usd")])
def test_the_capture_is_a_real_cap_hit(captured, case, subtype):
    """The premise. If the CLI stops naming caps this way, this test says so first."""
    run = captured[case]
    doc = json.loads(run["stdout"])
    assert doc["subtype"] == subtype
    assert doc["is_error"] is True
    assert run["returncode"] != 0
    # EMPTY stderr is why the cap lands on the wrapper's generic exit arm: there is
    # no rejected-flag text to route it anywhere else.
    assert run["stderr"] == ""
    # The tokens up to the cap were spent. A cap row with no cost would under-report.
    assert doc["total_cost_usd"] > 0


# ------------------------------------------------- the row names the cap (RED first)

@pytest.mark.parametrize("case,subtype", [("turn_cap", "error_max_turns"),
                                          ("budget_cap", "error_max_budget_usd")])
def test_a_capped_run_records_the_cap_subtype(captured, case, subtype):
    """Before ASK-2011 this row read `failed:exit 1` and the cap was invisible."""
    run = captured[case]
    row = usage_ledger.failure_row(f"exit {run['returncode']}", bot="voiceloop",
                                   job="test", stdout=run["stdout"], stderr=run["stderr"])
    assert row["subtype"] == subtype
    assert usage_ledger.is_cap_hit(row) is True
    # Still a failure, one kind per refusal (chief PR #34 round 1), and the spend is kept.
    assert row["kind"] == "failure"
    assert row["is_error"] is True
    assert row["total_cost_usd"] == json.loads(run["stdout"])["total_cost_usd"]


def test_an_ordinary_non_zero_exit_is_not_a_cap_hit():
    """The guard cannot fire on every failure, or the brake counts crashes as caps."""
    row = usage_ledger.failure_row("exit 137", bot="voiceloop", stderr="Killed")
    assert row["subtype"] == "failed:exit 137"
    assert usage_ledger.is_cap_hit(row) is False


def test_a_successful_run_is_not_a_cap_hit(captured):
    doc = {"type": "result", "subtype": "success", "is_error": False,
           "result": "pong", "num_turns": 1, "total_cost_usd": 0.01}
    text, row = usage_ledger.finish(json.dumps(doc), bot="voiceloop")
    assert text == "pong\n"
    assert usage_ledger.is_cap_hit(row) is False


# --------------------------------------------------------------- the argv carries it

def test_the_argv_carries_both_flags(monkeypatch, tmp_path):
    """The DoR's first check: `the argv carries the flags`."""
    seen = {}

    def fake_run(argv, **kw):
        seen["argv"] = argv
        return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(
            {"type": "result", "subtype": "success", "is_error": False,
             "result": "ok", "num_turns": 1, "total_cost_usd": 0.01}), stderr="")

    binary = tmp_path / "claude"
    binary.write_text("#!/bin/sh\n")
    monkeypatch.setattr(prompt_render.subprocess, "run", fake_run)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    assert prompt_render.run_model("hi", str(binary)) == "ok\n"
    argv = seen["argv"]
    assert usage_ledger.TURNS_FLAG in argv
    assert usage_ledger.BUDGET_FLAG in argv
    # A flag with no value is a flag the CLI rejects.
    assert int(argv[argv.index(usage_ledger.TURNS_FLAG) + 1]) >= usage_ledger.MIN_TURNS
    assert float(argv[argv.index(usage_ledger.BUDGET_FLAG) + 1]) >= usage_ledger.MIN_BUDGET_USD


def test_a_capped_live_run_is_handled_not_crashed(captured, monkeypatch, tmp_path):
    """The DoR's second check: a real captured capped run parses and is handled."""
    run = captured["turn_cap"]
    ledger = tmp_path / "ledger.jsonl"
    monkeypatch.setenv(usage_ledger.LEDGER_ENV, str(ledger))

    def fake_run(argv, **kw):
        return subprocess.CompletedProcess(argv, run["returncode"],
                                           stdout=run["stdout"], stderr=run["stderr"])

    binary = tmp_path / "claude"
    binary.write_text("#!/bin/sh\n")
    monkeypatch.setattr(prompt_render.subprocess, "run", fake_run)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    assert prompt_render.run_model("hi", str(binary)) is None  # handled, no raise
    rows = usage_ledger.read(str(ledger))
    assert len(rows) == 1
    assert rows[0]["subtype"] == "error_max_turns"


# ------------------------------------------------------------- the fallback strip

def test_the_fallback_drops_the_cap_flags_with_their_values():
    argv = ["claude", "--model", "m", "-p", "hi", "--output-format", "json",
            "--max-turns", "24", "--max-budget-usd", "1.5"]
    assert usage_ledger.without_added_flags(argv) == ["claude", "--model", "m", "-p", "hi"]


def test_an_unknown_cap_flag_is_a_rejected_flag():
    assert usage_ledger.rejected_flag("error: unknown option '--max-turns'") is True
    assert usage_ledger.rejected_flag("error: unrecognized --max-budget-usd") is True
    # Not every error names a flag we add.
    assert usage_ledger.rejected_flag("error: API overloaded") is False


def test_an_old_binary_still_answers(monkeypatch, tmp_path):
    """The blast radius: a binary that refuses a cap flag must not darken the fleet."""
    calls = []

    def fake_run(argv, **kw):
        calls.append(argv)
        if usage_ledger.TURNS_FLAG in argv:
            return subprocess.CompletedProcess(argv, 2, stdout="",
                                               stderr="error: unknown option '--max-turns'")
        return subprocess.CompletedProcess(argv, 0, stdout="pong\n", stderr="")

    binary = tmp_path / "claude"
    binary.write_text("#!/bin/sh\n")
    monkeypatch.setattr(prompt_render.subprocess, "run", fake_run)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    assert prompt_render.run_model("hi", str(binary)) == "pong\n"
    assert usage_ledger.BUDGET_FLAG not in calls[1]
    assert "json" not in calls[1]


# ------------------------------------------------------------------ sizing the caps

def _run_row(bot, turns, cost):
    return {"kind": "run", "bot": bot, "num_turns": turns, "total_cost_usd": cost}


def test_size_caps_is_three_times_the_median():
    rows = [_run_row("chief", 4, 1.0), _run_row("chief", 10, 3.0), _run_row("chief", 30, 9.0)]
    sized = usage_ledger.size_caps(rows)
    assert sized["chief"]["turns"] == 30      # 3 x median 10
    assert sized["chief"]["budget_usd"] == 9.0  # 3 x median 3.0
    assert sized["chief"]["runs"] == 3


def test_size_caps_never_sizes_below_the_floor():
    """3x a one-turn median is 3 turns, which would cap every real run."""
    sized = usage_ledger.size_caps([_run_row("tiny", 1, 0.001)])
    assert sized["tiny"]["turns"] == usage_ledger.MIN_TURNS
    assert sized["tiny"]["budget_usd"] == usage_ledger.MIN_BUDGET_USD


def test_size_caps_ignores_failure_rows():
    """A failure row carries no num_turns; counting it drags the median to the floor."""
    rows = [_run_row("chief", 20, 6.0), _run_row("chief", 20, 6.0),
            {"kind": "failure", "bot": "chief", "num_turns": None, "total_cost_usd": None}]
    assert usage_ledger.size_caps(rows)["chief"]["runs"] == 2
    assert usage_ledger.size_caps(rows)["chief"]["turns"] == 60


def test_caps_for_reads_the_sized_file(tmp_path, monkeypatch):
    caps = tmp_path / "caps.json"
    caps.write_text(json.dumps({"chief": {"turns": 30, "budget_usd": 9.0}}))
    monkeypatch.setenv(usage_ledger.CAPS_ENV, str(caps))
    assert usage_ledger.caps_for("chief") == (30, 9.0)
    assert usage_ledger.caps_for("unknown-bot") == (usage_ledger.MIN_TURNS,
                                                   usage_ledger.MIN_BUDGET_USD)


def test_caps_for_survives_a_missing_or_broken_file(tmp_path, monkeypatch):
    monkeypatch.setenv(usage_ledger.CAPS_ENV, str(tmp_path / "absent.json"))
    assert usage_ledger.caps_for("chief") == (usage_ledger.MIN_TURNS,
                                             usage_ledger.MIN_BUDGET_USD)
    broken = tmp_path / "broken.json"
    broken.write_text("{not json")
    monkeypatch.setenv(usage_ledger.CAPS_ENV, str(broken))
    assert usage_ledger.caps_for("chief") == (usage_ledger.MIN_TURNS,
                                             usage_ledger.MIN_BUDGET_USD)


def test_the_env_override_wins_and_is_not_floored(monkeypatch):
    monkeypatch.setenv(usage_ledger.TURNS_ENV, "1")
    monkeypatch.setenv(usage_ledger.BUDGET_ENV, "0.01")
    assert usage_ledger.caps_for("chief") == (1, 0.01)


def test_the_per_call_path_never_reads_the_ledger(monkeypatch):
    """The ledger grows without bound; caps_for is on every bot's hot path."""
    def boom(*a, **k):
        raise AssertionError("caps_for read the ledger")
    monkeypatch.setattr(usage_ledger, "read", boom)
    usage_ledger.cap_args("chief")


# ------------------------------------------------- what the Step 4 brake will read

def _cap_row(bot, ts):
    return {"kind": "failure", "bot": bot, "subtype": "error_max_turns", "ts": ts}


def test_cap_hits_counts_only_this_bot_inside_the_window():
    import datetime as dt
    now = dt.datetime(2026, 9, 29, 12, 0, tzinfo=dt.timezone.utc)
    rows = [
        _cap_row("chief", "2026-09-29T11:00:00Z"),   # in
        _cap_row("chief", "2026-09-28T13:00:00Z"),   # in (23h)
        _cap_row("chief", "2026-09-28T11:00:00Z"),   # out (25h)
        _cap_row("research", "2026-09-29T11:30:00Z"),  # other bot
        {"kind": "failure", "bot": "chief", "subtype": "failed:exit 1",
         "ts": "2026-09-29T11:45:00Z"},              # not a cap
        _cap_row("chief", "not-a-timestamp"),        # unreadable
    ]
    assert usage_ledger.cap_hits("chief", rows=rows, now=now) == 2
    assert usage_ledger.cap_hits("research", rows=rows, now=now) == 1


def test_three_hits_is_the_documented_pause_threshold():
    """Step 4 (ASK-2010) reads this constant; the DoR's number is 3 in 24 hours."""
    assert usage_ledger.CAP_HITS_TO_PAUSE == 3
    assert usage_ledger.CAP_WINDOW_HOURS == 24


# ----------------------------------------------- the sizing pass WRITES the file

def test_the_sizing_pass_writes_the_file_caps_for_reads(tmp_path, monkeypatch):
    """Without a writer, `caps_for` never finds a file and every bot runs on floors.

    The DoR says "sized at 3x each bot's median from the ledger". `size_caps`
    computes it and nothing persisted it, so the sized number reached no run.
    """
    ledger = tmp_path / "ledger.jsonl"
    with open(ledger, "w", encoding="utf-8") as fh:
        for turns, cost in ((10, 3.0), (20, 6.0), (30, 9.0)):
            fh.write(json.dumps({"kind": "run", "bot": "chief",
                                 "num_turns": turns, "total_cost_usd": cost}) + "\n")
    monkeypatch.setenv(usage_ledger.LEDGER_ENV, str(ledger))
    caps = tmp_path / "nested" / "caps.json"      # the parent does not exist yet
    monkeypatch.setenv(usage_ledger.CAPS_ENV, str(caps))

    sized = usage_ledger.write_caps()
    assert sized["chief"]["turns"] == 60          # 3 x median 20
    assert json.loads(caps.read_text())["chief"]["budget_usd"] == 18.0
    # The point of writing it: the per-call path now reads a SIZED cap, not a floor.
    assert usage_ledger.caps_for("chief") == (60, 18.0)


def test_the_sizing_pass_is_reachable_as_a_command(tmp_path, monkeypatch):
    """A function with no entry point is a cap nobody ever sizes."""
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(json.dumps({"kind": "run", "bot": "chief",
                                  "num_turns": 20, "total_cost_usd": 6.0}) + "\n")
    caps = tmp_path / "caps.json"
    env = dict(os.environ, **{usage_ledger.LEDGER_ENV: str(ledger),
                              usage_ledger.CAPS_ENV: str(caps)})
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    proc = subprocess.run([sys.executable, "-m", "voiceloop.usage_ledger", "size-caps"],
                          cwd=root, env=env, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(caps.read_text())["chief"] == {"turns": 60, "budget_usd": 18.0, "runs": 1}
