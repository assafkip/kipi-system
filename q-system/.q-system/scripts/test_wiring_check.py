#!/usr/bin/env python3
"""Pins what `wiring-check.py` actually detects (ASK-132).

`.claude/rules/coding-audhd.md` claimed ENFORCED while naming no executable.
The executable existed (`wiring-check.py`, wired PostToolUse in
`.claude/settings.json:186`) but nothing proved its checks fire, so the rule's
three file-inspectable limits were enforced only by belief.

Three contracts:

1. A dirty fixture -- 3 nested control blocks, a 40-line function, a `print(` --
   is reported on all three counts. This caught the real defect: `_nesting_depth`
   counted levels BELOW a node, so `for > if > while` scored 2 and slipped past
   `MAX_NESTING = 2` while violating "max nesting: 2 levels".
2. A clean fixture produces no output at all. Without this half, a checker that
   warned on everything would pass contract 1.
3. The nesting assertion is bound to the detector, not to unrelated noise: the
   same fixture run against a copy with `MAX_NESTING = 99` must go quiet. A
   substring assertion that passes no matter what the script does is not a test.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "wiring-check.py"

# 3 nested control blocks + a 40-line function + a leftover print().
DIRTY = (
    "def deep(items):\n"
    "    for item in items:\n"
    "        if item:\n"
    "            while item:\n"
    "                item = None\n"
    "\n"
    "\n"
    "def long_one():\n"
    + "".join(f"    value_{n} = {n}\n" for n in range(1, 40))
    + "\n"
    "\n"
    "def show(value):\n"
    "    print(value)\n"
)

# No debug statement, no nesting, short function, and the function IS called --
# so the orphan-function check stays quiet too.
CLEAN = (
    "def add_one(value):\n"
    "    return value + 1\n"
    "\n"
    "\n"
    "RESULT = add_one(1)\n"
)

FAILURES: list[str] = []


def expect(label: str, condition: bool) -> None:
    if condition:
        print(f"  PASS {label}")
    else:
        print(f"  FAIL {label}")
        FAILURES.append(label)


def write_fixture(tmp: Path, name: str, content: str) -> Path:
    path = tmp / name
    path.write_text(content, encoding="utf-8")
    return path


def run_check(script: Path, target: Path) -> str:
    """Feed the hook one file path the way PostToolUse does; return its message."""
    payload = json.dumps({"tool_input": {"file_path": str(target)}})
    proc = subprocess.run(
        [sys.executable, str(script)],
        input=payload,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise SystemExit(
            f"{script.name} exited {proc.returncode} (expected 0): {proc.stderr}"
        )
    if not proc.stdout.strip():
        return ""
    return json.loads(proc.stdout)["message"]


def mutated_script(tmp: Path) -> Path:
    """A copy with the nesting ceiling raised, for the negative self-test."""
    source = SCRIPT.read_text(encoding="utf-8")
    if "MAX_NESTING = 2" not in source:
        raise SystemExit("MAX_NESTING = 2 not found; the mutation no longer applies")
    path = tmp / "wiring-check-mutated.py"
    path.write_text(source.replace("MAX_NESTING = 2", "MAX_NESTING = 99"), encoding="utf-8")
    return path


def test_dirty_reports_all_three(tmp: Path) -> None:
    message = run_check(SCRIPT, write_fixture(tmp, "dirty_fixture.py", DIRTY))
    expect("dirty: reports nesting depth 3", "nesting depth 3" in message)
    expect("dirty: reports the 40-line function", "`long_one()` is 40 lines" in message)
    expect("dirty: reports the leftover print()", "print() statement" in message)


def test_clean_is_silent(tmp: Path) -> None:
    message = run_check(SCRIPT, write_fixture(tmp, "clean_fixture.py", CLEAN))
    expect("clean: no warnings at all", message == "")


def test_nesting_assertion_is_bound_to_the_detector(tmp: Path) -> None:
    message = run_check(mutated_script(tmp), write_fixture(tmp, "dirty_fixture.py", DIRTY))
    expect("mutation: MAX_NESTING = 99 silences the nesting report",
           "nesting depth" not in message)


def main() -> int:
    print(f"test_wiring_check.py -- pinning {SCRIPT.name}")
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        test_dirty_reports_all_three(tmp)
        test_clean_is_silent(tmp)
        test_nesting_assertion_is_bound_to_the_detector(tmp)
    if FAILURES:
        print(f"\nFAIL: {len(FAILURES)} contract(s) broken")
        return 1
    print("\nPASS: wiring-check.py enforces the file-inspectable coding-audhd limits")
    return 0


if __name__ == "__main__":
    sys.exit(main())
