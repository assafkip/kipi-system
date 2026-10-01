#!/usr/bin/env python3
"""Pins two Phase-1 gate reporting defects in validate-separation.py.

ASK-1902: `capability gate` FAILs but names no failing test. The OLD caller
tailed the last 15 raw lines of the gate subprocess's combined stdout+stderr.
capability-gate.py's own report() prints one "RED: test-failed rc=... <path>"
line per failure, each followed by up to 20 lines of that test's tail -- so a
single long tail (or 2+ failures) pushes the line naming the artifact out of
that 15-line window, and the FAIL prints a count with nothing to act on
(reproduced 2026-09-19: "FAIL: 2" with only one line saying what broke).
`run_capability_gate_phase()` fixes this by pulling the gate's own "RED:"
lines out of the FULL stdout instead of tailing the raw combination.

ASK-1903: Gate 1.2b warns "memory-lint produced no summary" on ANY checkout
with no auto-memory directory. memory-lint.py exits 0 and prints
"memory-lint: no memory directory at <path> (nothing to sweep)" on that path
-- a healthy no-op, not a broken linter -- but the OLD caller only looked for
a "structural: N" line, which that no-op path never prints either, so a
missing directory and a genuinely crashed linter produced the identical warn.
`evaluate_memory_lint_output()` fixes this by reading memory-lint's own
no-directory line before falling back to "no summary means broken".

Each case is proven by comparing the OLD inline logic (reproduced here
verbatim, not imported -- it no longer exists in the file) against the NEW
extracted function on the SAME input: the old logic must reproduce the bug,
the new one must not. That is the negative self-test: a check that cannot
show the old code failing is not proof the new code fixed anything.
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]


def load_validator():
    spec = importlib.util.spec_from_file_location(
        "kipi_validate_separation_capline", REPO_ROOT / "validate-separation.py"
    )
    if spec is None or spec.loader is None:
        raise SystemExit("cannot load validate-separation.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VS = load_validator()


# --- ASK-1902: capability gate FAIL names no failing test -------------------

def old_capability_gate_tail(stdout, stderr):
    """The exact pre-fix logic: last 15 lines of combined stdout+stderr."""
    return [("    " + l) for l in (stdout + stderr).splitlines()[-15:]]


def make_gate_stdout(named_path, tail_line_count):
    """A capability-gate.py report() for one failure with a tail long enough
    to push the "RED:" line out of a 15-line tail window."""
    lines = [
        "capability-gate mode=skeleton",
        "  declared: 200 tests (0 quarantined), 0 skeleton-only, 0 declared-inert",
        f"  RED: test-failed rc=1: {named_path}",
    ]
    lines += [f"    traceback frame {i}" for i in range(tail_line_count)]
    lines.append("capability-gate: RED (1)")
    return "\n".join(lines) + "\n"


class CapabilityGateLineTest(unittest.TestCase):
    def test_old_tail_loses_the_failing_path_on_a_long_tail(self):
        named_path = "q-system/.q-system/scripts/test/test-something-specific.py"
        stdout = make_gate_stdout(named_path, tail_line_count=20)
        old_lines = old_capability_gate_tail(stdout, "")
        self.assertFalse(
            any(named_path in l for l in old_lines),
            "the old tail-last-15-lines logic was expected to lose the named "
            "path on a 20-line traceback tail -- if this fails, the negative "
            "control itself is broken and proves nothing",
        )

    def test_new_function_names_the_failing_path_on_the_same_input(self):
        named_path = "q-system/.q-system/scripts/test/test-something-specific.py"
        stdout = make_gate_stdout(named_path, tail_line_count=20)

        class _StubResult:
            returncode = 1
            stderr = ""

        _StubResult.stdout = stdout
        import subprocess as _subprocess
        real_run = _subprocess.run

        def fake_run(cmd, capture_output, text, **kw):
            return _StubResult()

        _subprocess.run = fake_run
        try:
            passed, lines = VS.run_capability_gate_phase("stub-gate.py", "/repo")
        finally:
            _subprocess.run = real_run

        self.assertFalse(passed)
        self.assertTrue(
            any(named_path in l for l in lines),
            "run_capability_gate_phase must name the failing artifact even "
            "when its traceback tail is longer than 15 lines: got %r" % (lines,),
        )

    def test_new_function_bounds_named_lines_and_says_how_many_more(self):
        stdout_lines = ["capability-gate mode=skeleton"]
        for i in range(15):
            stdout_lines.append(f"  RED: test-failed rc=1: fixture/test-{i}.py")
        stdout_lines.append("capability-gate: RED (15)")
        stdout = "\n".join(stdout_lines) + "\n"

        class _StubResult:
            returncode = 1
            stderr = ""

        _StubResult.stdout = stdout
        import subprocess as _subprocess
        real_run = _subprocess.run
        _subprocess.run = lambda *a, **kw: _StubResult()
        try:
            passed, lines = VS.run_capability_gate_phase("stub-gate.py", "/repo", max_named_lines=10)
        finally:
            _subprocess.run = real_run

        self.assertFalse(passed)
        named = [l for l in lines if "test-" in l and "fixture/" in l]
        self.assertEqual(len(named), 10, "expected exactly 10 named artifacts, got %r" % (lines,))
        self.assertTrue(any("5 more" in l for l in lines), "expected an overflow count line: %r" % (lines,))

    def test_new_function_passes_clean_on_exit_zero(self):
        class _StubResult:
            returncode = 0
            stdout = "capability-gate mode=skeleton\ncapability-gate: GREEN\n"
            stderr = ""

        import subprocess as _subprocess
        real_run = _subprocess.run
        _subprocess.run = lambda *a, **kw: _StubResult()
        try:
            passed, lines = VS.run_capability_gate_phase("stub-gate.py", "/repo")
        finally:
            _subprocess.run = real_run

        self.assertTrue(passed)
        self.assertEqual(lines, [])


# --- ASK-1903: memory-lint "no summary" warn on a healthy empty checkout ----

def old_memory_lint_summary_check(returncode, stdout):
    """The exact pre-fix logic: look for a "structural:" line or warn "no summary"."""
    summary = next((l for l in stdout.splitlines() if l.startswith("structural:")), None)
    if summary is None:
        return ("broken", f"memory-lint produced no summary (exit {returncode})")
    if summary.split()[1] != "0":
        return ("dirty", summary)
    return ("clean", summary)


NO_DIR_STDOUT = "memory-lint: no memory directory at /home/x/.claude/projects/foo/memory (nothing to sweep)\n"
CLEAN_STDOUT = "memory-lint: 12 memory file(s) in /x/memory\n\nstructural: 0   advisory: 3\n"
DIRTY_STDOUT = "memory-lint: 12 memory file(s) in /x/memory\n\nstructural: 2   advisory: 0\n"
CRASH_STDOUT = "Traceback (most recent call last):\n  File \"memory-lint.py\", line 1\nZeroDivisionError\n"


class MemoryLintClassificationTest(unittest.TestCase):
    def test_old_logic_misreports_a_healthy_missing_directory_as_broken(self):
        status, _ = old_memory_lint_summary_check(0, NO_DIR_STDOUT)
        self.assertEqual(
            status, "broken",
            "the old logic was expected to misclassify a missing memory dir as "
            "'broken' -- if this fails, the negative control itself is broken",
        )

    def test_new_function_treats_missing_directory_as_skip_not_broken(self):
        status, message = VS.evaluate_memory_lint_output(0, NO_DIR_STDOUT)
        self.assertEqual(status, "skip")
        self.assertIn("no memory directory", message)

    def test_new_function_still_flags_a_genuine_crash(self):
        status, message = VS.evaluate_memory_lint_output(1, CRASH_STDOUT)
        self.assertEqual(status, "broken")
        self.assertIn("exit 1", message)

    def test_new_function_reports_clean_and_dirty_unchanged(self):
        clean_status, _ = VS.evaluate_memory_lint_output(0, CLEAN_STDOUT)
        self.assertEqual(clean_status, "clean")
        dirty_status, _ = VS.evaluate_memory_lint_output(0, DIRTY_STDOUT)
        self.assertEqual(dirty_status, "dirty")


if __name__ == "__main__":
    unittest.main()
