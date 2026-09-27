#!/usr/bin/env python3
"""PR #374 review round 6: a captured fixture may be redacted, and a redaction must prove itself.

WHY. One producer writes its own absolute path into its output, and this repo is PUBLIC and ships
to every instance via kipi update. Round 4 answered that by excluding the fixture from the skeleton
leak sweep, which left the home path in the file and only silenced the detector. The right answer is
to redact the content and say so. The risk that creates is the obvious one: "redacted" becomes the
word you write on an ordinary edit. So a fixture claiming redactions has to name them AND keep the
pre-redaction sha, or load() refuses it.
"""
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import dc_fixtures  # noqa: E402


def redacted_doc(**prov_overrides):
    content = "ran the detector at ~/projects/example/detect.mjs\n0 findings\n"
    doc = {
        "_provenance": {
            "producer": "detect-antipatterns.mjs",
            "command": "node detect-antipatterns.mjs page.html",
            "captured_at": "2026-09-19T00:00:00+00:00",
            "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
            "captured_content_sha256": "0" * 64,
            "redactions": ["absolute home path -> ~"],
        },
        "content": content,
    }
    doc["_provenance"].update(prov_overrides)
    return doc


class RedactionMustProveItself(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="dcredact-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.real = dc_fixtures.FIXTURES
        dc_fixtures.FIXTURES = self.tmp
        self.addCleanup(setattr, dc_fixtures, "FIXTURES", self.real)

    def write(self, doc):
        (self.tmp / "f.json").write_text(json.dumps(doc))

    def test_a_redaction_that_names_itself_and_keeps_the_original_sha_loads(self):
        self.write(redacted_doc())
        self.assertIn("~/projects", dc_fixtures.load("f")["content"])

    def test_a_redaction_without_the_pre_redaction_sha_is_refused(self):
        # otherwise "redactions" is a word that excuses any edit
        self.write(redacted_doc(captured_content_sha256="  "))
        with self.assertRaises(dc_fixtures.NotCaptured):
            dc_fixtures.load("f")

    def test_a_redaction_that_does_not_say_what_it_changed_is_refused(self):
        for empty in ([], ["  "], "absolute home path"):
            self.write(redacted_doc(redactions=empty))
            with self.assertRaises(dc_fixtures.NotCaptured):
                dc_fixtures.load("f")

    def test_an_ordinary_unredacted_fixture_is_unaffected(self):
        doc = redacted_doc()
        del doc["_provenance"]["redactions"]
        del doc["_provenance"]["captured_content_sha256"]
        self.write(doc)
        self.assertIn("0 findings", dc_fixtures.load("f")["content"])


class TheShippedFixtureCarriesNoHomePath(unittest.TestCase):
    def test_the_impeccable_receipt_is_redacted_not_excluded(self):
        # the skeleton leak sweep is armed over this file again, so this is belt and braces: the
        # sweep would catch a home path, this says which file and why
        doc = dc_fixtures.load("impeccable-receipt")
        self.assertNotIn("/Users/", doc["content"])
        self.assertTrue(doc["_provenance"]["redactions"])


if __name__ == "__main__":
    unittest.main()
