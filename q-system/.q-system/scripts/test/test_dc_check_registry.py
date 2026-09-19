#!/usr/bin/env python3
"""dc-11: outside checks run from a closed registry in the gate, and the tripwire says when it skipped.

WHY. checks/ only had to be non-empty. Round A-checks of the RCA (2026-09-18) sealed with the
tripwire's FAIL written into checks/tripwire.txt: the gate read that a file existed, not what it
said, and never ran the check itself. Now design-chain.json names checks from a registry the gate
owns, seal runs each on every page, and a skip is not a pass.

The REAL gate, the REAL reader gate (injected runner) and the REAL tripwire, with real producers.
bio_gate and voice-lint are not in the registry yet (follow-ups): only the tripwire half of round
A-checks is asserted here.
"""
import json
import unittest

from test_dc_reader_runs import Runs

SLOP = ("<!doctype html><html><head><meta charset='utf-8'><style>body{font-family:Inter,sans-serif;"
        "font-size:18px} h1{background:linear-gradient(90deg,#8b5cf6,#ec4899);-webkit-background-clip:text;"
        "color:transparent}</style></head><body><h1>Unlock the power of AI</h1>"
        "<p>A small firm retypes the same client data into three systems.</p>"
        "<button>Get started</button></body></html>")
CLEAN = ("<!doctype html><html><head><meta charset='utf-8'><style>body{font:18px/1.5 Georgia,serif;"
         "margin:40px} button{font:18px Georgia,serif}</style></head><body><h1>Two records that should agree</h1>"
         "<p>A small firm retypes the same client data into three systems.</p>"
         "<form action='#book'><button>Book a 30-minute call</button></form></body></html>")


class Registry(Runs):
    def declare(self, checks):
        cfg = json.loads((self.inst / "design-chain.json").read_text())
        cfg["checks"] = checks
        (self.inst / "design-chain.json").write_text(json.dumps(cfg))

    def page(self, html):
        (self.rd / "Home-laptop.html").write_text(html)
        self.read_page(*self.STAY)


class RoundAChecks(Registry):
    def test_a_page_the_tripwire_fails_does_not_seal_with_every_reader_staying(self):
        # RED FIRST: the RCA's round A-checks sealed; its checks/ held the FAIL as text
        (self.rd / "checks" / "tripwire.txt").write_text("FAIL: 4 AI-default tells found. exit=2\n")
        self.declare([{"name": "tripwire"}])
        self.page(SLOP)
        rc, out = self.seal()
        self.assertEqual(rc, 2, out)
        self.assertIn("the tripwire check FAILED this page (exit 2)", out)
        self.assertIn("Gradient text", out)
        self.assertFalse((self.rd / "receipts.json").exists())

    def test_a_clean_page_seals_and_the_receipt_records_the_check(self):
        self.declare([{"name": "tripwire"}])
        self.page(CLEAN)
        rc, out = self.seal()
        self.assertEqual(rc, 0, out)
        stages = json.loads((self.rd / "receipts.json").read_text())["Home-laptop.html"]["stages"]
        self.assertIn(("check:tripwire", 0), [(s["stage"], s["exit"]) for s in stages])


class TheRegistryIsClosed(Registry):
    def test_an_unknown_check_name_refuses(self):
        self.declare([{"name": "tripwire"}, {"name": "always-pass"}])
        self.page(CLEAN)
        rc, out = self.seal()
        self.assertEqual(rc, 2, out)
        self.assertIn("checks names ['always-pass'], which the gate does not run", out)

    def test_a_skipped_check_is_not_a_pass(self):
        self.declare([{"name": "tripwire"}])
        self.page(CLEAN.replace("<head>", "<head><!-- eyeball-gate-skip -->"))
        rc, out = self.seal()
        self.assertEqual(rc, 2, out)
        self.assertIn("the tripwire check did not run on this page (exit 3)", out)
        self.assertIn("eyeball-gate-skip", out)


class TheFolderNoLongerCounts(Registry):
    def test_with_declared_checks_an_empty_checks_folder_is_fine(self):
        for f in (self.rd / "checks").iterdir():
            f.unlink()
        self.declare([{"name": "tripwire"}])
        self.page(CLEAN)
        rc, out = self.seal()
        self.assertEqual(rc, 0, out)

    def test_without_a_checks_key_the_old_folder_rule_stays(self):
        for f in (self.rd / "checks").iterdir():
            f.unlink()
        self.page(CLEAN)
        rc, out = self.seal()
        self.assertEqual(rc, 2, out)
        self.assertIn("missing or empty", out)


if __name__ == "__main__":
    unittest.main()
