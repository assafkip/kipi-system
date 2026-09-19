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
        self.assertEqual(rec["Home-laptop.html"]["readers"], {"runs": 2, "leave_runs": 1})

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
