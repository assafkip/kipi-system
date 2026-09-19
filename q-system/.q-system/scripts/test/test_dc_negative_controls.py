#!/usr/bin/env python3
"""dc-21: the fixtures carry provenance, and the negative controls are permanent tests.

WHY. The chain was proven green on verdicts typed by hand, and the RCA's negative controls
(scratchpad negctl/run.py, 2026-09-18) lived in a scratch directory that nothing re-runs. A
control that is not a test is a control that stops existing. These run the REAL gate at its
tracked path with the real producers and a real browser (verify contract 2).

What each control pins, as measured on the gate at c1c2f83d (Sana's split, 2026-09-19):
  - round B (a page and nothing but a hand-written receipt) never reads COMPLETE;
  - control C (round A's records, with a page the real standard producer FAILS) refuses, so a
    green elsewhere is not a dead gate. The RCA's old C (A minus standard.json) is obsolete:
    seal writes standard.json itself since dc-02;
  - the bland control (no colour, no motion, four lines) sealed at the craft tier against the
    exemplar captures refuses on a design axis, not on a missing input.
Round A itself still seals today (nothing reads reader verdicts or check results): it is
dc-07's RED FIRST test, and A-checks is dc-11's.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import dc_fixtures  # noqa: E402

REAL_GATE = HERE.parent / "design-chain-gate.py"
PAGE_BLAND = ("<html><head><meta charset='utf-8'><style>body{font:18px/1.5 Georgia,serif;margin:40px}"
              "</style></head><body><h1>We help small firms</h1><p>We fix your data.</p>"
              "<p>We are careful.</p><p><a href='#'>Book a call</a></p></body></html>")
PAGE_TINY = ("<html><head><meta charset='utf-8'><style>body,p,a,h1{font-size:9px}</style></head>"
             "<body><h1>Hi</h1><p>Small print.</p><a href='#'>Book</a></body></html>")


class Round(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="dc21-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.inst = self.tmp / "inst"
        self.rd = self.inst / "site" / "design" / "r1"
        self.rd.mkdir(parents=True)

    def config(self, **extra):
        (self.inst / "design-chain.json").write_text(json.dumps({"project": "dc21", "owners": [], **extra}))

    def round_a_records(self):
        """Round A from the RCA: every reader leaves, the checks fail, proof and critique are empty."""
        rd = self.rd
        (rd / "brief.md").write_text("brief\n")
        (rd / "directions.md").write_text("# D1\n# D2\n# D3\n")
        (rd / "critique.md").write_text("".join(f"{i % 9 + 1}. yes\n" for i in range(27)))
        (rd / "proof.md").write_text("x\n")
        (rd / "checks").mkdir(exist_ok=True)
        (rd / "checks" / "tripwire.txt").write_text("FAIL: 4 AI-default tells found. exit=2\n")
        (rd / "checks" / "bio_gate.txt").write_text("BLOCKED: employer claim unsupported\n")
        (rd / "gate").mkdir(exist_ok=True)
        (rd / "gate" / "icp-round.md").write_text(
            "reader 1: would LEAVE. calls him a data fixer\nreader 2: would LEAVE. repair shop\n"
            "reader 3: would LEAVE. unclear what he sells\n")

    def gate(self, *args):
        env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_PROJECT_DIR", "DESIGN_CHAIN_ALLOW")}
        env["DESIGN_CHAIN_STATE"] = str(self.tmp / "state")
        r = subprocess.run([sys.executable, str(REAL_GATE), *args], capture_output=True, text=True,
                           env=env, timeout=600)
        return r.returncode, r.stdout + r.stderr


class TheLoaderRefusesATypedFixture(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="dc21-fx-"))
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.real = dc_fixtures.FIXTURES
        dc_fixtures.FIXTURES = self.dir
        self.addCleanup(setattr, dc_fixtures, "FIXTURES", self.real)

    def put(self, name, doc):
        (self.dir / f"{name}.json").write_text(json.dumps(doc))

    def test_no_provenance_block(self):
        self.put("typed", {"content": "ran\n"})
        with self.assertRaisesRegex(dc_fixtures.NotCaptured, "no _provenance"):
            dc_fixtures.load("typed")

    def test_a_missing_field(self):
        doc = dc_fixtures.wrap("ran\n", "design-impeccable-check.py", "x", "2026-09-19")
        doc["_provenance"]["command"] = " "
        self.put("half", doc)
        with self.assertRaisesRegex(dc_fixtures.NotCaptured, "command"):
            dc_fixtures.load("half")

    def test_content_edited_after_capture(self):
        doc = dc_fixtures.wrap("real output\n", "p.py", "python3 p.py", "2026-09-19")
        doc["content"] = "ran\n"
        self.put("edited", doc)
        with self.assertRaisesRegex(dc_fixtures.NotCaptured, "edited after capture"):
            dc_fixtures.load("edited")

    def test_every_committed_fixture_loads(self):
        # a census taken from the directory, with a floor, so an empty directory is not a pass
        names = sorted(p.stem for p in self.real.glob("*.json"))
        self.assertGreaterEqual(len(names), 2, names)
        dc_fixtures.FIXTURES = self.real
        for n in names:
            doc = dc_fixtures.load(n)
            self.assertTrue(doc["content"].strip(), n)


class RoundB(Round):
    def test_a_page_with_only_a_hand_written_receipt_is_never_complete(self):
        self.config()
        page = self.rd / "Home-html-laptop.html"
        page.write_text("<html><body>nothing</body></html>")
        (self.rd / "receipts.json").write_text(json.dumps(
            {page.name: {"sha256": hashlib.sha256(page.read_bytes()).hexdigest(), "sealed": "typed-by-hand"}}))
        rc, out = self.gate("status-page", str(page))
        self.assertEqual(rc, 2, out)
        self.assertTrue(out.startswith("OPEN"), out)


class ControlC(Round):
    def test_round_a_records_with_a_page_the_standard_fails_refuse(self):
        # proves the gate is alive on the real producers: the same records that seal round A today
        self.config()
        self.round_a_records()
        (self.rd / "Home-html-laptop.html").write_text(PAGE_TINY)
        rc, out = self.gate("seal", str(self.rd))
        self.assertEqual(rc, 2, out)
        self.assertIn("FAILS the standard", out)
        self.assertFalse((self.rd / "receipts.json").exists())


class TheBlandControl(Round):
    def test_a_bland_page_is_refused_at_the_craft_tier_on_a_design_axis(self):
        self.config(craft={"tier": "craft", "require_gap_check": True})
        refs = self.inst / "site" / "design" / "references"
        refs.mkdir(parents=True)
        for name in sorted(p.stem for p in dc_fixtures.FIXTURES.glob("exemplar-*.json")):
            (refs / (name.removeprefix("exemplar-") + ".json")).write_text(dc_fixtures.load(name)["content"])
        page = self.rd / "Home-laptop.html"
        page.write_text(PAGE_BLAND)
        from playwright.sync_api import sync_playwright   # a missing browser is a failure, not a skip
        with sync_playwright() as pw:
            b = pw.chromium.launch()
            pg = b.new_page(viewport={"width": 1440, "height": 900})
            pg.goto(page.as_uri())
            pg.screenshot(path=str(self.rd / "Home-laptop.png"))
            b.close()
        (self.rd / "brief.md").write_text("brief\n")
        (self.rd / "directions.md").write_text("# A\n# B\n# C\n")
        (self.rd / "critique.md").write_text("".join(f"{i % 9 + 1}. considered\n" for i in range(27)))
        (self.rd / "proof.md").write_text("Home-laptop.html: proof\n")
        (self.rd / "checks").mkdir()
        (self.rd / "checks" / "bio_gate.txt").write_text("ok\n")
        (self.rd / "gate").mkdir()
        (self.rd / "gate" / "icp.md").write_text("answers\n")
        rc, out = self.gate("seal", str(self.rd))
        self.assertEqual(rc, 2, out)
        # refused on what the page LOOKS like, not on a missing screenshot or capture
        self.assertNotIn("no screenshot beside this page", out)
        self.assertNotIn("could not measure", out)
        self.assertRegex(out, r"below the exemplar floor\. (distinct background colours|type sizes in the fold|"
                              r"distinct corner radii|interactive controls in the fold|transitions per)")
        self.assertFalse((self.rd / "receipts.json").exists())


if __name__ == "__main__":
    unittest.main()
