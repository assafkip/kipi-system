"""Hook-layer tests for the prd-os plugin.

These exercise the scope hook (PreToolUse) and stop-gate hook (Stop) as
standalone subprocesses, the same way Claude Code will invoke them. The
contract under test:

  scope_hook.py
    - exit 0 whenever ISSUE_GATE_OFF=1, stdin is malformed, the tool isn't
      one of {Edit, Write, NotebookEdit}, no file_path is present, or the
      runner's `scope` subcommand allows the path
    - exit 2 only when the runner's `scope` subcommand exits 2; stderr from
      the runner is forwarded verbatim

  stop_gate.py
    - exit 0 whenever the runner's `gate` subcommand exits 0 (no active
      issue / status closed / all receipts present / ISSUE_GATE_OFF=1
      honored inside the runner)
    - exit 2 only when the runner's `gate` subcommand exits 2; stderr
      forwarded

Tests use ephemeral repos under tmp_path and set CLAUDE_PLUGIN_ROOT so the
hooks find the plugin runner without any install/wiring. CLAUDE_PROJECT_DIR
points at the ephemeral repo so the runner's config discovery is clean.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Callable

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCOPE_HOOK = PLUGIN_ROOT / "hooks" / "scope_hook.py"
STOP_HOOK = PLUGIN_ROOT / "hooks" / "stop_gate.py"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def primed_repo(fake_repo, write_config, write_issue_spec, run_runner):
    """A fake_repo with config, a single issue in-progress, receipts cleared.

    Returns (repo_path, issue_id). Useful for scope-hook tests that need an
    active issue with known allowed_files.
    """
    write_config(
        fake_repo,
        {"config_schema_version": 1, "issues_dir": ".prd-os/issues"},
    )
    issues_dir = fake_repo / ".prd-os" / "issues"
    write_issue_spec(
        issues_dir,
        "issue-hook-test",
        allowed_files=["src/*"],
        disallowed_files=["src/secret.py"],
    )
    assert run_runner(fake_repo, "load", "issue-hook-test").returncode == 0
    assert run_runner(fake_repo, "approve").returncode == 0
    return fake_repo, "issue-hook-test"


@pytest.fixture
def run_scope_hook() -> Callable[..., subprocess.CompletedProcess]:
    def _run(
        repo: Path,
        payload: dict,
        *,
        env_extra: dict | None = None,
    ) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        env["CLAUDE_PROJECT_DIR"] = str(repo)
        env["CLAUDE_PLUGIN_ROOT"] = str(PLUGIN_ROOT)
        if env_extra:
            env.update(env_extra)
        return subprocess.run(
            [sys.executable, str(SCOPE_HOOK)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            env=env,
            cwd=str(repo),
        )

    return _run


@pytest.fixture
def run_stop_hook() -> Callable[..., subprocess.CompletedProcess]:
    def _run(
        repo: Path,
        *,
        env_extra: dict | None = None,
    ) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        env["CLAUDE_PROJECT_DIR"] = str(repo)
        env["CLAUDE_PLUGIN_ROOT"] = str(PLUGIN_ROOT)
        if env_extra:
            env.update(env_extra)
        return subprocess.run(
            [sys.executable, str(STOP_HOOK)],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(repo),
        )

    return _run


def _edit(path: str) -> dict:
    return {"tool_name": "Edit", "tool_input": {"file_path": path}}


# ---------------------------------------------------------------------------
# Scope hook
# ---------------------------------------------------------------------------


def test_scope_hook_gate_off_bypasses_before_runner(run_scope_hook, primed_repo):
    """ISSUE_GATE_OFF=1 must short-circuit before invoking the runner.

    The disallowed path would otherwise be blocked (see
    test_scope_hook_disallowed_takes_precedence); the override is the only
    way to punch through at the hook layer because the runner's `scope`
    subcommand does NOT itself honor ISSUE_GATE_OFF."""
    repo, _ = primed_repo
    result = run_scope_hook(repo, _edit("src/secret.py"), env_extra={"ISSUE_GATE_OFF": "1"})
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""


def test_scope_hook_malformed_stdin_allows(run_scope_hook, primed_repo):
    """Non-JSON stdin must never break the session."""
    repo, _ = primed_repo
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(repo)
    env["CLAUDE_PLUGIN_ROOT"] = str(PLUGIN_ROOT)
    result = subprocess.run(
        [sys.executable, str(SCOPE_HOOK)],
        input="{not valid json",
        capture_output=True,
        text=True,
        env=env,
        cwd=str(repo),
    )
    assert result.returncode == 0


def test_scope_hook_non_scoped_tool_allows(run_scope_hook, primed_repo):
    """Read, Bash, Grep etc. are not scoped tools; hook must exit 0."""
    repo, _ = primed_repo
    payload = {"tool_name": "Read", "tool_input": {"file_path": "src/secret.py"}}
    result = run_scope_hook(repo, payload)
    assert result.returncode == 0


def test_scope_hook_missing_file_path_allows(run_scope_hook, primed_repo):
    """Scoped tool with no file path (e.g., bad payload) must not block."""
    repo, _ = primed_repo
    result = run_scope_hook(repo, {"tool_name": "Edit", "tool_input": {}})
    assert result.returncode == 0


def test_scope_hook_allowed_path_passes(run_scope_hook, primed_repo):
    repo, _ = primed_repo
    result = run_scope_hook(repo, _edit("src/foo.py"))
    assert result.returncode == 0, result.stderr


def test_scope_hook_denied_path_blocks_and_forwards_stderr(
    run_scope_hook, primed_repo
):
    """A path outside allowed_files must exit 2 and forward runner stderr."""
    repo, issue_id = primed_repo
    result = run_scope_hook(repo, _edit("README.md"))
    assert result.returncode == 2
    assert "DSSE scope block" in result.stderr
    assert issue_id in result.stderr


def test_scope_hook_disallowed_takes_precedence(run_scope_hook, primed_repo):
    """`disallowed_files` beats `allowed_files` — same rule as runner."""
    repo, _ = primed_repo
    result = run_scope_hook(repo, _edit("src/secret.py"))
    assert result.returncode == 2
    assert "disallowed" in result.stderr


def test_scope_hook_notebook_path_honored(run_scope_hook, primed_repo):
    """NotebookEdit uses `notebook_path` instead of `file_path`."""
    repo, _ = primed_repo
    payload = {
        "tool_name": "NotebookEdit",
        "tool_input": {"notebook_path": "src/ok.ipynb"},
    }
    result = run_scope_hook(repo, payload)
    assert result.returncode == 0, result.stderr


def test_scope_hook_no_active_issue_allows(run_scope_hook, fake_repo, write_config):
    """With no active issue loaded, runner `scope` returns 0; hook passes."""
    write_config(fake_repo, {"config_schema_version": 1})
    result = run_scope_hook(fake_repo, _edit("any/path.py"))
    assert result.returncode == 0


def test_scope_hook_missing_config_does_not_break_session(
    run_scope_hook, tmp_path, monkeypatch
):
    """No .prd-os/config.json means the runner errors out. The hook must
    still exit 0 — we never break the session for missing plugin config."""
    repo = tmp_path / "bare"
    repo.mkdir()
    (repo / ".git").mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    result = run_scope_hook(repo, _edit("src/foo.py"))
    assert result.returncode == 0


def test_scope_hook_enforces_when_env_unset_but_walkup_finds_config(
    primed_repo,
):
    """Fail-open safeguard: CLAUDE_PROJECT_DIR missing must NOT silently
    disable the hook. Walk-up from CWD still finds `.prd-os/config.json`,
    and enforcement must hold. Codex stop-review flagged this as the
    silent-fail-open vector.
    """
    repo, _ = primed_repo
    env = os.environ.copy()
    env.pop("CLAUDE_PROJECT_DIR", None)
    env["CLAUDE_PLUGIN_ROOT"] = str(PLUGIN_ROOT)
    result = subprocess.run(
        [sys.executable, str(SCOPE_HOOK)],
        input=json.dumps(_edit("README.md")),
        capture_output=True,
        text=True,
        env=env,
        cwd=str(repo),
    )
    assert result.returncode == 2, (
        "walk-up discovery must still block when env is unset; "
        f"got stderr={result.stderr!r}"
    )
    assert "DSSE scope block" in result.stderr


def test_scope_hook_enforces_when_env_points_at_subdir_of_configured_repo(
    primed_repo,
):
    """Fail-open vector: CLAUDE_PROJECT_DIR points into a subdirectory of
    the configured repo. Walk-up from the env-specified dir must still find
    `.prd-os/config.json` and enforcement must hold.
    """
    repo, _ = primed_repo
    subdir = repo / "deep" / "nested" / "sub"
    subdir.mkdir(parents=True)
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(subdir)
    env["CLAUDE_PLUGIN_ROOT"] = str(PLUGIN_ROOT)
    result = subprocess.run(
        [sys.executable, str(SCOPE_HOOK)],
        input=json.dumps(_edit("README.md")),
        capture_output=True,
        text=True,
        env=env,
        cwd=str(subdir),
    )
    assert result.returncode == 2, (
        "walk-up from env subdir must still block; "
        f"got stderr={result.stderr!r}"
    )
    assert "DSSE scope block" in result.stderr


def test_scope_hook_falls_back_to_cwd_when_env_points_at_bogus_path(
    primed_repo, tmp_path
):
    """Fail-open vector: CLAUDE_PROJECT_DIR set to a non-existent directory.
    Must fall back to CWD walk-up rather than silently disable.
    """
    repo, _ = primed_repo
    bogus = tmp_path / "does" / "not" / "exist"
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(bogus)
    env["CLAUDE_PLUGIN_ROOT"] = str(PLUGIN_ROOT)
    result = subprocess.run(
        [sys.executable, str(SCOPE_HOOK)],
        input=json.dumps(_edit("README.md")),
        capture_output=True,
        text=True,
        env=env,
        cwd=str(repo),
    )
    assert result.returncode == 2, (
        "bogus env must fall back to CWD walk-up; "
        f"got stderr={result.stderr!r}"
    )


def test_scope_hook_exits_zero_when_env_unset_and_no_repo_marker(
    tmp_path, monkeypatch
):
    """Fully dormant: no CLAUDE_PROJECT_DIR, no `.prd-os/config.json` and
    no `.git` reachable by walk-up → exit 0. Nothing to enforce on."""
    isolated = tmp_path / "island"
    isolated.mkdir()
    env = os.environ.copy()
    env.pop("CLAUDE_PROJECT_DIR", None)
    env["CLAUDE_PLUGIN_ROOT"] = str(PLUGIN_ROOT)
    # Force CWD into a directory that has no .git anywhere up to /tmp/.
    # pytest's tmp_path is under /private/var/folders/... which won't have
    # `.prd-os/config.json`; walk-up may or may not hit a `.git` before /.
    # The hook's contract still says "plugin not configured => exit 0."
    result = subprocess.run(
        [sys.executable, str(SCOPE_HOOK)],
        input=json.dumps(_edit("src/foo.py")),
        capture_output=True,
        text=True,
        env=env,
        cwd=str(isolated),
    )
    assert result.returncode == 0


# ---------------------------------------------------------------------------
# Stop gate hook
# ---------------------------------------------------------------------------


def test_stop_hook_no_active_issue_passes(run_stop_hook, fake_repo, write_config):
    write_config(fake_repo, {"config_schema_version": 1})
    result = run_stop_hook(fake_repo)
    assert result.returncode == 0


def test_stop_hook_in_progress_without_receipts_blocks(
    run_stop_hook, primed_repo
):
    """Issue in-progress with zero receipts must block session end."""
    repo, issue_id = primed_repo
    result = run_stop_hook(repo)
    assert result.returncode == 2
    assert "DSSE stop gate" in result.stderr
    assert issue_id in result.stderr


def test_stop_hook_all_receipts_passes(run_stop_hook, primed_repo, run_runner):
    repo, _ = primed_repo
    for receipt in ("verified", "reviewed", "findings_triaged"):
        assert run_runner(repo, "mark", receipt).returncode == 0
    result = run_stop_hook(repo)
    assert result.returncode == 0, result.stderr


def test_stop_hook_gate_off_env_lets_runner_pass(run_stop_hook, primed_repo):
    """ISSUE_GATE_OFF=1 is honored inside the runner's `gate` command, so the
    hook sees a 0 exit and returns 0. This pins the runner-layer bypass.
    """
    repo, _ = primed_repo
    result = run_stop_hook(repo, env_extra={"ISSUE_GATE_OFF": "1"})
    assert result.returncode == 0, result.stderr


def test_stop_hook_closed_issue_passes(run_stop_hook, primed_repo, run_runner):
    repo, _ = primed_repo
    for receipt in ("verified", "reviewed", "findings_triaged"):
        run_runner(repo, "mark", receipt)
    assert run_runner(repo, "close").returncode == 0
    result = run_stop_hook(repo)
    assert result.returncode == 0


def test_stop_hook_missing_config_does_not_break_session(
    run_stop_hook, tmp_path, monkeypatch
):
    repo = tmp_path / "bare"
    repo.mkdir()
    (repo / ".git").mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    result = run_stop_hook(repo)
    assert result.returncode == 0


def test_stop_hook_enforces_when_env_unset_but_walkup_finds_config(
    primed_repo,
):
    """Same fail-open guard as the scope hook: no CLAUDE_PROJECT_DIR must
    not silently disable the stop gate. Walk-up still finds the config
    and receipts-less in-progress issue is still blocked."""
    repo, issue_id = primed_repo
    env = os.environ.copy()
    env.pop("CLAUDE_PROJECT_DIR", None)
    env["CLAUDE_PLUGIN_ROOT"] = str(PLUGIN_ROOT)
    result = subprocess.run(
        [sys.executable, str(STOP_HOOK)],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(repo),
    )
    assert result.returncode == 2, (
        "walk-up discovery must still block when env is unset; "
        f"got stderr={result.stderr!r}"
    )
    assert issue_id in result.stderr


def test_stop_hook_enforces_when_env_points_at_subdir_of_configured_repo(
    primed_repo,
):
    repo, issue_id = primed_repo
    subdir = repo / "a" / "b" / "c"
    subdir.mkdir(parents=True)
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(subdir)
    env["CLAUDE_PLUGIN_ROOT"] = str(PLUGIN_ROOT)
    result = subprocess.run(
        [sys.executable, str(STOP_HOOK)],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(subdir),
    )
    assert result.returncode == 2, (
        "walk-up from env subdir must still block; "
        f"got stderr={result.stderr!r}"
    )
    assert issue_id in result.stderr


def test_stop_hook_falls_back_to_cwd_when_env_points_at_bogus_path(
    primed_repo, tmp_path
):
    repo, issue_id = primed_repo
    bogus = tmp_path / "no" / "such" / "dir"
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(bogus)
    env["CLAUDE_PLUGIN_ROOT"] = str(PLUGIN_ROOT)
    result = subprocess.run(
        [sys.executable, str(STOP_HOOK)],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(repo),
    )
    assert result.returncode == 2
    assert issue_id in result.stderr


def test_stop_hook_exits_zero_when_env_unset_and_no_repo_marker(tmp_path):
    isolated = tmp_path / "island"
    isolated.mkdir()
    env = os.environ.copy()
    env.pop("CLAUDE_PROJECT_DIR", None)
    env["CLAUDE_PLUGIN_ROOT"] = str(PLUGIN_ROOT)
    result = subprocess.run(
        [sys.executable, str(STOP_HOOK)],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(isolated),
    )
    assert result.returncode == 0
