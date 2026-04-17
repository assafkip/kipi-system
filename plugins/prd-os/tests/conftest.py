"""Shared fixtures for prd-os plugin tests.

Each test gets an ephemeral repo under pytest's tmp_path so nothing touches
the host repo's live `.claude/state/` or live issue specs. CLAUDE_PROJECT_DIR
is set per-test to point at the ephemeral repo so `config.discover_repo_root`
resolves cleanly without walking the host filesystem.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Callable

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PLUGIN_ROOT / "scripts"
ISSUE_RUNNER = SCRIPTS_DIR / "issue_runner.py"
PRD_RUNNER = SCRIPTS_DIR / "prd_runner.py"
PRD_SPLIT = SCRIPTS_DIR / "prd_split.py"
FINDINGS_WRITER = SCRIPTS_DIR / "findings_writer.py"


@pytest.fixture
def import_config():
    """Import config.py as a standalone module (no package install)."""
    spec = importlib.util.spec_from_file_location(
        "prd_os_config", SCRIPTS_DIR / "config.py"
    )
    module = importlib.util.module_from_spec(spec)
    # Register before exec so dataclass() can resolve string annotations on
    # Python 3.9 (it looks up cls.__module__ in sys.modules).
    sys.modules["prd_os_config"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def fake_repo(tmp_path: Path, monkeypatch) -> Path:
    """Create an empty ephemeral repo root and bind CLAUDE_PROJECT_DIR to it."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()  # walk-up discovery marker (not used when env set)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    return repo


@pytest.fixture
def write_config() -> Callable[[Path, dict], Path]:
    """Factory that writes `.prd-os/config.json` into a fake repo."""

    def _write(repo: Path, payload: dict) -> Path:
        target = repo / ".prd-os" / "config.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, indent=2))
        return target

    return _write


@pytest.fixture
def write_issue_spec() -> Callable[..., Path]:
    """Factory that writes a minimal issue spec into an issues_dir."""

    def _write(
        issues_dir: Path,
        issue_id: str,
        *,
        status: str = "open",
        allowed_files: list[str] | None = None,
        disallowed_files: list[str] | None = None,
    ) -> Path:
        issues_dir.mkdir(parents=True, exist_ok=True)
        allowed_files = allowed_files or []
        disallowed_files = disallowed_files or []

        def _yaml_list(items):
            if not items:
                return "[]"
            return "\n" + "\n".join(f"  - {p}" for p in items)

        body = (
            "---\n"
            f"id: {issue_id}\n"
            f"title: {issue_id} fixture\n"
            f"status: {status}\n"
            "priority: p0\n"
            f"allowed_files: {_yaml_list(allowed_files)}\n"
            f"disallowed_files: {_yaml_list(disallowed_files)}\n"
            "required_checks: []\n"
            "required_reviews: []\n"
            "---\n\n"
            f"Fixture spec for {issue_id}.\n"
        )
        path = issues_dir / f"{issue_id}.md"
        path.write_text(body)
        return path

    return _write


@pytest.fixture
def run_runner() -> Callable[..., subprocess.CompletedProcess]:
    """Invoke issue_runner.py in a subprocess with a given repo root."""

    def _run(repo: Path, *args: str, env_extra: dict | None = None) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        env["CLAUDE_PROJECT_DIR"] = str(repo)
        if env_extra:
            env.update(env_extra)
        return subprocess.run(
            [sys.executable, str(ISSUE_RUNNER), *args],
            cwd=str(repo),
            capture_output=True,
            text=True,
            env=env,
        )

    return _run


@pytest.fixture
def run_prd_runner() -> Callable[..., subprocess.CompletedProcess]:
    """Invoke prd_runner.py in a subprocess with a given repo root."""

    def _run(repo: Path, *args: str, env_extra: dict | None = None) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        env["CLAUDE_PROJECT_DIR"] = str(repo)
        if env_extra:
            env.update(env_extra)
        return subprocess.run(
            [sys.executable, str(PRD_RUNNER), *args],
            cwd=str(repo),
            capture_output=True,
            text=True,
            env=env,
        )

    return _run


@pytest.fixture
def run_prd_split() -> Callable[..., subprocess.CompletedProcess]:
    """Invoke prd_split.py in a subprocess with a given repo root."""

    def _run(repo: Path, *args: str, env_extra: dict | None = None) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        env["CLAUDE_PROJECT_DIR"] = str(repo)
        if env_extra:
            env.update(env_extra)
        return subprocess.run(
            [sys.executable, str(PRD_SPLIT), *args],
            cwd=str(repo),
            capture_output=True,
            text=True,
            env=env,
        )

    return _run


@pytest.fixture
def run_findings_writer() -> Callable[..., subprocess.CompletedProcess]:
    """Invoke findings_writer.py. Pass stdin as bytes via `stdin_text` kwarg."""

    def _run(
        repo: Path,
        *args: str,
        stdin_text: str | None = None,
        env_extra: dict | None = None,
    ) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        env["CLAUDE_PROJECT_DIR"] = str(repo)
        if env_extra:
            env.update(env_extra)
        return subprocess.run(
            [sys.executable, str(FINDINGS_WRITER), *args],
            cwd=str(repo),
            capture_output=True,
            text=True,
            env=env,
            input=stdin_text,
        )

    return _run
