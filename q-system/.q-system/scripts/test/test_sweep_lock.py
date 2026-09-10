#!/usr/bin/env python3
"""PR #272 major: two concurrent sweeps corrupt tracked source.

The sweep mutates TRACKED SOURCE in place and restores from its own backup. Two
overlapping sweeps interleave on the same file: A backs up the original, B backs
up A's MUTANT believing it is the original, and whichever restores last writes
the wrong bytes into the working tree. Each process's restore-sha check passes,
because each verifies against the sha IT captured.

The dirty-tree refusal does not cover it: the second sweep starts while the
first has the tree momentarily clean between pairs.
"""

import importlib.util
import os
import shutil
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SWEEP = HERE.parent / "mutation-sweep.py"
_spec = importlib.util.spec_from_file_location("mutation_sweep", SWEEP)
ms = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ms)


class SweepLockCase(unittest.TestCase):

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="sweeplock-"))
        self.lock = self.root / "q-system/output/mutation-sweep/.sweep.lock"

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_the_first_sweep_takes_the_lock(self):
        release = ms.acquire_sweep_lock(self.root)
        self.assertTrue(self.lock.is_file(), "no lock file was created")
        self.assertEqual(self.lock.read_text().strip(), str(os.getpid()),
                         "the lock does not record its holder")
        release()
        self.assertFalse(self.lock.exists(), "release left the lock behind")

    def test_a_second_sweep_is_refused_while_the_first_lives(self):
        """The negative self-test. If this passes, tracked source is at risk."""
        release = ms.acquire_sweep_lock(self.root)
        try:
            with self.assertRaises(SystemExit) as caught:
                ms.acquire_sweep_lock(self.root)
            self.assertEqual(caught.exception.code, 3)
        finally:
            release()

    def test_a_stale_lock_is_reclaimed(self):
        """An operator who has to clear a lock by hand eventually clears one
        while a sweep IS running, so a dead holder must not need a human."""
        self.lock.parent.mkdir(parents=True, exist_ok=True)
        # A pid that cannot exist: os.kill would raise for it.
        self.lock.write_text("999999999")
        release = ms.acquire_sweep_lock(self.root)
        self.assertEqual(self.lock.read_text().strip(), str(os.getpid()),
                         "the stale lock was not reclaimed")
        release()

    def test_a_corrupt_lock_is_reclaimed(self):
        self.lock.parent.mkdir(parents=True, exist_ok=True)
        self.lock.write_text("not a pid")
        release = ms.acquire_sweep_lock(self.root)
        self.assertEqual(self.lock.read_text().strip(), str(os.getpid()))
        release()

    def test_release_does_not_remove_someone_elses_lock(self):
        """Release is pid-checked, or a reclaimed-then-released lock would delete
        the live holder's file and re-open the race it just closed."""
        release = ms.acquire_sweep_lock(self.root)
        self.lock.write_text("999999999")   # someone else now holds it
        release()
        self.assertTrue(self.lock.is_file(), "release deleted another holder's lock")


if __name__ == "__main__":
    unittest.main(verbosity=2)
