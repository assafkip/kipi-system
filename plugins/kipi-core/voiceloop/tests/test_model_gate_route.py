"""run_model asks the model gate before it starts any provider (ASK-2394).

why: the gate only caps what passes through it. run_model is the wrapper every
voiceloop caller shares, so it is the first door routed (PRD prd-model-gate-
2026-10-02). The job key the gate sums on must be the SAME `bot` the meter writes,
or the budget reads $0 forever (PRD review finding 2), so these tests assert the
gate's own spend number moves by the row the meter wrote.
"""
from __future__ import annotations

import datetime as dt
import json

import pytest

from voiceloop import model_gate as mg
from voiceloop import prompt_render

TODAY = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENCODE", raising=False)
    monkeypatch.delenv("CHIEF_BOT", raising=False)
    monkeypatch.delenv("CHIEF_JOB", raising=False)
    monkeypatch.setenv("KIPI_USAGE_LEDGER", str(tmp_path / "usage.jsonl"))
    monkeypatch.setenv("KIPI_MODEL_GATE_LEDGER", str(tmp_path / "gate.jsonl"))
    stub_notify = tmp_path / "notify.sh"
    stub_notify.write_text("#!/bin/bash\nexit 0\n")
    stub_notify.chmod(0o755)
    monkeypatch.setenv("KIPI_MODEL_GATE_NOTIFY", str(stub_notify))
    monkeypatch.setenv("KIPI_MODEL_GATE_MODE", "enforce")
    ran = tmp_path / "ran"
    doc = {"type": "result", "subtype": "success", "is_error": False, "result": "hi",
           "total_cost_usd": 0.5, "modelUsage": {}}
    binary = tmp_path / "claude"
    binary.write_text(f"#!/bin/bash\ntouch '{ran}'\nprintf '%s' '{json.dumps(doc)}'\n")
    binary.chmod(0o755)
    return {"bin": str(binary), "ran": ran, "usage": tmp_path / "usage.jsonl"}


def _run(monkeypatch, env):
    # pytest re-sets PYTEST_CURRENT_TEST for the call phase, so the guard is lifted
    # here, in the test body; the stub is the binary, so no live call is possible.
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    return prompt_render.run_model("p", claude_bin=env["bin"], caller="c")


def test_a_refused_call_never_starts_the_binary(env, monkeypatch):
    with open(env["usage"], "w") as fh:
        fh.write(json.dumps({"ts": f"{TODAY}T00:00:00Z", "bot": "voiceloop", "total_cost_usd": 99}) + "\n")
    assert _run(monkeypatch, env) is None
    assert not env["ran"].exists()


def test_an_admitted_call_moves_the_gate_spend_by_the_metered_cost(env, monkeypatch):
    before = mg.spend(TODAY)[0].get("voiceloop", 0.0)
    assert _run(monkeypatch, env) == "hi\n"
    after = mg.spend(TODAY)[0].get("voiceloop", 0.0)
    assert env["ran"].exists() and after - before == pytest.approx(0.5)


def test_the_gate_job_is_the_bot_the_meter_writes(env, monkeypatch, tmp_path):
    monkeypatch.setenv("CHIEF_BOT", "chief")
    _run(monkeypatch, env)
    gate_rows = [json.loads(x) for x in (tmp_path / "gate.jsonl").read_text().splitlines()]
    usage_rows = [json.loads(x) for x in env["usage"].read_text().splitlines()]
    assert gate_rows[-1]["job"] == usage_rows[-1]["bot"] == "chief"


def test_the_opencode_branch_is_gated_too(env, monkeypatch, tmp_path):
    with open(env["usage"], "w") as fh:
        fh.write(json.dumps({"ts": f"{TODAY}T00:00:00Z", "bot": "voiceloop", "total_cost_usd": 99}) + "\n")
    monkeypatch.setenv("OPENCODE", "1")
    oc = tmp_path / "bin" / "opencode"
    oc.parent.mkdir()
    oc.write_text(f"#!/bin/bash\ntouch '{env['ran']}'\n")
    oc.chmod(0o755)
    monkeypatch.setenv("PATH", f"{oc.parent}:/usr/bin:/bin")
    assert _run(monkeypatch, env) is None
    assert not env["ran"].exists()


def test_every_admitted_call_is_settled_so_it_stops_counting_as_in_flight(env, monkeypatch, tmp_path):
    """The in-flight charge drops on the gate's own settle row (ASK-2401). Without
    it, three finished $0.50 calls still read as $1.00 each and the third is refused."""
    monkeypatch.setenv("KIPI_MODEL_GATE_JOB_USD", "2")
    assert [_run(monkeypatch, env) for _ in range(3)] == ["hi\n"] * 3
    kinds = [json.loads(x)["kind"] for x in (tmp_path / "gate.jsonl").read_text().splitlines()]
    assert kinds.count("call") == kinds.count("settle") == 3
