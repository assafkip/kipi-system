#!/usr/bin/env python3
"""Pins how validate.yml picks the diff base for the capability gate.

Founder-directed 2026-09-30: no full-suite run on a PR or on a push to main. The
full declared suite runs only in the nightly gates.yml. Before this, the push to
main took a bare `capability-gate.py --repo-root .`, which is the full suite, so
every merge paid it once more after the PR had already been graded.

The step's shell is EXECUTED here, not grepped: a text match would pass a step
that names --diff-base in a branch the push never reaches. python3 is a stub on
a sealed PATH that records its argv, so the gate itself never runs.

Set KIPI_VALIDATE_WORKFLOW to another copy of validate.yml to grade that copy
(the pre-fix file fails test_push_diffs_against_the_push_before_sha).
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = Path(os.environ.get("KIPI_VALIDATE_WORKFLOW")
                or ROOT / ".github" / "workflows" / "validate.yml")
STEP = "- name: Capability gate"


def _step_block(text: str) -> str:
    lines = text.splitlines()
    starts = [i for i, l in enumerate(lines) if l.strip().startswith(STEP)]
    assert len(starts) == 1, f"expected one {STEP!r} step, found {len(starts)}"
    i = starts[0]
    indent = len(lines[i]) - len(lines[i].lstrip())
    out = [lines[i]]
    for l in lines[i + 1:]:
        if l.strip() and len(l) - len(l.lstrip()) <= indent:
            break
        out.append(l)
    return "\n".join(out)


def _run_script(block: str) -> str:
    lines = block.splitlines()
    at = [i for i, l in enumerate(lines) if re.match(r"^\s+run:\s*\|\s*$", l)]
    assert len(at) == 1, "the capability gate step needs exactly one `run: |` block"
    run_indent = len(lines[at[0]]) - len(lines[at[0]].lstrip())
    body = []
    for l in lines[at[0] + 1:]:
        if l.strip() and len(l) - len(l.lstrip()) <= run_indent:
            break
        body.append(l)
    width = min(len(l) - len(l.lstrip()) for l in body if l.strip())
    return "\n".join(l[width:] for l in body) + "\n"


def _block() -> str:
    assert WORKFLOW.is_file(), f"missing {WORKFLOW}"
    return _step_block(WORKFLOW.read_text())


@pytest.fixture
def repo(tmp_path):
    """Two commits; returns (repo dir, first sha). Distinct messages and files,
    so the two commits can never collapse to one sha."""
    r = tmp_path / "repo"
    r.mkdir()
    env = _clean_env(tmp_path, os.environ["PATH"])

    def git(*a):
        return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t.invalid", *a],
                              cwd=r, env=env, check=True, capture_output=True, text=True).stdout.strip()
    git("init", "-q", "-b", "main")
    (r / "a.txt").write_text("one\n")
    git("add", "a.txt")
    git("commit", "-q", "-m", "first commit")
    first = git("rev-parse", "HEAD")
    (r / "b.txt").write_text("two\n")
    git("add", "b.txt")
    git("commit", "-q", "-m", "second commit")
    return r, first


def _clean_env(tmp_path, path):
    # Built from nothing: a hook that runs this test exports GIT_DIR, which would
    # bind every git call below to the real repo instead of the fixture.
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    return {"PATH": path, "HOME": str(home), "LC_ALL": "C"}


def _sealed_bin(tmp_path) -> Path:
    """PATH holds git and a recording python3 stub, nothing else. With the real
    python3 reachable the stub stubs nothing."""
    b = tmp_path / "bin"
    b.mkdir()
    real_git = shutil.which("git")
    assert real_git, "git is required"
    (b / "git").symlink_to(real_git)
    rec = tmp_path / "argv.txt"
    stub = b / "python3"
    stub.write_text(f"#!/bin/sh\nfor a in \"$@\"; do printf '%s\\n' \"$a\"; done > '{rec}'\n")
    stub.chmod(0o755)
    return b


def _drive(tmp_path, repo_dir, event, base_ref="", before=""):
    b = _sealed_bin(tmp_path)
    env = _clean_env(tmp_path, str(b))
    env.update({"EVENT": event, "BASE_REF": base_ref, "PUSH_BEFORE": before})
    bash = shutil.which("bash")
    p = subprocess.run([bash, "-e", "-c", _run_script(_block())], cwd=repo_dir, env=env,
                       capture_output=True, text=True)
    assert p.returncode == 0, f"step failed: {p.stdout}\n{p.stderr}"
    argv = (tmp_path / "argv.txt").read_text().splitlines()
    assert argv and argv[0].endswith("capability-gate.py"), f"the gate was not invoked: {argv}"
    return argv, p.stdout


def _diff_base(argv):
    assert "--diff-base" in argv, f"bare gate invocation = the FULL suite: {argv}"
    return argv[argv.index("--diff-base") + 1]


def test_push_diffs_against_the_push_before_sha(tmp_path, repo):
    r, first = repo
    argv, out = _drive(tmp_path, r, "push", before=first)
    assert _diff_base(argv) == first
    assert f"capability gate diff base: {first}" in out, "the log must name the base it used"


@pytest.mark.parametrize("before", [
    "0" * 40,                                         # a branch's first push
    "deadbeef" * 5,                                   # force-push: old tip not in the clone
    "",                                               # no before in the payload
])
def test_unusable_push_base_falls_back_to_first_parent(tmp_path, repo, before):
    r, _ = repo
    argv, _ = _drive(tmp_path, r, "push", before=before)
    assert _diff_base(argv) == "HEAD^"


def test_pull_request_diffs_against_the_target_branch(tmp_path, repo):
    r, _ = repo
    argv, _ = _drive(tmp_path, r, "pull_request", base_ref="main")
    assert _diff_base(argv) == "origin/main"


def test_no_event_reaches_a_bare_gate_invocation():
    code = [l for l in _run_script(_block()).splitlines() if not l.lstrip().startswith("#")]
    calls = [l for l in code if "capability-gate.py" in l]
    assert calls, "the step no longer calls the gate"
    for l in calls:
        assert "--diff-base" in l, f"bare invocation runs the full suite: {l.strip()}"


def test_event_values_reach_the_shell_through_env_only():
    # An expression spliced into `run:` is not reachable by the driver above, and
    # a pushed ref name in a script body is a shell-injection surface.
    block = _block()
    assert "${{" not in _run_script(block)
    for var, expr in (("EVENT", "github.event_name"), ("BASE_REF", "github.base_ref"),
                      ("PUSH_BEFORE", "github.event.before")):
        assert re.search(rf"(?m)^\s+{var}:\s*\$\{{\{{\s*{re.escape(expr)}\s*\}}\}}\s*$", block), var


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", *sys.argv[1:]]))
