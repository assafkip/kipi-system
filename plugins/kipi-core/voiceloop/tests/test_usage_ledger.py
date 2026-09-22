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
    assert (row["tokens_fresh_in"], row["tokens_cache_read"], row["tokens_cache_create"]) == \
        (m["inputTokens"], m["cacheReadInputTokens"], m["cacheCreationInputTokens"])
    assert row["tokens_out"] == m["outputTokens"]
    assert row["is_error"] is False and row["limit_text"] is None
    assert (row["bot"], row["job"], row["model"]) == ("chief", "brief", "claude-haiku-4-5-20251001")


def test_a_non_json_stdout_passes_through_untouched():
    text, row = usage_ledger.finish("plain words\n", bot="t")
    assert text == "plain words\n"
    assert row["kind"] == "parse_error" and row["stdout_bytes"] == 12
    # the same key set as every other row: a consumer summing the ledger never KeyErrors
    for k in ("tokens_in", "tokens_out", "total_cost_usd", "is_error", "limit_text"):
        assert k in row


def test_a_limit_refusal_is_named_on_the_row():
    doc = {"type": "result", "subtype": "error_during_execution", "is_error": True,
           "result": "You've hit your usage limit. Resets at 9pm.", "modelUsage": {}}
    assert usage_ledger.row_from(doc, bot="t")["limit_text"].startswith("You've hit your usage limit")


def test_a_successful_post_about_rate_limits_is_not_a_refusal():
    # PR #410 review: the result IS the generated post, and he writes about this.
    doc = {"type": "result", "subtype": "success", "is_error": False, "modelUsage": {},
           "result": "Codex went dark mid-review again. Not a bug, a rate limit. "
                     "The weekly counter resets at midnight, so the graph lies on Mondays."}
    assert usage_ledger.row_from(doc, bot="t")["limit_text"] is None


def test_a_failed_call_still_leaves_a_row(captured, tmp_path, monkeypatch):
    # The 2026-09-12 shape: the fleet went dark and the caller got nothing back. The
    # ledger must not read as an idle fleet. Three arms: exit code, timeout, OSError.
    import subprocess
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("OPENCODE", raising=False)
    monkeypatch.setenv(usage_ledger.LEDGER_ENV, str(tmp_path / "l.jsonl"))
    fake_bin = tmp_path / "claude"; fake_bin.write_text("")
    refusal = json.dumps({"type": "result", "subtype": "error_during_execution", "is_error": True,
                          "result": "You've hit your usage limit.", "modelUsage": {}})

    class Exit1:
        returncode, stdout, stderr = 1, refusal, ""
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Exit1())
    assert prompt_render.run_model("hi", claude_bin=str(fake_bin), caller="c") is None

    def timeout(*a, **k):
        # the shape subprocess.run raises on POSIX: output None (round 4 measured it),
        # and when it is present it is bytes even under text=True (round 3)
        raise subprocess.TimeoutExpired(cmd="claude", timeout=1, output=None)
    monkeypatch.setattr(subprocess, "run", timeout)
    assert prompt_render.run_model("hi", claude_bin=str(fake_bin), caller="c") is None

    def oserr(*a, **k):
        raise OSError("boom")
    monkeypatch.setattr(subprocess, "run", oserr)
    assert prompt_render.run_model("hi", claude_bin=str(fake_bin), caller="c") is None

    rows = usage_ledger.read()
    assert [r["subtype"] for r in rows] == ["failed:exit 1", "failed:timeout", "failed:OSError"]
    assert rows[0]["limit_text"].startswith("You've hit your usage limit")
    assert rows[1]["tokens_in"] is None and rows[2]["tokens_in"] is None  # unknown, never zero


def test_a_stray_line_before_the_document_still_yields_plain_prose(captured):
    stdout = "warning: something\n" + json.dumps(captured["json_stdout"])
    text, row = usage_ledger.finish(stdout, bot="t")
    assert text == captured["plain_stdout"] and "parse_error" not in row


def test_the_reviser_goes_through_the_metered_chokepoint(captured, tmp_path, monkeypatch):
    # PR #410 review: revise shelled its own writer-tier claude -p and wrote no row.
    import subprocess
    from voiceloop import revise
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("OPENCODE", raising=False)
    monkeypatch.setenv(usage_ledger.LEDGER_ENV, str(tmp_path / "l.jsonl"))
    fake_bin = tmp_path / "claude"; fake_bin.write_text("")

    class Done:
        returncode, stderr = 0, ""
        stdout = json.dumps(captured["json_stdout"])
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Done())
    assert revise._run_prompt("p", claude_bin=str(fake_bin), model="m") == captured["plain_stdout"]
    rows = usage_ledger.read()
    assert len(rows) == 1 and rows[0]["job"] == "revise" and rows[0]["model"] == "m"


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
    assert seen["argv"][-2:] == ["--output-format", "json"]  # pinned, not read from the module
    rows = usage_ledger.read()
    assert len(rows) == 1 and rows[0]["bot"] == "cole" and rows[0]["job"] == "test_caller"
    assert rows[0]["total_cost_usd"] == captured["json_stdout"]["total_cost_usd"]


# ---- PR #410 round 2 --------------------------------------------------------------

_RATE_LIMIT_POST = ("Codex went dark mid-review again. Not a bug, a rate limit. "
                    "The weekly counter resets at midnight, so the graph lies on Mondays.")


def test_a_timed_out_call_whose_post_mentions_rate_limits_is_not_a_refusal():
    # failure_row must keep limit_text()'s guard: a SUCCESS document is a post.
    doc = {"type": "result", "subtype": "success", "is_error": False, "modelUsage": {},
           "result": _RATE_LIMIT_POST}
    row = usage_ledger.failure_row("timeout", bot="t", stdout=json.dumps(doc))
    assert row["limit_text"] is None


def test_every_row_shape_carries_schema_producer_and_kind(captured):
    ok = json.dumps(captured["json_stdout"])
    rows = [usage_ledger.finish(ok, bot="t")[1],
            usage_ledger.failure_row("timeout", bot="t"),
            usage_ledger.finish("not json", bot="t")[1]]
    assert [r["kind"] for r in rows] == ["run", "failure", "parse_error"]
    assert all(r["schema"] == 1 and r["producer"] == "voiceloop.usage_ledger" for r in rows)
    # a consumer summing tokens never hits KeyError, whatever the kind
    assert all("tokens_in" in r or r["kind"] == "parse_error" for r in rows)


def test_a_refusal_with_no_usage_records_unknown_not_zero():
    doc = {"type": "result", "subtype": "error_during_execution", "is_error": True,
           "result": "You've hit your usage limit.", "modelUsage": {}}
    row = usage_ledger.row_from(doc, bot="t")
    assert row["tokens_in"] is None and row["tokens_out"] is None


def test_an_init_event_before_the_result_still_yields_prose(captured):
    stdout = json.dumps({"type": "system", "subtype": "init"}) + "\n" + json.dumps(captured["json_stdout"])
    text, row = usage_ledger.finish(stdout, bot="t")
    assert text == captured["plain_stdout"] and row["kind"] == "run"


def test_the_opencode_branch_leaves_a_row(tmp_path, monkeypatch):
    import subprocess
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv(usage_ledger.LEDGER_ENV, str(tmp_path / "l.jsonl"))
    monkeypatch.setenv("OPENCODE", "1")
    monkeypatch.setattr(prompt_render.shutil, "which", lambda name: "/fake/opencode")

    class Done:
        returncode, stderr = 0, ""
        stdout = json.dumps({"type": "text", "part": {"text": "generated"}})
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Done())
    fake_bin = tmp_path / "claude"; fake_bin.write_text("")
    assert prompt_render.run_model("p", claude_bin=str(fake_bin), caller="c") == "generated"
    rows = usage_ledger.read()
    assert len(rows) == 1 and rows[0]["subtype"] == "unmetered:opencode" and rows[0]["kind"] == "unmetered" and rows[0]["is_error"] is False
    # a dead opencode run (no text events) is a failure row, not a clean one (round 6)
    Done.stdout = json.dumps({"type": "step"})
    assert prompt_render.run_model("p", claude_bin=str(fake_bin), caller="c") is None
    assert usage_ledger.read()[-1]["is_error"] is True


def test_a_cli_that_rejects_the_flag_falls_back_to_a_plain_call(tmp_path, monkeypatch):
    import subprocess
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("OPENCODE", raising=False)
    monkeypatch.setenv(usage_ledger.LEDGER_ENV, str(tmp_path / "l.jsonl"))
    calls = []

    def fake_run(argv, **kw):
        calls.append(argv)
        class R:
            pass
        r = R()
        if "--output-format" in argv:
            r.returncode, r.stdout, r.stderr = 1, "", "error: unknown option '--output-format'"
        else:
            r.returncode, r.stdout, r.stderr = 0, "plain prose\n", ""
        return r
    monkeypatch.setattr(subprocess, "run", fake_run)
    fake_bin = tmp_path / "claude"; fake_bin.write_text("")
    assert prompt_render.run_model("p", claude_bin=str(fake_bin), caller="c") == "plain prose\n"
    assert len(calls) == 2 and "--output-format" not in calls[1]
    assert usage_ledger.read()[-1]["subtype"] == "unmetered:cli:no-json-flag"


# ---- PR #410 round 3 --------------------------------------------------------------

def test_a_partial_post_with_no_document_is_never_a_refusal():
    row = usage_ledger.failure_row("timeout", bot="t", stdout="half a post about a rate limit")
    assert row["limit_text"] is None and row["tokens_in"] is None


def test_a_large_stdout_is_scanned_without_suffix_copies(captured, monkeypatch):
    # Forty junk lines that each OPEN a brace and never close it, then the document
    # pretty-printed across lines. The line scan resolves none of it, so only the
    # brace scan can find the document, which is the path this test pins (round 8:
    # the earlier input was resolved by the line loop and the quadratic mutant
    # stayed green). The pin is exact rather than a memory bound: every decode in
    # the brace scan must be handed the ORIGINAL string plus an index, never a
    # suffix copy of it. Forty tries stay under the scan's cap of fifty.
    junk = "".join("{" + "x" * 100_000 + "\n" for _ in range(40))
    stdout = junk + json.dumps(captured["json_stdout"], indent=2)
    seen = []
    real = json.JSONDecoder.raw_decode

    def recording(self, s, idx=0):
        seen.append((s is stdout, "\n" in s))
        return real(self, s, idx)

    monkeypatch.setattr(json.JSONDecoder, "raw_decode", recording)
    text, row = usage_ledger.finish(stdout, bot="t")
    assert text == captured["plain_stdout"]
    brace_scan = [same for same, multiline in seen if multiline]
    assert len(brace_scan) >= 41  # the forty junk braces, then the document
    assert all(brace_scan), "a decode was handed a copy of stdout, not stdout"


# ---- PR #410 round 4 --------------------------------------------------------------

def test_a_refusal_document_with_exit_zero_is_not_handed_to_the_caller_as_a_post():
    doc = {"type": "result", "subtype": "error_during_execution", "is_error": True,
           "result": "You've hit your usage limit.", "modelUsage": {}}
    text, row = usage_ledger.finish(json.dumps(doc), bot="t")
    assert text is None and row["limit_text"].startswith("You've hit")


def test_bytes_in_a_timeout_are_decoded_and_kept(captured):
    row = usage_ledger.failure_row("timeout", bot="t", stdout=json.dumps(captured["json_stdout"]).encode())
    assert row["total_cost_usd"] == captured["json_stdout"]["total_cost_usd"]


def test_an_unwritable_ledger_announces_itself_once(tmp_path, capsys):
    bad = str(tmp_path / "no" / "\0bad")
    assert usage_ledger.append({"a": 1}, path=bad) is False
    assert usage_ledger.append({"a": 2}, path=bad) is False
    err = capsys.readouterr().err
    assert err.count("usage_ledger: cannot append") == 1


def test_the_reviser_never_takes_the_opencode_branch(captured, tmp_path, monkeypatch):
    import subprocess
    from voiceloop import revise
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("OPENCODE", "1")
    monkeypatch.setattr(prompt_render.shutil, "which", lambda name: "/fake/opencode")
    monkeypatch.setenv(usage_ledger.LEDGER_ENV, str(tmp_path / "l.jsonl"))
    seen = {}

    class Done:
        returncode, stderr = 0, ""
        stdout = json.dumps(captured["json_stdout"])

    def fake_run(argv, **kw):
        seen["argv"] = argv
        return Done()
    monkeypatch.setattr(subprocess, "run", fake_run)
    fake_bin = tmp_path / "claude"; fake_bin.write_text("")
    revise._run_prompt("p", claude_bin=str(fake_bin), model="writer-tier")
    assert seen["argv"][0] == str(fake_bin) and "writer-tier" in seen["argv"]


# ---- PR #410 round 5 --------------------------------------------------------------

def test_a_malformed_document_never_fails_the_call(captured, tmp_path, monkeypatch):
    import subprocess
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("OPENCODE", raising=False)
    monkeypatch.setenv(usage_ledger.LEDGER_ENV, str(tmp_path / "l.jsonl"))
    doc = dict(captured["json_stdout"], modelUsage="not a dict")

    class Done:
        returncode, stderr = 0, ""
        stdout = json.dumps(doc)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Done())
    fake_bin = tmp_path / "claude"; fake_bin.write_text("")
    assert prompt_render.run_model("p", claude_bin=str(fake_bin), caller="c") == captured["plain_stdout"]
    rows = usage_ledger.read()
    assert rows and rows[-1]["kind"] == "run" and rows[-1]["tokens_in"] is None


def test_a_missing_binary_leaves_a_row(tmp_path, monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("OPENCODE", raising=False)
    monkeypatch.setenv(usage_ledger.LEDGER_ENV, str(tmp_path / "l.jsonl"))
    assert prompt_render.run_model("p", claude_bin=str(tmp_path / "absent"), caller="c") is None
    assert usage_ledger.read()[-1]["subtype"] == "failed:no-binary"


def test_a_bare_relative_ledger_path_still_writes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(usage_ledger.LEDGER_ENV, "ledger.jsonl")
    assert usage_ledger.append({"a": 1}) is True
    assert usage_ledger.read() == [{"a": 1}]


# ---- PR #410 round 6 --------------------------------------------------------------

def test_a_ledger_that_raises_never_fails_the_call_on_any_path(captured, tmp_path, monkeypatch):
    # The guard test round 6 asked for: the ledger itself blows up (not a value the
    # row builder tolerates), on the timeout, exit and success arms. Delete _meter's
    # try/except and every one of these raises.
    import subprocess
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("OPENCODE", raising=False)
    monkeypatch.setenv(usage_ledger.LEDGER_ENV, str(tmp_path / "l.jsonl"))
    fake_bin = tmp_path / "claude"; fake_bin.write_text("")

    def boom(*a, **k):
        raise RuntimeError("ledger exploded")
    monkeypatch.setattr(usage_ledger, "failure_row", boom)
    monkeypatch.setattr(usage_ledger, "append", boom)

    def timeout(*a, **k):
        raise subprocess.TimeoutExpired(cmd="claude", timeout=1, output=None)
    monkeypatch.setattr(subprocess, "run", timeout)
    assert prompt_render.run_model("p", claude_bin=str(fake_bin), caller="c") is None

    class Exit1:
        returncode, stdout, stderr = 1, "", ""
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Exit1())
    assert prompt_render.run_model("p", claude_bin=str(fake_bin), caller="c") is None

    class Done:
        returncode, stderr = 0, ""
        stdout = json.dumps(captured["json_stdout"])
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Done())
    assert prompt_render.run_model("p", claude_bin=str(fake_bin), caller="c") == captured["plain_stdout"]


def test_a_none_token_value_on_the_failure_arms_leaves_a_row(captured, tmp_path, monkeypatch):
    import subprocess
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("OPENCODE", raising=False)
    monkeypatch.setenv(usage_ledger.LEDGER_ENV, str(tmp_path / "l.jsonl"))
    fake_bin = tmp_path / "claude"; fake_bin.write_text("")
    doc = json.loads(json.dumps(captured["json_stdout"]))
    next(iter(doc["modelUsage"].values()))["inputTokens"] = None  # the reviewer's constructed value

    class Exit1:
        returncode, stderr = 1, ""
        stdout = json.dumps(doc)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Exit1())
    assert prompt_render.run_model("p", claude_bin=str(fake_bin), caller="c") is None
    assert usage_ledger.read(), "the failure left a row"


def test_json_mode_output_with_no_result_is_a_failed_call_not_prose():
    text, row = usage_ledger.finish(json.dumps({"type": "system", "subtype": "init"}), bot="t")
    assert text is None and row["kind"] == "parse_error" and row["is_error"] is True
    text, row = usage_ledger.finish("plain prose the CLI printed\n", bot="t")
    assert text == "plain prose the CLI printed\n" and row["is_error"] is False


# ---- PR #410 round 7 --------------------------------------------------------------

def test_a_failed_plain_fallback_is_a_failure_row_not_a_clean_one(tmp_path, monkeypatch):
    # pins ok=(returncode==0) on the older-CLI fallback; ok=True leaves this red
    import subprocess
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("OPENCODE", raising=False)
    monkeypatch.setenv(usage_ledger.LEDGER_ENV, str(tmp_path / "l.jsonl"))

    def fake_run(argv, **kw):
        class R:
            pass
        r = R()
        if "--output-format" in argv:
            r.returncode, r.stdout, r.stderr = 1, "", "error: unknown option '--output-format'"
        else:
            r.returncode, r.stdout, r.stderr = 2, "", "boom"
        return r
    monkeypatch.setattr(subprocess, "run", fake_run)
    fake_bin = tmp_path / "claude"; fake_bin.write_text("")
    assert prompt_render.run_model("p", claude_bin=str(fake_bin), caller="c") is None
    row = usage_ledger.read()[-1]
    assert row["is_error"] is True and row["kind"] == "failure"


def test_a_truncated_json_document_is_never_the_post(captured):
    cut = json.dumps(captured["json_stdout"])[:200]
    text, row = usage_ledger.finish(cut, bot="t")
    assert text is None and row["kind"] == "parse_error"


# ---- PR #410 round 9 --------------------------------------------------------------

VERBOSE_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures",
                               "claude-p-verbose-capture-2026-09-22.json")


@pytest.fixture
def verbose():
    with open(VERBOSE_FIXTURE) as fh:
        doc = json.load(fh)
    prov = doc.get("_provenance") or {}
    assert prov.get("connector") == "claude-code-cli" and prov.get("captured_at")
    return doc["payload"]


def test_the_verbose_array_form_yields_the_post_and_the_row(verbose):
    # The real capture: the result document sits past the 50th brace, behind the
    # init event, so neither scan reaches it. The whole-text parse does.
    assert verbose["braces_before_result"] > 50
    stdout = json.dumps(verbose["verbose_stdout"]) + "\n"
    text, row = usage_ledger.finish(stdout, bot="t")
    assert text == verbose["plain_stdout"]
    assert row["kind"] == "run" and row["tokens_out"] > 0 and row["is_error"] is False


def test_a_truncated_verbose_array_is_a_dead_json_call_not_prose(verbose):
    stdout = json.dumps(verbose["verbose_stdout"])[:2000]
    text, row = usage_ledger.finish(stdout, bot="t")
    assert text is None and row["kind"] == "parse_error" and row["is_error"] is True


def test_read_skips_a_torn_line_and_keeps_the_rest(tmp_path, monkeypatch):
    path = tmp_path / "usage.jsonl"
    good = json.dumps({"ts": "2026-09-22T00:00:00Z", "bot": "t", "kind": "call"})
    path.write_text(good + "\n" + good[:20] + "\n\n" + good + "\n")
    rows = usage_ledger.read(str(path))
    assert len(rows) == 2 and all(r["bot"] == "t" for r in rows)
