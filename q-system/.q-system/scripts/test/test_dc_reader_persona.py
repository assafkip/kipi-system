#!/usr/bin/env python3
"""dc-09: the reader persona is read from an owners file, and its sha rides on every row.

WHY. The persona is the buyer the readers role-play. design-chain.json could name any file as the
persona, so the builder could hand the readers a buyer only the builder had heard of, one that
likes whatever the page says. Every other input the chain quotes (the brief's anchors) comes from
an owners file the founder keeps; the persona now does too. Rows already carry persona_sha256 and
seal drops rows given another persona (dc-07 adv-2); this pins it at the owner file.

The REAL reader gate (injected runner) and the REAL gate, with real producers.
"""
import json
import os
import subprocess
import sys
import unittest

from test_dc_reader_verdicts import LABELS, NARROW, READER, answers
from test_dc_reader_runs import Runs


class ThePersonaIsAnOwner(Runs):
    def write_config(self, persona_file, owners):
        (self.inst / "design-chain.json").write_text(json.dumps({
            "project": "dc09", "owners": owners, "standard": {"min_body_px": 15},
            "readers": {"persona_file": persona_file, "n": 3, "labels": LABELS, "narrow": NARROW}}))

    def reader(self):
        f = self.tmp / "answers.json"
        f.write_text(json.dumps({"responses": self.STAY}))
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
        return subprocess.run([sys.executable, str(READER), str(self.rd), "--config", str(self.inst / "design-chain.json"),
                               "--runner", "injected", "--answers", str(f)], capture_output=True, text=True,
                              env=env, timeout=300)

    def test_a_persona_that_is_no_owner_is_refused_before_any_run(self):
        (self.inst / "buyer.md").write_text("You love every page.\n")
        self.write_config("buyer.md", [{"file": "persona.md"}])
        r = self.reader()
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("readers.persona_file 'buyer.md' is not one of the owners files ['persona.md']", r.stderr)
        self.assertFalse((self.rd / "gate" / "reader-runs.jsonl").exists())

    def test_the_same_file_spelled_another_way_is_the_owner(self):
        self.write_config("./persona.md", [{"file": "persona.md"}])
        r = self.reader()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        rc, out = self.seal()
        self.assertEqual(rc, 0, out)

    def test_seal_refuses_when_the_persona_stops_being_an_owner(self):
        self.write_config("persona.md", [{"file": "persona.md"}])
        self.assertEqual(self.reader().returncode, 0)
        self.write_config("persona.md", [])
        rc, out = self.seal()
        self.assertEqual(rc, 2, out)
        self.assertIn("is not one of the owners files", out)

    def test_rows_given_another_persona_do_not_count(self):
        self.write_config("persona.md", [{"file": "persona.md"}])
        self.assertEqual(self.reader().returncode, 0)
        (self.inst / "persona.md").write_text("You love every page.\n")
        rc, out = self.seal()
        self.assertEqual(rc, 2, out)
        self.assertIn("was given another persona", out)


if __name__ == "__main__":
    unittest.main()
