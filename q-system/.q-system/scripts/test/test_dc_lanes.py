#!/usr/bin/env python3
"""dc-20: lanes. A deck, brand sheet or motion piece is not measured against a web bar.

WHY. The chain measured every round as a web page: the standard, gap, impeccable and tripwire
producers are web-only, and the tripwire refuses any page with no interactive element, which is every
deck. A non-site lane skips those four stages and records each as {exit: null, not_applicable:
"lane: <lane>"}, never as a pass (Sana 2026-09-19).

WHO SAYS WHICH LANE (Sana, after the adversarial review): the lane is where the round lives, in the
INSTANCE config, never the round's word. The first design put it in the round's manifest, and a
builder whose landing page failed the standard wrote {"lane": "deck"} and sealed it. Now
design-chain.json `lanes` maps a lane to its rounds folder; the site rounds folder (rounds_dir, or
the exemplars folder's parent) is always site, and so is any round the map does not name. A manifest
`lane` is optional and refuses when it disagrees. A non-site lane needs exactly one design-chain.json
above the round, and its receipt binds the config's bytes.

Runs the gate COPY beside the stub producers, as test_design_chain_gate.py does (its Base).
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import test_design_chain_gate as dcg  # noqa: E402  (module setup copies the gate beside the stubs)


class Lanes(dcg.Base):
    def cfg(self, **over):
        p = self.inst / "design-chain.json"
        c = json.loads(p.read_text())
        c.update(over)
        p.write_text(json.dumps(c))

    def lane(self, lane):
        """Make this round's folder (site/design) the given lane's rounds folder in the instance config."""
        if lane == "site":
            self.cfg(rounds_dir=None, lanes={})
        else:
            self.cfg(rounds_dir="site/pages", lanes={lane: "site/design"})

    def manifest_lane(self, lane):
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

    def test_the_rounds_own_word_is_not_a_lane(self):
        # adv-1: the builder's manifest cannot make a site round a deck
        self.complete_chain()
        self.manifest_lane("deck")
        rc, out = self.seal()
        self.assertEqual(rc, 2, out)
        self.assertIn("lane", out)

    def test_a_manifest_lane_that_agrees_with_the_location_seals(self):
        self.complete_chain()
        (self.round / "standard.json").unlink()
        self.lane("deck")
        self.manifest_lane("deck")
        self.assertEqual(self.seal()[0], 0)

    def test_a_config_that_names_the_site_lane_or_overlaps_refuses(self):
        self.complete_chain()
        self.cfg(lanes={"site": "site/design"})
        self.assertEqual(self.seal()[0], 2)
        self.cfg(lanes={"site": "site/elsewhere"})       # the site lane is never named, wherever it points
        self.assertEqual(self.seal()[0], 2)
        self.cfg(lanes={"deck": "site/design"})           # the site rounds folder itself
        self.assertEqual(self.seal()[0], 2)
        self.cfg(rounds_dir="site/pages", lanes={"deck": "site/design", "brand": "site/design"})
        self.assertEqual(self.seal()[0], 2)

    def test_a_config_written_beside_the_round_does_not_make_a_lane(self):
        # Sana: find_config takes the nearest config; a second one cannot claim a lane
        self.complete_chain()
        (self.round / "standard.json").unlink()
        near = json.loads((self.inst / "design-chain.json").read_text())
        near["lanes"] = {"deck": "."}                    # beside the round, claiming its folder as deck
        near["rounds_dir"] = "../pages"
        (self.round.parent / "design-chain.json").write_text(json.dumps(near))
        rc, out = self.seal()
        self.assertEqual(rc, 2, out)
        self.assertIn("two design-chain.json files above", out)

    def test_a_config_edit_after_a_deck_seal_opens_the_round(self):
        self.complete_chain()
        (self.round / "standard.json").unlink()
        self.lane("deck")
        self.assertEqual(self.seal()[0], 0)
        self.cfg(note="changed")
        self.assertEqual(self.status()[0], 2)

    def test_a_deck_with_the_craft_web_checks_on_seals_without_their_files(self):
        # adv-5: gap and impeccable are web-only, so their files are not a deck's to produce
        self.complete_chain()
        (self.round / "standard.json").unlink()
        self.lane("deck")
        self.cfg(craft={"tier": "craft", "require_gap_check": True, "require_impeccable": True})
        rc, out = self.seal()
        self.assertEqual(rc, 0, out)
        stages = {r["stage"]: r for r in self.receipt()["__assets__"] and self.receipt()[self.page.name]["stages"]}
        self.assertEqual(stages["gap"]["not_applicable"], "lane: deck")
        self.assertEqual(stages["impeccable"]["not_applicable"], "lane: deck")

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


class RealGateLaneRules(unittest.TestCase):
    """The lane rules at the gate's tracked path, not the copy beside the stubs."""

    @classmethod
    def setUpClass(cls):
        import importlib.util
        spec = importlib.util.spec_from_file_location("dc20_real_gate", Path(dcg.REAL_GATE))
        cls.gate = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.gate)

    def setUp(self):
        import shutil
        import tempfile
        self.tmp = Path(tempfile.mkdtemp(prefix="dc20-real-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (self.tmp / "decks" / "r1").mkdir(parents=True)
        (self.tmp / "site" / "design" / "r2").mkdir(parents=True)

    def lane_of(self, rd, cfg):
        (self.tmp / "design-chain.json").write_text(json.dumps(cfg))
        return self.gate.round_lane(self.tmp / rd)

    def test_the_lane_comes_from_where_the_round_lives(self):
        cfg = {"owners": [], "lanes": {"deck": "decks"}}
        self.assertEqual(self.lane_of("decks/r1", cfg), ("deck", None))
        self.assertEqual(self.lane_of("site/design/r2", cfg), ("site", None))
        self.assertEqual(self.lane_of("decks/r1", {"owners": []}), ("site", None))

    def test_a_not_applicable_row_is_believed_only_for_its_non_site_lane(self):
        row = self.gate.na_record("gap", "brand")
        self.assertTrue(self.gate._believed_na(row, "brand"))
        self.assertFalse(self.gate._believed_na(row, "site"))
        self.assertFalse(self.gate._believed_na(row, "deck"))
        self.assertFalse(self.gate._believed_na(self.gate.na_record("readers", "brand"), "brand"))


if __name__ == "__main__":
    unittest.main()
