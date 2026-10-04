#!/usr/bin/env python3
"""lessons-push-guard.py: a committed non-lesson path cannot ride a lessons push.

sp-368fb6f6. The weekly lessons routine checked only STAGED paths, so a file a
Stop hook committed onto the branch was invisible to it. Every repo here is a
throwaway under tmp_path with a `git init --bare` remote; nothing reaches
github.com. Fixture content is placeholder text only: kipi-system is public.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "lessons-push-guard.py"


@pytest.fixture(autouse=True)
def _no_inherited_git(monkeypatch):
    # A hook-launched pytest exports GIT_DIR, which outranks cwd= and would aim
    # every fixture command at the real repo.
    for k in ("GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE"):
        monkeypatch.delenv(k, raising=False)


def git(cwd, *args):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    assert r.returncode == 0, f"git {args}: {r.stderr}"
    return r.stdout


def commit(root, rel, body="placeholder\n", msg="c"):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)
    git(root, "add", rel)
    git(root, "commit", "-q", "-m", msg)


@pytest.fixture
def clone(tmp_path):
    bare = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    root = tmp_path / "clone"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    for k, v in (("user.email", "t@t.t"), ("user.name", "t"), ("commit.gpgsign", "false")):
        git(root, "config", k, v)
    git(root, "remote", "add", "origin", str(bare))
    commit(root, "README.md")
    commit(root, "q-system/memory/stamp", "old\n")
    git(root, "push", "-q", "origin", "main")
    git(root, "fetch", "-q", "origin")
    git(root, "checkout", "-q", "-b", "lessons/weekly-x")
    return root


def run_guard(root, via_stdin=False):
    if via_stdin:  # the shape the prompt uses: main's copy, piped
        return subprocess.run([sys.executable, "-"], input=SCRIPT.read_text(), cwd=root,
                              capture_output=True, text=True)
    return subprocess.run([sys.executable, str(SCRIPT)], cwd=root, capture_output=True, text=True)


def staged_check_refuses(root) -> bool:
    """The routine's OLD check, verbatim regex: a staged-only view."""
    staged = git(root, "diff", "--cached", "--name-only")
    r = subprocess.run(["grep", "-v", "-E",
                        r"^(q-system/lessons/[^/]+\.md|lesson-candidates/\.processed\.json)$"],
                       input=staged, capture_output=True, text=True)
    return r.returncode == 0


def test_lessons_only_branch_passes(clone):
    commit(clone, "q-system/lessons/a-gate-that-lies.md")
    commit(clone, "lesson-candidates/.processed.json", "{}\n")
    r = run_guard(clone)
    assert r.returncode == 0, r.stderr
    assert run_guard(clone, via_stdin=True).returncode == 0


def test_a_committed_stamp_is_refused_where_the_staged_check_saw_nothing(clone):
    commit(clone, "q-system/lessons/a.md")
    # The 2026-10-04 shape: a Stop hook commits a non-lesson file after the
    # lessons commit. Nothing is staged when the push step runs.
    commit(clone, "q-system/memory/stamp", "new\n", msg="chore: update session memory")
    assert not staged_check_refuses(clone), "control: the old check must be blind here"
    for via_stdin in (False, True):
        r = run_guard(clone, via_stdin=via_stdin)
        assert r.returncode == 2, (via_stdin, r.stdout, r.stderr)
        assert "q-system/memory/stamp" in r.stderr
        assert "q-system/lessons/a.md" not in r.stderr


def test_a_rename_into_lessons_still_names_the_old_public_path(clone):
    commit(clone, "q-system/lessons/a.md")
    git(clone, "mv", "q-system/memory/stamp", "q-system/lessons/stamp.md")
    git(clone, "commit", "-q", "-m", "mv")
    r = run_guard(clone)
    assert r.returncode == 2 and "q-system/memory/stamp" in r.stderr


def test_a_nested_lesson_path_is_refused(clone):
    commit(clone, "q-system/lessons/sub/nested.md")
    assert run_guard(clone).returncode == 2


def test_no_base_fails_closed_with_a_distinct_code(clone):
    r = subprocess.run([sys.executable, str(SCRIPT), "--base", "origin/nope"], cwd=clone,
                       capture_output=True, text=True)
    assert r.returncode == 3, r.stderr


def test_added_then_deleted_is_still_refused(clone):
    # The net diff is clean here; the pushed history still carries the blob.
    commit(clone, "q-system/lessons/a.md")
    commit(clone, "lesson-candidates/held-0001.md")
    git(clone, "rm", "-q", "lesson-candidates/held-0001.md")
    git(clone, "commit", "-q", "-m", "drop it")
    assert git(clone, "diff", "--name-only", "origin/main...HEAD").split() == ["q-system/lessons/a.md"]
    r = run_guard(clone)
    assert r.returncode == 2 and "lesson-candidates/held-0001.md" in r.stderr, r.stderr
