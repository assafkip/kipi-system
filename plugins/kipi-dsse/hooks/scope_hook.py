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

    try:
        result = subprocess.run(
            ["python3", str(_runner_path()), "scope", str(file_path)],
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
