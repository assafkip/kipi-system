#!/usr/bin/env python3
"""RED FIRST. Issue mbl-changelog-convention (prd-morning-brief-learns,
Codex finding-3). The convention is documented ONCE in
plugins/kipi-core/skills/README.md and asserted on the skill this PRD creates.
No wildcard over existing skills: the allowed_files of this issue are read from
its own spec and checked for a `*`, so the scope cannot quietly widen.

Every list here is derived from disk (git-tracked paths, the issue specs),
never restated (lesson: derive-a-value-from-its-owner-never-restate-it-in-a-test).
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent.parent
README = ROOT / "plugins" / "kipi-core" / "skills" / "README.md"
ISSUES = ROOT / ".prd-os" / "issues"
THIS_ISSUE = ISSUES / "mbl-changelog-convention.md"
OWNER_OF_IMPROVE = ISSUES / "mbl-improve-skill.md"
DATED = re.compile(r"^- (\d{4}-\d{2}-\d{2}): \S")


def _spec(path: Path):
    text = path.read_text(encoding="utf-8")
    status = next(l.split(":", 1)[1].strip() for l in text.splitlines() if l.startswith("status:"))
    allowed = []
    in_block = False
    for line in text.splitlines():
        if line.startswith("allowed_files:"):
            in_block = True
            continue
        if in_block:
            if line.startswith("  - "):
                allowed.append(line[4:].strip())
            else:
                in_block = False
    assert allowed, f"{path.name}: no allowed_files parsed"
    return status, allowed


def _changelog_lines(text: str):
    """Lines of the `## Changelog` section, or None when the heading is absent."""
    heads = [m.start() for m in re.finditer(r"^## Changelog\s*$", text, re.M)]
    if not heads:
        return None
    assert len(heads) == 1, "one Changelog heading per file"
    tail = text[heads[0]:].splitlines()[1:]
    assert not any(l.startswith("## ") for l in tail), "Changelog must be the last section"
    return [l for l in tail if l.strip()]


def _tracked_skill_files():
    out = subprocess.run(["git", "ls-files", "plugins/kipi-core/skills"], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout.split()
    files = [ROOT / p for p in out if p.endswith("/SKILL.md")]
    assert files, "git ls-files found no SKILL.md; the derivation is broken"
    return files


def test_readme_states_the_convention():
    assert README.is_file(), f"missing: {README.relative_to(ROOT)}"
    text = README.read_text(encoding="utf-8")
    assert "## Changelog convention" in text
    assert "- YYYY-MM-DD:" in text and "Newest first" in text


def test_no_wildcard_in_this_issues_scope():
    status, allowed = _spec(THIS_ISSUE)
    assert not any("*" in a for a in allowed), allowed
    assert not any(a.endswith("SKILL.md") for a in allowed), "this issue edits no skill file"


def _git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout


def test_no_existing_skill_file_was_modified_by_this_issue():
    """Read git, not the spec (both Codex reviewers on this issue: a declared
    scope proves nothing about the diff). Two checks: no commit that names this
    issue touches a pre-existing SKILL.md, and while the issue is active the
    working tree carries no SKILL.md change."""
    status, _ = _spec(THIS_ISSUE)
    for path in _tracked_skill_files():
        rel = str(path.relative_to(ROOT))
        touching = _git("log", "--format=%s", "--", rel)
        assert THIS_ISSUE.stem not in touching, f"{rel} was modified by a commit of {THIS_ISSUE.stem}"
    if status == "in-progress":
        dirty = _git("diff", "HEAD", "--name-only").split() + _git("diff", "--cached", "--name-only").split()
        assert not [p for p in dirty if p.endswith("/SKILL.md")], dirty


def test_every_changelog_section_that_exists_is_well_formed():
    """Applies to any skill that adopted the section; a malformed one fails."""
    for path in _tracked_skill_files():
        lines = _changelog_lines(path.read_text(encoding="utf-8"))
        if lines is None:
            continue
        dates = []
        for line in lines:
            m = DATED.match(line)
            assert m, f"{path.relative_to(ROOT)}: changelog line not '- YYYY-MM-DD: text': {line!r}"
            dates.append(m.group(1))
        assert dates, f"{path.relative_to(ROOT)}: empty Changelog section"
        assert dates == sorted(dates, reverse=True), f"{path.relative_to(ROOT)}: newest first"


def test_improve_skill_carries_the_header_once_its_owner_closes():
    status, allowed = _spec(OWNER_OF_IMPROVE)
    skill = ROOT / next(a for a in allowed if a.endswith("SKILL.md"))
    if not skill.is_file():
        assert status != "closed", f"{OWNER_OF_IMPROVE.name} is closed but {skill.relative_to(ROOT)} is absent"
        pytest.skip(f"{skill.relative_to(ROOT)} not built yet; owner {OWNER_OF_IMPROVE.stem} is {status}; "
                    f"this test fails the day it closes without the header")
    lines = _changelog_lines(skill.read_text(encoding="utf-8"))
    assert lines, f"{skill.relative_to(ROOT)} must carry a ## Changelog section with at least one dated line"


def test_this_file_runs_its_own_tests_under_python3():
    """runner=python3 means `python3 <this file>` IS the run. Two halves, both
    needed (Codex minor on this issue: a nonexistent -k returns nonzero even
    when the real tests are broken): the plain run exits 0 only because tests
    were collected AND passed (pytest exits 5 on zero collected), and a
    selection that matches nothing exits nonzero. The inner run skips this
    test via an env var so it does not recurse."""
    import os
    if os.environ.get("KIPI_SELFTEST_INNER"):
        pytest.skip("inner run")
    env = dict(os.environ, KIPI_SELFTEST_INNER="1")
    ok = subprocess.run([sys.executable, __file__], capture_output=True, text=True, env=env)
    assert ok.returncode == 0, ok.stdout[-600:]
    assert "passed" in ok.stdout, "no test ran under python3 <file>"
    none = subprocess.run([sys.executable, __file__, "-k", "no_such_test_zzz"], capture_output=True, text=True, env=env)
    assert none.returncode != 0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", *sys.argv[1:]]))
