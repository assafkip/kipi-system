#!/usr/bin/env python3
"""Self-test for prompt-only-enforcement-guard.py."""

# prompt-only-enforcement-skip

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path


GUARD = Path(__file__).resolve().parent / "prompt-only-enforcement-guard.py"

CASES = [
    (
        "bad.md",
        "The prompt enforces that report cards never invent numbers.\n",
        2,
    ),
    (
        "bad-skill.md",
        "The fable skill blocks untested fixes before they land.\n",
        2,
    ),
    (
        "good-hook.md",
        "The hook enforces the blocker. The prompt only explains the rule.\n",
        0,
    ),
    (
        "good-test.md",
        "The test validates the behavior. The skill describes when to run it.\n",
        0,
    ),
    (
        "good-negative.md",
        "Prompt-only enforcement is invalid; use a hook or test.\n",
        0,
    ),
    (
        "good-skip.md",
        "<!-- prompt-only-enforcement-skip -->\nThe prompt enforces a fixture here.\n",
        0,
    ),
]


def run(path: Path) -> int:
    return subprocess.run(
        [sys.executable, str(GUARD), str(path)],
        capture_output=True,
        text=True,
        check=False,
    ).returncode


def main() -> int:
    failures = 0
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        for name, content, want in CASES:
            path = base / name
            path.write_text(content, encoding="utf-8")
            got = run(path)
            ok = got == want
            print(f"  [{'PASS' if ok else 'FAIL'}] {name}: exit {got} (want {want})")
            if not ok:
                failures += 1

    if failures:
        print(f"prompt-only-enforcement-guard self-test: {failures} FAILED")
        return 1

    print(f"prompt-only-enforcement-guard self-test: all {len(CASES)} cases passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
