"""Self-contained test for the cross-runner concurrency guard at issue load.

issue_runner must refuse to load an issue while a non-archived PRD is active
(symmetric with prd-os's prd_runner refusing to start a PRD while an issue is
active). An archived PRD, or no PRD state, must not block.

Run: python3 test_concurrency_guard.py   (also discoverable by pytest)
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
_SPEC = f"""\
---
id: issue-a
title: issue-a fixture
status: open
priority: p0
allowed_files:
  - src/a.py
disallowed_files: []
required_checks: []
required_reviews: []
---
{_MARKER}

body
"""


def _repo(d):
    repo = Path(d)
    (repo / ".git").mkdir()
    issues = repo / ".prd-os" / "issues"
    issues.mkdir(parents=True)
    (issues / "issue-a.md").write_text(_SPEC)
    return repo


def _write_prd_state(repo, prd_id, status):
    p = repo / ".claude" / "state" / "active-prd.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"prd_id": prd_id, "status": status}))


def _load(repo):
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(repo)
    return subprocess.run(
        [sys.executable, str(RUNNER), "load", "issue-a"],
        cwd=str(repo), capture_output=True, text=True, env=env,
    )


def test_load_refused_when_prd_active():
    with tempfile.TemporaryDirectory() as d:
        repo = _repo(d)
        _write_prd_state(repo, "prd-live-2026-04-16", "in-review")
        r = _load(repo)
        assert r.returncode == 2, r.stdout
        assert "prd-live-2026-04-16" in r.stderr
        assert "load issue" in r.stderr


def test_load_allowed_when_prd_archived():
    with tempfile.TemporaryDirectory() as d:
        repo = _repo(d)
        _write_prd_state(repo, "prd-old-2026-04-16", "archived")
        r = _load(repo)
        assert r.returncode == 0, r.stderr


def test_load_allowed_when_no_prd_state():
    with tempfile.TemporaryDirectory() as d:
        repo = _repo(d)
        r = _load(repo)
        assert r.returncode == 0, r.stderr


if __name__ == "__main__":
    test_load_refused_when_prd_active()
    test_load_allowed_when_prd_archived()
    test_load_allowed_when_no_prd_state()
    print("ok")
