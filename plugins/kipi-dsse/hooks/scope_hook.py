#!/usr/bin/env python3
"""PreToolUse hook: block Edit/Write/NotebookEdit outside the active issue scope.

Reads hook JSON on stdin. Exits 0 (allow) when:
  - ISSUE_GATE_OFF=1, or
  - no active issue, or
  - tool is not Edit/Write/NotebookEdit, or
  - target path matches allowed_files.

Exits 2 (block) with stderr when out of scope. Exits 0 on any unexpected error.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


SCOPED_TOOLS = {"Edit", "Write", "NotebookEdit"}


def _runner_path() -> Path:
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if plugin_root:
        return Path(plugin_root) / "scripts" / "issue_runner.py"
    return Path(__file__).resolve().parents[1] / "scripts" / "issue_runner.py"


def _repo_root(cwd: str | None) -> Path | None:
    """The git top-level for cwd, or None if it cannot be determined."""
    try:
        result = subprocess.run(
            ["git", "-C", cwd or ".", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    top = result.stdout.strip()
    if not top:
        return None
    try:
        return Path(top).resolve()
    except Exception:
        return None


def _resolve_target(file_path: str, cwd: str | None) -> Path:
    """Resolve a possibly-relative target against the SESSION's cwd.

    Never against the hook process's own cwd. A relative path in the payload
    is relative to where the TOOL CALL happens, which is `payload["cwd"]`; the
    hook process may be launched from anywhere.
    """
    p = Path(file_path)
    if p.is_absolute():
        return p.resolve()
    base = Path(cwd) if cwd else Path.cwd()
    return (base / p).resolve()


def _outside_repo(file_path: str, cwd: str | None) -> bool:
    """True only when the target provably sits outside the repo.

    The gate exists to keep the issue's DIFF scoped. A path outside the repo
    cannot appear in any diff, so blocking it protects nothing while blocking
    real work: analysis scaffolding written to the session scratchpad had to
    choose between ISSUE_GATE_OFF=1 and routing around the hook via a bash
    heredoc, and the heredoc route then collided with the destructive-op
    matcher, which scans whole command strings. That carve-out stands.

    What changed 2026-08-05: the root came from `payload["cwd"]` while the
    target was resolved with a bare `Path(file_path).resolve()`, i.e. against
    the HOOK PROCESS's cwd. Two sides deriving one location from different
    sources. When they differed, an in-repo file resolved under the wrong
    parent, `relative_to` raised, the target was judged "outside the repo",
    and the gate returned 0. Measured: the same payload naming the same
    repo-relative disallowed path was BLOCKED from inside the repo and ALLOWED
    from anywhere else. A gate that silently disables itself based on its own
    working directory is gap-class #9 -- a gate must fail CLOSED.

    Fails SAFE: if the repo root cannot be resolved, return False so the
    normal allowed_files check still runs.
    """
    root = _repo_root(cwd)
    if root is None:
        return False
    try:
        _resolve_target(file_path, cwd).relative_to(root)
    except ValueError:
        return True
    except Exception:
        return False
    return False


def main() -> int:
    if os.environ.get("ISSUE_GATE_OFF") == "1":
        return 0
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0

    tool = payload.get("tool_name") or payload.get("tool") or ""
    if tool not in SCOPED_TOOLS:
        return 0

    tool_input = payload.get("tool_input") or {}
    file_path = (
        tool_input.get("file_path")
        or tool_input.get("notebook_path")
        or tool_input.get("path")
    )
    if not file_path:
        return 0

    session_cwd = payload.get("cwd")
    if _outside_repo(str(file_path), session_cwd):
        return 0

    try:
        result = subprocess.run(
            # Absolute, and run from the session's cwd: the runner resolves a
            # relative target against ITS cwd too, so handing it a bare
            # relative path reintroduced the same derivation split one layer
            # down. Both halves now agree on one base.
            ["python3", str(_runner_path()), "scope",
             str(_resolve_target(str(file_path), session_cwd))],
            cwd=session_cwd or None,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return 0

    if result.returncode == 2:
        sys.stderr.write(result.stderr or "DSSE scope block\n")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
