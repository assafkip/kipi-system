#!/usr/bin/env python3
"""The loop's agent-scratch files at the repo root must be un-stageable (ASK-922).

why this shape: the autonomous loop writes two kinds of transient file at the repo
root -- the refusal sentinels (`.sana-needs-scope`, `.sana-blocked-capability`) and
the per-issue PR body it feeds to `gh pr create` (`.pr-body-ask-<n>.md`). PR #141
closed the sentinel half after one was swept into a commit by `git add -A`; the
PR-body half was left uncovered (spillover sp-b2a5e5be), so the same `git add -A`
still commits it.

The assertion is made against the SHIPPED `.gitignore` in this checkout, resolved
through `git rev-parse --show-toplevel`, not a synthetic copy written by the test.
A copy would only prove the pattern I typed agrees with the pattern I typed; the
defect is in the file the repo actually ships, so that is the file consulted.

NEGATIVE SELF-TEST: the DoR asks for an anchored pattern (`/.pr-body-*.md`) rather
than a bare glob, because a bare glob would also swallow a legitimately-tracked
`.pr-body-*.md` anywhere in the tree. A fix that ignores the name at every depth
would satisfy the positive case, so `test_pattern_is_anchored_to_the_repo_root`
fails it.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(subprocess.run(
    ["git", "-C", str(Path(__file__).resolve().parent), "rev-parse", "--show-toplevel"],
    capture_output=True, text=True, check=True).stdout.strip())

# The name the loop actually writes. ASK-700's was observed on disk at the root of
# its own worktree; any issue number exercises the same pattern.
SCRATCH = ".pr-body-ask-700.md"


def _check_ignore(relpath):
    """(exit code, -v output). check-ignore does not require the path to exist."""
    p = subprocess.run(["git", "-C", str(REPO), "check-ignore", "-v", "--", relpath],
                       capture_output=True, text=True)
    return p.returncode, p.stdout.strip()


def test_pr_body_scratch_is_ignored():
    """RED before the .gitignore edit: exit 1, no output."""
    rc, out = _check_ignore(SCRATCH)
    assert rc == 0, (
        f"`{SCRATCH}` is not ignored, so a broad `git add -A` in an agent worktree "
        "stages it and the loop commits its own PR-body scratch. Add an anchored "
        "`/.pr-body-*.md` next to the sentinel entries in .gitignore.")
    assert ".gitignore" in out, f"expected .gitignore to be the source: {out!r}"


def test_the_sentinels_it_sits_next_to_are_still_ignored():
    """PR #141's fix must survive this change; an edit near it could undo it."""
    for name in (".sana-needs-scope", ".sana-blocked-capability"):
        rc, out = _check_ignore(name)
        assert rc == 0, f"`{name}` stopped being ignored: {out!r}"


def test_pattern_is_anchored_to_the_repo_root():
    """A bare `.pr-body-*.md` glob would ignore the name at every depth.

    The scratch file only ever lands at the root -- that is where the loop writes it
    and where `gh pr create` is run -- so a tree-wide ignore buys nothing and could
    silently hide a real file someone puts under a subdirectory later.
    """
    nested = f"q-system/.q-system/scripts/{SCRATCH}"
    rc, out = _check_ignore(nested)
    assert rc != 0, (
        f"`{nested}` is ignored too, so the pattern is not anchored to the repo "
        f"root: {out!r}")


def test_no_scratch_file_is_already_tracked():
    """An ignore does nothing for a path git is already tracking."""
    tracked = subprocess.run(
        ["git", "-C", str(REPO), "ls-files", "--", ".pr-body-*.md"],
        capture_output=True, text=True, check=True).stdout.strip()
    assert not tracked, f"scratch files already committed, ignore will not cover them:\n{tracked}"


def test_a_real_root_file_is_not_ignored():
    """Guards the opposite bug: a pattern broad enough to swallow the repo."""
    rc, out = _check_ignore("README.md")
    assert rc != 0, f"README.md became ignored: {out!r}"


if __name__ == "__main__":
    # The capability-gate manifest runner is `python3 <file>` (capability-gate.py:127),
    # and a pytest module with no __main__ collects nothing under it and exits 0 --
    # reported coverage that never ran (sp-bbdcf57b). This file runs itself.
    raise SystemExit(subprocess.call(
        [sys.executable, "-m", "pytest", "-q", os.path.abspath(__file__)]))
