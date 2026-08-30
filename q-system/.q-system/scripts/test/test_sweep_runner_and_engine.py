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

class SubjectRollupCase(unittest.TestCase):
    """PR #272 codex major: the loudest line was a known over-count.

    `sweep()` settled each test on its FIRST confirmed subject and broke, so a
    test guarding two subjects was credited against one. `subject_rollup` reads
    those same pairs, so the second subject read "no declared test guards its
    failure path" -- while the tool's own `--subject` mode, walking every
    declared test, reported it GUARDED. The tool contradicted itself on one
    fixture.
    """

    @staticmethod
    def _results(truncate):
        """One test that KILLS subject A and SURVIVES subject B.

        `truncate` reproduces the old break: keep only the first confirmed pair.
        """
        pairs = [{"subject": "a.py", "verdict": "KILLED"},
                 {"subject": "b.py", "verdict": "SURVIVED"}]
        if truncate:
            pairs = pairs[:1]
        return [{"test": "test_both.py", "pairs": pairs},
                {"test": "test_shallow.py",
                 "pairs": [{"subject": "b.py", "verdict": "SURVIVED"}]}]

    @staticmethod
    def _results_b_killed(truncate):
        """One test that SURVIVES subject A and KILLS subject B.

        Ordered so the truncation drops the KILL: this is the shape that made a
        guarded subject read unguarded, and the order matters because the old
        break kept whichever pair came first.
        """
        pairs = [{"subject": "a.py", "verdict": "SURVIVED"},
                 {"subject": "b.py", "verdict": "KILLED"}]
        if truncate:
            pairs = pairs[:1]
        return [{"test": "test_both.py", "pairs": pairs}]

    def test_a_subject_guarded_by_a_multi_subject_test_is_not_called_unguarded(self):
        by_subject, unguarded = ms.subject_rollup(self._results_b_killed(False))
        self.assertIn("test_both.py", by_subject["b.py"]["killed"],
                      "the test that kills b.py is not credited against it")
        self.assertNotIn("b.py", unguarded,
                         "b.py is killed by a declared test and must not be "
                         "reported as guarded by nothing: %r" % (unguarded,))

    def test_the_truncated_shape_is_what_produced_the_wrong_headline(self):
        """The negative half. Without it, the case above could pass for a reason
        unrelated to the fix -- so this shows the same population going WRONG
        under the old break."""
        by_subject, unguarded = ms.subject_rollup(self._results_b_killed(True))
        self.assertNotIn("b.py", by_subject,
                         "truncation should drop the KILLED pair this fix "
                         "restores; if it does not, the fixture proves nothing")

    def test_the_sweep_loop_does_not_settle_on_the_first_confirmed_subject(self):
        src = SWEEP.read_text()
        self.assertNotIn("break  # first CONFIRMED subject settles this test", src,
                         "the break is back; the per-subject rollup over-counts "
                         "again")

class CITargetsCase(unittest.TestCase):
    """PR #272 codex minor: a commented-out CI step is not coverage."""

    def _targets(self, workflow_text):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".github/workflows").mkdir(parents=True)
            (root / ".github/workflows/ci.yml").write_text(workflow_text)
            (root / "realdir").mkdir()
            return ms.ci_pytest_targets(root)

    def test_a_commented_out_invocation_is_not_a_target(self):
        """verify.yml carries one of these today. Counting it claimed a runner
        that does not run, which is the failure this whole tool hunts."""
        self.assertEqual(self._targets("      # pytest realdir\n"), [])

    def test_prose_is_not_a_path(self):
        """`pytest must exist BEFORE the gate` yielded a target named `must`."""
        self.assertEqual(
            self._targets("      # pytest must exist BEFORE the gate\n"), [])
        self.assertEqual(
            self._targets("      run: pytest must exist BEFORE the gate\n"), [],
            "a bare word that names no path in the tree is prose")

    def test_a_real_invocation_is_still_found(self):
        """The negative cases above are worthless if nothing passes."""
        self.assertEqual(self._targets("      - run: pytest realdir -q\n"),
                         ["realdir"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
