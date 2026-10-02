"""The model gate refuses at the choke point, keyed on the item, once-alerted.

why: RCA token-waste-loops (2026-10-02). Every cap was local to one path; a PR took
16 review rounds because the only round cap was keyed on the head sha. These tests
drive the gate and its shell door against temp ledgers and a stub alert command.
Nothing here can reach the live ledger or the live alert path: both are refused by
the module itself under pytest unless a temp path is named.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
from pathlib import Path

import pytest

from voiceloop import model_gate as mg

ROOT = Path(__file__).resolve().parents[4]
DOOR = ROOT / "q-system" / ".q-system" / "scripts" / "model-gate.sh"
DAY = dt.datetime(2026, 10, 5, 12, 0, tzinfo=dt.timezone.utc)


@pytest.fixture
def env(tmp_path, monkeypatch):
    usage = tmp_path / "usage.jsonl"
    alerts = tmp_path / "alerts.txt"
    stub = tmp_path / "notify.sh"
    stub.write_text(f'#!/bin/bash\necho "$*" >> "{alerts}"\n')
    stub.chmod(0o755)
    monkeypatch.setenv("KIPI_USAGE_LEDGER", str(usage))
    monkeypatch.setenv("KIPI_MODEL_GATE_LEDGER", str(tmp_path / "gate.jsonl"))
    monkeypatch.setenv("KIPI_MODEL_GATE_NOTIFY", str(stub))
    for k in list(os.environ):
        if k.startswith("KIPI_MODEL_GATE_USD_") or k in (
                "KIPI_MODEL_GATE_MODE", "KIPI_MODEL_GATE_JOB_USD", "KIPI_MODEL_GATE_FLEET_USD",
                "KIPI_MODEL_GATE_ROUNDS", "KIPI_MODEL_GATE_UNSETTLED_USD"):
            monkeypatch.delenv(k)
    return {"usage": usage, "alerts": alerts, "tmp": tmp_path}


def spent(env, bot, usd, day="2026-10-05"):
    with open(env["usage"], "a") as fh:
        fh.write(json.dumps({"ts": f"{day}T01:00:00Z", "bot": bot, "total_cost_usd": usd}) + "\n")


def alerts(env):
    return env["alerts"].read_text().splitlines() if env["alerts"].exists() else []


def test_enforce_refuses_a_job_over_its_daily_budget(env, monkeypatch):
    monkeypatch.setenv("KIPI_MODEL_GATE_MODE", "enforce")
    spent(env, "lgtm", 26.0)
    row = mg.check("lgtm", now=DAY)
    assert row["admit"] is False and row["reasons"] == ["job_budget"]
    assert mg.check("radar", now=DAY)["admit"] is True  # another job is untouched


def test_report_mode_admits_but_logs_and_alerts(env, monkeypatch):
    monkeypatch.setenv("KIPI_MODEL_GATE_MODE", "report")
    spent(env, "lgtm", 26.0)
    row = mg.check("lgtm", now=DAY)
    assert row["admit"] is True and row["reasons"] == ["job_budget"]
    assert len(alerts(env)) == 1 and "would refuse" in alerts(env)[0]


def test_one_alert_per_job_limit_and_day(env, monkeypatch):
    monkeypatch.setenv("KIPI_MODEL_GATE_MODE", "enforce")
    spent(env, "lgtm", 26.0)
    for _ in range(5):
        mg.check("lgtm", now=DAY)
    assert len(alerts(env)) == 1


def test_fleet_ceiling_refuses_every_job(env, monkeypatch):
    monkeypatch.setenv("KIPI_MODEL_GATE_MODE", "enforce")
    for bot in ("a", "b", "c", "d", "e"):
        spent(env, bot, 20.0)
    assert mg.check("fresh-job", now=DAY)["reasons"] == ["fleet_ceiling"]


def test_round_cap_is_keyed_on_the_item_not_the_sha(env, monkeypatch):
    """The 16-round PR: each fix commit changed the sha. The item does not change."""
    monkeypatch.setenv("KIPI_MODEL_GATE_MODE", "enforce")
    got = [mg.check("pr-review", item="owner/repo#421", now=DAY)["admit"] for _ in range(4)]
    assert got == [True, True, True, False]
    assert mg.check("pr-review", item="owner/repo#422", now=DAY)["admit"] is True


def test_report_week_rounds_do_not_count_after_the_flip(env, monkeypatch):
    monkeypatch.setenv("KIPI_MODEL_GATE_MODE", "report")
    for _ in range(5):
        mg.check("pr-review", item="owner/repo#9", now=DAY)
    monkeypatch.setenv("KIPI_MODEL_GATE_MODE", "enforce")
    assert mg.check("pr-review", item="owner/repo#9", now=DAY)["admit"] is True


def test_default_mode_flips_on_the_enforce_date(env):
    assert mg.mode(dt.datetime(2026, 10, 8, 23, tzinfo=dt.timezone.utc)) == "report"
    assert mg.mode(dt.datetime(2026, 10, 9, 0, tzinfo=dt.timezone.utc)) == "enforce"


def test_a_typo_in_the_mode_does_not_switch_the_gate_off(env, monkeypatch):
    monkeypatch.setenv("KIPI_MODEL_GATE_MODE", "reprot")
    assert mg.mode(dt.datetime(2026, 10, 9, tzinfo=dt.timezone.utc)) == "enforce"


def test_unsettled_calls_are_charged_so_parallel_calls_cannot_all_pass(env, monkeypatch):
    """No usage row has landed yet, so a $0 reading would admit every call."""
    monkeypatch.setenv("KIPI_MODEL_GATE_MODE", "enforce")
    monkeypatch.setenv("KIPI_MODEL_GATE_JOB_USD", "3")
    got = [mg.check("bot", now=DAY)["admit"] for _ in range(5)]
    assert got == [True, True, True, False, False]


def test_a_cost_less_failure_row_is_charged_not_free(env, monkeypatch):
    monkeypatch.setenv("KIPI_MODEL_GATE_MODE", "enforce")
    monkeypatch.setenv("KIPI_MODEL_GATE_JOB_USD", "2")
    spent(env, "bot", None)
    spent(env, "bot", None)
    assert mg.check("bot", now=DAY)["admit"] is False


def test_per_job_budget_override(env, monkeypatch):
    monkeypatch.setenv("KIPI_MODEL_GATE_MODE", "enforce")
    monkeypatch.setenv("KIPI_MODEL_GATE_USD_VOICE_LOOP", "500")
    spent(env, "voice-loop", 60.0)
    assert mg.check("voice-loop", now=DAY)["admit"] is True


def test_a_corrupt_ledger_fails_closed_in_enforce_and_alerts_once(env, monkeypatch):
    monkeypatch.setenv("KIPI_MODEL_GATE_MODE", "enforce")
    (env["tmp"] / "gate.jsonl").write_text("{not json\n" + json.dumps({"kind": "call"}) + "\n")
    rows = [mg.check("bot", now=DAY) for _ in range(3)]
    assert all(r["admit"] is False and r["reasons"] == ["gate_error"] for r in rows)
    assert len(alerts(env)) == 1
    monkeypatch.setenv("KIPI_MODEL_GATE_MODE", "report")
    assert mg.check("bot", now=DAY)["admit"] is True


def test_under_pytest_the_live_ledger_is_refused(monkeypatch):
    monkeypatch.delenv("KIPI_MODEL_GATE_LEDGER", raising=False)
    monkeypatch.delenv("KIPI_USAGE_LEDGER", raising=False)
    with pytest.raises(mg.GateError):
        mg.check("bot", now=DAY)


def _door(env, *args, extra=None):
    e = dict(os.environ)
    e.pop("PYTEST_CURRENT_TEST", None)
    e.update(extra or {})
    return subprocess.run(["bash", str(DOOR), *args], capture_output=True, text=True, env=e, timeout=60)


def test_door_refusal_never_runs_the_command_and_exits_75(env, monkeypatch):
    monkeypatch.setenv("KIPI_MODEL_GATE_MODE", "enforce")
    spent(env, "lgtm", 99.0, day=dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d"))
    marker = env["tmp"] / "ran"
    r = _door(env, "--job", "lgtm", "--", "bash", "-c", f"touch {marker}")
    assert r.returncode == 75 and "MODEL_GATE_REFUSED" in r.stderr
    assert not marker.exists()


def test_door_admits_passes_stdout_and_records_the_measured_cost(env, monkeypatch):
    monkeypatch.setenv("KIPI_MODEL_GATE_MODE", "enforce")
    doc = {"type": "result", "subtype": "success", "is_error": False, "result": "hi",
           "total_cost_usd": 0.42, "modelUsage": {}}
    r = _door(env, "--job", "door-job", "--item", "owner/repo#1", "--",
              "printf", "%s", json.dumps(doc))
    assert r.returncode == 0 and json.loads(r.stdout)["result"] == "hi"
    rows = [json.loads(x) for x in env["usage"].read_text().splitlines()]
    assert rows[-1]["bot"] == "door-job" and rows[-1]["total_cost_usd"] == 0.42


def test_door_fails_closed_when_the_gate_cannot_run(env, monkeypatch):
    marker = env["tmp"] / "ran"
    r = _door(env, "--job", "x", "--", "bash", "-c", f"touch {marker}",
              extra={"KIPI_MODEL_GATE_PKG": str(env["tmp"] / "nowhere")})
    assert r.returncode == 75 and "MODEL_GATE_ERROR" in r.stderr and not marker.exists()
    assert len(alerts(env)) == 1


# --- review round 1 (PR #503, #504) -------------------------------------------


def test_a_torn_last_line_does_not_brick_the_gate(env, monkeypatch):
    monkeypatch.setenv("KIPI_MODEL_GATE_MODE", "enforce")
    mg.check("bot", now=DAY)
    with open(env["tmp"] / "gate.jsonl", "a") as fh:
        fh.write('{"kind": "call", "job": "vo')  # a crash mid-append
    rows = [mg.check("bot", now=DAY) for _ in range(3)]
    assert all(r["kind"] == "call" for r in rows)


def test_known_free_rows_are_not_charged(env, monkeypatch):
    monkeypatch.setenv("KIPI_MODEL_GATE_MODE", "enforce")
    monkeypatch.setenv("KIPI_MODEL_GATE_JOB_USD", "2")
    with open(env["usage"], "a") as fh:
        for sub in ("failed:no-binary", "unmetered:opencode", "failed:no-binary"):
            fh.write(json.dumps({"ts": "2026-10-05T01:00:00Z", "bot": "bot",
                                 "total_cost_usd": None, "subtype": sub}) + "\n")
    assert mg.check("bot", now=DAY)["admit"] is True


def test_the_fleet_ceiling_alerts_once_for_the_fleet(env, monkeypatch):
    monkeypatch.setenv("KIPI_MODEL_GATE_MODE", "report")
    spent(env, "big", 150.0)
    monkeypatch.setenv("KIPI_MODEL_GATE_USD_BIG", "1000")
    for job in ("a", "b", "c", "big"):
        mg.check(job, now=DAY)
    assert sum("fleet_ceiling" in a for a in alerts(env)) == 1


def test_the_round_cap_is_per_item_across_jobs(env, monkeypatch):
    monkeypatch.setenv("KIPI_MODEL_GATE_MODE", "enforce")
    for job in ("review-a", "review-b", "review-c"):
        mg.check(job, item="owner/repo#7", now=DAY)
    assert mg.check("review-d", item="owner/repo#7", now=DAY)["admit"] is False


def test_the_round_window_releases_a_long_lived_item(env, monkeypatch):
    monkeypatch.setenv("KIPI_MODEL_GATE_MODE", "enforce")
    old = DAY - dt.timedelta(days=8)
    for _ in range(3):
        mg.check("w", item="ASK-45", now=old)
    assert mg.check("w", item="ASK-45", now=DAY)["admit"] is True


def test_yesterdays_spend_does_not_count_today(env, monkeypatch):
    monkeypatch.setenv("KIPI_MODEL_GATE_MODE", "enforce")
    spent(env, "lgtm", 99.0, day="2026-10-04")
    assert mg.check("lgtm", now=DAY)["admit"] is True


def test_door_refuses_a_flag_with_no_value(env):
    r = _door(env, "--job")
    assert r.returncode == 2


# --- review round 2 (PR #503, #504; ASK-2401) ---------------------------------


def test_usage_rows_from_other_paths_do_not_cancel_the_in_flight_charge(env, monkeypatch):
    """120 cheap rows the bot wrote outside the gate used to zero every in-flight call."""
    monkeypatch.setenv("KIPI_MODEL_GATE_MODE", "enforce")
    monkeypatch.setenv("KIPI_MODEL_GATE_JOB_USD", "3")
    for _ in range(120):
        spent(env, "bot", 0.0)
    got = [mg.check("bot", now=DAY)["admit"] for _ in range(5)]
    assert got == [True, True, True, False, False]
    mg.settle("bot", now=DAY)
    assert mg.check("bot", now=DAY)["admit"] is True  # a settled call frees its estimate


def test_door_charges_nothing_for_a_binary_that_never_started(env, monkeypatch):
    monkeypatch.setenv("KIPI_MODEL_GATE_MODE", "enforce")
    monkeypatch.setenv("KIPI_MODEL_GATE_JOB_USD", "2")
    codes = [_door(env, "--job", "radar", "--", str(env["tmp"] / "no-such-claude"), "-p", "x").returncode
             for _ in range(4)]
    assert codes == [127, 127, 127, 127]
    subs = [json.loads(x)["subtype"] for x in env["usage"].read_text().splitlines()]
    assert subs == ["failed:no-binary"] * 4
    assert mg.check("radar")["admit"] is True and alerts(env) == []


def test_a_failed_alert_is_recorded_and_retried_not_a_gate_error(env, monkeypatch):
    monkeypatch.setenv("KIPI_MODEL_GATE_MODE", "enforce")
    calls = env["tmp"] / "notify-calls"
    fail = env["tmp"] / "fail.sh"
    fail.write_text(f'#!/bin/bash\necho x >> "{calls}"\nexit 1\n')
    fail.chmod(0o755)
    monkeypatch.setenv("KIPI_MODEL_GATE_NOTIFY", str(fail))
    spent(env, "lgtm", 26.0)
    rows = [mg.check("lgtm", now=DAY) for _ in range(2)]
    assert [r["kind"] for r in rows] == ["refusal", "refusal"]
    kinds = [json.loads(x)["kind"] for x in (env["tmp"] / "gate.jsonl").read_text().splitlines()]
    assert kinds.count("alert-failed") == 2
    assert len(calls.read_text().splitlines()) == 2  # the second call retried the send


def test_an_unmetered_but_billed_call_is_charged(env, monkeypatch):
    """cli:no-json-flag is a real call with an unknown cost, not a free one."""
    monkeypatch.setenv("KIPI_MODEL_GATE_MODE", "enforce")
    monkeypatch.setenv("KIPI_MODEL_GATE_JOB_USD", "2")
    with open(env["usage"], "a") as fh:
        for _ in range(2):
            fh.write(json.dumps({"ts": "2026-10-05T01:00:00Z", "bot": "bot", "total_cost_usd": None,
                                 "subtype": "unmetered:cli:no-json-flag"}) + "\n")
    assert mg.check("bot", now=DAY)["admit"] is False
