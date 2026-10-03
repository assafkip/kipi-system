"""The call-count model gate. Every ledger, marker and alert sink is a temp path."""
import datetime as dt
import json
import os
import re
import subprocess
import sys

import pytest

PKG = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PKG)

from voiceloop import model_gate, prompt_render  # noqa: E402

DOOR = os.path.join(PKG, "..", "..", "q-system", ".q-system", "scripts", "model-gate.sh")
BEFORE = dt.datetime(2026, 10, 9, 12, tzinfo=dt.timezone.utc)
AFTER = dt.datetime(2026, 10, 11, 12, tzinfo=dt.timezone.utc)


@pytest.fixture
def gate(tmp_path, monkeypatch):
    sent = tmp_path / "sent.txt"
    stub = tmp_path / "notify.sh"
    # Exits with $NOTIFY_RC so a test can make the send fail.
    stub.write_text(f'#!/bin/bash\necho "$1" >> "{sent}"\nexit "${{NOTIFY_RC:-0}}"\n')
    for k in ("KIPI_MODEL_GATE_MODE", "KIPI_MODEL_GATE_PER_JOB", "KIPI_MODEL_GATE_FLEET"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("KIPI_MODEL_GATE_DIR", str(tmp_path / "gate"))
    monkeypatch.setenv("KIPI_MODEL_GATE_MARKER_DIR", str(tmp_path))
    monkeypatch.setenv("KIPI_NOTIFY", str(stub))
    return lambda: sent.read_text().splitlines() if sent.exists() else []


def test_per_job_limit_refuses_that_job_only(gate, monkeypatch):
    monkeypatch.setenv("KIPI_MODEL_GATE_PER_JOB", "2")
    assert [model_gate.check("a", now=AFTER)["admit"] for _ in range(3)] == [True, True, False]
    assert model_gate.check("b", now=AFTER)["admit"]


def test_fleet_limit_refuses_every_job(gate, monkeypatch):
    monkeypatch.setenv("KIPI_MODEL_GATE_FLEET", "2")
    assert model_gate.check("a", now=AFTER)["admit"] and model_gate.check("b", now=AFTER)["admit"]
    row = model_gate.check("c", now=AFTER)
    assert not row["admit"] and row["reason"].startswith("fleet")


def test_report_admits_over_limit_and_enforce_refuses(gate, monkeypatch):
    monkeypatch.setenv("KIPI_MODEL_GATE_PER_JOB", "0")
    assert model_gate.check("a", now=BEFORE) == {
        "admit": True, "mode": "report", "reason": "job a at 0/0 calls today"}
    assert model_gate.check("a", now=AFTER)["admit"] is False
    monkeypatch.setenv("KIPI_MODEL_GATE_MODE", "report")
    assert model_gate.check("a", now=AFTER)["admit"] is True
    monkeypatch.setenv("KIPI_MODEL_GATE_MODE", "reprot")  # a typo enforces
    assert model_gate.check("a", now=BEFORE)["admit"] is False


def test_one_fleet_breach_alerts_once_not_once_per_job(gate, monkeypatch):
    monkeypatch.setenv("KIPI_MODEL_GATE_FLEET", "1")
    model_gate.check("first", now=AFTER)
    for job in ("a", "b", "c", "d", "e"):
        model_gate.check(job, now=AFTER)
    assert len([x for x in gate() if "fleet" in x]) == 1


def test_one_alert_per_job_per_day(gate, monkeypatch):
    monkeypatch.setenv("KIPI_MODEL_GATE_PER_JOB", "0")
    for _ in range(4):
        model_gate.check("a", now=AFTER)
        model_gate.check("b", now=AFTER)
    model_gate.check("a", now=AFTER + dt.timedelta(days=1))
    sent = gate()
    assert len(sent) == 3, sent
    assert sum("job a" in s for s in sent) == 2


def test_a_failed_send_is_not_retried(gate, monkeypatch, capsys):
    monkeypatch.setenv("KIPI_MODEL_GATE_PER_JOB", "0")
    monkeypatch.setenv("NOTIFY_RC", "1")
    for _ in range(3):
        model_gate.check("a", now=AFTER)
    assert len(gate()) == 1
    assert "not retried" in capsys.readouterr().err
    rows = [json.loads(x) for x in open(os.path.join(os.environ["KIPI_MODEL_GATE_DIR"], "2026-10-11.jsonl"))]
    assert [r["kind"] for r in rows] == ["alerted"]


def test_an_unusable_ledger_follows_the_mode_and_alerts_once(gate, tmp_path, monkeypatch):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("")
    monkeypatch.setenv("KIPI_MODEL_GATE_DIR", str(blocker))
    assert [model_gate.check("a", now=BEFORE)["admit"] for _ in range(3)] == [True] * 3
    assert model_gate.check("a", now=AFTER)["admit"] is False
    assert len(gate()) == 2  # one per day, never one per call


def test_a_torn_line_is_skipped(gate, monkeypatch):
    monkeypatch.setenv("KIPI_MODEL_GATE_PER_JOB", "1")
    os.makedirs(os.environ["KIPI_MODEL_GATE_DIR"])
    with open(os.path.join(os.environ["KIPI_MODEL_GATE_DIR"], "2026-10-11.jsonl"), "w") as fh:
        fh.write('{"kind": "call", "job": "a"')
    assert model_gate.check("a", now=AFTER)["admit"]


def test_run_model_asks_the_gate_before_any_provider(gate, monkeypatch, tmp_path):
    monkeypatch.delenv("PYTEST_CURRENT_TEST")
    monkeypatch.setenv("KIPI_MODEL_GATE_MODE", "enforce")
    monkeypatch.setenv("KIPI_MODEL_GATE_PER_JOB", "0")
    monkeypatch.setenv("KIPI_USAGE_LEDGER", str(tmp_path / "usage.jsonl"))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("provider reached"))
    monkeypatch.setattr(model_gate, "_notify", lambda text: None)
    assert prompt_render.run_model("hi", str(tmp_path / "claude")) is None
    # The refusal is metered: a ledger blind to refusals reads as an idle fleet.
    rows = [json.loads(x) for x in (tmp_path / "usage.jsonl").read_text().splitlines()]
    assert [r["subtype"] for r in rows] == ["failed:model-gate-refused"]


def _door(*cmd, **env):
    return subprocess.run(["bash", DOOR, "--job", "shell", "--", *cmd], capture_output=True,
                          text=True, env={**os.environ, "KIPI_MODEL_GATE_PKG": PKG, **env})


def test_shell_door_runs_admitted_and_refuses_with_75(gate):
    ok = _door("echo", "ran", KIPI_MODEL_GATE_MODE="enforce")
    assert (ok.returncode, ok.stdout) == (0, "ran\n")
    no = _door("echo", "ran", KIPI_MODEL_GATE_MODE="enforce", KIPI_MODEL_GATE_PER_JOB="0")
    assert (no.returncode, no.stdout) == (75, "")
    assert "MODEL_GATE_REFUSED" in no.stderr


def test_shell_door_enforce_date_matches_the_module():
    assert re.search(r'"(\d{4}-\d{2}-\d{2})"', open(DOOR).read()).group(1) == model_gate.ENFORCE_FROM


def test_a_suite_without_a_gate_dir_never_touches_the_live_ledger(monkeypatch):
    monkeypatch.delenv("KIPI_MODEL_GATE_DIR", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    assert not model_gate.gate_dir().startswith(os.path.expanduser("~/.config"))


def test_defaults_sit_between_a_normal_day_and_the_runaway():
    # usage ledger since voiceloop logging began, 2026-10-01 excluded: busiest
    # normal caller 213 calls, busiest normal fleet day 412. The runaway
    # (2026-10-01) was critic.judge() 1180, fleet 1679. Above normal, or the gate
    # refuses ordinary work; at most half the runaway, or it stops nothing in time.
    assert 213 * 1.5 <= model_gate.PER_JOB_DEFAULT <= 1180 / 2
    assert 412 * 1.5 <= model_gate.FLEET_DEFAULT <= 1679 / 2


def test_default_per_job_limit_stops_a_critic_judge_loop(gate):
    n = model_gate.PER_JOB_DEFAULT
    admits = [model_gate.check("critic.judge()", now=AFTER)["admit"] for _ in range(n + 1)]
    assert admits.count(True) == n and admits[-1] is False


def _refusing_gate(monkeypatch):
    """Drive the REAL run_model into a gate refusal: enforce, per-job limit 0."""
    monkeypatch.delenv("PYTEST_CURRENT_TEST")
    monkeypatch.delenv("CHIEF_JOB", raising=False)
    monkeypatch.setenv("KIPI_MODEL_GATE_MODE", "enforce")
    monkeypatch.setenv("KIPI_MODEL_GATE_PER_JOB", "0")
    monkeypatch.setattr(model_gate, "_notify", lambda text: None)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("provider reached"))


def test_a_gate_refusal_is_never_scored_as_a_critic_fail(gate, monkeypatch, tmp_path):
    from voiceloop import critic
    _refusing_gate(monkeypatch)
    row = {"id": "tells-a-story", "text": "Does it tell a story?", "tier": critic.QUALITY}
    # A quality row fails CLOSED on a dead call; a refusal is not a dead call.
    verdict, _detail, fmt = critic.judge("a draft", row, claude_bin=str(tmp_path / "claude"))
    assert verdict == critic.NOT_JUDGED and verdict != critic.FAIL
    assert fmt == critic.FORMAT_GATED


def test_a_gated_critic_run_neither_revises_nor_accepts(gate, monkeypatch, tmp_path):
    from voiceloop import critic
    _refusing_gate(monkeypatch)
    checklist = tmp_path / "checklist.json"
    checklist.write_text(json.dumps([
        {"id": "tells-a-story", "text": "Does it tell a story?", "tier": "quality"},
        {"id": "no-hashtags", "text": "Is it free of hashtags?", "tier": "style"}]))
    log = tmp_path / "critic-log.jsonl"
    out = critic.run("a draft", "x", path=str(checklist), log_path=str(log),
                     claude_bin=str(tmp_path / "claude"),
                     reviser=lambda *a: pytest.fail("revised an unjudged draft"),
                     regate=lambda t: pytest.fail("regated an unjudged draft"))
    assert out.status == critic.GATED and out.text == ""
    verdicts = [json.loads(x)["verdict"] for x in log.read_text().splitlines()]
    assert critic.FAIL not in verdicts and critic.NOT_JUDGED in verdicts


def test_run_model_keys_the_gate_on_the_callers_job_not_the_bot(gate, monkeypatch, tmp_path):
    monkeypatch.delenv("PYTEST_CURRENT_TEST")
    monkeypatch.delenv("CHIEF_JOB", raising=False)
    monkeypatch.setenv("CHIEF_BOT", "voiceloop")
    monkeypatch.setenv("KIPI_MODEL_GATE_MODE", "enforce")
    monkeypatch.setenv("KIPI_MODEL_GATE_PER_JOB", "1")
    monkeypatch.setattr(model_gate, "_notify", lambda text: None)
    seen = []
    real = model_gate.check
    monkeypatch.setattr(model_gate, "check", lambda job, **k: seen.append(job) or real(job, **k))
    missing = str(tmp_path / "no-claude")  # admitted calls stop at the no-binary arm
    monkeypatch.setenv("KIPI_USAGE_LEDGER", str(tmp_path / "usage.jsonl"))
    for caller in ("critic.judge()", "critic.judge()", "revise"):
        prompt_render.run_model("hi", missing, caller=caller, allow_opencode=False)
    assert seen == ["critic.judge()", "critic.judge()", "revise"]
    day = [json.loads(x) for x in open(os.path.join(os.environ["KIPI_MODEL_GATE_DIR"],
                                                  model_gate._today() + ".jsonl"))]
    # the loop's second call is refused; a different caller of the same bot is not
    assert [r["job"] for r in day if r["kind"] == "call"] == ["critic.judge()", "revise"]


def _checklist(tmp_path, *tiers):
    path = tmp_path / "checklist.json"
    path.write_text(json.dumps([{"id": f"row-{t}", "text": "Is it fine?", "tier": t}
                                for t in tiers]))
    return str(path)


def test_a_gate_refusal_during_revise_is_gated_not_a_reviser_failure(gate, monkeypatch, tmp_path):
    from voiceloop import critic, revise
    _refusing_gate(monkeypatch)
    # the critic is answered by a runner (no gate); only the reviser reaches the gate
    out = critic.run("a draft", "x", path=_checklist(tmp_path, "quality"),
                     log_path=str(tmp_path / "log.jsonl"),
                     runner=lambda p: "VERDICT: FAIL\nWHY: no story",
                     reviser=revise.reviser(claude_bin=str(tmp_path / "claude"), model="m"),
                     regate=lambda t: pytest.fail("regated a revision that never ran"))
    assert out.status == critic.GATED, out.reasons
    assert not any("reviser returned nothing" in r for r in out.reasons)


def test_a_refused_style_row_fails_open(gate, monkeypatch, tmp_path):
    from voiceloop import critic
    _refusing_gate(monkeypatch)
    answers = {critic.MODEL_QUALITY: "VERDICT: PASS\nWHY: fine"}
    real = prompt_render.run_model

    def run_model(prompt, claude_bin, **k):
        # quality is answered; style goes through the real (refusing) gate
        if k.get("model") in answers:
            return answers[k["model"]]
        return real(prompt, claude_bin, **k)
    monkeypatch.setattr(prompt_render, "run_model", run_model)
    out = critic.run("a draft", "x", path=_checklist(tmp_path, "quality", "style"),
                     log_path=str(tmp_path / "log.jsonl"), claude_bin=str(tmp_path / "claude"))
    assert out.status == critic.ACCEPTED and out.text == "a draft"
    verdicts = [json.loads(x)["verdict"] for x in (tmp_path / "log.jsonl").read_text().splitlines()]
    assert critic.NOT_JUDGED in verdicts
