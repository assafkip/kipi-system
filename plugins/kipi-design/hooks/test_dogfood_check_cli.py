#!/usr/bin/env python3
"""ASK-1746 / dc-11: `dogfood_gate.py --check FILE [--as PATH]` says SKIPPED apart from PASS.

WHY. The hook exits 0 for a clean page and for one it never scanned (an internal path, not HTML,
the eyeball-gate-skip marker), so design-chain seal, reading the exit code, could not tell a pass
from a skip. --check gives a skip its own exit code, 3, and seal reads it as not run.

Runs the real CLI in a subprocess. A unittest file (not a script with its own counter) so the
issue verifier can count what ran.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dogfood_gate.py")
CLEAN = ("<!doctype html><html><head><meta charset='utf-8'><style>body{font:18px/1.5 Georgia,serif;"
         "background:#fff;color:#111}</style></head><body><h1>Two records that should agree</h1>"
         "<p>A small firm retypes the same client data into three systems.</p>"
         "<form action='#book'><button>Book a 30-minute call</button></form></body></html>")
GARISH = ("<!doctype html><html><head><style>body{font-family:'Inter',sans-serif}"
          ".g{background:linear-gradient(90deg,#7c3aed,#2563eb);-webkit-background-clip:text;color:transparent}"
          "</style></head><body><h1><span class='g'>Unlock the Future of Synergy</span></h1>"
          "<button>Get Started</button></body></html>")


class CheckMode(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dogfood-check-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def check(self, html, name="page.html", as_path=None):
        p = os.path.join(self.tmp, name)
        if html is not None:
            with open(p, "w") as fh:
                fh.write(html)
        args = [sys.executable, HOOK, "--check", p] + (["--as", as_path] if as_path else [])
        r = subprocess.run(args, capture_output=True, text=True, timeout=60)
        return r.returncode, r.stderr

    def test_a_clean_page_exits_0(self):
        rc, err = self.check(CLEAN)
        self.assertEqual(rc, 0, err)

    def test_a_slop_page_exits_2_and_names_its_tells(self):
        rc, err = self.check(GARISH)
        self.assertEqual(rc, 2, err)
        self.assertIn("Gradient", err)

    def test_the_skip_marker_exits_4_not_0(self):
        # 4 is NOT_APPLICABLE: an operator exemption is a scope decision, not a checker that could
        # not run. On 3 the seal read it as "did not run" and refused the round forever, so the
        # documented bypass made a page unsealable (PR #374 review round 6, major)
        rc, err = self.check(CLEAN.replace("<head>", "<head><!-- eyeball-gate-skip -->"))
        self.assertEqual(rc, 4, err)
        self.assertIn("eyeball-gate-skip", err)

    def test_an_internal_path_by_as_exits_4_not_0(self):
        rc, err = self.check(CLEAN, as_path="/repo/q-system/output/view.html")
        self.assertEqual(rc, 4, err)
        self.assertIn("not a public page", err)

    def test_a_file_that_is_not_html_still_exits_3(self):
        # deliberately NOT 4: is_page() already called this a page, so markup missing from it is a
        # real problem rather than a scope question, and a refusal is right
        rc, err = self.check("just text, no markup")
        self.assertEqual(rc, 3, err)
        self.assertIn("not an HTML document", err)

    def test_an_unreadable_file_exits_2_never_0(self):
        rc, err = self.check(None, name="missing.html")
        self.assertEqual(rc, 2, err)


if __name__ == "__main__":
    unittest.main()
