#!/usr/bin/env python3
"""The auto-commit Stop hook (ASK-498).

The property: it is a safety net for GENERATED STATE, and it must never sweep an
instance's source tree into an unattended generic commit.
"""
from __future__ import annotations

import os
import subprocess
import sys

import pytest

HOOK = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))), "q-system", "hooks", "auto-commit.py")


def _repo(tmp_path):
    d = tmp_path / "repo"
    d.mkdir()
    run = lambda *a: subprocess.run(a, cwd=d, capture_output=True, text=True)
    run("git", "init", "-q")
    run("git", "config", "user.email", "t@t.t")
    run("git", "config", "user.name", "t")
    (d / "seed.txt").write_text("x")
    run("git", "add", "-A")
    run("git", "commit", "-q", "-m", "seed")
    return d, run


def _write(root, rel, body="content\n"):
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body)


def _fire(root):
    return subprocess.run([sys.executable, HOOK], capture_output=True, text=True,
                          cwd=root, env=dict(os.environ, CLAUDE_PROJECT_DIR=str(root)))


def _tracked(run):
    return run("git", "ls-files").stdout.split()


def test_the_hook_exists_where_settings_points():
    """Load-path proof. The Stop hook runs $CLAUDE_PROJECT_DIR/q-system/hooks/auto-commit.py."""
    assert os.path.isfile(HOOK), HOOK


def test_source_code_is_never_swept_into_a_generic_commit(tmp_path):
    """THE case. Three real sweeps (d96e621, 7a252f4, f0a3183) took feature work
    onto main under 'chore: update project files', twice racing the agent writing it."""
    root, run = _repo(tmp_path)
    _write(root, "q-consult/pipeline/repo_links.py", "# real work\n")
    _write(root, "q-consult/tests/test_thing.py", "# a test\n")
    out = _fire(root)
    tracked = _tracked(run)
    assert "q-consult/pipeline/repo_links.py" not in tracked
    assert "q-consult/tests/test_thing.py" not in tracked
    assert "update project files" not in run("git", "log", "--oneline").stdout


def test_unclassified_files_are_reported_not_silently_left(tmp_path):
    """Silence would recreate the defect in reverse: work uncommitted, nobody told."""
    root, _run = _repo(tmp_path)
    _write(root, "q-consult/pipeline/repo_links.py")
    out = _fire(root)
    assert "NOT committed" in out.stdout
    assert "q-consult/pipeline/repo_links.py" in out.stdout


def test_the_generated_state_safety_net_still_works(tmp_path):
    """Negative control. Without this, deleting the whole hook would pass every
    test above -- proving only that nothing is committed, which is not the goal."""
    root, run = _repo(tmp_path)
    _write(root, "memory/MEMORY.md", "- note\n")
    _write(root, "q-system/canonical/decisions.md", "RULE-1\n")
    _fire(root)
    tracked = _tracked(run)
    assert "memory/MEMORY.md" in tracked
    assert "q-system/canonical/decisions.md" in tracked


def test_a_mixed_tree_commits_state_and_leaves_source(tmp_path):
    """The real-world shape: an agent mid-edit while session memory also changed."""
    root, run = _repo(tmp_path)
    _write(root, "memory/MEMORY.md", "- note\n")
    _write(root, "q-consult/pipeline/repo_links.py", "# real work\n")
    _fire(root)
    tracked = _tracked(run)
    assert "memory/MEMORY.md" in tracked
    assert "q-consult/pipeline/repo_links.py" not in tracked


def _hook_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location("auto_commit", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_declared_skips_are_not_reported_as_unclassified():
    """q-system/output is gitignored on purpose; nagging about it is noise.

    Driven through `group_files` directly, not the CLI: `get_changed_files` already
    filters q-system/output before classify ever sees it, so the end-to-end route
    could never reach this branch. Mutation-caught -- routing declared skips into
    the unclassified list left the CLI test green because the path never arrived.
    """
    mod = _hook_module()
    groups, unclassified = mod.group_files({
        "q-system/output/report.json",
        "memory/MEMORY.md",
        "q-consult/pipeline/x.py",
    })
    assert unclassified == ["q-consult/pipeline/x.py"], \
        "a declared skip must not be reported as unclassified"
    assert list(groups.values()) == [["memory/MEMORY.md"]]


def test_classify_answers_the_three_cases():
    mod = _hook_module()
    assert mod.classify("memory/MEMORY.md") == ("chore", "update auto-memory")
    assert mod.classify("q-system/output/x.json") == mod.SKIP_DECLARED
    assert mod.classify("q-consult/pipeline/x.py") == mod.SKIP_UNCLASSIFIED


def test_every_auto_commit_still_declares_its_bypass(tmp_path):
    """The hook cannot know the issue, so it must keep declaring the hatch and
    stay countable in the bypass ledger."""
    root, run = _repo(tmp_path)
    _write(root, "memory/MEMORY.md", "- note\n")
    _fire(root)
    body = run("git", "log", "-1", "--format=%B").stdout
    assert "[no-issue:" in body


def test_the_hook_never_raises_into_session_exit(tmp_path):
    """It is a Stop hook. A crash here must not cost the session."""
    out = subprocess.run([sys.executable, HOOK], capture_output=True, text=True,
                         cwd=str(tmp_path),
                         env=dict(os.environ, CLAUDE_PROJECT_DIR="/nonexistent/nope"))
    assert out.returncode == 0
