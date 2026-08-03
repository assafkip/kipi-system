#!/usr/bin/env python3
"""The mutation checker's own safety properties (ASK-316).

WHY THIS FILE EXISTS. mutation-check.py is the thing that decides whether a
safety test can fail. If IT reports a clean run when a mutation never applied,
it manufactures exactly the false confidence it was built to remove, one level
up. So the properties pinned here are all about the checker REFUSING rather than
answering: absent find-text, a mutation that breaks syntax, a malformed
declaration, a baseline that is already red.

Every one of these is a case where the wrong behaviour is silent and green.

Isolation: every fixture is built in a tempdir. Nothing here copies the real
repo, runs a real suite, or reads capability-manifest.json.
"""

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CHECKER = Path(__file__).resolve().parent.parent / "mutation-check.py"


def load_checker():
    spec = importlib.util.spec_from_file_location("mutation_check", CHECKER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MC = load_checker()


def green_suite(path: Path, must_contain: str = "GUARD") -> None:
    """A suite that passes only while `must_contain` survives in target.py."""
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "from pathlib import Path\n"
        "text = (Path(__file__).parent / 'target.py').read_text()\n"
        f"sys.exit(0 if {must_contain!r} in text else 1)\n",
        encoding="utf-8")


class TestDeclarationValidation(unittest.TestCase):
    """A malformed declaration is REFUSED, never skipped.

    Skipping is how a mutation suite reports all-clear while checking nothing --
    the silent-absence class the capability gate exists for.
    """

    def bad(self, mutant, needle):
        with self.assertRaises(MC.Refusal) as ctx:
            MC.validate_mutant("suite.sh", mutant)
        self.assertIn(needle, str(ctx.exception))

    def test_missing_fields_are_refused(self):
        base = {"id": "m", "target": "a.py", "find": "x", "why": "because"}
        for key in ("id", "target", "find", "why"):
            mutant = dict(base)
            mutant.pop(key)
            self.bad(mutant, key)

    def test_empty_field_is_refused(self):
        self.bad({"id": "m", "target": "a.py", "find": "x", "why": ""}, "why")

    def test_noop_mutation_is_refused(self):
        self.bad({"id": "m", "target": "a.py", "find": "x", "replace": "x",
                  "why": "w"}, "mutates nothing")

    def test_unknown_kind_is_refused(self):
        self.bad({"id": "m", "target": "a.py", "find": "x", "why": "w",
                  "kind": "vibes"}, "kind must be one of")

    def test_target_escaping_the_repo_is_refused(self):
        for target in ("/etc/passwd", "~/x.py", "../../outside.py"):
            self.bad({"id": "m", "target": target, "find": "x", "why": "w"},
                     "escapes the repo")

    def test_call_site_kind_is_accepted(self):
        MC.validate_mutant("suite.sh", {
            "id": "m", "target": "a.sh", "find": "x", "replace": "",
            "kind": "call-site", "why": "the caller stops invoking it"})


class TestApplyValidation(unittest.TestCase):
    """APPLIED, DIFFERING, PARSING -- all three before any result is trusted."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tree = Path(self.tmp.name)
        (self.tree / "target.py").write_text("GUARD = 1\nvalue = 2\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_absent_find_text_is_refused_not_counted(self):
        """THE CENTRAL CASE. A mutation that silently did not apply leaves the
        suite green, which reads exactly like coverage."""
        with self.assertRaises(MC.Refusal) as ctx:
            MC.apply_mutant(self.tree, {
                "id": "m", "target": "target.py", "find": "NOT_PRESENT",
                "replace": "", "why": "w"})
        self.assertIn("silently not apply", str(ctx.exception))

    def test_missing_target_is_refused(self):
        with self.assertRaises(MC.Refusal) as ctx:
            MC.apply_mutant(self.tree, {
                "id": "m", "target": "nope.py", "find": "x", "replace": "",
                "why": "w"})
        self.assertIn("does not exist", str(ctx.exception))

    def test_unparseable_mutation_is_refused_and_target_restored(self):
        """A mutant that breaks syntax kills every test for the wrong reason.

        Counting it as coverage is worse than useless: it certifies a suite that
        may assert nothing. The file must also be put back, or the refusal
        poisons every later mutant in the same tree copy.
        """
        with self.assertRaises(MC.Refusal) as ctx:
            MC.apply_mutant(self.tree, {
                "id": "m", "target": "target.py", "find": "GUARD = 1",
                "replace": "def (", "why": "w"})
        self.assertIn("does not parse", str(ctx.exception))
        self.assertEqual("GUARD = 1\nvalue = 2\n",
                         (self.tree / "target.py").read_text(encoding="utf-8"))

    def test_applied_mutation_returns_the_original_for_restore(self):
        original, mutated = MC.apply_mutant(self.tree, {
            "id": "m", "target": "target.py", "find": "GUARD = 1",
            "replace": "GONE = 1", "why": "w"})
        self.assertIn("GUARD", original)
        self.assertNotIn("GUARD", mutated)
        self.assertEqual(mutated, (self.tree / "target.py").read_text(encoding="utf-8"))

    def test_bash_syntax_is_checked_too(self):
        (self.tree / "t.sh").write_text("set -e\nif true; then echo hi; fi\n",
                                        encoding="utf-8")
        with self.assertRaises(MC.Refusal):
            MC.apply_mutant(self.tree, {
                "id": "m", "target": "t.sh", "find": "fi\n", "replace": "",
                "why": "w"})


class TestRunVerdicts(unittest.TestCase):
    """Baseline red refuses; green-under-mutation is SURVIVED, not silence."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tree = Path(self.tmp.name)
        (self.tree / "target.py").write_text("GUARD = 1\n", encoding="utf-8")
        self.entry = {"path": "suite.py", "runner": "python3",
                      "mutants": [{"id": "drop-guard", "target": "target.py",
                                   "find": "GUARD", "replace": "GONE",
                                   "why": "the guard disappears"}]}

    def tearDown(self):
        self.tmp.cleanup()

    def test_red_baseline_is_refused(self):
        """Every mutant would 'kill' a suite that was already failing. Reporting
        that as full coverage is the most flattering possible wrong answer."""
        (self.tree / "suite.py").write_text("import sys\nsys.exit(1)\n",
                                            encoding="utf-8")
        with self.assertRaises(MC.Refusal) as ctx:
            MC.check_entry(self.tree, self.entry)
        self.assertIn("baseline is RED", str(ctx.exception))

    def test_covered_mutant_is_killed_and_target_restored(self):
        green_suite(self.tree / "suite.py")
        result = MC.check_entry(self.tree, self.entry)
        self.assertEqual("KILLED", result["mutants"][0]["verdict"])
        self.assertEqual("GUARD = 1\n",
                         (self.tree / "target.py").read_text(encoding="utf-8"),
                         "the tree must be restored so later mutants run clean")

    def test_timeout_is_refused_not_counted_as_a_kill(self):
        """A deadline says nothing about the mutant, and "did not finish" must
        never be read as "the suite caught it".

        Observed, not imagined: the first version of run_suite used
        subprocess.run(capture_output=True, timeout=...), which waits on pipe EOF
        rather than child exit and, on timeout, kills only the direct child. Two
        real gate suites hung ~40 minutes past their deadline holding an orphaned
        grandchild's pipe. The runner is now capability-gate.py's run_contained.
        """
        (self.tree / "suite.py").write_text(
            "import time\ntime.sleep(30)\n", encoding="utf-8")
        entry = dict(self.entry, timeout_s=5)
        with self.assertRaises(MC.Refusal) as ctx:
            MC.check_entry(self.tree, entry)
        self.assertIn("deadline", str(ctx.exception))

    def test_the_runner_is_the_gates_contained_one(self):
        """One runner, not two. A second copy of the process-group handling would
        drift from the gate's, and this is the half that hangs when it does."""
        self.assertEqual("run_contained", MC.run_contained.__name__)
        self.assertIn("capability_gate", MC.run_contained.__module__)

    def test_uncovered_mutant_is_reported_survived(self):
        (self.tree / "suite.py").write_text("import sys\nsys.exit(0)\n",
                                            encoding="utf-8")
        result = MC.check_entry(self.tree, self.entry)
        self.assertEqual("SURVIVED", result["mutants"][0]["verdict"])

    def test_survived_mutant_makes_the_report_nonzero(self):
        result = {"path": "suite.py", "baseline": 0,
                  "mutants": [{"id": "m", "kind": "logic", "target": "t.py",
                               "why": "w", "verdict": "SURVIVED"}]}
        self.assertEqual(1, MC.report([result], []))

    def test_errored_mutant_outranks_a_clean_report(self):
        """ERROR must not be swallowed by an otherwise all-killed run: an
        un-appliable declaration means the run proved less than it claims."""
        result = {"path": "suite.py", "baseline": 0,
                  "mutants": [{"id": "a", "kind": "logic", "target": "t.py",
                               "why": "w", "verdict": "KILLED"},
                              {"id": "b", "kind": "logic", "target": "t.py",
                               "why": "w", "verdict": "ERROR", "detail": "absent"}]}
        self.assertEqual(2, MC.report([result], []))

    def test_all_killed_is_the_only_zero(self):
        result = {"path": "suite.py", "baseline": 0,
                  "mutants": [{"id": "a", "kind": "logic", "target": "t.py",
                               "why": "w", "verdict": "KILLED"}]}
        self.assertEqual(0, MC.report([result], []))


class TestCliContract(unittest.TestCase):
    """The wiring the weekly job depends on: --require and the no-mutants exit."""

    def run_cli(self, manifest_text, *args):
        with tempfile.TemporaryDirectory() as td:
            man = Path(td) / "m.json"
            man.write_text(manifest_text, encoding="utf-8")
            return subprocess.run(
                [sys.executable, str(CHECKER), "--manifest", str(man), *args],
                capture_output=True, text=True, check=False)

    def test_manifest_with_no_mutants_is_refused(self):
        proc = self.run_cli('{"expected_tests": [{"path": "a.py", "runner": "python3"}]}')
        self.assertEqual(2, proc.returncode)
        self.assertIn("no expected_tests entry declares", proc.stderr)

    def test_require_names_a_suite_that_lost_its_declarations(self):
        """A gate suite quietly losing its `mutants` list would otherwise read as
        a clean run -- absence is invisible to an exit code unless asked for."""
        manifest = ('{"expected_tests": [{"path": "other.py", "runner": "python3",'
                    ' "mutants": [{"id": "m", "target": "t.py", "find": "x",'
                    ' "replace": "", "why": "w"}]}]}')
        proc = self.run_cli(manifest, "--require", "test-severity-floor")
        self.assertEqual(2, proc.returncode)
        self.assertIn("test-severity-floor", proc.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
