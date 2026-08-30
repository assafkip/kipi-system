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
        # MUTATE A COPY, NEVER THE LIVE ENGINE (codex minor, PR #272).
        #
        # This appended to the tracked mutation-sweep.py and restored it in a
        # `finally`. A `finally` does not run on SIGKILL, on a power loss, or
        # when the interpreter dies mid-write, so an interrupted run left the
        # repo's own engine corrupted with a stray comment -- or worse, truncated.
        # That is precisely the signal-unsafe pattern this PR documents as a scar
        # and refuses elsewhere, committed inside the test suite that guards it.
        #
        # A second module loaded from a temp path gives the same measurement with
        # nothing tracked in the blast radius.
        import importlib.util as _ilu
        import shutil as _shutil

        copy_path = Path(self.tmp) / "engine_copy.py"
        _shutil.copy2(ms.__file__, copy_path)
        spec = _ilu.spec_from_file_location("engine_copy", copy_path)
        engine = _ilu.module_from_spec(spec)
        spec.loader.exec_module(engine)

        live_before = Path(ms.__file__).read_bytes()
        before = engine.test_fingerprint(self.tmp, self.test_rel, None, "bash")
        copy_path.write_bytes(copy_path.read_bytes() + b"\n# an unrelated comment\n")
        after = engine.test_fingerprint(self.tmp, self.test_rel, None, "bash")

        self.assertNotEqual(before, after,
                            "an engine edit left the fingerprint unchanged")
        # Compared against bytes captured BEFORE the mutation. The first version of
        # this line compared the live file to itself, which is true by
        # construction and checks nothing -- the decorative-assertion shape this
        # whole tool exists to find.
        self.assertEqual(Path(ms.__file__).read_bytes(), live_before,
                         "the live engine was modified; this test must only "
                         "ever write to its copy")

    def test_changing_the_declared_timeout_invalidates(self):
        """PR #272. A verdict produced under a 60s cap says nothing about the
        same test under 600s -- a mutant that "survived" may simply have been
        killed. Any manifest field changing HOW the test runs belongs in the
        key, and runner was round one of exactly this."""
        a = ms.test_fingerprint(self.tmp, self.test_rel, None, "bash", 60)
        b = ms.test_fingerprint(self.tmp, self.test_rel, None, "bash", 600)
        self.assertNotEqual(a, b, "a timeout change reused the old verdict")

    def test_the_same_timeout_still_reuses_the_cache(self):
        self.assertEqual(
            ms.test_fingerprint(self.tmp, self.test_rel, None, "bash", 60),
            ms.test_fingerprint(self.tmp, self.test_rel, None, "bash", 60))

    def test_an_unreadable_test_is_a_miss_not_a_hit(self):
        os.remove(self.tmp / self.test_rel)
        self.assertIsNone(self.fp())
        # None must never compare equal to a stored fingerprint.
        self.assertNotEqual(self.fp(), hashlib.sha256(b"x").hexdigest()[:16])


if __name__ == "__main__":
    unittest.main(verbosity=2)
