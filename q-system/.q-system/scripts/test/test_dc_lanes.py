#!/usr/bin/env python3
"""dc-20: lanes. A deck, brand sheet or motion piece is not measured against a web bar.

WHY. The chain measured every round as a web page: the standard, gap, impeccable and tripwire
producers are web-only, and the tripwire refuses any page with no interactive element, which is every
deck. Sana 2026-09-19: craft-manifest.json declares lane in {site, brand, deck, motion} (default and
unknown: site). A non-site lane skips those four stages and records each as
{exit: null, not_applicable: "lane: <lane>"}, never as a pass. The receipt believes such a row only
when the digest-bound manifest names that non-site lane and the stage is web-only. The page is still
HTML in every lane, so the readers still read it. The receipt carries __lane__ for audit.

Runs the gate COPY beside the stub producers, as test_design_chain_gate.py does (its Base).
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import test_design_chain_gate as dcg  # noqa: E402  (module setup copies the gate beside the stubs)


class Lanes(dcg.Base):
    def lane(self, lane):
        (self.round / "craft-manifest.json").write_text(json.dumps({"lane": lane}))

    def seal(self):
        return dcg.run(["seal", str(self.round)], env=self.env)

    def status(self):
        return dcg.run(["status-page", str(self.page)], env=self.env)

    def receipt(self):
        return json.loads((self.round / "receipts.json").read_text())

    def standard_row(self):
        return next(r for r in self.receipt()[self.page.name]["stages"] if r["stage"] == "standard")

    def test_a_site_round_runs_the_standard(self):
        self.complete_chain()
        rc, out = self.seal()
        self.assertEqual(rc, 0, out)
        row = self.standard_row()
        self.assertEqual(row["exit"], 0)
        self.assertNotIn("not_applicable", row)
        self.assertEqual(self.receipt()["__lane__"], "site")
        self.assertEqual(self.status()[0], 0)

    def test_a_deck_round_records_the_standard_as_not_applicable(self):
        self.complete_chain()
        (self.round / "standard.json").unlink()
        self.lane("deck")
        rc, out = self.seal()
        self.assertEqual(rc, 0, out)
        self.assertNotIn("stage standard", out)            # the producer did not run
        row = self.standard_row()
        self.assertIsNone(row["exit"])
        self.assertEqual(row["not_applicable"], "lane: deck")
        self.assertEqual(self.receipt()["__lane__"], "deck")
        rc, out = self.status()
        self.assertEqual(rc, 0, out)

    def test_an_unknown_lane_is_a_site(self):
        self.complete_chain()
        self.lane("video")
        rc, out = self.seal()
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.standard_row()["exit"], 0)

    def test_flipping_the_lane_after_the_seal_opens_the_round(self):
        self.complete_chain()
        self.lane("deck")
        self.assertEqual(self.seal()[0], 0)
        self.lane("site")
        self.assertEqual(self.status()[0], 2)

    def edit_receipt(self, fn):
        rec = self.receipt()
        fn(rec)
        (self.round / "receipts.json").write_text(json.dumps(rec))

    def test_a_not_applicable_row_in_a_site_receipt_opens_the_round(self):
        self.complete_chain()
        self.assertEqual(self.seal()[0], 0)

        def na(rec):
            for r in rec[self.page.name]["stages"]:
                if r["stage"] == "standard":
                    r.update(path="", sha256="", exit=None, not_applicable="lane: deck")
        self.edit_receipt(na)
        rc, out = self.status()
        self.assertEqual(rc, 2, out)

    def test_a_not_applicable_row_for_a_stage_that_is_not_web_only_opens_the_round(self):
        self.complete_chain()
        self.lane("deck")
        self.assertEqual(self.seal()[0], 0)

        def extra(rec):
            rec[self.page.name]["stages"].append({"stage": "readers", "path": "", "sha256": "", "exit": None,
                                                  "not_applicable": "lane: deck"})
        self.edit_receipt(extra)
        self.assertEqual(self.status()[0], 2)

    def test_a_site_row_called_not_applicable_for_the_site_lane_opens_the_round(self):
        # the site lane skips nothing, whatever the row's label says
        self.complete_chain()
        self.assertEqual(self.seal()[0], 0)

        def na(rec):
            for r in rec[self.page.name]["stages"]:
                if r["stage"] == "standard":
                    r.update(path="", sha256="", exit=None, not_applicable="lane: site")
        self.edit_receipt(na)
        self.assertEqual(self.status()[0], 2)

    def test_a_not_applicable_row_naming_another_lane_opens_the_round(self):
        self.complete_chain()
        self.lane("deck")
        self.assertEqual(self.seal()[0], 0)

        def relabel(rec):
            for r in rec[self.page.name]["stages"]:
                if r["stage"] == "standard":
                    r["not_applicable"] = "lane: brand"
        self.edit_receipt(relabel)
        self.assertEqual(self.status()[0], 2)

    def test_a_receipt_lane_that_disagrees_with_the_manifest_opens_the_round(self):
        self.complete_chain()
        self.lane("deck")
        self.assertEqual(self.seal()[0], 0)
        self.edit_receipt(lambda rec: rec.update(__lane__="brand"))
        self.assertEqual(self.status()[0], 2)


if __name__ == "__main__":
    unittest.main()
