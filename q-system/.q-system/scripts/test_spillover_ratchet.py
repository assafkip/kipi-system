#!/usr/bin/env python3
"""Tests for spillover-ratchet.py (ASK-343).

Two properties decide whether this hook is worth having at all:

  1. It must EXIT 2. The hook contract is exit 2 = stderr fed to Claude,
     exit 0 = pass. The first version of this file exited 0, so it wrote to a
     stderr nobody read -- inert on arrival, the same defect the ledger had.
  2. It must not cry wolf. A ratchet that fires on README.md gets switched off,
     and a switched-off gate protects nothing.

Temp ledgers only, never the live one.
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "spillover-ratchet.py"
spec = importlib.util.spec_from_file_location("sr", SCRIPT)
sr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sr)

ROWS = [
    {"id": "sp-aaa", "status": "open", "severity": "minor", "source": "s",
     "description": "capability-gate.py reports a timeout as RED"},
    {"id": "sp-bbb", "status": "open", "severity": "major", "source": "s",
     "description": "capability-gate.py has a second, blocking problem"},
    {"id": "sp-ccc", "status": "resolved", "severity": "minor", "source": "s",
     "description": "capability-gate.py had a third, already handled"},
    {"id": "sp-ddd", "status": "open", "severity": "minor", "source": "s",
     "description": "see the README for the full context of this unrelated note"},
]


class MatchTest(unittest.TestCase):
    def rows(self):
        return [r for r in ROWS
                if r["status"] == "open" and r["severity"] == "minor"]

    def test_matches_the_named_file(self):
        hits = sr.findings_for("q-system/.q-system/scripts/capability-gate.py", self.rows())
        self.assertEqual([h["id"] for h in hits], ["sp-aaa"])

    def test_matches_on_basename_not_full_path(self):
        """A finding written from another checkout names the file, not your path."""
        hits = sr.findings_for("/somewhere/else/entirely/capability-gate.py", self.rows())
        self.assertEqual([h["id"] for h in hits], ["sp-aaa"])

    def test_generic_stem_does_not_cry_wolf(self):
        """README appears in unrelated prose everywhere. Firing on it is how a
        ratchet gets switched off."""
        self.assertEqual(sr.findings_for("README.md", self.rows()), [])

    def test_partial_name_does_not_match(self):
        """gate.py must not match capability-gate.py."""
        self.assertEqual(sr.findings_for("gate.py", self.rows()), [])

    def test_blocking_severities_are_not_delivered_here(self):
        """major/blocker go through `gates run`, not the ratchet. Delivering them
        twice trains people to dismiss both."""
        rows = sr.ledger_rows(Path("/nonexistent"))
        self.assertEqual(rows, [])
        self.assertNotIn("sp-bbb", [h["id"] for h in
                                    sr.findings_for("capability-gate.py", self.rows())])

    def test_resolved_findings_are_not_delivered(self):
        self.assertNotIn("sp-ccc", [h["id"] for h in
                                    sr.findings_for("capability-gate.py", self.rows())])


class ExitCodeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / ".prd-os").mkdir(parents=True)
        (self.root / ".prd-os" / "spillover.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in ROWS))
        (self.root / "capability-gate.py").write_text("# x\n")
        subprocess.run(["git", "init", "-q"], cwd=self.root, capture_output=True)
        self.home = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()
        self.home.cleanup()

    def run_hook(self, target, day="d1"):
        env = dict(os.environ, HOME=self.home.name, KIPI_RATCHET_DATE=day)
        return subprocess.run([sys.executable, str(SCRIPT), str(target)],
                              capture_output=True, text=True, env=env, cwd=self.root)

    # --- THE PROPERTY THAT MAKES IT NOT INERT ------------------------------
    def test_exits_2_so_the_agent_actually_sees_it(self):
        r = self.run_hook(self.root / "capability-gate.py")
        self.assertEqual(r.returncode, 2,
                         "exit 0 means stderr is discarded and the hook is inert")
        self.assertIn("sp-aaa", r.stderr)

    def test_asks_for_triage_not_a_fix(self):
        """Fixing an adjacent bug mid-task is scope creep, which the repo rules
        forbid. The ask has to be 'is this still true'."""
        r = self.run_hook(self.root / "capability-gate.py")
        self.assertIn("DO NOT fix", r.stderr)
        self.assertIn("STILL TRUE", r.stderr)

    def test_fires_once_per_file_per_day(self):
        first = self.run_hook(self.root / "capability-gate.py", day="d1")
        second = self.run_hook(self.root / "capability-gate.py", day="d1")
        self.assertEqual(first.returncode, 2)
        self.assertEqual(second.returncode, 0, "a second edit must not re-interrupt")

    def test_a_new_day_re_asks(self):
        self.run_hook(self.root / "capability-gate.py", day="d1")
        third = self.run_hook(self.root / "capability-gate.py", day="d2")
        self.assertEqual(third.returncode, 2, "a deferred note should come back")

    def test_file_with_no_notes_is_silent(self):
        (self.root / "quiet_file.py").write_text("# x\n")
        r = self.run_hook(self.root / "quiet_file.py")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stderr.strip(), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
