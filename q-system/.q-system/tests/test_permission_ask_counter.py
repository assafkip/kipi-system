#!/usr/bin/env python3
"""RED FIRST. Issue mbl-two-measurements (plan 2i). The counter is advisory and
refuses to print a number when its sample is unreadable (exit 3). Samples and
ledgers are tmp_path; the live session store is never read by a test.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
MODULE = HERE.parent / "scripts" / "permission-ask-counter.py"


@pytest.fixture(scope="module")
def counter():
    assert MODULE.is_file(), f"missing: {MODULE}"
    spec = importlib.util.spec_from_file_location("permission_ask_counter", MODULE)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _rec(text):
    return json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}})


PICK_THEN_ASK_1 = "Two paths. My call: rebase, since we push weekly.\n\nWant me to kick it off?"
PICK_THEN_ASK_2 = "I recommend 2a first, it is the cheapest red-to-green.\nSay go and I start there?"
PICK_THEN_ACT = "My call: rebase. Starting the rebase now; results in the next message."
ASK_THEN_ACT = "Want me to kick it off? My call: rebase, and the answer is yes. Rebase started, results next."
ASK_NO_PICK = "Three options are on the table. Which one do you want?"
PLAIN = "Shipped the command. Remote divergence untouched."


def _sample(tmp_path, texts):
    d = tmp_path / "projects" / "proj-a"
    d.mkdir(parents=True)
    (d / "session.jsonl").write_text("\n".join(_rec(t) for t in texts) + "\n" +
                                     json.dumps({"type": "user", "message": {"content": "ok"}}) + "\n")
    return tmp_path / "projects"


def test_two_pick_then_menu_turns_count_two_and_one_ledger_row(counter, tmp_path, capsys):
    sample = _sample(tmp_path, [PICK_THEN_ASK_1, PLAIN, PICK_THEN_ACT, ASK_NO_PICK, PICK_THEN_ASK_2])
    ledger = tmp_path / "ledger.jsonl"
    rc = counter.main(["--sample", str(sample), "--ledger", str(ledger)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "pick-then-ask: 2 of 5 turns" in out and "ADVISORY" in out
    rows = [json.loads(l) for l in ledger.read_text().splitlines()]
    assert len(rows) == 1 and rows[0]["count"] == 2 and rows[0]["turns"] == 5 and rows[0]["rate"] == 0.4


def test_broken_apparatus_exits_3_and_appends_nothing(counter, tmp_path, capsys):
    """The manifest's bypass_check selects on 'broken_apparatus_exits_3'; the
    runner refused to close on a name that matched nothing (a zero-selection
    gate can never go green), which is exactly the check working."""
    ledger = tmp_path / "ledger.jsonl"
    rc = counter.main(["--sample", str(tmp_path / "absent"), "--ledger", str(ledger)])
    assert rc == 3 and not ledger.exists()
    assert "Refusing" in capsys.readouterr().err


def test_zero_turns_is_broken_apparatus_not_a_perfect_score(counter, tmp_path):
    d = tmp_path / "projects" / "p"
    d.mkdir(parents=True)
    (d / "s.jsonl").write_text(json.dumps({"type": "user", "message": {"content": "hi"}}) + "\n")
    assert counter.main(["--sample", str(tmp_path / "projects"), "--no-ledger"]) == 3


def test_a_multi_block_record_is_one_turn_classified_once(counter, tmp_path, capsys):
    """Both Codex reviewers: each text block was a turn, so a pick in block one
    and the ask in block two was invisible and the denominator was inflated."""
    two_block = json.dumps({"type": "assistant", "message": {"content": [
        {"type": "text", "text": "Two paths. My call: rebase, since we push weekly."},
        {"type": "tool_use", "name": "Bash", "input": {}},
        {"type": "text", "text": "Want me to kick it off?"}]}})
    d = tmp_path / "projects" / "p"
    d.mkdir(parents=True)
    (d / "s.jsonl").write_text(two_block + "\n" + _rec(PLAIN) + "\n")
    rc = counter.main(["--sample", str(tmp_path / "projects"), "--no-ledger"])
    assert rc == 0
    assert "pick-then-ask: 1 of 2 turns" in capsys.readouterr().out


def test_an_unreadable_transcript_fails_closed(counter, tmp_path, capsys):
    sample = _sample(tmp_path, [PICK_THEN_ASK_1, PLAIN])
    locked = sample / "proj-a" / "locked.jsonl"
    locked.write_text(_rec(PLAIN) + "\n")
    locked.chmod(0)
    try:
        rc = counter.main(["--sample", str(sample), "--no-ledger"])
    finally:
        locked.chmod(0o644)
    assert rc == 3 and "unreadable" in capsys.readouterr().err


def test_classifier_shape(counter):
    assert counter.is_pick_then_ask(PICK_THEN_ASK_1) and counter.is_pick_then_ask(PICK_THEN_ASK_2)
    assert not counter.is_pick_then_ask(PICK_THEN_ACT), "a pick followed by action is the contract kept"
    assert not counter.is_pick_then_ask(ASK_THEN_ACT), "an ask that the turn then answers itself is not a hand-back; only the ENDING counts"
    assert not counter.is_pick_then_ask(ASK_NO_PICK), "a menu with no pick is a different failure"
    assert not counter.is_pick_then_ask(PLAIN)


def test_default_sample_is_resolved_inside_the_script_and_it_is_advisory(counter):
    src = MODULE.read_text(encoding="utf-8")
    assert 'Path.home() / ".claude" / "projects"' in src
    assert "PreToolUse" not in src and "exit 2" not in src.lower()
    assert "ADVISORY" in src


def test_this_file_runs_its_own_tests_under_python3():
    if os.environ.get("KIPI_SELFTEST_INNER"):
        pytest.skip("inner run")
    env = dict(os.environ, KIPI_SELFTEST_INNER="1")
    ok = subprocess.run([sys.executable, __file__], capture_output=True, text=True, env=env)
    assert ok.returncode == 0 and "passed" in ok.stdout, ok.stdout[-600:]
    none = subprocess.run([sys.executable, __file__, "-k", "no_such_test_zzz"], capture_output=True, text=True, env=env)
    assert none.returncode != 0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", *sys.argv[1:]]))
