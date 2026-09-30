#!/usr/bin/env python3
"""PR #374 review round 3: what counts as internal, and what counts as shipping.

WHY. INTERNAL_MARKERS is documented as "a path segment match" and was a bare substring test, so
/testimonials/ matched "/test", /schedule-a-call/ matched "/schedule" and /reports/ matched
"/report": three ordinary marketing pages skipped the whole chain at every surface. BASH_SHOW_RE
knew one deploy verb, `vercel deploy`, so `netlify deploy`, `npx vercel --prod` and `aws s3 sync`
put an unsealed page in front of the world before Stop could refuse it.
"""
import importlib.util
import unittest
from pathlib import Path

GATE = Path(__file__).resolve().parent.parent / "design-chain-gate.py"


def gate():
    spec = importlib.util.spec_from_file_location("dc_internal_gate", GATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class WhatIsInternal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gate = gate()

    def test_a_public_page_whose_path_merely_contains_a_marker_is_public(self):
        for path in ("/site/testimonials/index.html", "/site/schedule-a-call/index.html",
                     "/site/reportage/index.html", "/site/testing-the-waters/index.html",
                     "/site/logbook/index.html"):
            self.assertTrue(self.gate.is_page(path), f"{path} was read as internal")

    def test_the_internal_folders_are_still_internal(self):
        for path in ("/x/node_modules/p.html", "/x/dist/p.html", "/x/tests/p.html", "/x/test/p.html",
                     "/x/fixtures/p.html", "/x/logs/p.html", "/x/dashboard/p.html", "/x/reports/p.html",
                     "/x/exemplars/p.html", "/x/.next/p.html"):
            self.assertFalse(self.gate.is_page(path), f"{path} was read as public")

    def test_the_internal_file_names_are_still_internal(self):
        for path in ("/x/daily-schedule-2026-09-19.html", "/x/morning-log-2026-09-19.html"):
            self.assertFalse(self.gate.is_page(path), f"{path} was read as public")


class WhatCountsAsShipping(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gate = gate()

    def shows(self, cmd):
        return bool(self.gate.BASH_SHOW_RE.search(cmd))

    def test_the_deploy_verbs_that_put_a_page_in_front_of_the_world(self):
        for cmd in ("vercel deploy --prod", "vercel --prod", "npx vercel --prod",
                    "netlify deploy --prod --dir site", "aws s3 sync site/ s3://bucket",
                    "rsync -av site/ deploy@host:/var/www/"):
            self.assertTrue(self.shows(cmd), f"{cmd!r} shipped without the gate seeing it")

    def test_ordinary_commands_are_not_deploys(self):
        for cmd in ("git push", "git push origin main", "npm run build", "python3 build.py",
                    "rsync -av site/ ../backup/", "aws s3 ls s3://bucket"):
            self.assertFalse(self.shows(cmd), f"{cmd!r} was read as a deploy")


if __name__ == "__main__":
    unittest.main()
