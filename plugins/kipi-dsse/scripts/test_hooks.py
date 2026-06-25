"""Self-contained tests for the kipi-dsse PreToolUse scope hook and Stop gate.

These hooks are the sole issue-scope/stop enforcement after the legacy prd-os
copies were removed. They were previously untested. Tests drive the real hook
scripts as subprocesses (the way Claude Code invokes them), against state
written by the real issue_runner, with CLAUDE_PLUGIN_ROOT + CLAUDE_PROJECT_DIR
set the way production sets them.

Run: python3 test_hooks.py   (also discoverable by pytest)
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = PLUGIN_ROOT / "scripts"
RUNNER = SCRIPTS / "issue_runner.py"
SCOPE_HOOK = PLUGIN_ROOT / "hooks" / "scope_hook.py"
STOP_GATE = PLUGIN_ROOT / "hooks" / "stop_gate.py"

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
disallowed_files:
  - src/secret.py
required_checks: []
required_reviews: []
---
{_MARKER}

body
"""


def _env(repo):
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(repo)
    env["CLAUDE_PLUGIN_ROOT"] = str(PLUGIN_ROOT)
    env.pop("ISSUE_GATE_OFF", None)
    return env


def _runner(repo, *args, env_extra=None):
    env = _env(repo)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, str(RUNNER), *args],
        cwd=str(repo), capture_output=True, text=True, env=env,
    )


def _hook(script, repo, payload, env_extra=None):
    env = _env(repo)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, str(script)],
        cwd=str(repo), capture_output=True, text=True, env=env,
        input=json.dumps(payload) if payload is not None else "",
    )


def _new_repo(d, *, active=True):
    """Repo with config + issue spec. When active, load+approve the issue so
    state carries allowed_files_snapshot and an in-progress, unclosed issue."""
    repo = Path(d)
    (repo / ".git").mkdir()
    issues = repo / ".prd-os" / "issues"
    issues.mkdir(parents=True)
    (issues / "issue-a.md").write_text(_SPEC)
    if active:
        assert _runner(repo, "load", "issue-a").returncode == 0
        assert _runner(repo, "approve").returncode == 0
    return repo


def _edit(path):
    return {"tool_name": "Edit", "tool_input": {"file_path": path}}


def _env_no_project(repo):
    """Env with plugin root but no CLAUDE_PROJECT_DIR, to exercise cwd walk-up."""
    env = _env(repo)
    env.pop("CLAUDE_PROJECT_DIR", None)
    return env


def _hook_no_project(script, repo, payload, *, cwd):
    return subprocess.run(
        [sys.executable, str(script)],
        cwd=str(cwd), capture_output=True, text=True, env=_env_no_project(repo),
        input=json.dumps(payload),
    )


# Spec where allowed_files is a glob that also matches a disallowed entry, so
# disallowed must take precedence.
_SPEC_PRECEDENCE = f"""\
---
id: issue-a
title: issue-a fixture
status: open
priority: p0
allowed_files:
  - src/*
disallowed_files:
  - src/secret.py
required_checks: []
required_reviews: []
---
{_MARKER}

body
"""


# --- scope hook --------------------------------------------------------------


def test_scope_allows_in_scope_path():
    with tempfile.TemporaryDirectory() as d:
        repo = _new_repo(d)
        r = _hook(SCOPE_HOOK, repo, _edit("src/a.py"))
        assert r.returncode == 0, r.stderr


def test_scope_blocks_out_of_scope_path():
    with tempfile.TemporaryDirectory() as d:
        repo = _new_repo(d)
        r = _hook(SCOPE_HOOK, repo, _edit("other/x.py"))
        assert r.returncode == 2, f"expected block, got {r.returncode}: {r.stdout}"


def test_scope_blocks_disallowed_path():
    with tempfile.TemporaryDirectory() as d:
        repo = _new_repo(d)
        r = _hook(SCOPE_HOOK, repo, _edit("src/secret.py"))
        assert r.returncode == 2


def test_scope_gate_off_bypasses():
    with tempfile.TemporaryDirectory() as d:
        repo = _new_repo(d)
        r = _hook(SCOPE_HOOK, repo, _edit("other/x.py"), env_extra={"ISSUE_GATE_OFF": "1"})
        assert r.returncode == 0


def test_scope_no_active_issue_allows():
    with tempfile.TemporaryDirectory() as d:
        repo = _new_repo(d, active=False)
        r = _hook(SCOPE_HOOK, repo, _edit("anything.py"))
        assert r.returncode == 0, r.stderr


def test_scope_non_scoped_tool_allows():
    with tempfile.TemporaryDirectory() as d:
        repo = _new_repo(d)
        r = _hook(SCOPE_HOOK, repo, {"tool_name": "Read", "tool_input": {"file_path": "other/x.py"}})
        assert r.returncode == 0


def test_scope_malformed_stdin_allows():
    with tempfile.TemporaryDirectory() as d:
        repo = _new_repo(d)
        r = subprocess.run(
            [sys.executable, str(SCOPE_HOOK)], cwd=str(repo),
            capture_output=True, text=True, env=_env(repo), input="not json{",
        )
        assert r.returncode == 0


def test_scope_missing_file_path_allows():
    with tempfile.TemporaryDirectory() as d:
        repo = _new_repo(d)
        r = _hook(SCOPE_HOOK, repo, {"tool_name": "Edit", "tool_input": {}})
        assert r.returncode == 0


def test_scope_notebook_path_honored():
    with tempfile.TemporaryDirectory() as d:
        repo = _new_repo(d)
        payload = {"tool_name": "NotebookEdit", "tool_input": {"notebook_path": "other/x.ipynb"}}
        r = _hook(SCOPE_HOOK, repo, payload)
        assert r.returncode == 2, f"out-of-scope notebook should block: {r.stdout}"


def test_scope_disallowed_takes_precedence_over_allowed_glob():
    with tempfile.TemporaryDirectory() as d:
        repo = Path(d)
        (repo / ".git").mkdir()
        issues = repo / ".prd-os" / "issues"
        issues.mkdir(parents=True)
        (issues / "issue-a.md").write_text(_SPEC_PRECEDENCE)
        assert _runner(repo, "load", "issue-a").returncode == 0
        assert _runner(repo, "approve").returncode == 0
        # src/secret.py matches allowed glob src/* AND disallowed src/secret.py.
        r = _hook(SCOPE_HOOK, repo, _edit("src/secret.py"))
        assert r.returncode == 2, "disallowed must win over an allowing glob"
        # A sibling under src/* that is NOT disallowed still passes.
        assert _hook(SCOPE_HOOK, repo, _edit("src/ok.py")).returncode == 0


def test_scope_missing_config_does_not_break_session():
    with tempfile.TemporaryDirectory() as d:
        repo = Path(d)
        (repo / ".git").mkdir()  # repo marker, but NO .prd-os/config.json
        r = _hook(SCOPE_HOOK, repo, _edit("anything.py"))
        assert r.returncode == 0, r.stderr


def test_scope_walkup_resolves_when_env_unset():
    with tempfile.TemporaryDirectory() as d:
        repo = _new_repo(d)
        # No CLAUDE_PROJECT_DIR; cwd is the repo (.git present) so walk-up finds it.
        r = _hook_no_project(SCOPE_HOOK, repo, _edit("other/x.py"), cwd=repo)
        assert r.returncode == 2, "walk-up should resolve the repo and enforce scope"


def test_scope_dormant_when_no_repo_marker():
    with tempfile.TemporaryDirectory() as d:
        bare = Path(d)  # no .git, no config, no CLAUDE_PROJECT_DIR
        r = _hook_no_project(SCOPE_HOOK, bare, _edit("anything.py"), cwd=bare)
        assert r.returncode == 0, r.stderr


# --- stop gate ---------------------------------------------------------------


def test_stop_blocks_when_issue_unclosed():
    with tempfile.TemporaryDirectory() as d:
        repo = _new_repo(d)
        r = _hook(STOP_GATE, repo, {})
        assert r.returncode == 2, f"expected block, got {r.returncode}: {r.stdout}"


def test_stop_allows_when_no_active_issue():
    with tempfile.TemporaryDirectory() as d:
        repo = _new_repo(d, active=False)
        r = _hook(STOP_GATE, repo, {})
        assert r.returncode == 0, r.stderr


def test_stop_hook_active_bypasses():
    with tempfile.TemporaryDirectory() as d:
        repo = _new_repo(d)
        r = _hook(STOP_GATE, repo, {"stop_hook_active": True})
        assert r.returncode == 0


def test_stop_gate_off_bypasses():
    with tempfile.TemporaryDirectory() as d:
        repo = _new_repo(d)
        r = _hook(STOP_GATE, repo, {}, env_extra={"ISSUE_GATE_OFF": "1"})
        assert r.returncode == 0


def test_stop_exhaustion_allows_after_max_firings():
    with tempfile.TemporaryDirectory() as d:
        repo = _new_repo(d)
        # Same blocking signature fires; after MAX (3) it exhausts and allows.
        codes = [_hook(STOP_GATE, repo, {}).returncode for _ in range(5)]
        assert codes[0] == 2
        assert codes[-1] == 0, f"expected exhaustion to allow, got {codes}"


def test_stop_allows_when_all_receipts_present():
    with tempfile.TemporaryDirectory() as d:
        repo = _new_repo(d)
        for receipt in ("verified", "reviewed", "findings_triaged"):
            assert _runner(repo, "mark", receipt).returncode == 0, receipt
        r = _hook(STOP_GATE, repo, {})
        assert r.returncode == 0, f"all receipts present should allow stop: {r.stderr}"


def test_stop_allows_when_issue_closed():
    with tempfile.TemporaryDirectory() as d:
        repo = Path(d)
        # Real git repo with a commit: close pins its receipt to HEAD.
        subprocess.run(["git", "init", "-q"], cwd=str(repo), check=True)
        subprocess.run(
            ["git", "-c", "user.email=t@t", "-c", "user.name=t",
             "commit", "--allow-empty", "-q", "-m", "init"],
            cwd=str(repo), check=True,
        )
        issues = repo / ".prd-os" / "issues"
        issues.mkdir(parents=True)
        (issues / "issue-a.md").write_text(_SPEC)
        assert _runner(repo, "load", "issue-a").returncode == 0
        assert _runner(repo, "approve").returncode == 0
        for receipt in ("verified", "reviewed", "findings_triaged"):
            assert _runner(repo, "mark", receipt).returncode == 0
        assert _runner(repo, "close").returncode == 0, "close should succeed"
        r = _hook(STOP_GATE, repo, {})
        assert r.returncode == 0, r.stderr


def test_stop_missing_config_does_not_break_session():
    with tempfile.TemporaryDirectory() as d:
        repo = Path(d)
        (repo / ".git").mkdir()  # repo marker, no config, no active issue
        r = _hook(STOP_GATE, repo, {})
        assert r.returncode == 0, r.stderr


def test_stop_walkup_resolves_when_env_unset():
    with tempfile.TemporaryDirectory() as d:
        repo = _new_repo(d)
        r = _hook_no_project(STOP_GATE, repo, {}, cwd=repo)
        assert r.returncode == 2, "walk-up should resolve the repo and block on unclosed issue"


def test_stop_dormant_when_no_repo_marker():
    with tempfile.TemporaryDirectory() as d:
        bare = Path(d)  # no .git, no config, no active issue
        r = _hook_no_project(STOP_GATE, bare, {}, cwd=bare)
        assert r.returncode == 0, r.stderr


if __name__ == "__main__":
    import pytest as _p
    raise SystemExit(_p.main([str(Path(__file__))]))
