#!/usr/bin/env python3
"""PR #272 major: --resume must not replay a verdict for code that changed.

The cache matched on test PATH alone, so editing a test and resuming replayed
the OLD verdict under the NEW file's name. An unattended report then described a
version of the code that no longer exists, with nothing saying so -- and a
resumed run is precisely the run nobody is watching.
"""

import hashlib
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SWEEP = HERE.parent / "mutation-sweep.py"

_spec = importlib.util.spec_from_file_location("mutation_sweep", SWEEP)
ms = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ms)


class ResumeCacheKeyCase(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="resume-key-"))
        self.test_rel = "t/test_thing.sh"
        self.subj_rel = "s/thing.sh"
        for rel, body in ((self.test_rel, "echo test v1\n"),
                          (self.subj_rel, "echo subject v1\n")):
            path = self.tmp / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body)

    def fp(self, cached=None):
        return ms.test_fingerprint(self.tmp, self.test_rel, cached)

    def test_an_unchanged_tree_reuses_the_verdict(self):
        """The cache has to still WORK, or the fix is just a slower sweep."""
        self.assertEqual(self.fp(), self.fp())

    def test_editing_the_test_invalidates(self):
        before = self.fp()
        (self.tmp / self.test_rel).write_text("echo test v2\n")
        self.assertNotEqual(before, self.fp())

    def test_editing_the_subject_invalidates(self):
        """A verdict is a claim about a test AND the subject it was measured
        against, so a changed subject invalidates it just as a changed test does."""
        cached = {"pairs": [{"subject": self.subj_rel}]}
        before = self.fp(cached)
        (self.tmp / self.subj_rel).write_text("echo subject v2\n")
        self.assertNotEqual(before, self.fp(cached))

    def test_a_row_with_no_fingerprint_is_a_miss(self):
        """Rows written before this change carry no test_sha. Trusting them
        silently would be the same defect wearing a compatibility argument."""
        legacy = {"test": self.test_rel, "pairs": []}
        self.assertIsNone(legacy.get("test_sha"))
        self.assertNotEqual(legacy.get("test_sha"), self.fp(legacy))

    def test_changing_the_declared_runner_invalidates(self):
        """PR #272 major. ASK-1145 flipped 13 tests from python3 to pytest, and
        that CHANGES WHICH ASSERTIONS EXECUTE -- python3 on a pytest module runs
        none of them. Keying on file content alone reused the old verdict and
        never ran the newly enabled ones: the zero-execution defect surviving its
        own fix."""
        a = ms.test_fingerprint(self.tmp, self.test_rel, None, "python3")
        b = ms.test_fingerprint(self.tmp, self.test_rel, None, "pytest")
        self.assertNotEqual(a, b, "flipping the runner reused the old verdict")

    def test_the_same_runner_still_reuses_the_cache(self):
        self.assertEqual(
            ms.test_fingerprint(self.tmp, self.test_rel, None, "pytest"),
            ms.test_fingerprint(self.tmp, self.test_rel, None, "pytest"))

    def test_changing_ANY_engine_code_invalidates(self):
        """PR #272, three rounds on one fingerprint. Round 1 hashed the tables;
        round 2 added three functions; round 3 found two more still missing.
        Each round the hand-list was short by exactly what I had not thought
        about, which is the stale-hand-list defect itself. The module is now the
        fingerprint, so there is no list to keep complete."""
        before = ms.test_fingerprint(self.tmp, self.test_rel, None, "bash")
        src = Path(ms.__file__)
        original = src.read_bytes()
        try:
            src.write_bytes(original + b"\n# an unrelated comment\n")
            after = ms.test_fingerprint(self.tmp, self.test_rel, None, "bash")
        finally:
            src.write_bytes(original)
        self.assertNotEqual(before, after,
                            "an engine edit left the fingerprint unchanged")

    def test_an_unreadable_test_is_a_miss_not_a_hit(self):
        os.remove(self.tmp / self.test_rel)
        self.assertIsNone(self.fp())
        # None must never compare equal to a stored fingerprint.
        self.assertNotEqual(self.fp(), hashlib.sha256(b"x").hexdigest()[:16])


if __name__ == "__main__":
    unittest.main(verbosity=2)
