"""gate_proof judges a wrapper by running it, never by reading it (ASK-2540).

The pair below is the helper's negative self-test. Both wrappers call
`prompt_render.run_model`, whose source calls `model_gate.check`, so a source
scan rates both gated. Only the first is. The second hands run_model a `runner=`
that shells the binary itself, the exact shape that let live calls skip the gate
and the ledger (RCA token-burn-recurs-after-gate, root cause #1).

Targets here are f-strings on purpose: the fleet check registers only CONSTANT
targets, so these fixtures never count as a proof of a real wrapper.
"""
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from voiceloop import gate_proof, prompt_render  # noqa: E402


def gated_wrapper(prompt, claude_bin):
    return prompt_render.run_model(prompt, claude_bin, caller="gate-proof-fixture()")


def early_return_wrapper(prompt, claude_bin):
    # Shells the model itself and hands the text in as `runner=`: run_model returns
    # on the runner before its gate and its meter, as the live caller did.
    def runner(p):
        return subprocess.run([claude_bin, "-p", p], capture_output=True, text=True).stdout
    return prompt_render.run_model(prompt, claude_bin, runner=runner, caller="gate-proof-fixture()")


def test_a_gated_wrapper_is_green(tmp_path):
    v = gate_proof.prove(lambda b: gated_wrapper("hi", b),
                         target=f"{__name__}:gated_wrapper", workdir=str(tmp_path))
    assert v.ok, v.reasons
    assert v.result == "pong\n"
    assert len(v.stub_calls) == 1 and "--output-format" in v.stub_calls[0]["argv"]
    assert v.ledger_rows[0]["kind"] == "run" and v.ledger_rows[0]["job"] == "gate-proof-fixture()"
    assert [r["job"] for r in v.gate_rows if r["kind"] == "call"] == ["gate-proof-fixture()"]
    assert v.target_entered is True


def test_a_wrapper_that_returns_before_the_gate_is_red(tmp_path):
    v = gate_proof.prove(lambda b: early_return_wrapper("hi", b),
                         target=f"{__name__}:early_return_wrapper", workdir=str(tmp_path))
    assert not v.ok
    # The model WAS called (the stub ran) and nothing metered or gated it.
    assert len(v.stub_calls) == 1
    assert v.ledger_rows == [] and v.gate_rows == []
    joined = " | ".join(v.reasons)
    assert "usage ledger has 0 rows" in joined and "model gate recorded 0 admitted calls" in joined
    with pytest.raises(AssertionError, match="not runtime-gated"):
        gate_proof.assert_gated(lambda b: early_return_wrapper("hi", b), workdir=str(tmp_path / "again"))


def test_a_target_the_call_never_entered_is_red(tmp_path):
    v = gate_proof.prove(lambda b: gated_wrapper("hi", b),
                         target=f"{__name__}:early_return_wrapper", workdir=str(tmp_path))
    assert not v.ok and v.target_entered is False
    assert any("never entered" in r for r in v.reasons)


def test_a_wrapper_that_never_reaches_a_binary_is_red(tmp_path):
    v = gate_proof.prove(lambda b: "canned", workdir=str(tmp_path))
    assert not v.ok
    assert any("stub claude ran 0 times" in r for r in v.reasons)


def test_a_row_not_from_this_call_is_red(tmp_path):
    # A wrapper that writes a ledger row and passes the gate, but whose row is not
    # built from the call's output (a failure row with no cost), is not metered.
    from voiceloop import model_gate, usage_ledger

    def fake(b):
        model_gate.check("fake()")
        subprocess.run([b, "-p", "x"], capture_output=True)
        usage_ledger.append(usage_ledger.failure_row("made-up", bot="t", job="fake()", ok=True))
    v = gate_proof.prove(fake, workdir=str(tmp_path))
    assert not v.ok
    assert any("kind is 'unmetered'" in r for r in v.reasons)
    assert any("not this proof's marker" in r for r in v.reasons)


def test_the_environment_is_restored(tmp_path, monkeypatch):
    monkeypatch.setenv("KIPI_USAGE_LEDGER", str(tmp_path / "outer.jsonl"))
    before = dict(os.environ)
    gate_proof.prove(lambda b: gated_wrapper("hi", b), workdir=str(tmp_path / "w"))
    assert dict(os.environ) == before
    assert not (tmp_path / "outer.jsonl").exists()


def test_live_is_refused_under_pytest(tmp_path):
    with pytest.raises(RuntimeError, match="refused under pytest"):
        gate_proof.prove(lambda b: None, live_bin="/nonexistent/claude", workdir=str(tmp_path))
