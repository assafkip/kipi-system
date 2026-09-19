"""ASK-1810: verify computes the green, so nobody types it.

Founder, 2026-09-18: "If the test passes, that's not the answer. The answer is: did the test
pass, and could you then run it on production and it would pass again every time." And:
"Ensure that you're not running the 6000 tests that take over ten minutes for every single
thing."

Each rule below is pinned RED FIRST by a fixture that breaks exactly that rule, and a twin
that does not. Fixtures come from producers: every issue spec here is rendered by the real
prd_split.py from a real PRD, then loaded and verified by the real issue_runner.py.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

DSSE = Path(__file__).resolve().parent
PRDOS = DSSE.parents[1] / "prd-os/scripts"


def _run(repo: Path, script: Path, *args: str, env_extra=None, stdin=None):
    env = dict(os.environ)
    for leak in ("CLAUDE_PROJECT_DIR", "KIPI_HOME", "QROOT", "KIPI_REAL_PATH_LOG"):
        env.pop(leak, None)
    env["PYTHONPATH"] = str(PRDOS)
    if env_extra:
        env.update(env_extra)
    return subprocess.run([sys.executable, str(script), *args], cwd=repo, input=stdin,
                          capture_output=True, text=True, env=env)


def _issue(repo: Path, *args, **kw):
    return _run(repo, DSSE / "issue_runner.py", *args, **kw)


def _repo(tmp_path: Path, files: dict, allowed: list, check: str) -> Path:
    """A virgin repo holding `files`, with one approved PRD split into one loaded issue."""
    repo = tmp_path / "repo"
    repo.mkdir()
    for cmd in (["init", "-q"], ["config", "user.email", "t@t.co"], ["config", "user.name", "t"]):
        subprocess.run(["git", *cmd], cwd=repo, capture_output=True)
    for rel, text in {"README.md": "# t\n", **files}.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text)
    subprocess.run(["git", "add", "-A"], cwd=repo, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, capture_output=True)
    assert _run(repo, PRDOS / "prd_os_init.py").returncode == 0
    created = _run(repo, PRDOS / "prd_runner.py", "new", "probe", "--title", "T")
    assert created.returncode == 0, created.stderr
    prd_id = json.loads(created.stdout)["created"]
    spec = repo / ".prd-os/prds" / f"{prd_id}.md"
    manifest = json.dumps([{"id": "probe-1", "title": "Probe", "allowed_files": allowed,
                            "required_checks": [check], "acceptance": "a", "finding_id": "finding-1",
                            "bypass_check": "python3 -c \"print('no bypass')\""}])
    body = spec.read_text()
    at = body.index("\n## Issues") + len("\n## Issues")
    spec.write_text(body[:at] + "\n\n```json\n" + manifest + "\n```\n" + body[at:])
    assert _run(repo, PRDOS / "prd_runner.py", "advance", "draft").returncode == 0
    add = _run(repo, PRDOS / "findings_writer.py", "add", prd_id, "--source", "claude-review",
               stdin='[{"severity":"major","body":"probe"}]')
    assert add.returncode == 0, add.stderr
    assert _run(repo, PRDOS / "findings_writer.py", "set-disposition", prd_id, "finding-1", "accepted",
                "--reason-code", "valid-fix-now", "--actor", "t").returncode == 0
    for step in ("in-review", "approved"):
        assert _run(repo, PRDOS / "prd_runner.py", "advance", step).returncode == 0
    assert _run(repo, PRDOS / "prd_split.py").returncode == 0
    assert _run(repo, PRDOS / "prd_runner.py", "clear").returncode == 0
    assert _issue(repo, "load", "probe-1").returncode == 0
    assert _issue(repo, "approve").returncode == 0
    return repo


def _state(repo: Path) -> dict:
    return json.loads(_issue(repo, "status").stdout)


TOOL = "def answer():\n    return 42\n"
REAL_TEST = (
    "import importlib.util, unittest\nfrom pathlib import Path\n"
    "HERE = Path(__file__).resolve().parents[1]\n"
    "s = importlib.util.spec_from_file_location('tool', HERE / 'scripts' / 'tool.py')\n"
    "tool = importlib.util.module_from_spec(s); s.loader.exec_module(tool)\n\n"
    "class T(unittest.TestCase):\n    def test_answer(self):\n        self.assertEqual(tool.answer(), 42)\n\n"
    "if __name__ == '__main__':\n    unittest.main()\n")
COPY_TEST = REAL_TEST.replace(
    "tool = importlib.util.module_from_spec(s); s.loader.exec_module(tool)\n",
    "import shutil, tempfile\nd = Path(tempfile.mkdtemp())\nshutil.copy(HERE / 'scripts' / 'tool.py', d / 'tool.py')\n"
    "s = importlib.util.spec_from_file_location('tool', d / 'tool.py')\n"
    "tool = importlib.util.module_from_spec(s); s.loader.exec_module(tool)\n")
HIDDEN_TEST = REAL_TEST.replace(
    "if __name__ == '__main__':\n    unittest.main()\n",
    "if __name__ == '__main__':\n    unittest.main()\n\n"
    "class Hidden(unittest.TestCase):\n    def test_never_runs(self):\n        self.fail('hidden')\n")


def _tool_repo(tmp_path, test_text, check="python3 tests/test_tool.py"):
    return _repo(tmp_path, {"scripts/tool.py": TOOL, "tests/test_tool.py": test_text},
                 ["scripts/tool.py", "tests/test_tool.py"], check)


# --- rule 1: the full suite never runs from an issue ---------------------------------

def test_a_full_suite_check_is_refused_before_anything_runs(tmp_path):
    repo = _repo(tmp_path, {"verify.sh": "touch ran-it\n"}, ["verify.sh"], "bash verify.sh --full")
    r = _issue(repo, "verify")
    assert r.returncode == 2, r.stdout + r.stderr
    assert "full suite" in r.stderr
    assert not (repo / "ran-it").exists(), "the full-suite check ran before the refusal"
    assert not _state(repo)["receipts"]["verified"]


# --- rule 2: the real path, measured -------------------------------------------------

def test_a_check_that_runs_a_copy_of_the_script_is_refused(tmp_path):
    repo = _tool_repo(tmp_path, COPY_TEST)
    r = _issue(repo, "verify")
    assert r.returncode == 2, r.stdout + r.stderr
    assert "scripts/tool.py" in r.stderr and "tracked path" in r.stderr
    assert "Python processes only" in r.stderr, "the refusal must state what the observer cannot see"


def test_the_same_check_on_the_tracked_script_goes_green(tmp_path):
    repo = _tool_repo(tmp_path, REAL_TEST)
    r = _issue(repo, "verify")
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["real_path"]["python3 tests/test_tool.py"] == ["scripts/tool.py"]


def test_a_script_launched_as_a_subprocess_at_its_real_path_counts(tmp_path):
    launch = REAL_TEST.replace(
        "tool = importlib.util.module_from_spec(s); s.loader.exec_module(tool)\n",
        "import subprocess, sys\nsubprocess.run([sys.executable, str(HERE / 'scripts' / 'tool.py')], check=True, env={})\n"
        "tool = type('t', (), {'answer': staticmethod(lambda: 42)})\n")
    repo = _tool_repo(tmp_path, launch)
    r = _issue(repo, "verify")
    assert r.returncode == 0, r.stderr     # env={} scrubs the child; the parent's argv still counts


def test_an_issue_with_no_python_script_is_not_asked_for_one(tmp_path):
    repo = _repo(tmp_path, {}, ["README.md"], "python3 -c \"print('ok')\"")
    r = _issue(repo, "verify")
    assert r.returncode == 0, r.stderr


# --- rule 3: tests defined vs tests ran --------------------------------------------

def test_tests_hidden_below_a_mid_file_main_are_refused_with_both_numbers(tmp_path):
    repo = _tool_repo(tmp_path, HIDDEN_TEST)
    r = _issue(repo, "verify")
    assert r.returncode == 2, r.stdout + r.stderr
    assert "2 defined, 1 ran, 0 skipped" in r.stderr
    assert "tests/test_tool.py" in r.stderr


def test_the_count_is_read_from_pytest_as_well(tmp_path):
    repo = _tool_repo(tmp_path, HIDDEN_TEST.replace("        self.fail('hidden')\n", "        pass\n"),
                      check="python3 -m pytest tests/test_tool.py -q")
    r = _issue(repo, "verify")
    assert r.returncode == 0, r.stderr        # pytest ignores the __main__ guard and runs both
    row = json.loads(r.stdout)["defined_vs_ran"][0]
    assert (row["defined"], row["ran"]) == (2, 2)


# --- rule 4: repeats ----------------------------------------------------------------

FLAKY = ("import os, sys\nfrom pathlib import Path\n"
         "p = Path('counter'); n = int(p.read_text()) if p.exists() else 0\n"
         "p.write_text(str(n + 1)); sys.exit(1 if n % 3 == 2 else 0)\n")


def test_a_check_that_fails_one_run_in_three_is_refused(tmp_path):
    repo = _repo(tmp_path, {"flaky.py": FLAKY}, ["README.md"], "python3 flaky.py")
    r = _issue(repo, "verify")
    assert r.returncode == 2, r.stdout + r.stderr
    assert "green" in r.stderr and "of 10" in r.stderr
    assert int((repo / "counter").read_text()) == 10, "it did not run the check ten times"


def test_checks_too_slow_for_five_runs_in_the_budget_are_refused(tmp_path):
    repo = _repo(tmp_path, {}, ["README.md"], "python3 -c \"import time; time.sleep(0.3)\"")
    r = _issue(repo, "verify", env_extra={"KIPI_VERIFY_BUDGET_S": "1"})
    assert r.returncode == 2, r.stdout + r.stderr
    assert "at least 5 are needed" in r.stderr


def test_the_budget_seam_can_only_lower_the_budget(tmp_path):
    repo = _repo(tmp_path, {}, ["README.md"], "python3 -c \"print('ok')\"")
    r = _issue(repo, "verify", env_extra={"KIPI_VERIFY_BUDGET_S": "999999"})
    assert r.returncode == 0, r.stderr
    assert _state(repo)["verified_green"]["repeats"]["budget_seconds"] == 1200.0


# --- sealed, so close sees an edit --------------------------------------------------

@pytest.mark.parametrize("field", ["real_path", "defined_vs_ran", "repeats"])
def test_an_edited_green_field_fails_close(tmp_path, field):
    repo = _tool_repo(tmp_path, REAL_TEST)
    assert _issue(repo, "verify").returncode == 0
    state_path = repo / ".claude/state/active-issue.json"
    state = json.loads(state_path.read_text())
    del state["verified_green"][field]
    state_path.write_text(json.dumps(state))
    r = _issue(repo, "close")
    assert r.returncode == 2, r.stdout + r.stderr
    assert "presence and shape are checked" in r.stderr


EDITS_THAT_KEEP_THE_SHAPE = {
    "real_path": lambda g: g["real_path"].update(driven=["scripts/other.py"]),
    "defined_vs_ran": lambda g: g["defined_vs_ran"][0].update(defined=7, ran=7),   # fixture has 1 and 1
    "repeats": lambda g: g["repeats"].update(first_pass_seconds=0.01),
}


@pytest.mark.parametrize("field", sorted(EDITS_THAT_KEEP_THE_SHAPE))
def test_a_value_edited_inside_a_valid_shape_fails_close_on_the_seal(tmp_path, field):
    # the shape check cannot see these; only the seal can, so a seal that skips a field
    # lets this edit through (the deletion test above passes on the shape check alone)
    repo = _tool_repo(tmp_path, REAL_TEST)
    assert _issue(repo, "verify").returncode == 0
    state_path = repo / ".claude/state/active-issue.json"
    state = json.loads(state_path.read_text())
    EDITS_THAT_KEEP_THE_SHAPE[field](state["verified_green"])
    state_path.write_text(json.dumps(state))
    r = _issue(repo, "close")
    assert r.returncode == 2, r.stdout + r.stderr
    assert "does not match its evidence" in r.stderr


# --- grandfathered by load time -----------------------------------------------------

def test_an_issue_loaded_before_contract_2_keeps_the_old_verify(tmp_path):
    repo = _repo(tmp_path, {"flaky.py": FLAKY}, ["README.md"], "python3 flaky.py")
    state_path = repo / ".claude/state/active-issue.json"
    state = json.loads(state_path.read_text())
    assert state.pop("verify_contract") == 2, "load did not stamp the contract"
    state_path.write_text(json.dumps(state))
    r = _issue(repo, "verify")
    assert r.returncode == 0, r.stderr
    assert (repo / "counter").read_text() == "1", "a grandfathered issue ran the new repeats"



# --- ASK-1810 review round 1, Sana's triage 2026-09-19 -------------------------------

def test_a_check_that_copies_the_script_with_cp_and_runs_the_copy_is_refused(tmp_path):
    # finding-7a: any .py argument of ANY program counted as driven, so `cp tool.py tmp`
    # then running the copy passed -- the ASK-1796 copy-the-gate shape, not an evasion
    cp_test = REAL_TEST.replace(
        "tool = importlib.util.module_from_spec(s); s.loader.exec_module(tool)\n",
        "import subprocess, tempfile\nd = Path(tempfile.mkdtemp())\n"
        "subprocess.run(['cp', str(HERE / 'scripts' / 'tool.py'), str(d / 'tool.py')], check=True)\n"
        "s = importlib.util.spec_from_file_location('tool', d / 'tool.py')\n"
        "tool = importlib.util.module_from_spec(s); s.loader.exec_module(tool)\n")
    repo = _tool_repo(tmp_path, cp_test)
    r = _issue(repo, "verify")
    assert r.returncode == 2, r.stdout + r.stderr
    assert "tracked path" in r.stderr


PRINTS_A_FAKE_COUNT = HIDDEN_TEST.replace(
    "        self.assertEqual(tool.answer(), 42)\n",
    "        print('Ran 5 tests in 0.001s')\n        self.assertEqual(tool.answer(), 42)\n", 1).replace(
    "if __name__ == '__main__':\n    unittest.main()\n\nclass Hidden",
    "if __name__ == '__main__':\n    unittest.main(exit=False)\n    raise SystemExit(0)\n\nclass Hidden")


def test_a_ran_line_printed_by_a_test_does_not_count(tmp_path):
    # finding-4: unittest writes its summary to stderr; a test's print goes to stdout
    repo = _tool_repo(tmp_path, PRINTS_A_FAKE_COUNT)
    r = _issue(repo, "verify")
    assert r.returncode == 2, r.stdout + r.stderr
    assert "2 defined, 1 ran" in r.stderr


@pytest.mark.parametrize("check", ["python3 -m pytest tests -q", "python3 -m pytest . -q",
                                   "cd tests && python3 -m pytest test_tool.py -q",
                                   "python3 -m unittest discover"])
def test_a_test_runner_given_no_test_file_is_refused_before_anything_runs(tmp_path, check):
    # finding-5 and finding-8: a directory, '.', a cd or discover skipped the count entirely
    repo = _tool_repo(tmp_path, REAL_TEST, check=check + " && touch ran-it")
    r = _issue(repo, "verify")
    assert r.returncode == 2, r.stdout + r.stderr
    assert "name the test files this issue changes" in r.stderr
    assert not (repo / "ran-it").exists(), "the check ran before the refusal"


def test_a_dotted_unittest_module_is_counted_as_its_file(tmp_path):
    files = {"scripts/tool.py": TOOL, "tests/test_tool.py": REAL_TEST, "tests/__init__.py": ""}
    repo = _repo(tmp_path, files, ["scripts/tool.py", "tests/test_tool.py"], "python3 -m unittest tests.test_tool")
    r = _issue(repo, "verify")
    assert r.returncode == 0, r.stderr
    row = json.loads(r.stdout)["defined_vs_ran"][0]
    assert (row["status"], row["defined"], row["ran"]) == ("ok", 1, 1), row


@pytest.mark.parametrize("check", ["py.test -q", "bash verify.sh --full=1"])
def test_more_spellings_of_the_full_suite_are_refused(tmp_path, check):
    repo = _repo(tmp_path, {"verify.sh": "touch ran-it\n"}, ["verify.sh"], check)
    r = _issue(repo, "verify")
    assert r.returncode == 2, r.stdout + r.stderr
    assert "full suite" in r.stderr


def test_a_test_file_that_does_not_parse_is_a_refusal_not_a_traceback(tmp_path):
    # finding-11
    repo = _repo(tmp_path, {"scripts/tool.py": TOOL, "tests/test_tool.py": "def test_ok(: pass\n"},
                 ["scripts/tool.py", "tests/test_tool.py"],
                 "python3 scripts/tool.py && python3 -c \"print('ok')\" tests/test_tool.py")
    r = _issue(repo, "verify")
    assert r.returncode == 2, r.stdout + r.stderr
    assert "Traceback" not in r.stderr
    assert "tests/test_tool.py" in r.stderr and "does not parse" in r.stderr


NESTED = (
    "import unittest\nimport importlib.util\nfrom pathlib import Path\n"
    "HERE = Path(__file__).resolve().parents[1]\n"
    "s = importlib.util.spec_from_file_location('tool', HERE / 'scripts' / 'tool.py')\n"
    "tool = importlib.util.module_from_spec(s); s.loader.exec_module(tool)\n\n"
    "class T(unittest.TestCase):\n    def test_answer(self):\n        self.assertEqual(tool.answer(), 42)\n\n"
    "    class Inner(unittest.TestCase):\n        def test_nested_never_runs(self):\n            self.fail('hidden')\n\n"
    "if True:\n    class Guarded(unittest.TestCase):\n        def test_guarded(self):\n            pass\n\n"
    "if __name__ == '__main__':\n    unittest.main()\n")


def test_tests_in_a_nested_class_or_under_an_if_are_counted(tmp_path):
    # finding-12: the count missed both, so a nested TestCase that never runs passed
    repo = _tool_repo(tmp_path, NESTED)
    r = _issue(repo, "verify")
    assert r.returncode == 2, r.stdout + r.stderr
    assert "3 defined, 2 ran" in r.stderr


@pytest.mark.parametrize("value", ["abc", "-inf", "0", "-1", "nan"])
def test_a_bad_budget_value_is_refused_before_anything_runs(tmp_path, value):
    # finding-9: 'abc' and '-inf' were tracebacks after the checks had run
    repo = _repo(tmp_path, {}, ["README.md"], "touch ran-it")
    r = _issue(repo, "verify", env_extra={"KIPI_VERIFY_BUDGET_S": value})
    assert r.returncode == 2, r.stdout + r.stderr
    assert "Traceback" not in r.stderr
    assert "KIPI_VERIFY_BUDGET_S" in r.stderr
    assert not (repo / "ran-it").exists()


def test_amend_lifts_an_issue_onto_the_current_contract_and_never_lowers_it(tmp_path):
    # ASK-1810 itself was loaded before contract 2 existed; reloading would reset the review
    # cap, so amend is the one way up (Sana, 2026-09-19)
    repo = _repo(tmp_path, {}, ["README.md"], "python3 -c \"print('ok')\"")
    state_path = repo / ".claude/state/active-issue.json"
    for before in (None, 1, "2"):
        state = json.loads(state_path.read_text())
        state.pop("verify_contract", None)
        if before is not None:
            state["verify_contract"] = before
        state_path.write_text(json.dumps(state))
        assert _issue(repo, "amend", "--reason", "probe").returncode == 0
        assert json.loads(state_path.read_text())["verify_contract"] == 2, before


def test_the_observer_reports_an_error_in_the_chained_sitecustomize(tmp_path):
    # finding-10: swallowed silently, so the observed run differed from production unseen
    nxt = tmp_path / "next"
    nxt.mkdir()
    (nxt / "sitecustomize.py").write_text("raise RuntimeError('boom')\n")
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(DSSE / "real_path_observer"), str(nxt)]),
               KIPI_REAL_PATH_LOG=str(tmp_path / "log"))
    r = subprocess.run([sys.executable, "-c", "pass"], capture_output=True, text=True, env=env)
    assert "Error in sitecustomize" in r.stderr and "boom" in r.stderr

# --- the observer leaves the interpreter as it found it -----------------------------

def test_the_observer_still_runs_the_interpreters_own_sitecustomize(tmp_path):
    nxt = tmp_path / "next"
    nxt.mkdir()
    (nxt / "sitecustomize.py").write_text("import os\nos.environ['CHAINED'] = 'yes'\n")
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(DSSE / "real_path_observer"), str(nxt)]),
               KIPI_REAL_PATH_LOG=str(tmp_path / "log"))
    r = subprocess.run([sys.executable, "-c", "import os; print(os.environ.get('CHAINED'))"],
                       capture_output=True, text=True, env=env)
    assert r.stdout.strip() == "yes", r.stderr
