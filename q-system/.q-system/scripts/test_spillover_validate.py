#!/usr/bin/env python3
"""Tests for spillover-validate.py (ASK-337).

The property under test is the one that makes a bulk void safe: a finding whose
subject still exists ANYWHERE in the fleet must never be proposed for deletion,
and a finding with no extractable subject must never be silently lumped in with
the confirmed-dead ones.

Runs against temp roots, never the live ledger.
"""
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "spillover-validate.py"
spec = importlib.util.spec_from_file_location("sv", SCRIPT)
sv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sv)


class ClassifyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "scripts").mkdir(parents=True)
        (self.root / "scripts" / "alive.py").write_text("# here\n")
        (self.root / "somedir" / "thing").mkdir(parents=True)
        subprocess.run(["git", "init", "-q"], cwd=self.root, capture_output=True)
        subprocess.run(["git", "add", "-A"], cwd=self.root, capture_output=True)
        self.roots = [self.root]
        self.index = {self.root: sv.tracked_index(self.root)}

    def tearDown(self):
        self.tmp.cleanup()

    def c(self, desc):
        return sv.classify(desc, self.roots, self.index)[0]

    def test_existing_path_is_still_exists(self):
        self.assertEqual(self.c("scripts/alive.py drops the retry counter"),
                         "still-exists")

    def test_bare_filename_of_tracked_file_is_still_exists(self):
        """Findings name 'alive.py', not a path from root. This is the case a
        single-root os.path.exists() check got wrong 209 times."""
        self.assertEqual(self.c("alive.py drops the retry counter"), "still-exists")

    def test_module_stem_is_still_exists(self):
        self.assertEqual(self.c("alive.load_sidecar raises AttributeError"),
                         "still-exists")

    def test_existing_directory_is_still_exists(self):
        self.assertEqual(self.c("somedir/thing is a symlink through a root-owned path"),
                         "still-exists")

    def test_missing_path_is_confirmed_gone(self):
        self.assertEqual(self.c("scripts/deleted_long_ago.py leaks a handle"),
                         "confirmed-gone")

    # --- THE NEGATIVE SELF-TEST --------------------------------------------
    def test_anchorless_text_is_unresolvable_not_gone(self):
        """The property that makes --apply safe.

        Measured 2026-08-03: the no-concrete-subject class is mostly REAL
        findings naming a component rather than a file. Collapsing it into
        confirmed-gone would delete ~100 live findings. Same defect class as
        ASK-327: an absent result is not a negative result.
        """
        b = self.c("we should also look at the retry path someday")
        self.assertEqual(b, "unresolvable")
        self.assertNotEqual(b, "confirmed-gone")

    def test_english_words_do_not_count_as_subjects(self):
        """Without the NOISE filter, 'this.thing' style prose marks everything
        still-exists and the validator proposes nothing, ever."""
        self.assertEqual(self.c("the process should never do that"), "unresolvable")


class DryRunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / ".prd-os").mkdir(parents=True)
        rows = [
            {"id": "sp-gone01", "source": "s", "status": "open",
             "description": "scripts/deleted_long_ago.py leaks a handle"},
            {"id": "sp-vague1", "source": "s", "status": "open",
             "description": "we should also look at this someday"},
        ]
        self.ledger = self.root / ".prd-os" / "spillover.jsonl"
        self.ledger.write_text("".join(json.dumps(r) + "\n" for r in rows))

    def tearDown(self):
        self.tmp.cleanup()

    def test_dry_run_writes_nothing(self):
        before = self.ledger.read_bytes()
        r = subprocess.run([sys.executable, str(SCRIPT), "--repo-root", str(self.root)],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.ledger.read_bytes(), before,
                         "a dry run must not touch the ledger")
        self.assertIn("DRY RUN", r.stdout)

    def test_vague_row_is_not_in_the_proposal(self):
        r = subprocess.run([sys.executable, str(SCRIPT), "--repo-root", str(self.root),
                            "--json"], capture_output=True, text=True)
        data = json.loads(r.stdout)
        gone_ids = [x["id"] for x in data["confirmed-gone"]]
        self.assertNotIn("sp-vague1", gone_ids)
        self.assertIn("sp-vague1", [x["id"] for x in data["unresolvable"]])


if __name__ == "__main__":
    unittest.main(verbosity=2)
