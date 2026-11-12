"""Tests for run_tokens.py and budget_check.py (ASK-4649).

Fixtures are real records cut from chief's 2026-11-11/12 build transcripts
(fixtures/run_tokens/ (.ndjson, since *.jsonl is gitignored)). In that whole set (12,352 ids, 9,192 written more than
once) no repeated id carried a different output_tokens, so the larger-snapshot
case can only be built by editing a real record: those copies are derived from
the fixture in the test, not invented.
"""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FX = HERE / "fixtures" / "run_tokens"
sys.path.insert(0, str(HERE))
import run_tokens  # noqa: E402


def run(script, *args):
    p = subprocess.run([sys.executable, str(HERE / script), *args], capture_output=True, text=True)
    return p.returncode, (json.loads(p.stdout) if p.stdout.strip() else None)


def test_repeated_id_counts_once():
    # main.jsonl: id A written twice (out 137), id B three times (out 307)
    rc, r = run("run_tokens.py", str(FX / "main.ndjson"))
    assert rc == 0
    assert r["requests"] == 2
    assert r["output_tokens"] == 137 + 307
    assert r["cache_write_tokens"] == 49911 + 14824
    assert r["cache_read_tokens"] == 27828 + 77739


def test_largest_snapshot_wins_in_either_order(tmp_path):
    line = (FX / "main.ndjson").read_text().splitlines()[0]
    def with_out(n):
        d = json.loads(line)
        d["message"]["usage"]["output_tokens"] = n
        return json.dumps(d)
    f = tmp_path / "t.jsonl"
    f.write_text("\n".join([with_out(50), with_out(900), with_out(400)]) + "\n")
    rc, r = run("run_tokens.py", str(f))
    assert (rc, r["requests"], r["output_tokens"]) == (0, 1, 900)


def test_subagent_transcript_is_added(tmp_path):
    (tmp_path / "sess").mkdir()
    (tmp_path / "sess" / "subagents").mkdir()
    (tmp_path / "sess.jsonl").write_text((FX / "main.ndjson").read_text())
    (tmp_path / "sess" / "subagents" / "agent-x.jsonl").write_text((FX / "subagent.ndjson").read_text())
    rc, r = run("run_tokens.py", str(tmp_path / "sess.jsonl"))
    assert r["requests"] == 2
    rc, r = run("run_tokens.py", str(tmp_path / "sess.jsonl"), "--subagents", "--by-agent")
    assert r["requests"] == 3 and r["output_tokens"] == 444 + 292
    assert len(r["by_agent"]) == 2
    rc, r2 = run("run_tokens.py", str(tmp_path))  # a directory finds both
    assert r2["output_tokens"] == 444 + 292


def test_context_percentiles():
    rep = run_tokens.report([str(FX / "main.ndjson"), str(FX / "subagent.ndjson")])
    # per-request context: 77741, 92565, 77330
    assert rep["context_median"] == 77741
    assert rep["context_p90"] == 92565


def test_empty_and_malformed_exit_nonzero(tmp_path):
    e = tmp_path / "empty.jsonl"
    e.write_text("")
    m = tmp_path / "bad.jsonl"
    m.write_text('{"usage": "assistant" not json\n')
    for f in (e, m, tmp_path / "missing.jsonl"):
        rc, r = run("run_tokens.py", str(f))
        assert rc != 0 and r["requests"] == 0


def test_budget_over_cap_exits_2_and_under_exits_0():
    f = str(FX / "main.ndjson")  # 444 output tokens
    assert run("budget_check.py", f, "--prs", "2", "--cap-per-pr", "200")[0] == 2   # 222 per PR
    assert run("budget_check.py", f, "--prs", "2", "--cap-per-pr", "300")[0] == 0
    assert run("budget_check.py", f, "--prs", "2", "--cap-total", "400")[0] == 2


def test_budget_cannot_evaluate_is_not_a_pass(tmp_path):
    f = str(FX / "main.ndjson")
    assert run("budget_check.py", f, "--prs", "0", "--cap-per-pr", "999")[0] == 1
    e = tmp_path / "e.jsonl"
    e.write_text("")
    assert run("budget_check.py", str(e), "--prs", "1", "--cap-total", "999")[0] == 1


def test_unreadable_transcript_is_named_and_fails(tmp_path):
    # review of #765: a file that fails to open used to be skipped with exit 0
    d = tmp_path / "locked.jsonl"
    d.write_text((FX / "main.ndjson").read_text())
    d.chmod(0)
    try:
        if d.open("rb"):  # running as root: chmod does not bite, nothing to test
            return
    except OSError:
        pass
    ok = str(FX / "main.ndjson")
    rc, r = run("run_tokens.py", ok, str(d))
    assert rc != 0 and r["unreadable"] == [str(d)] and r["requests"] == 2
    rc, r = run("budget_check.py", ok, str(d), "--prs", "2", "--cap-total", "999999")
    assert rc == 1 and r["unreadable"] == [str(d)]
    d.chmod(0o600)
