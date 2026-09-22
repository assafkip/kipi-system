#!/usr/bin/env python3
"""ASK-1840: seal counts a page's reader runs over every version of its bytes, caps them per round,
and writes the count into the receipt.

WHY. dc-08 made reader rows append-only and read every run on the page's CURRENT bytes. So after a
LEAVE run, one newline made those rows about other bytes, and re-running until the readers said STAY
sealed (dc-08 adversarial review, adv-2, reproduced with the real reader gate and a real seal).

The REAL reader gate (injected runner) writes every row; the REAL gate seals with real producers.
Cross-round and cross-commit re-rolls are ASK-1834's (CI recompute), not tested here.
"""
import json
import unittest

from test_dc_reader_runs import Runs
from test_dc_reader_verdicts import PAGE, answers


class Rerolls(Runs):
    LEAVE = [answers("LEAVE", "ops consulting")] * 3

    def edit(self, n):
        (self.rd / "Home-laptop.html").write_text(PAGE + "\n" * n)

    def test_a_reroll_after_a_one_byte_edit_is_on_the_receipt(self):
        self.read_page(*self.LEAVE)
        self.edit(1)
        self.read_page(*self.STAY)
        rc, out = self.seal()
        self.assertEqual(rc, 0, out)
        rec = json.loads((self.rd / "receipts.json").read_text())
        self.assertEqual(rec["Home-laptop.html"]["readers"], {"runs": 2, "leave_runs": 1, "reader_runs_max": 3})

    def test_rerolls_past_the_cap_refuse(self):
        self.config(reader_runs_max=1)
        self.read_page(*self.LEAVE)
        self.edit(1)
        self.read_page(*self.STAY)
        rc, out = self.seal()
        self.assertEqual(rc, 2, out)
        self.assertIn("Home-laptop.html has had 2 reader runs in this round (1 with a LEAVE), over "
                      "readers.reader_runs_max 1", out)

    def test_the_default_cap_is_three(self):
        for k in range(4):
            self.edit(k)
            self.read_page(*self.LEAVE if k < 3 else self.STAY)
        rc, out = self.seal()
        self.assertEqual(rc, 2, out)
        self.assertIn("has had 4 reader runs in this round (3 with a LEAVE), over readers.reader_runs_max 3", out)

    def test_renaming_the_page_does_not_reset_its_history(self):
        # ASK-1840 adv-1: the count keyed on the page name, so a rename started it over
        self.config(reader_runs_max=1)
        self.read_page(*self.LEAVE)
        (self.rd / "Home-laptop.html").rename(self.rd / "Home2-laptop.html")
        (self.rd / "proof.md").write_text("Home2-laptop.html: proof\n")
        self.read_page(*self.STAY)
        rc, out = self.seal()
        self.assertEqual(rc, 2, out)
        self.assertIn("holds reader rows for ['Home-laptop.html'], which this round no longer holds", out)

    def test_raising_the_cap_after_the_runs_refuses(self):
        # ASK-1840 adv-2: the cap was read live and never recorded
        self.config(reader_runs_max=1)
        self.read_page(*self.LEAVE)
        self.edit(1)
        self.read_page(*self.STAY)
        self.config(reader_runs_max=50)
        rc, out = self.seal()
        self.assertEqual(rc, 2, out)
        self.assertIn("readers is weaker than the config run", out)

    def test_rows_with_no_run_id_from_one_invocation_are_one_run(self):
        # ASK-1840 std-2: one old n=5 invocation counted as five runs
        self.config(n=5)
        self.read_page(*[answers("STAY", "ops consulting")] * 5)
        rows = self.rows()
        for r in rows:
            del r["_provenance"]["run_id"]
        (self.rd / "gate" / "reader-runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
        rc, out = self.seal()
        self.assertEqual(rc, 2, out)
        self.assertNotIn("reader runs in this round", out)
        self.assertIn("carries no run id", out)

    def test_the_cap_message_names_a_remedy_that_works(self):
        # ASK-1840 std-1: it named editing the page and a FOUNDER line, neither of which lowers the count
        self.config(reader_runs_max=1)
        self.read_page(*self.LEAVE)
        self.edit(1)
        self.read_page(*self.STAY)
        rc, out = self.seal()
        self.assertIn("Start a new round for this page", out)
        self.assertNotIn("FOUNDER line", out)

    def test_other_pages_runs_are_not_this_page_s(self):
        (self.rd / "About-laptop.html").write_text(PAGE.replace("Two records", "About the work"))
        (self.rd / "proof.md").write_text("Home-laptop.html: proof\nAbout-laptop.html: proof\n")
        self.config(reader_runs_max=1)
        self.read_page(*self.STAY, page="Home-laptop.html")
        self.read_page(*self.STAY, page="About-laptop.html")
        rc, out = self.seal()
        self.assertEqual(rc, 0, out)

    def test_a_cap_that_is_not_a_whole_number_refuses(self):
        self.config(reader_runs_max="3")
        rc, out = self.seal()
        self.assertEqual(rc, 2, out)
        self.assertIn("readers.reader_runs_max", out)


if __name__ == "__main__":
    unittest.main()
