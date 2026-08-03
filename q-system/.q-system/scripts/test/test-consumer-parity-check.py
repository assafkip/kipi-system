#!/usr/bin/env python3
"""consumer-parity-check: does it re-find the known defect, and can it be seen to fail?

THE REPRODUCER (ASK-315): the check is run against capability-map-gen.py AT d20f412,
the revision before the one-sided-exclusion fixes. A gate that cannot re-find a known
past defect is not verified, it is only untested. The fixture is the byte-exact file
from that commit, and `test_fixture_matches_the_real_commit` pins it to git so the
fixture cannot quietly drift away from the history it claims to be.

THE NEGATIVE SELF-TEST: `TestNegativeSelfTest` removes the predicate from ONE walker on
a COPY of the current module and proves the check goes red on exactly that walker.
Four of the five defect classes in the originating RCA had a guard that had never been
seen to fail; this file exists so this gate is not the fifth.

Isolation: every mutation happens on a string or in a tempdir. Nothing here writes to
the live module.
"""

import ast
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent
CHECK = SCRIPTS / "consumer-parity-check.py"
LIVE_MODULE = SCRIPTS / "capability-map-gen.py"
FIXTURE = HERE / "fixtures" / "capability-map-gen.d20f412.py"
PREFIX_COMMIT = "d20f412"
MODULE_PATH_IN_REPO = "q-system/.q-system/scripts/capability-map-gen.py"


def load_check():
    spec = importlib.util.spec_from_file_location("consumer_parity_check", CHECK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


CP = load_check()


class TestReproducerAgainstThePreFixCommit(unittest.TestCase):
    """RED on the real historical file. This is the observed-RED the DoR demands."""

    @classmethod
    def setUpClass(cls):
        cls.findings = CP.check_source(
            FIXTURE.read_text(encoding="utf-8"), MODULE_PATH_IN_REPO)
        cls.by_scope = {}
        for finding in cls.findings:
            cls.by_scope.setdefault(finding.scope, []).append(finding)

    def test_fixture_matches_the_real_commit(self):
        """The fixture is d20f412's file, not a transcription of it.

        Skipped where the object is unreachable (an instance after kipi update has the
        scripts but not this repo's history). Where history exists, this is the pin.
        """
        try:
            blob = subprocess.run(
                ["git", "show", f"{PREFIX_COMMIT}:{MODULE_PATH_IN_REPO}"],
                cwd=str(SCRIPTS), capture_output=True, timeout=30)
        except (OSError, subprocess.SubprocessError) as exc:  # pragma: no cover
            self.skipTest(f"git unavailable: {exc}")
        if blob.returncode != 0:  # pragma: no cover - instance checkouts
            self.skipTest(f"{PREFIX_COMMIT} not in this checkout's history")
        self.assertEqual(
            blob.stdout.decode("utf-8", "replace"),
            FIXTURE.read_text(encoding="utf-8"),
            "the fixture has drifted from the commit it claims to reproduce")

    def test_finds_the_unfiltered_walkers(self):
        self.assertTrue(
            self.findings,
            "the pre-fix module has walkers that skip is_vendored; a check that "
            "cannot re-find a known past defect is not verified")

    def test_collect_domains_glob_is_a_full_bypass(self):
        """`for p in sorted(root.glob("q-*"))` applied NO exclusion predicate."""
        hits = [f for f in self.by_scope.get("collect_domains", [])
                if ".glob(" in f.expr and "rglob" not in f.expr]
        self.assertEqual(1, len(hits), f"expected the q-* glob; got {self.findings}")
        self.assertEqual("bypass", hits[0].severity)
        self.assertIn("is_vendored", hits[0].missing)

    def test_find_nested_repos_applied_only_the_inner_constant(self):
        """Partial application is the shape, not just total absence.

        find_nested_repos filtered on SKIP_DIRS while every sibling walker used
        is_vendored, which also knows about virtualenvs and vendor markers. That is
        instance 4's shape exactly: filtered, but not to parity.
        """
        hits = self.by_scope.get("find_nested_repos", [])
        self.assertEqual(1, len(hits), f"expected the .git walk; got {self.findings}")
        self.assertEqual("parity", hits[0].severity)
        self.assertIn("SKIP_DIRS", hits[0].applied)
        self.assertIn("is_vendored", hits[0].missing)

    def test_the_filtered_walkers_are_not_reported(self):
        """The engine and surface walks DID apply is_vendored. Flagging them too would
        make the report noise and the fix unfindable."""
        for scope in ("_iter_surface_files", "collect_skills", "collect_commands"):
            self.assertNotIn(scope, self.by_scope,
                             f"{scope} filtered correctly at d20f412")


class TestLiveModuleIsAtParity(unittest.TestCase):
    def test_current_module_has_no_findings(self):
        findings = CP.check_file(LIVE_MODULE, MODULE_PATH_IN_REPO)
        self.assertEqual(
            [], findings,
            "capability-map-gen.py is the seed BLOCKING module; every walker in it "
            "must filter through is_vendored and is_excluded_tree:\n"
            + "\n".join(f.render() for f in findings))

    def test_seed_module_is_in_the_blocking_set(self):
        self.assertTrue(CP.is_blocking(MODULE_PATH_IN_REPO))
        self.assertFalse(CP.is_blocking("q-system/.q-system/scripts/linear-sync.py"),
                         "everything but the seed reports until the FP rate is measured")


class TestHookPath(unittest.TestCase):
    """The wired path, end to end. A check whose LIBRARY is green while its hook
    entry point never blocks is the dead-switch shape capability-map-gen.py exists
    to detect; it would be absurd for this gate to ship with it."""

    def _run(self, file_path: str):
        return subprocess.run(
            [sys.executable, str(CHECK)],
            input=json.dumps({"tool_name": "Edit",
                              "tool_input": {"file_path": file_path}}),
            capture_output=True, text=True, timeout=60)

    def test_hook_exits_2_on_the_seed_module(self):
        with tempfile.TemporaryDirectory() as td:
            seed = Path(td) / MODULE_PATH_IN_REPO
            seed.parent.mkdir(parents=True)
            seed.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
            proc = self._run(str(seed))
        self.assertEqual(2, proc.returncode,
                         f"the seed module must BLOCK: {proc.stderr or proc.stdout}")
        self.assertIn("CONSUMER PARITY (blocked)", proc.stderr)

    def test_hook_reports_but_does_not_block_a_non_seed_module(self):
        """Everything else reports until the false-positive rate is measured."""
        with tempfile.TemporaryDirectory() as td:
            other = Path(td) / "some-other-engine.py"
            other.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
            proc = self._run(str(other))
        self.assertEqual(0, proc.returncode, proc.stderr)
        self.assertIn("consumer-parity-check (report)", proc.stdout)

    def test_hook_ignores_non_python_writes(self):
        proc = self._run("q-system/canonical/decisions.md")
        self.assertEqual(0, proc.returncode)
        self.assertEqual("", proc.stdout.strip())


class TestNegativeSelfTest(unittest.TestCase):
    """Corrupt one walker on a COPY and prove the check FAILS on it."""

    def setUp(self):
        self.source = LIVE_MODULE.read_text(encoding="utf-8")

    def _mutate(self, old: str, new: str) -> list:
        self.assertIn(old, self.source, "mutation target moved; update this test")
        with tempfile.TemporaryDirectory() as td:
            copy = Path(td) / "capability-map-gen.py"
            copy.write_text(self.source.replace(old, new, 1), encoding="utf-8")
            ast.parse(copy.read_text(encoding="utf-8"))  # the mutant must still parse
            return CP.check_file(copy, MODULE_PATH_IN_REPO)

    def test_dropping_the_tree_predicate_from_one_walker_goes_red(self):
        findings = self._mutate(
            "        if is_vendored(p) or is_excluded_tree(p, root):\n"
            "            continue\n"
            "        text = read_text(p)",
            "        if is_vendored(p):\n"
            "            continue\n"
            "        text = read_text(p)")
        self.assertEqual(1, len(findings),
                         f"exactly the mutated walker must go red; got {findings}")
        self.assertEqual("collect_skills", findings[0].scope)
        self.assertEqual(("is_excluded_tree",), findings[0].missing)
        self.assertEqual("parity", findings[0].severity)

    def test_dropping_every_predicate_from_one_walker_goes_red_as_bypass(self):
        findings = self._mutate(
            "        files = [f for f in p.rglob(\"*\")\n"
            "                 if f.is_file() and not is_vendored(f) "
            "and not is_excluded_tree(f, root)]",
            "        files = [f for f in p.rglob(\"*\") if f.is_file()]")
        self.assertEqual(1, len(findings), f"got {findings}")
        self.assertEqual("bypass", findings[0].severity)
        self.assertEqual((), findings[0].applied)

    def test_a_brand_new_unfiltered_walker_goes_red(self):
        """The whole point: a walker ADDED tomorrow is in the census automatically.

        No consumer list to update, so there is nothing to forget -- which is what
        "one predicate for all three consumers" got wrong while shipping a fourth.
        """
        findings = self._mutate(
            "def collect_domains(root: Path) -> list:\n    caps = []",
            "def collect_extras(root: Path) -> list:\n"
            "    return [p for p in root.rglob"
            "(\"*.yaml\") if p.is_file()]\n\n\n"
            "def collect_domains(root: Path) -> list:\n    caps = []")
        scopes = {f.scope for f in findings}
        self.assertIn("collect_extras", scopes,
                      f"a newly added unfiltered walker must be caught; got {findings}")


class TestPredicateModelling(unittest.TestCase):
    """The two rules that keep the report signal and not noise."""

    def test_a_module_with_no_declared_predicate_is_silent(self):
        src = ("from pathlib import Path\n\n"
               "def go(root):\n    return [p for p in root.rglob('*') if p.is_file()]\n")
        self.assertEqual([], CP.check_source(src, "x.py"),
                         "nothing declared means nothing to be at parity with")

    def test_calling_a_predicate_covers_the_constants_it_consults(self):
        """Applying is_vendored satisfies SKIP_DIRS. Demanding every constant at every
        walker is the noise that gets a gate switched off."""
        src = ("SKIP_DIRS = {'a'}\n\n"
               "def is_vendored(p):\n    return any(d in SKIP_DIRS for d in p.parts)\n\n"
               "def go(root):\n"
               "    for p in root.rglob('*'):\n"
               "        if is_vendored(p):\n            continue\n        yield p\n")
        self.assertEqual([], CP.check_source(src, "x.py"))

    def test_a_filtered_sibling_walker_does_not_vouch_for_an_unfiltered_one(self):
        """collect_domains' shape: an outer unfiltered loop wrapping a filtered
        comprehension. Whole-function granularity would call this clean, which is how
        a one-sided exclusion hides in plain sight."""
        src = ("SKIP_DIRS = {'a'}\n\n"
               "def is_vendored(p):\n    return any(d in SKIP_DIRS for d in p.parts)\n\n"
               "def go(root):\n"
               "    for d in sorted(root.glob('q-*')):\n"
               "        files = [f for f in d.rglob('*') if not is_vendored(f)]\n"
               "        yield d, files\n")
        findings = CP.check_source(src, "x.py")
        self.assertEqual(1, len(findings), f"got {findings}")
        self.assertEqual("bypass", findings[0].severity)
        self.assertIn("glob('q-*')", findings[0].expr)

    def test_an_ack_comment_silences_one_walker_only(self):
        src = ("SKIP_DIRS = {'a'}\n\n"
               "def is_vendored(p):\n    return any(d in SKIP_DIRS for d in p.parts)\n\n"
               "def go(root):\n"
               "    for p in root.glob('*'):  # parity-ack: top-level names only\n"
               "        yield p\n"
               "    for q in root.rglob('*'):\n"
               "        yield q\n")
        findings = CP.check_source(src, "x.py")
        self.assertEqual(1, len(findings), f"the ack must not cover the second walker: {findings}")
        self.assertIn("rglob", findings[0].expr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
