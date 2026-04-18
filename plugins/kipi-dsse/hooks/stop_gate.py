#!/usr/bin/env python3
"""Stop hook: refuse clean session end if an active issue is not closed.

Exits 0 when:
  - ISSUE_GATE_OFF=1, or
  - no active issue, or
  - spec is closed, or
  - all receipts exist (verified, reviewed, findings_triaged).

Exits 2 with stderr otherwise. Exits 0 on unexpected errors.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _runner_path() -> Path:
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if plugin_root:
        return Path(plugin_root) / "scripts" / "issue_runner.py"
    return Path(__file__).resolve().parents[1] / "scripts" / "issue_runner.py"


def main() -> int:
    if os.environ.get("ISSUE_GATE_OFF") == "1":
        return 0
    try:
        result = subprocess.run(
            ["python3", str(_runner_path()), "gate"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return 0
    if result.returncode == 2:
        sys.stderr.write(result.stderr or "DSSE stop gate: issue not closed\n")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
