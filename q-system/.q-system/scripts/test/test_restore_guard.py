#!/usr/bin/env python3
"""PR #272 BLOCKER: the restore overwrote a concurrent edit and called it success.

_restore copied its backup over the target unconditionally. If a human saved that
file while the sweep held it mutated, their work was replaced by the pre-mutation
content -- and the sha check then PASSED, because the result matched orig_sha
exactly as intended. Silent data loss reported as a successful restoration, by a
tool whose whole subject is checks that pass for the wrong reason.

The sweep lock keeps a second SWEEP out. It cannot keep a PERSON out, and a
person is who loses work here.
"""

import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SWEEP = HERE.parent / "mutation-sweep.py"
_spec = importlib.util.spec_from_file_location("mutation_sweep", SWEEP)
ms = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ms)


class _Sweep:
    """Just enough of the Sweep object for _backup/_restore."""
    def __init__(self, root):
        self.root = root


class RestoreGuardCase(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="restore-guard-"))
        self.target = self.tmp / "subject.sh"
        self.target.write_text("echo original\n")
        self.orig = ms.sha(self.target.read_bytes())
        self.sw = _Sweep(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _backup(self):
        return ms.Sweep._backup(self.sw, self.target)

    def test_a_normal_restore_still_works(self):
        """The guard must not break the ordinary path, or the sweep cannot run."""
        bpath = self._backup()
        mutant = "echo mutated\n"
        self.target.write_text(mutant)
        ms.Sweep._restore(self.sw, self.target, bpath, self.orig,
                          ms.sha(mutant.encode()))
        self.assertEqual(self.target.read_text(), "echo original\n")

    def test_a_concurrent_edit_is_not_overwritten(self):
        """The blocker. Somebody saved the file while we held it mutated."""
        bpath = self._backup()
        mutant = "echo mutated\n"
        self.target.write_text(mutant)
        mutant_sha = ms.sha(mutant.encode())
        # A human saves their own work over our mutant.
        self.target.write_text("echo THEIR IMPORTANT WORK\n")

        with self.assertRaises(SystemExit) as caught:
            ms.Sweep._restore(self.sw, self.target, bpath, self.orig, mutant_sha)

        self.assertIn("somebody else wrote it", str(caught.exception))
        self.assertEqual(self.target.read_text(), "echo THEIR IMPORTANT WORK\n",
                         "the concurrent edit was destroyed")

    def test_the_pre_mutation_copy_is_kept_for_reconciliation(self):
        """Refusing is only half of it: the original has to survive somewhere."""
        bpath = self._backup()
        mutant = "echo mutated\n"
        self.target.write_text(mutant)
        mutant_sha = ms.sha(mutant.encode())
        self.target.write_text("echo THEIRS\n")
        with self.assertRaises(SystemExit) as caught:
            ms.Sweep._restore(self.sw, self.target, bpath, self.orig, mutant_sha)
        kept = Path(str(bpath) + ".unrestored")
        self.assertTrue(kept.is_file() or Path(bpath).is_file(),
                        "the pre-mutation copy was not preserved")
        self.assertIn(".unrestored", str(caught.exception))

    def test_an_unknown_mutant_sha_refuses_rather_than_permits(self):
        """None means "we do not know what we wrote". An unknown must not read
        as permission to overwrite."""
        bpath = self._backup()
        self.target.write_text("echo SOMETHING ELSE\n")
        with self.assertRaises(SystemExit):
            ms.Sweep._restore(self.sw, self.target, bpath, self.orig, None)
        self.assertEqual(self.target.read_text(), "echo SOMETHING ELSE\n")

    def test_an_already_restored_file_is_accepted(self):
        """Another path may have restored it. That is not a stranger's edit."""
        bpath = self._backup()
        # Content is already the original.
        ms.Sweep._restore(self.sw, self.target, bpath, self.orig,
                          ms.sha(b"never written"))
        self.assertEqual(self.target.read_text(), "echo original\n")


class EmergencyRestoreCase(unittest.TestCase):
    """PR #272 blocker, round 2. The signal/atexit path bypassed the guard, so a
    kill mid-run permanently overwrote whatever a person had saved. The
    emergency path is where destroying work is LEAST forgivable, not most."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="emergency-"))
        self.target = self.tmp / "subject.sh"
        self.target.write_text("echo original\n")
        self.sw = _Sweep(self.tmp)
        ms._PENDING.clear()

    def tearDown(self):
        ms._PENDING.clear()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_mutant_is_restored_on_emergency_exit(self):
        """The whole point of the handler: a mutant must not outlive the run."""
        ms.Sweep._backup(self.sw, self.target)
        mutant = "echo mutated\n"
        self.target.write_text(mutant)
        ms._note_wrote(self.target, ms.sha(mutant.encode()))
        ms._restore_all()
        self.assertEqual(self.target.read_text(), "echo original\n")

    def test_a_concurrent_edit_survives_emergency_exit(self):
        """The blocker itself."""
        ms.Sweep._backup(self.sw, self.target)
        mutant = "echo mutated\n"
        self.target.write_text(mutant)
        ms._note_wrote(self.target, ms.sha(mutant.encode()))
        self.target.write_text("echo THEIR WORK\n")
        ms._restore_all()
        self.assertEqual(self.target.read_text(), "echo THEIR WORK\n",
                         "the emergency path destroyed a concurrent edit")

    def test_a_deleted_file_is_restored_on_emergency_exit(self):
        ms.Sweep._backup(self.sw, self.target)
        self.target.unlink()
        ms._restore_all()
        self.assertEqual(self.target.read_text(), "echo original\n")


if __name__ == "__main__":
    unittest.main(verbosity=2)
