#!/usr/bin/env python3
"""dc-15: a malformed exemplars.json refuses, and exemplar citation has a floor.

WHY. A roster that did not parse read as `named = []`, so a broken exemplars.json silently turned
the whole-set check off (RCA 2026-09-18, C8). And directions.md passed by citing ONE exemplar of
any number. Now a roster that cannot be read refuses, and directions.md cites at least
`exemplar_floor` exemplars (default: all of them, up to 3).
"""
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
GATE = HERE.parent / "design-chain-gate.py"


def load_gate():
    spec = importlib.util.spec_from_file_location("dc15_gate", GATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Exemplars(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="dc15-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.inst = self.tmp / "inst"
        self.ex = self.inst / "design" / "exemplars"
        self.ex.mkdir(parents=True)
        self.cfg = {"project": "dc15", "owners": []}
        self.cfg_path = self.inst / "design-chain.json"
        self.rd = self.inst / "site" / "design" / "r1"
        self.rd.mkdir(parents=True)
        self.page = self.rd / "Home-laptop.html"
        self.page.write_text("<html><body><p>x</p></body></html>")

    def write_cfg(self):
        self.cfg_path.write_text(json.dumps(self.cfg))

    def exemplars(self, *names):
        for n in names:
            (self.ex / n).write_text("shot")

    def direction_probs(self, text):
        self.write_cfg()
        (self.rd / "directions.md").write_text(text)
        return [p for p in load_gate().chain_problems(self.page, honor_seal=False) if "exemplar" in p]

    # -- floor
    def test_citing_one_of_three_refuses_by_default(self):
        self.exemplars("stripe.png", "linear.png", "figma.png")
        probs = self.direction_probs("# A\nfrom stripe.png\n# B\n# C\n")
        self.assertTrue(any("linear.png" in p and "figma.png" in p for p in probs), probs)

    def test_citing_all_three_passes(self):
        self.exemplars("stripe.png", "linear.png", "figma.png")
        self.assertEqual(self.direction_probs("# A\nstripe.png linear.png\n# B\nfigma.png\n# C\n"), [])

    def test_the_default_floor_stops_at_three(self):
        self.exemplars("a1.png", "a2.png", "a3.png", "a4.png", "a5.png")
        self.assertEqual(self.direction_probs("# A\na1.png a2.png a3.png\n# B\n# C\n"), [])

    def test_a_configured_floor_is_honoured(self):
        self.exemplars("stripe.png", "linear.png", "figma.png")
        self.cfg["exemplar_floor"] = 1
        self.assertEqual(self.direction_probs("# A\nstripe.png\n# B\n# C\n"), [])

    def test_a_floor_that_is_not_a_positive_integer_refuses(self):
        self.exemplars("stripe.png")
        self.cfg["exemplar_floor"] = "two"
        probs = self.direction_probs("# A\nstripe.png\n# B\n# C\n")
        self.assertTrue(any("exemplar_floor" in p for p in probs), probs)

    def test_a_longer_name_is_not_the_exemplar(self):
        # the dc-13 substring class: "a.png" is not cited by "data.png"
        self.exemplars("a.png")
        probs = self.direction_probs("# A\ndata.png\n# B\n# C\n")
        self.assertTrue(any("a.png" in p for p in probs), probs)

    def test_hidden_files_are_not_exemplars(self):
        self.exemplars("stripe.png", ".DS_Store")
        self.assertEqual(self.direction_probs("# A\nstripe.png\n# B\n# C\n"), [])

    def test_an_empty_exemplars_dir_needs_no_citation(self):
        # std-1, adv-4: no exemplars, no floor; the message must not blame an unset config key
        self.assertEqual(self.direction_probs("# A\n# B\n# C\n"), [])
        (self.ex / ".DS_Store").write_text("x")
        self.assertEqual(self.direction_probs("# A\n# B\n# C\n"), [])

    def test_hidden_or_nested_exemplars_still_count(self):
        # adv-3: hiding or nesting exemplars must not lower the default floor
        self.exemplars("a.png", ".b.png")
        (self.ex / "set").mkdir()
        (self.ex / "set" / "c.png").write_text("shot")
        probs = self.direction_probs("# A\na.png\n# B\n# C\n")
        self.assertTrue(any(".b.png" in p and "c.png" in p for p in probs), probs)

    def test_a_name_at_the_end_of_a_sentence_is_cited(self):
        # adv-5
        self.exemplars("a.png", "b.png")
        self.assertEqual(self.direction_probs("# A\nBuilt from a.png and b.png.\n# B\n# C\n"), [])

    # -- roster
    def roster_probs(self, roster_text):
        (self.inst / "design" / "teardown.md").write_text("stripe.com is dense\n")
        (self.inst / "design" / "exemplars.json").write_text(roster_text)
        (self.rd / "craft-manifest.json").write_text(json.dumps({"techniques": []}))
        self.cfg["craft"] = {"require_grounding": "design/teardown.md"}
        self.write_cfg()
        return [p for p in load_gate().craft_problems(self.rd, self.page, self.cfg, self.cfg_path)
                if "exemplars.json" in p]

    def test_a_roster_that_does_not_parse_refuses(self):
        # RED FIRST: `except ValueError: named = []` turned the whole-set check off
        probs = self.roster_probs("{not json")
        self.assertTrue(any("cannot be read" in p for p in probs), probs)

    def test_a_roster_of_the_wrong_shape_refuses(self):
        probs = self.roster_probs(json.dumps(["https://stripe.com"]))
        self.assertTrue(any("cannot be read" in p for p in probs), probs)

    def test_a_roster_missing_its_list_or_urls_refuses(self):
        # std-2, adv-1
        for bad in ({}, {"exemplar": [{"url": "https://stripe.com"}]}, {"exemplars": {}},
                    {"exemplars": [{"href": "https://stripe.com"}]}, {"exemplars": [{"url": ""}]}):
            probs = self.roster_probs(json.dumps(bad))
            self.assertTrue(any("cannot be read" in p for p in probs), (bad, probs))

    def test_a_roster_that_is_not_a_file_refuses(self):
        # adv-2
        (self.inst / "design").mkdir(parents=True, exist_ok=True)
        (self.inst / "design" / "exemplars.json").mkdir()
        (self.inst / "design" / "teardown.md").write_text("stripe.com\n")
        (self.rd / "craft-manifest.json").write_text(json.dumps({"techniques": []}))
        self.cfg["craft"] = {"require_grounding": "design/teardown.md"}
        self.write_cfg()
        probs = [p for p in load_gate().craft_problems(self.rd, self.page, self.cfg, self.cfg_path)
                 if "exemplars.json" in p]
        self.assertTrue(any("cannot be read" in p for p in probs), probs)

    def test_an_empty_roster_is_a_roster(self):
        self.assertEqual(self.roster_probs(json.dumps({"exemplars": []})), [])

    def test_a_good_roster_still_checks_the_whole_set(self):
        probs = self.roster_probs(json.dumps({"exemplars": [{"url": "https://stripe.com"},
                                                            {"url": "https://linear.app"}]}))
        self.assertTrue(any("linear.app" in p for p in probs), probs)
        self.assertFalse(any("cannot be read" in p for p in probs), probs)


if __name__ == "__main__":
    unittest.main()
