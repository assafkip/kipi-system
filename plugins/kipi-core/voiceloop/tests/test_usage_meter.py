"""ASK-2541: an Agent-tool run leaves one usage-ledger row, priced, and never twice.

The hook is driven as the harness drives it: `usage_meter.py subagent-stop` in a
subprocess, payload on stdin, ledger and state redirected to tmp. The transcript
is synthetic but real-shaped: one record per content block, the same message id
repeated with a partial then a final output count, the way Claude Code writes it.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
METER = HERE / "usage_meter.py"
sys.path.insert(0, str(HERE))
import model_prices  # noqa: E402


def _turn(mid, out, *, model="claude-opus-5-5", fresh=3, read=1000, write=200, w1h=0):
    usage = {"input_tokens": fresh, "output_tokens": out, "cache_read_input_tokens": read,
             "cache_creation_input_tokens": write,
             "cache_creation": {"ephemeral_5m_input_tokens": write - w1h, "ephemeral_1h_input_tokens": w1h}}
    return {"type": "assistant", "isSidechain": True, "agentId": "a1",
            "requestId": "req_" + mid, "message": {"id": mid, "model": model, "role": "assistant",
                                                   "usage": usage, "content": []}}


def _write(path: Path, records):
    with path.open("a") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")


def _stop(tmp: Path, transcript: Path, agent_id="a1"):
    env = dict(os.environ, KIPI_USAGE_LEDGER=str(tmp / "ledger.jsonl"),
               KIPI_AGENT_METER_STATE=str(tmp / "state"), KIPI_USAGE_METER_LOG=str(tmp / "meter.log"))
    payload = {"session_id": "s1", "transcript_path": str(tmp / "parent.jsonl"), "cwd": str(tmp),
               "hook_event_name": "SubagentStop", "stop_hook_active": False, "agent_id": agent_id,
               "agent_type": "general-purpose", "agent_transcript_path": str(transcript)}
    p = subprocess.run([sys.executable, "-I", str(METER), "subagent-stop"], input=json.dumps(payload),
                       capture_output=True, text=True, env=env, timeout=60)
    assert p.returncode == 0, p.stderr
    led = tmp / "ledger.jsonl"
    return [json.loads(x) for x in led.read_text().splitlines() if x.strip()] if led.exists() else []


def test_one_agent_run_writes_one_priced_row(tmp_path):
    t = tmp_path / "agent-a1.jsonl"
    _write(t, [{"type": "user", "message": {"role": "user", "content": "go"}},
               _turn("m1", 8), _turn("m1", 211),          # same turn, partial then final copy
               _turn("m2", 50, read=5000, write=0),
               _turn("m3", 10, write=400, w1h=100)])
    rows = _stop(tmp_path, t)
    assert len(rows) == 1, rows
    r = rows[0]
    assert r["kind"] == "agent" and r["bot"] == "agent" and r["job"] == "general-purpose"
    assert r["agent_id"] == "a1" and r["num_turns"] == 3
    assert r["tokens_out"] == 211 + 50 + 10           # the partial copy is not double-charged
    assert r["tokens_cache_read"] == 1000 + 5000 + 1000
    assert r["tokens_cache_create"] == 200 + 0 + 400
    want = model_prices.cost("claude-opus-5-5", fresh_in=9, out=271, cache_read=7000,
                             cache_write_5m=200 + 300, cache_write_1h=100)
    assert abs(r["total_cost_usd"] - round(want, 6)) < 1e-9
    # spot the table itself: Opus 5.5 is $4 in / $20 out / $0.20 read per MTok
    assert model_prices.cost("claude-opus-5-5", fresh_in=1_000_000) == 4.0
    assert model_prices.cost("claude-opus-5-5", cache_read=1_000_000) == 0.2


def test_a_restopped_agent_is_charged_only_for_new_turns(tmp_path):
    t = tmp_path / "agent-a1.jsonl"
    _write(t, [_turn("m1", 100)])
    assert len(_stop(tmp_path, t)) == 1
    assert len(_stop(tmp_path, t)) == 1, "a second stop with no new turns wrote another row"
    _write(t, [_turn("m2", 7)])
    rows = _stop(tmp_path, t)
    assert len(rows) == 2 and rows[1]["tokens_out"] == 7 and rows[1]["num_turns"] == 1


def test_unpriced_model_is_unknown_cost_not_free(tmp_path):
    t = tmp_path / "agent-a1.jsonl"
    _write(t, [_turn("m1", 5, model="claude-future-9")])
    r = _stop(tmp_path, t)[0]
    assert r["total_cost_usd"] is None and r["unpriced_models"] == ["claude-future-9"]


def test_fail_open_bad_payload_and_missing_transcript_exit_zero_and_log(tmp_path):
    rows = _stop(tmp_path, tmp_path / "nope.jsonl")
    assert rows == []
    assert "no readable agent transcript" in (tmp_path / "meter.log").read_text()
    env = dict(os.environ, KIPI_USAGE_METER_LOG=str(tmp_path / "meter.log"),
               KIPI_USAGE_LEDGER=str(tmp_path / "ledger.jsonl"))
    p = subprocess.run([sys.executable, "-I", str(METER), "subagent-stop"], input="not json",
                       capture_output=True, text=True, env=env, timeout=60)
    assert p.returncode == 0 and "payload is not JSON" in (tmp_path / "meter.log").read_text()


def test_a_limit_refusal_reaches_the_review_file_as_plain_text(tmp_path):
    import usage_meter
    raw = json.dumps({"type": "result", "subtype": "error_during_execution", "is_error": True,
                      "result": "Claude AI usage limit reached|1760000000"})
    assert usage_meter.review_text(raw) == "Claude AI usage limit reached|1760000000\n"


def test_a_stop_that_added_only_a_synthetic_turn_writes_no_row(tmp_path):
    t = tmp_path / "agent-a1.jsonl"
    _write(t, [_turn("m1", 5)])
    assert len(_stop(tmp_path, t)) == 1
    _write(t, [_turn("m2", 0, model="<synthetic>", read=0, write=0, fresh=0)])
    assert len(_stop(tmp_path, t)) == 1


def test_a_mixed_run_keeps_the_priced_part_and_says_it_is_partial(tmp_path):
    t = tmp_path / "agent-a1.jsonl"
    _write(t, [_turn("m1", 5), _turn("m2", 5, model="claude-future-9")])
    r = _stop(tmp_path, t)[0]
    assert r["total_cost_usd"] and r["cost_complete"] is False and r["unpriced_models"] == ["claude-future-9"]
