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

    def test_an_operator_exemption_is_recorded_not_refused(self):
        # this test used to assert the opposite, and in asserting it pinned the trap: the
        # DOCUMENTED per-file bypass returned the same exit as "the check could not run", so a page
        # carrying it could never seal and the operator had no way out (round 6, major). The
        # exemption is a scope decision; it is recorded as not applicable, with the reason, and the
        # exit stays null so nothing reads it as a pass.
        self.declare([{"name": "tripwire"}])
        self.page(CLEAN.replace("<head>", "<head><!-- eyeball-gate-skip -->"))
        rc, out = self.seal()
        self.assertEqual(rc, 0, out)
        stages = json.loads((self.rd / "receipts.json").read_text())["Home-laptop.html"]["stages"]
        na = [s for s in stages if s["stage"] == "check:tripwire"]
        self.assertEqual(len(na), 1, stages)
        self.assertIsNone(na[0]["exit"])
        self.assertIn("eyeball-gate-skip", na[0]["not_applicable"])

    def test_a_check_that_could_not_run_is_still_not_a_pass(self):
        # the other half: exit 3 keeps refusing. A page with no markup is a real problem on a file
        # the chain already called a page, not a scope question.
        self.declare([{"name": "tripwire"}])
        self.page("plain text, no markup at all")
        rc, out = self.seal()
        self.assertEqual(rc, 2, out)
        self.assertIn("did not run on this page (exit 3)", out)


VIOLET = CLEAN.replace("<form action='#book'><button>", "<form action='#book'><button style='background:#7c3aed;color:#fff'>")


class ReviewOfD2cd4b63(Registry):
    def test_a_brand_kit_inside_the_round_exempts_nothing(self):
        # adv-1: the walk from the page found a kit the builder dropped in the round
        self.declare([{"name": "tripwire"}])
        (self.rd / ".kipi-brand.json").write_text(json.dumps({"colors": ["#7c3aed"]}))
        self.page(VIOLET)
        rc, out = self.seal()
        self.assertEqual(rc, 2, out)
        self.assertIn("the tripwire check FAILED this page", out)

    def test_the_instance_brand_kit_still_exempts_its_own_colour(self):
        # control for the above, and for the kit being held: read from the held config dir
        self.declare([{"name": "tripwire"}])
        (self.inst / ".kipi-brand.json").write_text(json.dumps({"colors": ["#7c3aed"]}))
        self.page(VIOLET)
        rc, out = self.seal()
        self.assertEqual(rc, 0, out)

    def test_slop_in_a_linked_stylesheet_fails(self):
        # adv-3: the scan read the page HTML only
        self.declare([{"name": "tripwire"}])
        (self.rd / "shared.css").write_text("h1{font-family:Inter,sans-serif}")
        self.page(CLEAN.replace("</style>", "</style><link rel='stylesheet' href='shared.css'>"))
        rc, out = self.seal()
        self.assertEqual(rc, 2, out)
        self.assertIn("Inter", out)

    def test_a_page_sealed_with_checks_reads_sealed_afterwards(self):
        # std-2: the check stage had no producer on record, so the receipt was never believed
        self.declare([{"name": "tripwire"}])
        self.page(CLEAN)
        rc, out = self.seal()
        self.assertEqual(rc, 0, out)
        import os, subprocess, sys
        env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_PROJECT_DIR", "DESIGN_CHAIN_ALLOW")}
        env["DESIGN_CHAIN_STATE"] = str(self.tmp / "state")
        from test_dc_reader_verdicts import GATE
        r = subprocess.run([sys.executable, str(GATE), "status-page", str(self.rd / "Home-laptop.html")],
                           capture_output=True, text=True, env=env, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("neither at its path now nor in this repo's history", r.stdout + r.stderr)

    def test_a_check_named_twice_refuses(self):
        # std-3
        self.declare([{"name": "tripwire"}, {"name": "tripwire"}])
        self.page(CLEAN)
        rc, out = self.seal()
        self.assertEqual(rc, 2, out)
        self.assertIn("more than once", out)


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


class TheNotApplicableIsReDerived(unittest.TestCase):
    """A receipt that SAYS not applicable and cannot show it is the shape this rebuild refuses.
    _believed_na re-asks the checker about the page as it is now, so the word in the file is never
    the evidence (PR #374 review round 6)."""

    @classmethod
    def setUpClass(cls):
        import importlib.util
        from pathlib import Path as _P
        gate = _P(__file__).resolve().parent.parent / "design-chain-gate.py"
        spec = importlib.util.spec_from_file_location("dc_na_gate", gate)
        cls.gate = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.gate)

    def setUp(self):
        import shutil, tempfile
        from pathlib import Path as _P
        self.tmp = _P(tempfile.mkdtemp(prefix="dcna-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def rec(self, reason):
        return self.gate.scope_na_record("check:tripwire", reason)

    def test_an_exemption_that_is_still_on_the_page_is_believed(self):
        page = self.tmp / "Home-laptop.html"
        page.write_text("<html><body><!-- eyeball-gate-skip --><p>x</p></body></html>")
        self.assertTrue(self.gate._believed_na(self.rec("carries the eyeball-gate-skip marker"),
                                               "site", page))

    def test_an_exemption_the_page_no_longer_carries_is_not_believed(self):
        page = self.tmp / "Home-laptop.html"
        page.write_text("<html><body><p>x</p></body></html>")
        self.assertFalse(self.gate._believed_na(self.rec("carries the eyeball-gate-skip marker"),
                                                "site", page))

    def test_an_internal_path_claim_is_checked_against_the_path(self):
        internal = self.tmp / "q-system" / "output" / "view.html"
        internal.parent.mkdir(parents=True)
        internal.write_text("<html><body><p>x</p></body></html>")
        public = self.tmp / "site" / "pricing" / "index.html"
        public.parent.mkdir(parents=True)
        public.write_text("<html><body><p>x</p></body></html>")
        claim = self.rec("is not a public page (internal path, or not .html)")
        self.assertTrue(self.gate._believed_na(claim, "site", internal))
        self.assertFalse(self.gate._believed_na(claim, "site", public))

    def test_a_scope_claim_with_no_page_to_check_is_not_believed(self):
        self.assertFalse(self.gate._believed_na(self.rec("is not a public page"), "site", None))


if __name__ == "__main__":
    unittest.main()
