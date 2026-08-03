#!/usr/bin/env python3
"""Reproducer + regression suite for the spillover anchor bar (ASK-336).

Pairs with PRD prd-finding-quality-bar-2026-08-03.

why (measured 2026-08-03): `spillover add` accepted any string as --desc. The
kipi-system ledger reached 476 open findings at ~50/day, 82 of which named no
file, no test and no command. An unverifiable finding cannot be acted on by
anyone, including its author, so it is indistinguishable from noise.

The bar: a capture must carry at least ONE verifiable anchor. The escape hatch
(--force) is deliberate and countable, matching linear-issue-ref-check.py's
`[no-issue: reason]` shape -- a bar with no hatch gets deleted the first time it
blocks real work, and a silent hatch is the same as no bar.

Runs against a TEMP repo root, never the live ledger (fable-discipline: a test
that touches a live data path is blocked by fable-discipline-lint).
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RUNNER = Path(__file__).resolve().parent / "prd_runner.py"


class AnchorBarTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / ".prd-os").mkdir(parents=True)
        # A real prd-os repo, or the runner refuses on config before it ever
        # reaches the bar -- which would make the refusal tests pass for the
        # wrong reason. Caught on the first reproducer run 2026-08-03.
        (self.root / ".prd-os" / "config.json").write_text(json.dumps(
            {"config_schema_version": 1, "issues_dir": ".prd-os/issues",
             "findings_dir": ".prd-os/findings"}))
        # a real file inside the temp repo, for the positive case
        self.real = self.root / "realscript.py"
        self.real.write_text("# a real file\n")

    def tearDown(self):
        self.tmp.cleanup()

    def add(self, *extra, desc, source="test-src"):
        return subprocess.run(
            [sys.executable, str(RUNNER), "--repo-root", str(self.root),
             "spillover", "add", "--source", source, "--desc", desc, *extra],
            capture_output=True, text=True, cwd=str(self.root))

    def rows(self):
        p = self.root / ".prd-os" / "spillover.jsonl"
        if not p.is_file():
            return []
        return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]

    # --- the reproducer -----------------------------------------------------
    def test_anchorless_capture_is_refused(self):
        """The exact shape that produced 82 dead rows."""
        r = self.add(desc="we should also look at the retry path")
        self.assertNotEqual(r.returncode, 0,
                            "an anchorless capture must be refused")
        self.assertEqual(self.rows(), [], "nothing may be written on refusal")

    def test_refusal_names_the_missing_anchor(self):
        r = self.add(desc="we should also look at the retry path")
        msg = (r.stderr + r.stdout).lower()
        self.assertIn("anchor", msg)
        # it must TEACH the fix, not just say no
        self.assertTrue(any(w in msg for w in ("file", "command", "test")),
                        f"refusal must name what would satisfy it, got: {msg!r}")

    # --- the positive case --------------------------------------------------
    def test_capture_naming_a_real_file_succeeds(self):
        r = self.add(desc=f"realscript.py drops the retry counter on reentry")
        self.assertEqual(r.returncode, 0, r.stderr)
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].get("anchor"), "file")

    def test_capture_naming_a_test_symbol_succeeds(self):
        """A bare test SYMBOL is greppable, so it anchors without resolving as
        a path. A token carrying a file EXTENSION is a path claim and must
        resolve -- otherwise 'test_anything.py' becomes a universal bypass."""
        r = self.add(desc="test_forced_rows_are_countable fails on the reentry case")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.rows()[0].get("anchor"), "test")

    def test_capture_with_command_output_succeeds(self):
        r = self.add(desc="ran `pytest -q` and got: 3 failed, 0 passed")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.rows()[0].get("anchor"), "command")

    # --- THE NEGATIVE SELF-TEST --------------------------------------------
    def test_named_file_that_does_not_exist_is_refused(self):
        """Proves the check reads the filesystem, not the string shape.

        Without this, `anchor.py` in any sentence would satisfy the bar and the
        gate would be a spell-checker for filenames.
        """
        r = self.add(desc="totally_imaginary_module.py leaks a handle on close")
        self.assertNotEqual(r.returncode, 0,
                            "a path that does not resolve is not an anchor")
        self.assertEqual(self.rows(), [])

    # --- the hatch ----------------------------------------------------------
    def test_force_records_anchor_none(self):
        r = self.add("--force", desc="we should also look at the retry path")
        self.assertEqual(r.returncode, 0, r.stderr)
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].get("anchor"), "none",
                         "a forced row must be countable, not indistinguishable")

    def test_forced_rows_are_countable(self):
        self.add("--force", desc="one vague thing")
        self.add("--force", desc="another vague thing")
        self.add(desc="realscript.py has a real defect")
        forced = [r for r in self.rows() if r.get("anchor") == "none"]
        self.assertEqual(len(forced), 2)

    # --- the auto-capture path must not break ------------------------------
    def test_explicit_id_defer_row_still_writes(self):
        """findings_writer auto-creates defer-* rows carrying a finding id but
        often no file. Those must keep working, or deferring a review finding
        starts failing and the deferral silently vanishes -- the exact leak the
        June 2026 spillover PRD existed to close."""
        r = self.add("--id", "defer-prd-x-finding-3", "--force",
                     desc="deferred finding finding-3: the ladder threshold is undefined")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.rows()[0]["id"], "defer-prd-x-finding-3")


if __name__ == "__main__":
    unittest.main(verbosity=2)
