"""issue-start (`load`) refuses a spec while a depends_on issue is not closed (ASK-4233).

why: prd_split dropped depends_on, so an out-of-order spec started without a
word (spillover sp-e37fa02c). Specs with no depends_on key, which is every
spec split before this change, load exactly as before: the control below.

Run: python3 test_depends_on_start.py   (also discoverable by pytest)
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

RUNNER = Path(__file__).resolve().parent / "issue_runner.py"

_MARKER = (
    "<!-- generated-by: prd_split.py prd=prd-fixture finding=finding-fixture "
    "at=2026-04-20T00:00:00Z -->"
)


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True)


def _runner(repo, *args):
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(repo)
    return subprocess.run([sys.executable, str(RUNNER), *args],
                          cwd=str(repo), capture_output=True, text=True, env=env)


def _setup(tmp):
    repo = Path(tmp)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / ".prd-os").mkdir(parents=True, exist_ok=True)
    (repo / ".prd-os" / "config.json").write_text(json.dumps({
        "config_schema_version": 1,
        "issues_dir": ".prd-os/issues",
        "state_dir": ".claude/state",
    }))
    (repo / "src").mkdir()
    (repo / "src" / "tracked.py").write_text("x = 1\n")
    return repo


def _write_spec(repo, issue_id, status="open", depends_on_line=""):
    issues = repo / ".prd-os" / "issues"
    issues.mkdir(parents=True, exist_ok=True)
    (issues / f"{issue_id}.md").write_text(
        "---\n"
        f"id: {issue_id}\n"
        f"title: {issue_id} fixture\n"
        f"status: {status}\n"
        "priority: p0\n"
        "allowed_files:\n  - src/tracked.py\n"
        "disallowed_files: []\n"
        "required_checks:\n  - python3 src/tracked.py\n"
        "required_reviews: []\n"
        f"{depends_on_line}"
        "---\n\n"
        f"{_MARKER}\n\nFixture.\n"
    )


def test_load_refuses_while_a_listed_issue_is_not_closed_then_loads_once_closed():
    with tempfile.TemporaryDirectory() as tmp:
        repo = _setup(tmp)
        _write_spec(repo, "dep-first", status="open")
        _write_spec(repo, "dep-second", depends_on_line="depends_on: [dep-first]\n")
        blocked = _runner(repo, "load", "dep-second")
        assert blocked.returncode == 2, blocked.stdout + blocked.stderr
        assert "dep-first" in blocked.stderr, blocked.stderr
        assert not (repo / ".claude" / "state" / "active-issue.json").exists()
        _write_spec(repo, "dep-first", status="closed")
        ok = _runner(repo, "load", "dep-second")
        assert ok.returncode == 0, ok.stdout + ok.stderr
        assert json.loads(ok.stdout)["loaded"] == "dep-second"


def test_load_refuses_every_listed_issue_that_is_not_closed():
    with tempfile.TemporaryDirectory() as tmp:
        repo = _setup(tmp)
        _write_spec(repo, "dep-a", status="closed")
        _write_spec(repo, "dep-b", status="in-progress")
        _write_spec(repo, "dep-c",
                    depends_on_line="depends_on:\n  - dep-a\n  - dep-b\n")
        r = _runner(repo, "load", "dep-c")
        assert r.returncode == 2, r.stdout + r.stderr
        assert "dep-b" in r.stderr and "dep-a" not in r.stderr, r.stderr


def test_load_refuses_a_listed_issue_that_does_not_exist_with_its_own_message():
    with tempfile.TemporaryDirectory() as tmp:
        repo = _setup(tmp)
        _write_spec(repo, "dep-orphan", depends_on_line="depends_on: [dep-ghost]\n")
        r = _runner(repo, "load", "dep-orphan")
        assert r.returncode == 2, r.stdout + r.stderr
        assert "dep-ghost" in r.stderr and "no spec" in r.stderr, r.stderr
        assert "not closed" not in r.stderr, r.stderr


def test_control_spec_without_depends_on_loads_as_before():
    with tempfile.TemporaryDirectory() as tmp:
        repo = _setup(tmp)
        _write_spec(repo, "dep-plain")
        r = _runner(repo, "load", "dep-plain")
        assert r.returncode == 0, r.stdout + r.stderr
        assert json.loads(r.stdout)["loaded"] == "dep-plain"


def test_control_empty_depends_on_loads_as_before():
    with tempfile.TemporaryDirectory() as tmp:
        repo = _setup(tmp)
        _write_spec(repo, "dep-empty", depends_on_line="depends_on: []\n")
        r = _runner(repo, "load", "dep-empty")
        assert r.returncode == 0, r.stdout + r.stderr


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  [PASS] {fn.__name__}")
    print(f"depends-on start self-test: all {len(fns)} cases passed")
