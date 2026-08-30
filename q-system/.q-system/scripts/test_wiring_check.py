#!/usr/bin/env python3
"""Pins what `wiring-check.py` detects, and pins that detecting is ALL it does (ASK-132).

ADVISORY DETECTION, not enforcement. `wiring-check.py` exits 0 on every path,
a file made entirely of violations included: findings are surfaced as PostToolUse
feedback and the write lands regardless.

This suite used to end by printing that the script "enforces the file-inspectable
coding-audhd limits". It does not. A green line claiming enforcement is exactly
how a violation lands unattended -- someone reads "enforced", trusts it, and
stops looking. The claim was stronger than the code behind it, which is worse
than no claim at all. So the contract is named for what the code does.

Contract 6 holds that line mechanically: it asserts exit 0 directly. If anyone
flips this hook to a hard block, contract 6 goes red, and the fleet-wide decision
(24 instances, wired via settings-template.json) has to be taken deliberately
instead of arriving as a side effect of an unrelated edit.

Contracts:

1-3. A dirty fixture -- 3 nested control blocks, a 40-line function, a `print(`
   -- is reported on all three counts. This caught the original defect:
   `_nesting_depth` counted levels BELOW a node, so `for > if > while` scored 2
   and slipped past `MAX_NESTING = 2` while violating "max nesting: 2 levels".
4. A clean fixture produces no output at all. Without this half, a checker that
   warned on everything would pass contracts 1-3.
5. The nesting assertion is bound to the detector, not to unrelated noise: the
   same fixture against a copy with `MAX_NESTING = 99` must go quiet. A
   substring assertion that passes no matter what the script does is not a test.
6. Violations are ADVISORY: the dirty fixture exits 0 AND still reports. Both
   halves, because exit 0 alone is also what a silently broken detector returns.
7. A FLAT `if/elif/elif` chain -- zero real nesting -- reports no nesting at all.
   Python parses elif as an If inside the parent's `orelse`, and counting that
   as a level made a flat chain report "nesting depth 3".
8. `else:` followed by an indented `if` IS a real extra level and still reports.
   The over-correction guard for contract 7: the two shapes have near-identical
   ASTs and only column offset separates them.
9-10. An all-async stack (`async for > if > async with`) reports depth 3, and its
   sync twin reports the same. Both control-node tuples omitted ast.AsyncFor and
   ast.AsyncWith, so async nesting was invisible while sync nesting was caught.
   The sync twin is the control: without it, contract 9 could pass on a detector
   that reported everything.
11. A 4-deep stack emits exactly TWO nesting findings, not one. ast.walk() visits
   every node, so each over-deep node reports. A code comment used to claim only
   the outermost block warns; it was written from reading the loop rather than
   running it. This contract pins the observed number so the comment cannot drift
   back into fiction.

REF HATCH: WIRING_CHECK_REF=<git-ref> runs every contract against the copy of
wiring-check.py at that ref instead of the working tree, so the pre-fix failures
can be re-observed on demand and no contract here is one that has only ever been
watched pass. Against the pre-fix ref, contracts 7 and 9 FAIL. Measured, not
predicted -- an earlier draft of this line also claimed 11 would fail there.

Contract 11 PASSES at the pre-fix ref, and that is the point of it: the 4-deep
behaviour was always correct, it was the CODE COMMENT that described it wrongly.
So 11 is not a regression pin, it is a pin on a comment that had no test under
it. Its failability was shown by mutation instead: a copy that emits only the
first nesting finding (the behaviour the old comment described) reports 1 where
the real script reports 2, and 11 goes red.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKTREE_SCRIPT = Path(__file__).resolve().parent / "wiring-check.py"
REL_SCRIPT = "q-system/.q-system/scripts/wiring-check.py"

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

# Zero real nesting: three sibling branches of one conditional.
FLAT_ELIF = (
    "def branch(x):\n"
    "    if x == 1:\n"
    "        y = 1\n"
    "    elif x == 2:\n"
    "        y = 2\n"
    "    elif x == 3:\n"
    "        y = 3\n"
    "    return y\n"
)

# `else:` then an indented `if` then a `for`: a genuine 3-level stack whose AST
# is nearly the same shape as FLAT_ELIF.
ELSE_THEN_IF = (
    "def branch(x):\n"
    "    if x == 1:\n"
    "        y = 1\n"
    "    else:\n"
    "        if x == 2:\n"
    "            for i in x:\n"
    "                y = i\n"
    "    return y\n"
)

# 3 control levels, all async.
ASYNC_THREE_DEEP = (
    "async def scan(items):\n"
    "    async for a in items:\n"
    "        if a:\n"
    "            async with a as b:\n"
    "                a = b\n"
)

# The sync twin of ASYNC_THREE_DEEP, node for node.
SYNC_THREE_DEEP = (
    "def scan(items):\n"
    "    for a in items:\n"
    "        if a:\n"
    "            with a as b:\n"
    "                a = b\n"
)

# 4 control levels: for > if > while > with.
FOUR_DEEP = (
    "def deep(items):\n"
    "    for a in items:\n"
    "        if a:\n"
    "            while a:\n"
    "                with a as b:\n"
    "                    a = b\n"
)

FAILURES: list[str] = []
SANDBOX = Path(tempfile.mkdtemp(prefix="wiring-check-test-"))


def script_path() -> Path:
    """The wiring-check.py under test: the working tree, or a ref-extracted copy
    when WIRING_CHECK_REF is set (the pre-fix hatch)."""
    ref = os.environ.get("WIRING_CHECK_REF")
    if not ref:
        return WORKTREE_SCRIPT
    out = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "show", f"{ref}:{REL_SCRIPT}"],
        capture_output=True,
        text=True,
    )
    if out.returncode != 0:
        raise SystemExit(f"WIRING_CHECK_REF={ref} could not be read: {out.stderr.strip()}")
    dest = SANDBOX / f"wiring-check-{ref.replace('/', '_')}.py"
    dest.write_text(out.stdout, encoding="utf-8")
    return dest


SCRIPT = script_path()


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


def run_check(script: Path, target: Path) -> tuple[int, str]:
    """Feed the hook one file path the way PostToolUse does.

    Returns (exit code, message). The exit code is returned rather than asserted
    here because contract 6 is ABOUT the exit code -- swallowing it inside this
    helper is what let "enforces" go unchallenged in the first place.
    """
    payload = json.dumps({"tool_input": {"file_path": str(target)}})
    proc = subprocess.run(
        [sys.executable, str(script)],
        input=payload,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return proc.returncode, proc.stderr
    if not proc.stdout.strip():
        return proc.returncode, ""
    return proc.returncode, json.loads(proc.stdout)["message"]


def nesting_findings(message: str) -> list[str]:
    return [line.strip() for line in message.split("\n") if "nesting depth" in line]


def mutated_script(tmp: Path) -> Path:
    """A copy with the nesting ceiling raised, for the negative self-test."""
    source = SCRIPT.read_text(encoding="utf-8")
    if "MAX_NESTING = 2" not in source:
        raise SystemExit("MAX_NESTING = 2 not found; the mutation no longer applies")
    path = tmp / "wiring-check-mutated.py"
    path.write_text(source.replace("MAX_NESTING = 2", "MAX_NESTING = 99"), encoding="utf-8")
    return path


def test_dirty_reports_all_three(tmp: Path) -> None:
    _, message = run_check(SCRIPT, write_fixture(tmp, "dirty_fixture.py", DIRTY))
    expect("dirty: reports nesting depth 3", "nesting depth 3" in message)
    expect("dirty: reports the 40-line function", "`long_one()` is 40 lines" in message)
    expect("dirty: reports the leftover print()", "print() statement" in message)


def test_clean_is_silent(tmp: Path) -> None:
    _, message = run_check(SCRIPT, write_fixture(tmp, "clean_fixture.py", CLEAN))
    expect("clean: no warnings at all", message == "")


def test_nesting_assertion_is_bound_to_the_detector(tmp: Path) -> None:
    _, message = run_check(mutated_script(tmp), write_fixture(tmp, "dirty_fixture.py", DIRTY))
    expect("mutation: MAX_NESTING = 99 silences the nesting report",
           "nesting depth" not in message)


def test_violations_are_advisory_never_a_block(tmp: Path) -> None:
    """The rename, made assertable. Both halves: exit 0 is also what a silently
    broken detector returns, so 'it exited 0' only means advisory if it also
    reported something."""
    code, message = run_check(SCRIPT, write_fixture(tmp, "dirty_fixture.py", DIRTY))
    expect("advisory: a file full of violations still exits 0", code == 0)
    expect("advisory: and the violations were still reported", message != "")


def test_flat_elif_chain_is_not_nesting(tmp: Path) -> None:
    _, message = run_check(SCRIPT, write_fixture(tmp, "flat_elif.py", FLAT_ELIF))
    expect("elif: a flat if/elif/elif chain reports no nesting",
           not nesting_findings(message))


def test_else_then_if_is_still_nesting(tmp: Path) -> None:
    _, message = run_check(SCRIPT, write_fixture(tmp, "else_then_if.py", ELSE_THEN_IF))
    expect("elif: `else:` + indented `if` still reports depth 3",
           "nesting depth 3" in message)


def test_async_nesting_is_seen(tmp: Path) -> None:
    _, async_msg = run_check(SCRIPT, write_fixture(tmp, "async_deep.py", ASYNC_THREE_DEEP))
    _, sync_msg = run_check(SCRIPT, write_fixture(tmp, "sync_deep.py", SYNC_THREE_DEEP))
    expect("async: `async for > if > async with` reports depth 3",
           "nesting depth 3" in async_msg)
    expect("async: its sync twin reports depth 3 too (the control)",
           "nesting depth 3" in sync_msg)


def test_four_deep_stack_emits_two_findings(tmp: Path) -> None:
    _, message = run_check(SCRIPT, write_fixture(tmp, "four_deep.py", FOUR_DEEP))
    found = nesting_findings(message)
    expect(f"stack: a 4-deep stack emits exactly 2 nesting findings (got {len(found)})",
           len(found) == 2)


def main() -> int:
    ref = os.environ.get("WIRING_CHECK_REF")
    suffix = f" @ {ref}" if ref else ""
    print(f"test_wiring_check.py -- pinning {SCRIPT.name}{suffix}")
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        test_dirty_reports_all_three(tmp)
        test_clean_is_silent(tmp)
        test_nesting_assertion_is_bound_to_the_detector(tmp)
        test_violations_are_advisory_never_a_block(tmp)
        test_flat_elif_chain_is_not_nesting(tmp)
        test_else_then_if_is_still_nesting(tmp)
        test_async_nesting_is_seen(tmp)
        test_four_deep_stack_emits_two_findings(tmp)
    if FAILURES:
        print(f"\nFAIL: {len(FAILURES)} contract(s) broken")
        return 1
    print(
        "\nPASS: wiring-check.py DETECTS and REPORTS the file-inspectable "
        "coding-audhd limits.\n"
        "      ADVISORY DETECTION ONLY -- it exits 0 on violations, so findings "
        "are surfaced, never blocked.\n"
        "      A violating write still lands. Nothing here enforces anything."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
