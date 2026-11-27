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
if os.path.exists(os.path.join(d, "stderr")):
    sys.stderr.write("\\n\\nA new release of gh is available: 2.84.0 -> 2.85.1\\n")
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

    def run(body, *args, moving=False, noisy=False, script=WATCH, timeout=20):
        (d / "body.json").write_text(json.dumps(body))
        for f in ("n", "moving", "stderr"):
            (d / f).unlink(missing_ok=True)
        if moving:
            (d / "moving").write_text("1")
        if noisy:
            (d / "stderr").write_text("1")
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
    assert r.returncode == 3 and "deadline 3min reached" in r.stdout and "no change" not in r.stdout


def test_bad_usage_exits_64(stub):
    for bad in (("--stall-min", "x"), ("--stall-min", ""), ("--deadline-min", ""), ("--stall-min", "0"),
                ("--deadline-min", "0")):
        assert stub(pr_body(), *bad).returncode == 64, bad


def test_gh_stderr_notice_does_not_hide_a_merge(stub):
    # review round 1, finding 1: gh's upgrade notice on stderr made MERGED read as a failed read
    r = stub(pr_body(state="MERGED", mergeCommit={"oid": "cafe123"}), noisy=True)
    assert (r.returncode, r.stdout.strip()) == (0, "PR7 MERGED cafe123")


def test_running_checks_are_blamed_before_a_missing_reviewer(stub):
    # review round 1, finding 2: the reviewer job is itself a running check
    body = pr_body(statusCheckRollup=[{"name": "reviewer-hosted", "status": "IN_PROGRESS"}])
    r = stub(body, "--stall-min", "2")
    assert r.returncode == 3 and "checks still running: reviewer-hosted" in r.stdout
    assert "nothing started a reviewer" not in r.stdout


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


def test_mutant_stderr_folded_into_json_is_caught(stub, tmp_path):
    m = mutant(tmp_path, '--json "$FIELDS" 2>"$ERRF")"; else', '--json "$FIELDS" 2>&1)"; else')
    m2 = tmp_path / "mut2.sh"
    m2.write_text(m.read_text().replace('"$PR" --json "$FIELDS" 2>"$ERRF")"; fi', '"$PR" --json "$FIELDS" 2>&1)"; fi'))
    r = stub(pr_body(state="MERGED", mergeCommit={"oid": "x"}), "--stall-min", "1", noisy=True, script=m2)
    assert r.returncode == 3 and r.stdout.startswith("PR7 STALLED")  # old 2>&1 shape: merge hidden


def test_mutant_reason_order_is_caught(stub, tmp_path):
    src = WATCH.read_text()
    a = 'elif pend: why = "checks still running: " + ", ".join(pend)\n'
    b = 'elif not at_head: why = "no review or verdict at head " + head[:7] + " (nothing started a reviewer)"\n'
    assert a + b in src
    m = tmp_path / "mut3.sh"
    m.write_text(src.replace(a + b, b + a, 1))
    body = pr_body(statusCheckRollup=[{"name": "reviewer-hosted", "status": "IN_PROGRESS"}])
    r = stub(body, "--stall-min", "1", script=m)
    assert "nothing started a reviewer" in r.stdout  # mutated order blames the reviewer


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
    # review round 1, finding 3: English "for" in a one-shot wait is not a loop
    assert guard("sleep 120; gh pr checks 904  # one wait for the slow validate job").returncode == 0


def test_guard_blocks_multiline_loops():
    # review round 2: `do` on its own line must still be seen as a loop
    assert guard("while true\ndo\n  gh pr view 903 --json state\n  sleep 300\ndone").returncode == 2
    assert guard("for i in 1 2 3\ndo gh pr checks 9; sleep 5\ndone").returncode == 2


def test_guard_blocks_status_and_api_loops():
    assert guard("while :; do gh pr status; sleep 300; done").returncode == 2
    assert guard("while :; do gh api repos/o/r/pulls/903; sleep 300; done").returncode == 2


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
