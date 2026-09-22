"""usage_ledger against a REAL `claude -p` capture (ASK-2008).

The fixture holds the same prompt run twice on 2026-09-22, once with
`--output-format json` and once plain, wrapped in the capture_payload
provenance envelope. The tests never call a model.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from voiceloop import prompt_render, usage_ledger  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures",
                       "claude-p-capture-2026-09-22.json")


@pytest.fixture(scope="module")
def captured():
    with open(FIXTURE) as fh:
        doc = json.load(fh)
    prov = doc.get("_provenance") or {}
    assert prov.get("connector") == "claude-code-cli" and prov.get("captured_at"), \
        "fixture must be a real capture with provenance"
    return doc["payload"]


def test_finish_returns_the_plain_calls_bytes(captured):
    text, row = usage_ledger.finish(json.dumps(captured["json_stdout"]), bot="t")
    assert text == captured["plain_stdout"]
    assert row["parse_error" if "parse_error" in row else "subtype"] == "success"


def test_row_carries_cost_tokens_and_turns_from_the_real_result(captured):
    doc = captured["json_stdout"]
    row = usage_ledger.row_from(doc, bot="chief", job="brief", model="claude-haiku-4-5-20251001")
    m = doc["modelUsage"]["claude-haiku-4-5-20251001"]
    assert row["total_cost_usd"] == doc["total_cost_usd"]
    assert row["num_turns"] == doc["num_turns"]
    assert row["tokens_in"] == m["inputTokens"] + m["cacheReadInputTokens"] + m["cacheCreationInputTokens"]
    assert row["tokens_out"] == m["outputTokens"]
    assert row["is_error"] is False and row["limit_text"] is None
    assert (row["bot"], row["job"], row["model"]) == ("chief", "brief", "claude-haiku-4-5-20251001")


def test_a_non_json_stdout_passes_through_untouched():
    text, row = usage_ledger.finish("plain words\n", bot="t")
    assert text == "plain words\n"
    assert "parse_error" in row and row["stdout_bytes"] == 12


def test_a_limit_refusal_is_named_on_the_row():
    doc = {"type": "result", "subtype": "error_during_execution", "is_error": True,
           "result": "You've hit your usage limit. Resets at 9pm.", "modelUsage": {}}
    assert usage_ledger.row_from(doc, bot="t")["limit_text"].startswith("You've hit your usage limit")


def test_append_never_raises_and_read_returns_what_was_written(tmp_path, monkeypatch):
    p = tmp_path / "ledger.jsonl"
    monkeypatch.setenv(usage_ledger.LEDGER_ENV, str(p))
    assert usage_ledger.append({"bot": "t", "tokens_in": 1}) is True
    assert usage_ledger.read() == [{"bot": "t", "tokens_in": 1}]
    # an unwritable target is a False, never an exception
    assert usage_ledger.append({"bot": "t"}, path=str(tmp_path / "no" / "\0bad")) is False


def test_run_model_adds_the_json_flags_and_hands_back_plain_bytes(captured, tmp_path, monkeypatch):
    import subprocess
    seen = {}

    class Done:
        returncode, stderr = 0, ""
        stdout = json.dumps(captured["json_stdout"])

    def fake_run(argv, **kw):
        seen["argv"] = argv
        return Done()
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)  # subprocess.run is faked: no live call
    monkeypatch.delenv("OPENCODE", raising=False)
    monkeypatch.setenv(usage_ledger.LEDGER_ENV, str(tmp_path / "l.jsonl"))
    monkeypatch.setenv("CHIEF_BOT", "cole")
    monkeypatch.setattr(subprocess, "run", fake_run)
    fake_bin = tmp_path / "claude"
    fake_bin.write_text("")
    out = prompt_render.run_model("hi", claude_bin=str(fake_bin), caller="test_caller")
    assert out == captured["plain_stdout"]
    assert tuple(seen["argv"][-2:]) == usage_ledger.JSON_FLAGS
    rows = usage_ledger.read()
    assert len(rows) == 1 and rows[0]["bot"] == "cole" and rows[0]["job"] == "test_caller"
    assert rows[0]["total_cost_usd"] == captured["json_stdout"]["total_cost_usd"]
