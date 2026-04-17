#!/usr/bin/env python3
"""Stop hook: refuse clean session end while an active issue is not closed.

Invokes the plugin runner's `gate` subcommand. Exits 0 when:
  - runner reports the gate is clear (no active issue / status closed / all
    three receipts present / ISSUE_GATE_OFF=1 honored inside the runner), or
  - any unexpected error occurs (never break session end for innocuous
    reasons).

Exits 2 only when the runner returns 2. The stderr message from the runner is
forwarded verbatim so the founder sees the concrete missing-receipt list.

The runner is resolved via CLAUDE_PLUGIN_ROOT with a walk-up fallback for
direct invocation and tests. Repo root is discovered by the runner itself.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

RUNNER_TIMEOUT_SECONDS = 5
CONFIG_RELPATH = ".prd-os/config.json"


def _runner_path() -> Path:
    root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if root:
        return Path(root) / "scripts" / "issue_runner.py"
    return Path(__file__).resolve().parent.parent / "scripts" / "issue_runner.py"


def _discover_repo_with_config() -> Path | None:
    """Locate the host repo iff `.prd-os/config.json` exists.

    Walks up from a starting directory (CLAUDE_PROJECT_DIR when valid, else
    CWD) looking for `.prd-os/config.json`. Stops dormant at the first
    enclosing `.git` with no config above.

    Closes the same fail-open vectors as the scope hook: env set to a
    subdirectory of the configured repo, env set to a non-existent path,
    and Path.cwd() failures.
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


def main() -> int:
    repo = _discover_repo_with_config()
    if repo is None:
        return 0
    runner = _runner_path()
    try:
        result = subprocess.run(
            [
                sys.executable,
                str(runner),
                "--repo-root",
                str(repo),
                "gate",
            ],
            capture_output=True,
            text=True,
            timeout=RUNNER_TIMEOUT_SECONDS,
        )
    except Exception:
        return 0

    if result.returncode == 2:
        sys.stderr.write(result.stderr or "DSSE stop gate: issue not closed\n")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
