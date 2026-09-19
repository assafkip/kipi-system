#!/usr/bin/env python3
"""dc-14: a FOUNDER-FINDING[tag] line needs a disposition before seal.

WHY. A finding the founder raised on a round could sit in a round file and the round still sealed:
only WEAK[tag] in critique.md had to be answered (RCA 2026-09-18, S1). Same machinery now: every
FOUNDER-FINDING[tag] in any round .md file needs a '- tag: FIXED|DEFERRED|CARRIED <reason>' line.
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
GATE = HERE.parent / "design-chain-gate.py"


def load_gate():
    spec = importlib.util.spec_from_file_location("dc14_gate", GATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FounderFindings(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="dc14-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.inst = self.tmp / "inst"
        self.inst.mkdir()
        (self.inst / "design-chain.json").write_text(json.dumps({"project": "dc14", "owners": []}))
        self.rd = self.inst / "site" / "design" / "r1"
        self.rd.mkdir(parents=True)
        (self.rd / "brief.md").write_text("brief\n")

    def problems(self):
        return load_gate().founder_finding_problems(self.rd)

    def test_an_undisposed_finding_refuses_by_tag(self):
        (self.rd / "critique.md").write_text("FOUNDER-FINDING[hero-copy] the hero sells the tool, not the pain\n")
        probs = self.problems()
        self.assertTrue(any("hero-copy" in p and "no disposition" in p for p in probs), probs)

    def test_a_disposed_finding_passes(self):
        (self.rd / "critique.md").write_text("FOUNDER-FINDING[hero-copy] the hero sells the tool\n\n"
                                             "## Dispositions\n- hero-copy: FIXED hero now opens on the pain\n")
        self.assertEqual(self.problems(), [])

    def test_a_disposition_with_no_reason_refuses(self):
        (self.rd / "critique.md").write_text("FOUNDER-FINDING[hero-copy] x\n- hero-copy: FIXED\n")
        probs = self.problems()
        self.assertTrue(any("hero-copy" in p and "no reason" in p for p in probs), probs)

    def test_a_finding_in_any_round_file_counts(self):
        (self.rd / "checks").mkdir()
        (self.rd / "checks" / "notes.md").write_text("FOUNDER-FINDING[nav-width] nav too wide\n")
        probs = self.problems()
        self.assertTrue(any("nav-width" in p for p in probs), probs)

    def test_the_disposition_may_live_in_another_round_file(self):
        (self.rd / "notes.md").write_text("FOUNDER-FINDING[nav-width] nav too wide\n")
        (self.rd / "critique.md").write_text("- nav-width: CARRIED to round r2 brief\n")
        self.assertEqual(self.problems(), [])

    def test_seal_refuses_an_undisposed_founder_finding(self):
        # RED FIRST: only WEAK[tag] had to be answered
        (self.rd / "critique.md").write_text("FOUNDER-FINDING[hero-copy] the hero sells the tool\n")
        (self.rd / "Home-laptop.html").write_text("<html><body><p>x</p></body></html>")
        env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_PROJECT_DIR", "DESIGN_CHAIN_ALLOW")}
        env["DESIGN_CHAIN_STATE"] = str(self.tmp / "state")
        r = subprocess.run([sys.executable, str(GATE), "seal", str(self.rd)], capture_output=True, text=True,
                           env=env, timeout=600)
        out = r.stdout + r.stderr
        self.assertEqual(r.returncode, 2, out)
        self.assertIn("FOUNDER-FINDING[hero-copy]", out)


if __name__ == "__main__":
    unittest.main()
