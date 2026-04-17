#!/usr/bin/env python3
"""PreToolUse hook: block Edit/Write/NotebookEdit outside the active issue's scope.

Reads Claude Code hook JSON on stdin. Exits 0 (allow) when:
  - ISSUE_GATE_OFF=1 is set in the environment, or
  - stdin cannot be parsed as JSON, or
  - tool is not Edit/Write/NotebookEdit, or
  - no file path is present in tool_input, or
  - the plugin runner's `scope` subcommand allows the path.

Exits 2 (block) with a stderr message only when the runner reports a scope
violation. Any unexpected error (subprocess failure, missing runner, timeout)
returns 0 — this hook must never be the reason a normal session breaks.
Scope violations are the single code path that exits 2.

The runner is resolved via CLAUDE_PLUGIN_ROOT (set by Claude Code when a
plugin hook is invoked) with a walk-up fallback for direct invocation and
tests. Repo root is discovered by the runner itself via the CLAUDE_PROJECT_DIR
env and the standard walk-up rules defined in config.py.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

SCOPED_TOOLS = {"Edit", "Write", "NotebookEdit"}
RUNNER_TIMEOUT_SECONDS = 5
CONFIG_RELPATH = ".prd-os/config.json"


def _runner_path() -> Path:
    root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if root:
        return Path(root) / "scripts" / "issue_runner.py"
    return Path(__file__).resolve().parent.parent / "scripts" / "issue_runner.py"


def _discover_repo_with_config() -> Path | None:
    """Locate the host repo and return it iff `.prd-os/config.json` exists.

    Always walks up from a starting directory looking for
    `.prd-os/config.json`. Stops (dormant) at the first enclosing `.git`
    with no config above. The starting directory is:
      1. CLAUDE_PROJECT_DIR env var when it resolves to an existing directory
      2. otherwise CWD

    Invariants this closes:
      - env set but pointing at a subdirectory of the configured repo must
        still resolve to the repo (walk up from env, not direct check only)
      - env set but pointing at a non-existent / non-directory path must
        fall back to CWD walk-up, not silently disable the hook
      - Path.cwd() failures (disconnected fs, race conditions) keep the
        hook dormant rather than crashing
    """
    start: Path | None = None
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        try:
            candidate = Path(env).resolve()
        except (OSError, ValueError):
            candidate = None
        if candidate is not None and candidate.is_dir():
            start = candidate
    if start is None:
        try:
            start = Path.cwd().resolve()
        except (OSError, ValueError):
            return None
    for candidate in (start, *start.parents):
        if (candidate / CONFIG_RELPATH).is_file():
            return candidate
        if (candidate / ".git").exists():
            return None
    return None


def _extract_file_path(tool_input: dict) -> str | None:
    for key in ("file_path", "notebook_path", "path"):
        value = tool_input.get(key)
        if value:
            return str(value)
    return None


def main() -> int:
    if os.environ.get("ISSUE_GATE_OFF") == "1":
        return 0
    repo = _discover_repo_with_config()
    if repo is None:
        return 0

    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0

    tool = payload.get("tool_name") or payload.get("tool") or ""
    if tool not in SCOPED_TOOLS:
        return 0

    tool_input = payload.get("tool_input") or {}
    file_path = _extract_file_path(tool_input)
    if not file_path:
        return 0

    runner = _runner_path()
    try:
        result = subprocess.run(
            [
                sys.executable,
                str(runner),
                "--repo-root",
                str(repo),
                "scope",
                file_path,
            ],
            capture_output=True,
            text=True,
            timeout=RUNNER_TIMEOUT_SECONDS,
        )
    except Exception:
        return 0

    if result.returncode == 2:
        sys.stderr.write(result.stderr or "DSSE scope block\n")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
