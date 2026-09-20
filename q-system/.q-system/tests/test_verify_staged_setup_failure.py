"""
Regression test for ASK-1907: a verify.sh --staged run that could not even
START the staged-snapshot setup (git worktree add refused, or write-tree
could not read the index) must be distinguishable from a run that started,
executed checks, and one of them failed.

Before this fix, both cases exited 1 -- the same code a real check failure
uses -- and lefthook's static fail_text told the operator "verify.sh failed
on the STAGED snapshot... this will not pass later" regardless of which one
happened. Measured 2026-09-19: a worktree-add refusal from contention with a
second worktree of this repo exited in 0.10s (a real run is ~23s), yet wore
the exact same failure text a genuine 23s check failure gets.

This test never touches the real repo's .git: every scenario runs against a
throwaway git repo built under tmp_path, with a stub `git` on PATH that
forces exactly one git subcommand to fail (worktree add, or write-tree) and
forwards everything else, unchanged, to the real git. That is the
fable-discipline "verify against a copy" rule applied to a shell script that
itself exists to verify against a copy.
"""
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
VERIFY_SH = REPO_ROOT / "q-system" / ".q-system" / "verify.sh"
SETUP_FAIL_CODE = 3
CHECK_FAIL_CODE = 1

REAL_GIT = shutil.which("git")


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "a@a.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "a"], cwd=repo, check=True)
    (repo / "f.txt").write_text("hi\n")
    # A tracked .json file is not incidental: with ZERO tracked .json files
    # verify.sh's own JSONFILES pipeline (`git ls-files '*.json' | grep -v
    # ... | head`) has `grep -v` see no input, exit 1, and -- under
    # `set -o pipefail` with no `if` around the assignment -- kill the whole
    # script via errexit before it reaches ANY of this test's assertions.
    # That is a separate, real, pre-existing defect (captured to spillover,
    # not fixed here -- out of ASK-1907's scope), and this fixture works
    # around it rather than silently tripping over it.
    (repo / "dummy.json").write_text("{}\n")
    subprocess.run(["git", "add", "f.txt", "dummy.json"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    # Stage a second change so verify.sh's ANY_STAGED check is non-empty and
    # it proceeds to build the staged snapshot instead of exiting early.
    (repo / "g.txt").write_text("staged change\n")
    subprocess.run(["git", "add", "g.txt"], cwd=repo, check=True)


def _write_shim(shim_dir: Path, fail_subcommand: str, repo: Path) -> None:
    """A `git` on PATH that fails exactly ONE subcommand and forwards the
    rest, byte for byte, to the real git. Deterministic stand-in for a real
    lock-contention refusal -- no sleeps, no races, no flakiness."""
    shim_dir.mkdir(parents=True, exist_ok=True)
    shim = shim_dir / "git"
    if fail_subcommand == "worktree add":
        body = f"""#!/usr/bin/env bash
args=("$@")
for i in "${{!args[@]}}"; do
  if [ "${{args[$i]}}" = "worktree" ] && [ "${{args[$((i+1))]}}" = "add" ]; then
    echo "fatal: Unable to create '{repo}/.git/worktrees/wt/locked': File exists." >&2
    echo "fatal: another git process seems to be running in this repository" >&2
    exit 128
  fi
done
exec {REAL_GIT} "$@"
"""
    elif fail_subcommand == "write-tree":
        body = f"""#!/usr/bin/env bash
sub="$1"
if [ "$1" = "-C" ]; then sub="$3"; fi
if [ "$sub" = "write-tree" ]; then
  echo "fatal: git-write-tree: error building trees" >&2
  exit 128
fi
exec {REAL_GIT} "$@"
"""
    else:
        raise ValueError(fail_subcommand)
    shim.write_text(body)
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _run_verify_staged(repo: Path, shim_dir: Path | None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    if shim_dir is not None:
        env["PATH"] = f"{shim_dir}:{env['PATH']}"
    return subprocess.run(
        ["bash", str(VERIFY_SH), "--staged"],
        cwd=repo, env=env, capture_output=True, text=True, timeout=60,
    )


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    _init_repo(r)
    return r


def test_worktree_add_failure_is_setup_failed_not_check_failed(repo, tmp_path):
    shim_dir = tmp_path / "shim-wt"
    _write_shim(shim_dir, "worktree add", repo)
    result = _run_verify_staged(repo, shim_dir)
    assert result.returncode == SETUP_FAIL_CODE, (
        f"expected the distinct setup-failure exit code {SETUP_FAIL_CODE}, "
        f"got {result.returncode}. stderr:\n{result.stderr}"
    )
    assert result.returncode != CHECK_FAIL_CODE
    assert "SETUP FAILED" in result.stderr
    assert "no checks ran" in result.stderr
    # The underlying git error must be named, not swallowed.
    assert "worktrees/wt/locked" in result.stderr


def test_write_tree_failure_is_setup_failed_not_check_failed(repo, tmp_path):
    shim_dir = tmp_path / "shim-wr"
    _write_shim(shim_dir, "write-tree", repo)
    result = _run_verify_staged(repo, shim_dir)
    assert result.returncode == SETUP_FAIL_CODE
    assert "SETUP FAILED" in result.stderr
    assert "no checks ran" in result.stderr
    assert "could not read the staged index" in result.stderr


def test_setup_failure_never_claims_a_check_ran(repo, tmp_path):
    """The exact confusion from ASK-1907: a setup failure must not read as
    'a check ran on the staged snapshot and failed'."""
    shim_dir = tmp_path / "shim-wt2"
    _write_shim(shim_dir, "worktree add", repo)
    result = _run_verify_staged(repo, shim_dir)
    combined = result.stdout + result.stderr
    assert "verify.sh FAILED (" not in combined  # that phrasing is the check-failure summary


def test_real_worktree_add_still_succeeds_without_the_shim(repo):
    """Negative control: with a real, uncontended git, nothing in the new
    setup_fail wiring changes the happy path. The repo's one tracked
    dummy.json is valid, so the json-parse check runs and passes, and
    verify.sh exits 0 -- a DIFFERENT outcome than setup_fail's exit 3, which
    must never fire on a run that had no setup trouble."""
    result = _run_verify_staged(repo, None)
    assert result.returncode == 0, (
        f"expected a clean pass, got {result.returncode}. "
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "verify.sh ok" in result.stdout
    assert "SETUP FAILED" not in result.stderr
