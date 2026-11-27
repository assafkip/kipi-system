"""Tests for pr-progress-watch.sh and pr-progress-watch-guard.py (ASK-5842).

why a stub gh: the watcher's job is deciding from `gh pr view` JSON, so the test feeds
it three PR shapes through a fake `gh` first on PATH. It never reaches GitHub and
writes only under tmp_path (fable-discipline: no live data path).

why mutants here: a watcher test that stays green when the stall check is deleted is
decoration. Each mutant edits a COPY of the script, reruns one scenario, and must
change the outcome. (PR_WATCH_MIN_SEC=1 makes a "minute" one second so this is fast.)
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
WATCH = HERE / "pr-progress-watch.sh"
GUARD = HERE / "pr-progress-watch-guard.py"

STUB = """#!/usr/bin/env python3
import json, os, sys
d = os.environ["GH_STUB_DIR"]
n_path = os.path.join(d, "n")
n = int(open(n_path).read()) + 1 if os.path.exists(n_path) else 1
open(n_path, "w").write(str(n))
body = json.load(open(os.path.join(d, "body.json")))
if os.path.exists(os.path.join(d, "moving")):
    body["comments"] = [{}] * n
print(json.dumps(body))
"""

HEAD = "a" * 40


def pr_body(**kw):
    base = {"state": "OPEN", "mergeCommit": None, "headRefOid": HEAD, "reviews": [],
            "comments": [], "statusCheckRollup": [], "mergeable": "MERGEABLE",
            "reviewDecision": ""}
    base.update(kw)
    return base


@pytest.fixture
def stub(tmp_path):
    d = tmp_path / "stub"
    d.mkdir()
    gh = tmp_path / "bin" / "gh"
    gh.parent.mkdir()
    gh.write_text(STUB)
    gh.chmod(0o755)

    def run(body, *args, moving=False, script=WATCH, timeout=20):
        (d / "body.json").write_text(json.dumps(body))
        for f in ("n", "moving"):
            (d / f).unlink(missing_ok=True)
        if moving:
            (d / "moving").write_text("1")
        env = dict(os.environ, PATH=f"{gh.parent}:{os.environ['PATH']}", GH_STUB_DIR=str(d),
                   PR_WATCH_POLL_SEC="0.2", PR_WATCH_MIN_SEC="1")
        return subprocess.run(["bash", str(script), "7", *args], env=env, capture_output=True,
                              text=True, timeout=timeout)
    return run


def test_merged_exits_0_with_oid(stub):
    r = stub(pr_body(state="MERGED", mergeCommit={"oid": "deadbeef"}))
    assert (r.returncode, r.stdout.strip()) == (0, "PR7 MERGED deadbeef")


def test_closed_exits_0(stub):
    r = stub(pr_body(state="CLOSED"))
    assert (r.returncode, r.stdout.strip()) == (0, "PR7 CLOSED")


def test_stalled_names_red_check(stub):
    body = pr_body(statusCheckRollup=[{"name": "validate", "conclusion": "FAILURE"},
                                      {"name": "lint", "conclusion": "SUCCESS"}])
    r = stub(body, "--stall-min", "2", "--deadline-min", "30")
    assert r.returncode == 3
    assert r.stdout.startswith("PR7 STALLED") and "validate=FAILURE" in r.stdout


def test_stalled_no_verdict_at_head(stub):
    old = [{"state": "APPROVED", "author": {"login": "bot"}, "commit": {"oid": "b" * 40}}]
    r = stub(pr_body(reviews=old), "--stall-min", "2", "--deadline-min", "30")
    assert r.returncode == 3 and "no review or verdict at head aaaaaaa" in r.stdout


def test_stalled_conflict_and_changes_requested(stub):
    r = stub(pr_body(mergeable="CONFLICTING"), "--stall-min", "1")
    assert r.returncode == 3 and "merge conflict" in r.stdout
    r = stub(pr_body(reviewDecision="CHANGES_REQUESTED"), "--stall-min", "1")
    assert r.returncode == 3 and "changes requested" in r.stdout


def test_still_moving_runs_to_the_deadline(stub):
    # comment count changes every poll, so the stall clock never trips; only the deadline ends it
    r = stub(pr_body(), "--stall-min", "2", "--deadline-min", "3", moving=True)
    assert r.returncode == 3 and "deadline 3min reached, still moving" in r.stdout


def test_bad_usage_exits_64(stub):
    r = stub(pr_body(), "--stall-min", "x")
    assert r.returncode == 64


# ---- mutants: each edits a copy of the script and must flip a scenario ----

def mutant(tmp_path, old, new):
    src = WATCH.read_text()
    assert old in src, f"mutation anchor missing: {old!r}"
    p = tmp_path / "mut.sh"
    p.write_text(src.replace(old, new, 1))
    return p


def test_mutant_stall_check_removed_is_caught(stub, tmp_path):
    m = mutant(tmp_path, '-ge "$STALL_SEC"', '-ge 999999')
    r = stub(pr_body(mergeable="CONFLICTING"), "--stall-min", "1", "--deadline-min", "3", script=m)
    assert "no change for" not in r.stdout  # deadline ended it instead of the stall


def test_mutant_deadline_removed_is_caught(stub, tmp_path):
    m = mutant(tmp_path, '-ge "$DEADLINE_SEC"', '-ge 999999')
    with pytest.raises(subprocess.TimeoutExpired):
        stub(pr_body(), "--stall-min", "999", "--deadline-min", "2", moving=True, script=m, timeout=6)


def test_mutant_merged_exit_code_is_caught(stub, tmp_path):
    m = mutant(tmp_path, 'echo "PR$PR MERGED $oid"; exit 0', 'echo "PR$PR MERGED $oid"; exit 3')
    r = stub(pr_body(state="MERGED", mergeCommit={"oid": "x"}), script=m)
    assert r.returncode != 0


def test_mutant_fingerprint_reset_removed_is_caught(stub, tmp_path):
    m = mutant(tmp_path, 'last_fp="$fp"; last_change=$now', 'last_fp="$fp"')
    r = stub(pr_body(), "--stall-min", "2", "--deadline-min", "4", moving=True, script=m)
    assert "no change for" in r.stdout  # moving PR wrongly judged stalled


# ---- guard ----

def guard(command, tool="Bash"):
    payload = json.dumps({"tool_name": tool, "tool_input": {"command": command}})
    return subprocess.run([sys.executable, str(GUARD)], input=payload, capture_output=True, text=True)


LOOP = "while true; do gh pr view 903 --json state,mergeCommit; sleep 300; done"


def test_guard_blocks_hand_rolled_loop_and_names_script():
    r = guard(LOOP)
    assert r.returncode == 2
    assert "pr-progress-watch.sh" in r.stderr and "--stall-min" in r.stderr


def test_guard_allows_watcher_and_plain_calls():
    assert guard("bash q-system/.q-system/scripts/pr-progress-watch.sh 903").returncode == 0
    assert guard("gh pr view 903 --json state").returncode == 0
    assert guard(LOOP + " # pr-progress-watch").returncode == 0
    assert guard(LOOP + " # pr-watch-skip: quoting the scar in a note").returncode == 0
    assert guard(LOOP, tool="Edit").returncode == 0
    assert guard("sleep 5; echo hi").returncode == 0


def test_guard_malformed_stdin_allows():
    r = subprocess.run([sys.executable, str(GUARD)], input="{not json", capture_output=True, text=True)
    assert r.returncode == 0


def guard_mutant(tmp_path, old, new):
    src = GUARD.read_text()
    assert old in src
    p = tmp_path / "gm.py"
    p.write_text(src.replace(old, new, 1))
    return p


def run_guard(path, command):
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    return subprocess.run([sys.executable, str(path)], input=payload, capture_output=True, text=True)


def test_guard_mutants_are_caught(tmp_path):
    # watcher exemption removed -> the watcher command itself is blocked
    m = guard_mutant(tmp_path, "if WATCHER in command or ", "if ")
    cmd = "while true; do gh pr view 1; sleep 1; done  # pr-progress-watch"
    assert run_guard(m, cmd).returncode == 2 and run_guard(GUARD, cmd).returncode == 0
    # sleep requirement removed -> a loop without sleep is blocked
    m = guard_mutant(tmp_path, "and SLEEP_RE.search(command)", "and True")
    nosleep = "for i in 1 2; do gh pr view 1; done"
    assert run_guard(m, nosleep).returncode == 2 and run_guard(GUARD, nosleep).returncode == 0
