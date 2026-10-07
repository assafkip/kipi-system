"""2026-10-06: a deployment's live calls must be metered and gated, and a text-only
call can run bare.

Scar: a deployment observed its live calls by passing a recording `runner=`, and
`run_model` returns a runner's answer before the model gate and before the usage
ledger. 135 influencer reviews in one day left no ledger row and never reached the
gate. `run=` is the seam that keeps both. Never calls a model: `run` is faked.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from voiceloop import critic, model_gate, prompt_render, usage_ledger  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures",
                       "claude-p-capture-2026-09-22.json")


def _captured():
    with open(FIXTURE) as fh:
        return json.load(fh)["payload"]


def _isolate(tmp_path, monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)  # `run` is faked: no live call
    monkeypatch.delenv("OPENCODE", raising=False)
    monkeypatch.delenv("CHIEF_JOB", raising=False)
    monkeypatch.setenv(usage_ledger.LEDGER_ENV, str(tmp_path / "l.jsonl"))
    monkeypatch.setenv("KIPI_MODEL_GATE_DIR", str(tmp_path / "gate"))
    monkeypatch.setenv("KIPI_MODEL_GATE_MODE", "enforce")
    monkeypatch.setattr(model_gate, "_notify", lambda text: None)
    fake_bin = tmp_path / "claude"
    fake_bin.write_text("")
    return str(fake_bin)


def _recording_run(seen, stdout):
    class Done:
        returncode, stderr = 0, ""

    def run(argv, **kw):
        seen.append({"argv": list(argv), "kw": kw})
        d = Done()
        d.stdout = stdout
        return d
    return run


def _gate_calls(tmp_path):
    rows = []
    for name in os.listdir(tmp_path / "gate"):
        with open(tmp_path / "gate" / name) as fh:
            rows += [json.loads(line) for line in fh if line.strip()]
    return [r for r in rows if r.get("kind") == "call"]


def test_a_run_seam_call_is_metered_and_gated(tmp_path, monkeypatch):
    cap = _captured()
    binary = _isolate(tmp_path, monkeypatch)
    seen = []
    out = prompt_render.run_model("hi", binary, caller="influencer_hourly.review()",
                                  run=_recording_run(seen, json.dumps(cap["json_stdout"])))
    assert out == cap["plain_stdout"]
    assert len(seen) == 1, "the deployment's run must be the thing that shells"
    rows = usage_ledger.read()
    assert len(rows) == 1 and rows[0]["job"] == "influencer_hourly.review()"
    assert rows[0]["total_cost_usd"] == cap["json_stdout"]["total_cost_usd"]
    assert [c["job"] for c in _gate_calls(tmp_path)] == ["influencer_hourly.review()"]


def test_a_refusing_gate_stops_a_run_seam_call(tmp_path, monkeypatch):
    binary = _isolate(tmp_path, monkeypatch)
    monkeypatch.setenv("KIPI_MODEL_GATE_PER_JOB", "0")
    seen = []
    out = prompt_render.run_model("hi", binary, caller="job", refused="REFUSED",
                                  run=_recording_run(seen, "{}"))
    assert out == "REFUSED" and seen == [], "a refused call must never reach run"
    assert usage_ledger.read()[0]["subtype"] == "failed:model-gate-refused"


def test_bare_adds_the_strip_args_and_an_empty_cwd(tmp_path, monkeypatch):
    cap = _captured()
    binary = _isolate(tmp_path, monkeypatch)
    monkeypatch.setenv("TMPDIR", str(tmp_path / "tmp"))
    os.makedirs(tmp_path / "tmp")
    import tempfile
    monkeypatch.setattr(tempfile, "tempdir", None)  # re-read TMPDIR
    seen = []
    prompt_render.run_model("hi", binary, bare=True,
                            run=_recording_run(seen, json.dumps(cap["json_stdout"])))
    argv, kw = seen[0]["argv"], seen[0]["kw"]
    i = argv.index("--setting-sources")
    assert argv[i + 1] == "" and argv[argv.index("--tools") + 1] == ""
    assert argv[argv.index("-p") + 1] == "hi", "the prompt must still follow -p"
    assert kw["cwd"].startswith(str(tmp_path / "tmp")) and os.listdir(kw["cwd"]) == []


def test_bare_is_the_default(tmp_path, monkeypatch):
    cap = _captured()
    binary = _isolate(tmp_path, monkeypatch)
    seen = []
    prompt_render.run_model("hi", binary, run=_recording_run(seen, json.dumps(cap["json_stdout"])))
    assert "--setting-sources" in seen[0]["argv"] and "cwd" in seen[0]["kw"]


def test_a_live_runner_is_gated_and_metered(tmp_path, monkeypatch):
    # RCA 2026-10-06 item 2: the runner return sat above the gate and the ledger.
    _isolate(tmp_path, monkeypatch)
    out = prompt_render.run_model("hi", None, runner=lambda p: "text",
                                  caller="influencer_hourly.review()")
    assert out == "text"
    [row] = usage_ledger.read()
    assert row["job"] == "influencer_hourly.review()" and row["subtype"] == "unmetered:runner"
    assert [c["job"] for c in _gate_calls(tmp_path)] == ["influencer_hourly.review()"]


def test_a_refusing_gate_stops_a_live_runner(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setenv("KIPI_MODEL_GATE_PER_JOB", "0")
    called = []
    out = prompt_render.run_model("hi", None, runner=lambda p: called.append(p),
                                  refused="REFUSED")
    assert out == "REFUSED" and called == []


def test_a_runner_under_pytest_touches_no_ledger(tmp_path, monkeypatch):
    # Negative control: the test seam must not write the ledger (2026-09-22 pollution).
    monkeypatch.setenv(usage_ledger.LEDGER_ENV, str(tmp_path / "l.jsonl"))
    monkeypatch.setenv("KIPI_MODEL_GATE_DIR", str(tmp_path / "gate"))
    assert prompt_render.run_model("hi", None, runner=lambda p: "t") == "t"
    assert not (tmp_path / "l.jsonl").exists() and not (tmp_path / "gate").exists()


def test_without_bare_the_argv_and_cwd_are_unchanged(tmp_path, monkeypatch):
    # Negative control: the default path must not pick up the strip.
    cap = _captured()
    binary = _isolate(tmp_path, monkeypatch)
    seen = []
    prompt_render.run_model("hi", binary, bare=False,
                            run=_recording_run(seen, json.dumps(cap["json_stdout"])))
    assert "--setting-sources" not in seen[0]["argv"] and "--tools" not in seen[0]["argv"]
    assert "cwd" not in seen[0]["kw"]


def test_a_dirty_stable_dir_is_not_used(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    import tempfile
    monkeypatch.setattr(tempfile, "tempdir", None)
    stable = tmp_path / "kipi-headless-cwd"
    stable.mkdir()
    (stable / "CLAUDE.md").write_text("planted")
    got = prompt_render.bare_cwd()
    assert got != str(stable) and os.listdir(got) == []


def test_the_critic_judge_runs_bare(tmp_path, monkeypatch):
    binary = _isolate(tmp_path, monkeypatch)
    seen = []
    real = prompt_render.run_model

    def spy(*a, **kw):
        seen.append(kw)
        return real(*a, **kw, run=_recording_run([], json.dumps(_captured()["json_stdout"])))
    monkeypatch.setattr(prompt_render, "run_model", spy)
    critic.judge("a post", {"id": "x", "tier": critic.STYLE, "text": "c"},
                 claude_bin=binary)
    assert seen and seen[0].get("bare", True) is True, "the judge must not opt out of bare"


def test_the_reviser_declares_its_need_for_the_session():
    import inspect
    from voiceloop import revise
    assert "bare=False" in inspect.getsource(revise)
