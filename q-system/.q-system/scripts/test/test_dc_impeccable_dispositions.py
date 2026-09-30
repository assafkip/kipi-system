#!/usr/bin/env python3
"""The only two ways an impeccable finding stops counting: refuted by pixel measurement, or
answered by a canon entry. Round 2026-09-21 (ASK-1743).

WHY. The seal had no way to answer a finding at all, so a detector blind spot (a CSS gradient
scored against its worst stop, wherever that stop sits) and a founder canon decision (one
typeface) both blocked the seal, on all six pages. The gate's history is a run of bypasses
found in the "write that it is accepted" shape, so every test here that says ACCEPTED has a
sibling that proves the same door refuses the near miss.

Drives the REAL script with a stub DETECTOR that prints whatever finding lines a test hands it.
The refutation tests also need playwright; they skip by name without it.
"""
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
from test_dc_impeccable_exit import Served  # noqa: E402

SCRIPT = HERE.parent / "design-impeccable-check.py"
STUB = r"""
const t = process.argv[2] || '';
if (t.includes('impeccable-control')) { console.error('[gradient-text] x\n1 anti-pattern found.'); process.exit(2); }
const out = process.env.STUB_OUT || '';
if (!out) process.exit(0);
console.error(out + '\n1 anti-pattern found.'); process.exit(2);
"""
FONT = "only font used is general sans"
CANON_LINE = "**AGREED 2026-09-15: the typeface is General Sans** (free for commercial use)"
DECISION = "AGREED 2026-09-15: the typeface is General Sans"


def page(css_top: str) -> str:
    # white words on a panel that fades in from the page colour: the detector's blind-spot shape
    return ("<!doctype html><html><head><meta charset='utf-8'><style>body{margin:0;background:#fcfbf8;"
            "font:18px/1.4 sans-serif}.p{position:relative;height:700px;margin:40px;background:"
            "linear-gradient(to bottom,#1b3d66 0%,#1b3d66 45%,#fcfbf8 100%);background-color:#1b3d66}"
            f".p p{{position:absolute;left:24px;{css_top};color:#fff;margin:0}}</style></head><body>"
            "<div class='p'><p>Two records that should agree</p></div></body></html>")


def contrast(method="analytic-gradient", text="Two records that should agree"):
    return f'[low-contrast] browser contrast 1.0:1 median 1.0:1 (need 4.5:1) via {method} "{text}"'


class Base(unittest.TestCase):
    def setUp(self):
        if not shutil.which("node"):
            self.fail("node is not on PATH: the detector cannot run")
        self.tmp = Path(tempfile.mkdtemp(prefix="dcdisp-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.rd = self.tmp / "r1"
        self.rd.mkdir()
        (self.rd / "Home-laptop.html").write_text(page("top:40px"))
        self.det = self.tmp / "stub.mjs"
        self.det.write_text(STUB)
        (self.tmp / "canon").mkdir()
        (self.tmp / "canon" / "site-design.md").write_text(f"# canon\n\n{CANON_LINE}\n")
        self.srv = Served(self.rd)
        self.addCleanup(self.srv.close)

    def cfg(self, **entry):
        e = {"rule": "single-font", "finding": FONT, "owner": "canon/site-design.md", "decision": DECISION, **entry}
        p = self.tmp / "design-chain.json"
        p.write_text(json.dumps({"project": "t", "owners": [{"file": "canon/site-design.md", "anchors": []}],
                                 "impeccable": {"canon": [e]}}))
        return p

    def run_script(self, out, cfg=None):
        env = {**os.environ, "STUB_OUT": out}
        args = [sys.executable, str(SCRIPT), str(self.rd), "--detector", str(self.det),
                "--url-base", self.srv.base]
        if cfg:
            args += ["--config", str(cfg)]
        r = subprocess.run(args, capture_output=True, text=True, env=env, timeout=600)
        rec = self.rd / "checks" / "impeccable.txt"
        return r.returncode, r.stdout + r.stderr, rec.read_text() if rec.is_file() else ""


class TheCanonDoor(Base):
    def test_the_exact_finding_named_by_a_live_anchor_is_answered(self):
        rc, out, rec = self.run_script(f"[single-font] {FONT}", self.cfg())
        self.assertEqual(rc, 0, out)
        self.assertIn("CANON [single-font]", rec)
        self.assertIn("canon/site-design.md:3", rec)

    def test_without_the_config_the_same_finding_stands(self):
        rc, out, rec = self.run_script(f"[single-font] {FONT}")
        self.assertEqual(rc, 3, out)
        self.assertIn("STANDS [single-font]", rec)

    def test_a_different_single_font_still_flags(self):
        rc, out, rec = self.run_script("[single-font] only font used is inter", self.cfg())
        self.assertEqual(rc, 3, out)

    def test_a_stale_anchor_lets_the_finding_stand(self):
        (self.tmp / "canon" / "site-design.md").write_text("# canon\n\nthe typeface is Inter\n")
        rc, out, rec = self.run_script(f"[single-font] {FONT}", self.cfg())
        self.assertEqual(rc, 3, out)
        self.assertIn("NOT honoured", rec)

    def test_an_unrelated_owner_line_cannot_answer_the_finding(self):
        # PR #403 review (major): the regex '^#' matched a heading in a file with no typeface
        # decision and the finding sealed. A line that exists but is not the decision refuses.
        (self.tmp / "canon" / "site-design.md").write_text("# Deployment notes only\nNo typeface decision exists.\n")
        for dec in ("# Deployment notes only", "No typeface decision exists."):
            with self.subTest(decision=dec):
                rc, out, _ = self.run_script(f"[single-font] {FONT}", self.cfg(decision=dec))
                self.assertEqual(rc, 2, out)

    def test_a_decision_about_another_typeface_cannot_answer_this_one(self):
        (self.tmp / "canon" / "site-design.md").write_text("AGREED 2026-09-15: the typeface is Inter\n")
        rc, out, _ = self.run_script(f"[single-font] {FONT}",
                                     self.cfg(decision="AGREED 2026-09-15: the typeface is Inter"))
        self.assertEqual(rc, 2, out)
        self.assertIn("general sans", out)

    def test_a_regex_anchor_is_refused_outright(self):
        rc, out, _ = self.run_script(f"[single-font] {FONT}", self.cfg(anchor="^#"))
        self.assertEqual(rc, 2, out)
        self.assertIn("anchor", out)

    def test_a_defect_rule_can_never_be_answered_by_canon(self):
        for rule in ("low-contrast", "gradient-text", "ai-color-palette"):
            with self.subTest(rule=rule):
                rc, out, _ = self.run_script(f"[{rule}] x", self.cfg(rule=rule, finding="x"))
                self.assertEqual(rc, 2, out)
                self.assertIn("taste calls", out)

    def test_an_owner_the_config_does_not_list_is_refused(self):
        (self.tmp / "loose.md").write_text(f"{CANON_LINE}\n")
        rc, out, _ = self.run_script(f"[single-font] {FONT}", self.cfg(owner="loose.md"))
        self.assertEqual(rc, 2, out)
        self.assertIn("not one of the config's owners", out)

    def test_a_finding_line_that_does_not_parse_stands(self):
        rc, out, rec = self.run_script("something the parser has never seen", self.cfg())
        self.assertEqual(rc, 3, out)
        self.assertIn("STANDS [unparsed]", rec)


class TheMeasurementDoor(Base):
    def setUp(self):
        try:
            import playwright  # noqa: F401
            import PIL  # noqa: F401
        except ImportError:
            self.skipTest("playwright/Pillow not installed: the pixel re-measure was NOT exercised")
        super().setUp()

    def test_words_on_the_dark_end_are_refuted(self):
        rc, out, rec = self.run_script(contrast())
        self.assertEqual(rc, 0, out)
        self.assertIn("REFUTED [low-contrast]", rec)
        self.assertIn("pixel re-measure control: FIRED both ways", rec)

    def test_words_on_the_light_end_stand(self):
        # the negative self-test on the real page shape: same gradient, words where it IS light
        (self.rd / "Home-laptop.html").write_text(page("bottom:10px"))
        rc, out, rec = self.run_script(contrast())
        self.assertEqual(rc, 3, out)
        self.assertIn("did not refute", rec)

    def test_only_the_analytic_gradient_method_is_re_measured(self):
        rc, out, rec = self.run_script(contrast(method="solid-background"))
        self.assertEqual(rc, 3, out)
        self.assertNotIn("REFUTED", rec)

    def test_text_the_page_does_not_have_is_never_refuted(self):
        rc, out, rec = self.run_script(contrast(text="words not on this page"))
        self.assertEqual(rc, 3, out)


if __name__ == "__main__":
    unittest.main()
