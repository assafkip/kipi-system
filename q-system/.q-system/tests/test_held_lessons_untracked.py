#!/usr/bin/env python3
"""A held lesson never reaches the public repo (ASK-2278).

RED FIRST. A `held-<hash>.md` is the lesson the client-data gate could NOT
clear (lessons-distill.py writes it into lesson-candidates/). This repo is
public, and lessons-daily.sh persists with `git add q-system/lessons
lesson-candidates`, so every held lesson was committed and pushed: the one
place the pipeline parks text it suspects is private was the one place it
published it. Two were on main when this was found (added 2026-07-27 and
2026-08-24).

The fix is an ignore rule, not a change to the committer: `git add <dir>`
skips ignored files silently, so the job keeps staging the ledger and the
published lessons and the held file stays on the machine that wrote it.

Nothing here touches a live repo's index: the committer test builds its own
throwaway repo under tmp_path and scrubs inherited GIT_* env (a hook-exported
GIT_DIR outranks cwd=).
"""
import os
import shutil
import subprocess

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

_GIT_ENV = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR",
            "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_PREFIX")


def _env():
    return {k: v for k, v in os.environ.items() if k not in _GIT_ENV}


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, env=_env(), capture_output=True, text=True)


def test_no_held_lesson_is_tracked():
    tracked = _git(REPO, "ls-files", "lesson-candidates").stdout.split()
    held = [p for p in tracked if os.path.basename(p).startswith("held-")]
    assert held == [], f"held lessons are tracked in a public repo: {held}"


def test_a_new_held_lesson_is_ignored():
    r = _git(REPO, "check-ignore", "-q", "--no-index", "lesson-candidates/held-0123456789abcdef.md")
    assert r.returncode == 0, "lesson-candidates/held-*.md is not ignored"


def test_the_daily_committer_stages_the_ledger_but_not_a_held_lesson(tmp_path):
    """Drives the committer's own `git add` line against a repo carrying this
    repo's .gitignore: the ledger and a published lesson are staged, the held
    lesson is not. The ledger half is the control: it proves the add ran."""
    work = tmp_path / "skel"
    (work / "lesson-candidates").mkdir(parents=True)
    (work / "q-system" / "lessons").mkdir(parents=True)
    shutil.copy(os.path.join(REPO, ".gitignore"), work / ".gitignore")
    (work / "lesson-candidates" / ".processed.json").write_text("{}\n")
    (work / "lesson-candidates" / "held-0123456789abcdef.md").write_text("# HELD lesson\n")
    (work / "q-system" / "lessons" / "a-lesson.md").write_text("# lesson\n")
    assert _git(work, "init", "-q").returncode == 0
    _git(work, "add", "q-system/lessons", "lesson-candidates")
    staged = _git(work, "diff", "--cached", "--name-only").stdout.split()
    assert "lesson-candidates/.processed.json" in staged, staged
    assert "q-system/lessons/a-lesson.md" in staged, staged
    assert not [p for p in staged if "held-" in p], f"the committer staged a held lesson: {staged}"
