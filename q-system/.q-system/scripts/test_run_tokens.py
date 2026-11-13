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


# --- plan token cap (ASK-4721) -------------------------------------------------
# Scratch ledgers and a scratch cap file only. The cap file is a tmp copy with
# small numbers so a single row can sit exactly on, under or over a line.
NOW = "2026-11-12T12:00:00+00:00"


def _cap(tmp_path, windows, weights=None):
    p = tmp_path / "cap.json"
    p.write_text(json.dumps({"weights": weights or {"input": 1, "cache_read": 0.1, "cache_write": 1.25, "output": 5},
                             "windows": windows}))
    return str(p)


def _ledger(tmp_path, rows):
    p = tmp_path / "run-tokens.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return str(p)


def _row(ts, cr=0, out=0, cw=0, inp=0):
    return {"ts": ts, "ticket": "ASK-1", "input_tokens": inp, "cache_read_tokens": cr,
            "cache_write_tokens": cw, "output_tokens": out}


def test_cap_counts_weighted_not_raw(tmp_path, capsys):
    # 900 cache reads = 90 weighted. Raw (900) would be over a 100 cap; weighted is not.
    cap = _cap(tmp_path, [{"hours": 24, "cap": 100}])
    assert run_tokens.cap_check(_ledger(tmp_path, [_row("2026-11-12T11:00:00+00:00", cr=900)]), cap, NOW) == 0
    # 20 output = 100 weighted: the same cap, now reached.
    assert run_tokens.cap_check(_ledger(tmp_path, [_row("2026-11-12T11:00:00+00:00", out=20)]), cap, NOW) == 3


def test_cap_reached_exactly_pauses(tmp_path):
    cap = _cap(tmp_path, [{"hours": 24, "cap": 100}])
    assert run_tokens.cap_check(_ledger(tmp_path, [_row("2026-11-12T11:00:00+00:00", inp=99)]), cap, NOW) == 0
    assert run_tokens.cap_check(_ledger(tmp_path, [_row("2026-11-12T11:00:00+00:00", inp=100)]), cap, NOW) == 3


def test_cap_rows_outside_the_window_do_not_count(tmp_path):
    cap = _cap(tmp_path, [{"hours": 24, "cap": 100}])
    old = _row("2026-11-11T11:59:00+00:00", inp=500)  # 24h01m before NOW
    assert run_tokens.cap_check(_ledger(tmp_path, [old]), cap, NOW) == 0
    assert run_tokens.cap_check(_ledger(tmp_path, [old, _row("2026-11-12T11:00:00+00:00", inp=100)]), cap, NOW) == 3


def test_cap_any_window_over_pauses(tmp_path, capsys):
    # Under the day cap, over the week cap: the slow drain must stop too.
    cap = _cap(tmp_path, [{"hours": 24, "cap": 1000}, {"hours": 168, "cap": 150}])
    rows = [_row("2026-11-09T12:00:00+00:00", inp=100), _row("2026-11-12T11:00:00+00:00", inp=60)]
    assert run_tokens.cap_check(_ledger(tmp_path, rows), cap, NOW) == 3
    assert "OVER" in capsys.readouterr().out.split("168h")[1]


def test_cap_no_ledger_says_unmetered_and_runs(tmp_path, capsys):
    cap = _cap(tmp_path, [{"hours": 24, "cap": 100}])
    assert run_tokens.cap_check(str(tmp_path / "absent.jsonl"), cap, NOW) == 0
    assert "UNMETERED" in capsys.readouterr().out


def test_cap_broken_cap_file_is_rc2(tmp_path, capsys):
    for bad in ('{"weights": {"input": 1}, "windows": [{"hours": 24, "cap": 1}]}',
                '{"weights": {"input": 1, "cache_read": 0.1, "cache_write": 1.25, "output": 5}, "windows": []}',
                "not json"):
        p = tmp_path / "bad.json"
        p.write_text(bad)
        assert run_tokens.cap_check(_ledger(tmp_path, [_row(NOW, inp=1)]), str(p), NOW) == 2
    assert "BROKEN" in capsys.readouterr().out


def test_cap_shipped_file_loads():
    cfg, why = run_tokens._load_cap(run_tokens.DEFAULT_CAP_FILE)
    assert cfg is not None, why


def test_cap_cli_exit_codes(tmp_path):
    cap = _cap(tmp_path, [{"hours": 24, "cap": 100}])
    led = _ledger(tmp_path, [_row("2026-11-12T11:00:00+00:00", out=40)])
    p = subprocess.run([sys.executable, str(HERE / "run_tokens.py"), "--cap-check", led, "--cap-file", cap,
                        "--now", NOW], capture_output=True, text=True)
    assert p.returncode == 3 and "OVER" in p.stdout
