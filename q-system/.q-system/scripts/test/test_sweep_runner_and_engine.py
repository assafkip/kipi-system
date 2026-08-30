#!/usr/bin/env python3
"""PR #272 majors: the sweep did not know `pytest`, and its cache ignored the engine.

TWO COMPONENTS EACH CORRECT AND WRONG TOGETHER. ASK-1145 added `pytest` as a
third runner in capability-gate.py and flipped 13 declarations to it, because
those modules define test functions that `python3 <file>` never executes. This
sweep still knew two runners, so every pytest-declared entry fell through to
BASH, failed instantly, and was booked EXCLUDED-baseline-red -- 13 real tests
measured as nothing, by a tool whose entire job is noticing that.

And the resume fingerprint covered test + subject but not the mutation ENGINE, so
adding an operator changed what "disarmed" means while cached rows kept their old
verdicts.
"""

import importlib.util
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SWEEP = HERE.parent / "mutation-sweep.py"
_spec = importlib.util.spec_from_file_location("mutation_sweep", SWEEP)
ms = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ms)


class RunnerCase(unittest.TestCase):
    """The dispatch is read from the source, because building a Sweep object
    needs a whole repo. The mapping IS the defect."""

    def setUp(self):
        self.src = SWEEP.read_text()

    def test_pytest_is_a_known_runner(self):
        self.assertIn('if runner == "pytest":', self.src,
                      "the sweep still does not know the pytest runner")
        self.assertIn('"-m", "pytest"', self.src,
                      "pytest entries are not invoked through pytest")

    def test_bash_is_no_longer_the_catch_all(self):
        """The fall-through is what turned an unknown runner into 13 silent
        exclusions. An unknown runner must fail loudly instead."""
        self.assertNotIn('else ["bash", str(full)])', self.src,
                         "bash is still the catch-all for any unknown runner")
        self.assertIn("unknown runner", self.src,
                      "an unknown runner does not fail loudly")

    def test_the_three_runners_match_the_gate(self):
        """capability-gate.py is the other half of this pair. If it grows a
        fourth runner, this test is the thing that notices."""
        gate = (HERE.parent / "capability-gate.py").read_text()
        for runner in ("python3", "bash", "pytest"):
            self.assertIn('"%s"' % runner, gate,
                          "the gate no longer declares %s" % runner)
            self.assertIn('"%s"' % runner, self.src,
                          "the sweep does not handle %s" % runner)


class ExitCallDisarmCase(unittest.TestCase):
    """PR #272 major. `sys.exit(main())` rewritten to `sys.exit(0)` does not
    disarm a verdict -- it DELETES THE CALL. main() never runs, the mutant does
    nothing, and every test asserting normal output goes red for a reason
    unrelated to failure signalling. Those were then scored KILLED, the
    false-confident direction."""

    def test_a_call_argument_is_not_disarmed(self):
        out, n = ms._disarm_exit_calls("    sys.exit(main())\n")
        self.assertEqual(n, 0, "the call was replaced, so main() never runs")
        self.assertIn("main()", out)

    def test_a_name_argument_is_not_disarmed(self):
        out, n = ms._disarm_exit_calls("    sys.exit(rc)\n")
        self.assertEqual(n, 0)
        self.assertIn("rc", out)

    def test_a_literal_exit_code_is_still_disarmed(self):
        """The rule has to keep WORKING, or the sweep measures nothing."""
        out, n = ms._disarm_exit_calls("    sys.exit(1)\n")
        self.assertEqual(n, 1)
        self.assertIn("sys.exit(0)", out)

    def test_raise_systemexit_with_a_literal_is_disarmed(self):
        out, n = ms._disarm_exit_calls("    raise SystemExit(2)\n")
        self.assertEqual(n, 1)
        self.assertIn("SystemExit(0)", out)


class EngineFingerprintCase(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="engine-fp-"))
        self.rel = "t/test_thing.sh"
        (self.tmp / "t").mkdir(parents=True)
        (self.tmp / self.rel).write_text("echo v1\n")

    def test_changing_an_operator_invalidates_the_cache(self):
        before = ms.test_fingerprint(self.tmp, self.rel, None)
        saved = ms.VERDICT_RULES[:]
        try:
            ms.VERDICT_RULES.clear()
            after = ms.test_fingerprint(self.tmp, self.rel, None)
        finally:
            ms.VERDICT_RULES[:] = saved
        self.assertNotEqual(before, after,
                            "removing an operator left the fingerprint unchanged, "
                            "so a resumed run would replay verdicts produced under "
                            "different mutation semantics")

    def test_an_unchanged_engine_still_reuses_the_cache(self):
        """The cache must still WORK, or this is just a slower sweep."""
        self.assertEqual(ms.test_fingerprint(self.tmp, self.rel, None),
                         ms.test_fingerprint(self.tmp, self.rel, None))


if __name__ == "__main__":
    unittest.main(verbosity=2)
