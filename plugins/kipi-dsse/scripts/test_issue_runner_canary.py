"""ASK-2768: verify counts a mutant only from that mutant run's own test output.

The founder's test budget (2026-09-19) is one mutant per new decision point, and until this
nothing checked it: every closeout's "N of N mutants killed" was a typed number. The idea is
ported from the canary check in Anthropic's code-modernization plugin (proof_pack.py
check_canary, commit c1785e2e), not its code: a mutant counts only when its own recorded
runner output shows a test failing that the clean run of the same check did not fail.

Every fixture here is rendered by the real prd_split.py from a real PRD, then loaded,
mutated, and verified by the real issue_runner.py in a virgin temp repo. The repo builder is
loaded by path from the ASK-1810 test file, so both files exercise one producer.
"""
import importlib.util
import json
from pathlib import Path

import pytest

DSSE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location(
    "_ask1810_fixtures", DSSE / "test_issue_runner_verifiable_green.py")
_fx = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fx)
_repo, _issue, _state = _fx._repo, _fx._issue, _fx._state

# A new decision point: the branch a mutant flips.
TOOL = "def answer(flag=True):\n    if flag:\n        return 42\n    return 0\n"
MUTANT = TOOL.replace("if flag:", "if not flag:")
TEST = (
    "import importlib.util, unittest\nfrom pathlib import Path\n"
    "HERE = Path(__file__).resolve().parents[1]\n"
    "s = importlib.util.spec_from_file_location('tool', HERE / 'scripts' / 'tool.py')\n"
    "tool = importlib.util.module_from_spec(s); s.loader.exec_module(tool)\n\n"
    "class T(unittest.TestCase):\n"
    "    def test_answer(self):\n        self.assertEqual(tool.answer(), 42)\n"
    "{extra}\n"
    "if __name__ == '__main__':\n    unittest.main()\n")
BROKEN = "\n    def test_broken(self):\n        self.fail('broken before any mutant')\n"


def _tool_repo(tmp_path, extra="", check="python3 tests/test_tool.py"):
    return _repo(tmp_path, {"scripts/tool.py": TOOL, "tests/test_tool.py": TEST.format(extra=extra)},
                 ["scripts/tool.py", "tests/test_tool.py"], check)


def _mutant_run(repo: Path, name: str, mutate: bool = True):
    """Apply the mutant, record the run with the runner's own verb, put the code back."""
    tool = repo / "scripts/tool.py"
    if mutate:
        tool.write_text(MUTANT)
    try:
        return _issue(repo, "mutant", name)
    finally:
        tool.write_text(TOOL)


def _mutants(repo: Path) -> dict:
    return _state(repo)["verified_green"]["mutants"]


# --- reproducer: no mutant run, and verify used to say nothing ------------------------

def test_no_mutant_run_is_recorded_as_a_gap_not_silence(tmp_path):
    repo = _tool_repo(tmp_path)
    r = _issue(repo, "verify")
    assert r.returncode == 0, r.stdout + r.stderr
    out = json.loads(r.stdout)
    assert out["mutants"]["status"] == "gap", out
    assert "no mutant run" in out["mutants"]["reason"]
    assert _mutants(repo)["status"] == "gap"


# --- a mutant the tests catch: recorded with its file, sealed -------------------------

def test_a_caught_mutant_is_recorded_with_its_file_and_sealed(tmp_path):
    repo = _tool_repo(tmp_path)
    rec = _mutant_run(repo, "flip-answer")
    assert rec.returncode == 0, rec.stdout + rec.stderr
    r = _issue(repo, "verify")
    assert r.returncode == 0, r.stdout + r.stderr
    m = _mutants(repo)
    assert m["status"] == "ok", m
    [row] = m["rows"]
    assert row["name"] == "flip-answer" and row["status"] == "caught", row
    assert row["file"] == ".claude/state/mutants/probe-1/flip-answer.json"
    assert (repo / row["file"]).is_file()
    assert len(row["new_failures"]) == 1 and "test_answer" in row["new_failures"][0], row

    # Sealed: untouched, close gets past the seal and stops on the missing receipts.
    untouched = _issue(repo, "close")
    assert untouched.returncode == 2 and "missing receipts" in untouched.stderr, untouched.stderr
    state_file = repo / ".claude/state/active-issue.json"
    state = json.loads(state_file.read_text())
    state["verified_green"]["mutants"]["rows"][0]["new_failures"].append("typed: test_extra")
    state_file.write_text(json.dumps(state))
    edited = _issue(repo, "close")
    assert edited.returncode == 2 and "does not match its evidence" in edited.stderr, edited.stderr


# --- a mutant no test catches: refused, by name ----------------------------------------

def test_a_mutant_with_zero_new_failures_is_refused_by_name(tmp_path):
    repo = _tool_repo(tmp_path)
    assert _mutant_run(repo, "noop-mutant", mutate=False).returncode == 0
    r = _issue(repo, "verify")
    assert r.returncode == 2, r.stdout + r.stderr
    assert "noop-mutant" in r.stderr
    assert not _state(repo)["receipts"]["verified"]


# --- a test that fails in both runs is not the mutant's doing ---------------------------

@pytest.mark.parametrize("check", ["python3 tests/test_tool.py || true",
                                   "python3 -m pytest tests/test_tool.py -q || true"],
                         ids=["unittest", "pytest"])
def test_a_failure_in_both_clean_and_mutant_runs_is_not_counted(tmp_path, check):
    # Both runners: unittest names a failure on stderr, pytest on stdout.
    repo = _tool_repo(tmp_path, extra=BROKEN, check=check)
    assert _mutant_run(repo, "flip-answer").returncode == 0
    r = _issue(repo, "verify")
    assert r.returncode == 0, r.stdout + r.stderr
    [row] = _mutants(repo)["rows"]
    assert row["status"] == "caught", row
    assert len(row["new_failures"]) == 1, row
    assert "test_answer" in row["new_failures"][0]
    assert not any("test_broken" in f for f in row["new_failures"]), row


# --- a typed tally is a claim, never evidence -------------------------------------------

def test_a_typed_tally_is_not_shown_and_never_counts_as_caught(tmp_path):
    repo = _tool_repo(tmp_path)
    typed = repo / ".claude/state/mutants/probe-1/typed.json"
    typed.parent.mkdir(parents=True)
    typed.write_text(json.dumps({"name": "typed", "mutants_killed": "3 of 3"}))
    # Shaped like the verb's record, but its run is of a check this issue does not have, so
    # there is no clean run to compare it with.
    unpaired = typed.with_name("unpaired.json")
    unpaired.write_text(json.dumps({"runs": [{
        "command": "python3 tests/old_check.py", "returncode": 1, "stdout": "",
        "stderr": "FAIL: test_answer (__main__.T.test_answer)\n\nRan 1 test in 0.001s\n\nFAILED (failures=1)\n"}]}))
    r = _issue(repo, "verify")
    assert r.returncode == 0, r.stdout + r.stderr
    m = _mutants(repo)
    assert m["status"] == "gap", m
    assert [(x["name"], x["status"]) for x in m["rows"]] == [("typed", "not shown"),
                                                             ("unpaired", "not shown")], m


# --- the record lands only in the active issue's directory -----------------------------

def test_a_mutant_name_cannot_escape_the_issue_directory(tmp_path):
    repo = _tool_repo(tmp_path)
    r = _mutant_run(repo, "../escape")
    assert r.returncode == 2, r.stdout + r.stderr
    # The verb's own refusal, not argparse rejecting a verb it does not know (that passed
    # this test on a runner with no `mutant` verb at all).
    assert "mutant name" in r.stderr, r.stderr
    assert not list((repo / ".claude/state").rglob("escape*")), "a record landed outside the issue dir"


# --- a recorded mutant that shows nothing is named, not mistaken for no record --------

def test_a_crash_mutant_is_named_in_the_gap_not_told_to_record_one(tmp_path):
    # Review of PR #542, minor 1: a break that crashes the import stops unittest before it
    # prints a count, so the run shows no failing test. The gap said "no mutant run" and
    # told the engineer to record the mutant they had just recorded.
    repo = _tool_repo(tmp_path)
    tool = repo / "scripts/tool.py"
    tool.write_text("def answer(flag=True:\n    return 42\n")
    try:
        assert _issue(repo, "mutant", "crash-import").returncode == 0
    finally:
        tool.write_text(TOOL)
    r = _issue(repo, "verify")
    assert r.returncode == 0, r.stdout + r.stderr
    m = _mutants(repo)
    assert m["status"] == "gap", m
    assert [(x["name"], x["status"]) for x in m["rows"]] == [("crash-import", "not shown")], m
    assert "crash-import" in m["reason"] and "no mutant run" not in m["reason"], m["reason"]
