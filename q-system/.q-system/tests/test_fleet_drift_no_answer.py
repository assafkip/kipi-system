#!/usr/bin/env python3
"""A drift scan that did not run must not read as a clean fleet (codex major, PR #158 r1).

Both failure paths in detect_fleet_drift used to `return []`, which is
byte-identical to "I checked 23 instances and every one is clean". An empty list
also reads to the caller as a detector that RAN, so the blind-detector
notification meant to catch a detector producing nothing stayed quiet as well.
A crashed scanner was invisible twice over.

These are the reproducers for that. Each one drives the REAL detector against a
deliberately broken fleet-drift-scan.py and asserts the result is a loud
no-answer, not silence.
"""
import importlib.util
import pathlib
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve()
SCRIPT = HERE.parents[1] / "scripts" / "fleet-health-daily.py"


def load_module():
    """Import fleet-health-daily.py by path; its name is not a valid identifier."""
    spec = importlib.util.spec_from_file_location("fleet_health_daily", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class NoAnswerIsNotGreen(unittest.TestCase):
    def setUp(self):
        if not SCRIPT.exists():
            self.skipTest(f"no fleet-health-daily.py at {SCRIPT}")
        self.mod = load_module()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        # REPO_ROOT is where the detector looks for the scanner. Pointing it at a
        # temp dir is what keeps this test off the real fleet -- it never opens an
        # instance, and the scanner it finds is one this test wrote.
        self.mod.REPO_ROOT = self.root

    def _write_scanner(self, body: str):
        (self.root / "fleet-drift-scan.py").write_text(body)

    def test_unparseable_stdout_is_a_finding_not_silence(self):
        self._write_scanner("print('this is not json')\n")
        out = self.mod.detect_fleet_drift(None)
        self.assertTrue(
            out, "unparseable scanner output returned [] -- a crash read as a clean fleet"
        )
        self.assertEqual(out[0]["subject"], "fleet-drift-scan:no-answer")
        self.assertIn("not a clean fleet", out[0]["body"].lower())

    def test_scanner_that_crashes_is_a_finding(self):
        self._write_scanner("import sys\nsys.stderr.write('boom\\n')\nsys.exit(3)\n")
        out = self.mod.detect_fleet_drift(None)
        self.assertTrue(out, "a crashing scanner returned [] -- silence indistinguishable from green")
        self.assertEqual(out[0]["subject"], "fleet-drift-scan:no-answer")

    def test_stderr_tail_is_carried_so_the_issue_is_actionable(self):
        self._write_scanner(
            "import sys\nsys.stderr.write('ModuleNotFoundError: no such module\\n')\n"
            "sys.exit(1)\n"
        )
        out = self.mod.detect_fleet_drift(None)
        self.assertIn("ModuleNotFoundError", out[0]["body"],
                      "the no-answer issue does not say WHY, so nobody can act on it")

    def test_a_real_verdict_still_reports_drift(self):
        # The guard must not have replaced the detector's actual job.
        self._write_scanner(
            "import json\n"
            "print(json.dumps({'drift': [{'instance': 'inst-a', 'path': 'p/x.py',"
            " 'detail': 'deadbeef'}]}))\n"
        )
        out = self.mod.detect_fleet_drift(None)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["subject"], "inst-a:p/x.py")

    def test_a_clean_verdict_is_still_silent(self):
        # THE NEGATIVE SELF-TEST. Without this, every assertion above would pass
        # on a detector that returned a finding unconditionally -- which would be
        # a different bug wearing the same green.
        self._write_scanner("import json\nprint(json.dumps({'drift': []}))\n")
        out = self.mod.detect_fleet_drift(None)
        self.assertEqual(out, [], "a genuinely clean fleet must produce no finding")

    def test_absent_scanner_is_still_a_no_op(self):
        # No scanner file at all is "this feature is not installed here", which is
        # different from "it ran and broke". Unchanged behaviour, asserted so the
        # distinction does not quietly collapse into the no-answer path.
        out = self.mod.detect_fleet_drift(None)
        self.assertEqual(out, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
