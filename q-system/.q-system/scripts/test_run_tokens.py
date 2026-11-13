"""Tests for run_tokens.py and budget_check.py (ASK-4649).

Fixtures are real records cut from chief's 2026-11-11/12 build transcripts
(fixtures/run_tokens/ (.ndjson, since *.jsonl is gitignored)). In that whole set (12,352 ids, 9,192 written more than
once) no repeated id carried a different output_tokens, so the larger-snapshot
case can only be built by editing a real record: those copies are derived from
the fixture in the test, not invented.
"""
import json
import os
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


def _out_of_order_transcript(tmp_path, stamped=True):
    """A session transcript, derived from the real fixture records, whose earliest
    request by timestamp is NOT its first line.

    File order: id B (3 snapshots, 23:29:19+, context 92565), then id A (2 snapshots,
    23:29:15+, context 77741), then id C (a copy of B's record with a new id, a later
    time and a smaller context, 31002). So first-in-file is B, earliest is A, latest
    and smallest is C: each wrong pick gives a different number than the right one.
    """
    lines = (FX / "main.ndjson").read_text().splitlines()
    c = json.loads(lines[2])
    c["message"]["id"] = "msg_derived_C"
    c["timestamp"] = "2026-11-11T23:29:31.002Z"
    c["message"]["usage"].update(input_tokens=2, cache_read_input_tokens=30000, cache_creation_input_tokens=1000)
    recs = [json.loads(x) for x in lines[2:5] + lines[0:2]] + [c]
    if not stamped:
        for r in recs:
            r.pop("timestamp", None)
    sid = "0b5e1c2a-4f3d-4e6a-9c7b-2d8f1a3e5c47"
    proj = tmp_path / "home" / ".claude" / "projects" / "-fixture"
    proj.mkdir(parents=True)
    (proj / f"{sid}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in recs))
    return sid


def _record(tmp_path, sid):
    out = tmp_path / "rows.jsonl"
    env = {**os.environ, "HOME": str(tmp_path / "home")}
    p = subprocess.run([sys.executable, str(HERE / "run_tokens.py"), "--record", str(out),
                        "--session", sid, "--ticket", "ASK-4747"], capture_output=True, text=True, env=env)
    rows = [json.loads(x) for x in out.read_text().splitlines()] if out.exists() else []
    return p.returncode, rows


def test_record_row_carries_context_first_of_the_earliest_request(tmp_path):
    # ASK-4747 step 1: the worker's first-request context was the one number the
    # token analysis could not read from the ledger (token-drain-analysis-2026-11-12, s.2).
    rc, rows = _record(tmp_path, _out_of_order_transcript(tmp_path))
    assert rc == 0 and len(rows) == 1
    assert rows[0]["requests"] == 3
    assert rows[0]["context_first"] == 2 + 49911 + 27828  # id A, earliest by timestamp


def test_record_row_without_timestamps_has_null_context_first(tmp_path):
    # No stamped request: the row still lands (the aggregates are real), and the
    # start-up reads as unknown, never as a 0 that looks like a free start-up.
    rc, rows = _record(tmp_path, _out_of_order_transcript(tmp_path, stamped=False))
    assert rc == 0 and len(rows) == 1
    assert rows[0]["requests"] == 3 and rows[0]["context_first"] is None


def test_record_context_first_is_the_sessions_own_not_a_subagents(tmp_path):
    # Review of #789 (major): the row's start-up was the minimum over the session AND
    # its subagent files. Same layout as test_subagent_transcript_is_added; the
    # subagent fixture's records are 3 hours older than the session's.
    sid = "6c1f0e2b-8a4d-4b7e-9f3a-1e5d7c9b2a40"
    proj = tmp_path / "home" / ".claude" / "projects" / "-fixture"
    (proj / sid / "subagents").mkdir(parents=True)
    (proj / f"{sid}.jsonl").write_text((FX / "main.ndjson").read_text())
    (proj / sid / "subagents" / "agent-x.jsonl").write_text((FX / "subagent.ndjson").read_text())
    rc, rows = _record(tmp_path, sid)
    assert rc == 0 and rows[0]["requests"] == 3  # the subagent is still counted
    assert rows[0]["context_first"] == 2 + 49911 + 27828  # main.ndjson line 0, not the subagent's 77330


def test_record_context_first_is_null_when_any_request_is_unstamped(tmp_path):
    # Review of #789 (minor): an unstamped request may be the first one, so a stamped
    # later request must not be reported as the start-up.
    sid = _out_of_order_transcript(tmp_path)
    f = next((tmp_path / "home" / ".claude" / "projects" / "-fixture").glob(f"{sid}.jsonl"))
    recs = [json.loads(x) for x in f.read_text().splitlines()]
    for r in recs:
        if r["message"]["id"] == "msg_011Cgx1WH5VKhBJnXpsYjB9n":  # id A, the earliest
            r.pop("timestamp")
    f.write_text("".join(json.dumps(r) + "\n" for r in recs))
    rc, rows = _record(tmp_path, sid)
    assert rc == 0 and rows[0]["requests"] == 3 and rows[0]["context_first"] is None


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


def test_unreadable_directory_is_named_not_dropped(tmp_path):
    # An unlistable directory used to yield no files at all (Path.rglob swallows the
    # error), so the report said "zero requests (wrong path)" and never named it.
    d = tmp_path / "locked"
    d.mkdir()
    d.chmod(0)
    try:
        if list(d.iterdir()) is not None:  # running as root: chmod does not bite
            d.chmod(0o700)
            return
    except OSError:
        pass
    try:
        rc, r = run("run_tokens.py", str(FX / "main.ndjson"), str(d))
        assert rc == 1 and r["unreadable"] == [str(d)] and r["requests"] == 2
    finally:
        d.chmod(0o700)
