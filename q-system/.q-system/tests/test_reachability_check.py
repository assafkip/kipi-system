#!/usr/bin/env python3
"""reachability-check.py must go RED for each reason it exists.

A ratchet that only ever prints OK is decoration. Each case below names the
input that makes the check fail, so a future edit that neuters one of the three
failure paths is caught here rather than by the hole reopening.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
CHECK = REPO / "q-system/.q-system/scripts/reachability-check.py"
BASELINE_REL = "q-system/.q-system/test-reachability-baseline.json"


def _run(root):
    p = subprocess.run([sys.executable, str(CHECK), "--repo-root", str(root)],
                       capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def _clone(tmp):
    """A real git checkout: the check reads `git ls-files`, so a plain copy
    would report zero test files and pass for the wrong reason."""
    dst = Path(tmp) / "repo"
    subprocess.run(["git", "clone", "--quiet", "--shared", str(REPO), str(dst)],
                   check=True, capture_output=True)
    subprocess.run(["git", "-C", str(dst), "checkout", "--quiet", "HEAD"],
                   check=True, capture_output=True)
    return dst


def _commit(root, msg="fixture"):
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(root), "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "--quiet", "--no-verify", "-m", msg],
                   check=True, capture_output=True)


def test_clean_tree_is_green(tmp_path):
    root = _clone(tmp_path)
    rc, out = _run(root)
    assert rc == 0, f"clean tree should pass, got rc={rc}\n{out}"
    assert "OK" in out


def test_a_new_unreached_test_file_fails(tmp_path):
    root = _clone(tmp_path)
    # A brand-new test file in a directory no runner touches.
    d = root / "q-system/.q-system/tests"
    (d / "test_zz_nobody_runs_me.py").write_text("def test_x():\n    assert True\n")
    _commit(root)
    rc, out = _run(root)
    assert rc == 2, f"a new unreached test must fail, got rc={rc}\n{out}"
    assert "test_zz_nobody_runs_me.py" in out


def test_declaring_it_makes_it_pass(tmp_path):
    """The escape hatch works -- otherwise the check is unfixable and gets
    switched off, which is how a red-by-default gate dies."""
    root = _clone(tmp_path)
    d = root / "q-system/.q-system/tests"
    (d / "test_zz_nobody_runs_me.py").write_text("def test_x():\n    assert True\n")
    frag = root / "q-system/.q-system/capability/expected_tests" / \
        "q-system__.q-system__tests__test_zz_nobody_runs_me.py.json"
    frag.write_text(json.dumps(
        {"path": "q-system/.q-system/tests/test_zz_nobody_runs_me.py",
         "runner": "pytest"}, indent=1) + "\n")
    _commit(root)
    rc, out = _run(root)
    assert rc == 0, f"a declared test must pass, got rc={rc}\n{out}"


def test_a_baselined_file_that_became_reached_fails(tmp_path):
    """The baseline must shrink. If a frozen file gets declared and the name
    stays in the baseline, the list rots into names nobody prunes."""
    root = _clone(tmp_path)
    base = json.loads((root / BASELINE_REL).read_text())
    assert base["unreached"], "fixture needs a non-empty baseline"
    target = base["unreached"][0]
    frag = root / "q-system/.q-system/capability/expected_tests" / \
        (target.replace("/", "__") + ".json")
    frag.write_text(json.dumps({"path": target, "runner": "pytest"}, indent=1) + "\n")
    _commit(root)
    rc, out = _run(root)
    assert rc == 2, f"a now-reached baseline entry must fail, got rc={rc}\n{out}"
    assert target in out


def test_a_baseline_naming_a_deleted_file_fails(tmp_path):
    root = _clone(tmp_path)
    base = json.loads((root / BASELINE_REL).read_text())
    target = base["unreached"][0]
    os.remove(root / target)
    _commit(root)
    rc, out = _run(root)
    assert rc == 2, f"a baseline naming a deleted file must fail, got rc={rc}\n{out}"
    assert target in out


def test_a_commented_out_ci_run_does_not_count_as_coverage(tmp_path):
    """verify.yml carries a commented `pytest q-system/.q-system/tests` today.
    If comments counted, this check would claim coverage for a step that runs
    nothing -- the exact confident-wrong-answer shape it exists to prevent."""
    root = _clone(tmp_path)
    d = root / "q-system/.q-system/tests"
    (d / "test_zz_nobody_runs_me.py").write_text("def test_x():\n    assert True\n")
    wf = root / ".github/workflows/verify.yml"
    wf.write_text(wf.read_text() + "\n          #   pytest q-system/.q-system/tests\n")
    _commit(root)
    rc, out = _run(root)
    assert rc == 2, f"a commented CI line must not confer coverage, got rc={rc}\n{out}"
