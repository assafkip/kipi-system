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

    def write(self, name, text):
        f = self.rd / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text) if isinstance(text, str) else f.write_bytes(text)

    def test_a_weak_disposition_does_not_answer_a_founder_finding(self):
        # std-1: WEAK[layout] and FOUNDER-FINDING[layout] share the tag, so the tag is ambiguous
        self.write("critique.md", "WEAK[layout] cramped\n## Dispositions\n- layout: FIXED looser gutters\n")
        self.write("notes.md", "FOUNDER-FINDING[layout] pricing breaks on mobile\n")
        self.assertTrue(any("layout" in p and "WEAK" in p for p in self.problems()), self.problems())

    def test_other_spellings_of_the_marker_are_seen(self):
        # adv-1
        for spelling in ("FOUNDER-FINDING[Hero]", "founder-finding[hero]", "FOUNDER-FINDING [hero]",
                         "FOUNDER\u2011FINDING[hero]", "FOUNDER-FINDING\\[hero\\]"):
            self.write("critique.md", spelling + " x\n")
            self.assertTrue(any("hero" in p.casefold() for p in self.problems()), (spelling, self.problems()))

    def test_a_tag_no_disposition_can_answer_refuses(self):
        # adv-1: an underscore cannot appear in a disposition tag
        self.write("critique.md", "FOUNDER-FINDING[hero_cta] x\n")
        self.assertTrue(any("hero_cta" in p and "can name" in p for p in self.problems()), self.problems())

    def test_an_untagged_marker_refuses(self):
        # adv-2
        for text in ("FOUNDER-FINDING: cta is buried\n", "FOUNDER-FINDING[] x\n"):
            self.write("critique.md", text)
            self.assertTrue(any("no tag" in p for p in self.problems()), (text, self.problems()))

    def test_a_file_that_cannot_be_read_refuses(self):
        # adv-3
        self.write("notes.md", b"FOUNDER-FINDING[hero] x \xff\n")
        self.assertTrue(any("cannot be read" in p for p in self.problems()), self.problems())

    def test_other_text_files_are_scanned(self):
        # adv-4
        for name in ("notes.txt", "notes.markdown", "NOTES.MD"):
            for f in self.rd.iterdir():
                if f.name != "brief.md":
                    f.unlink()
            self.write(name, "FOUNDER-FINDING[hero] x\n")
            self.assertTrue(any("hero" in p for p in self.problems()), (name, self.problems()))

    def test_a_symlinked_directory_is_scanned(self):
        # adv-4
        outside = self.tmp / "elsewhere"
        outside.mkdir()
        (outside / "notes.md").write_text("FOUNDER-FINDING[hero] x\n")
        (self.rd / "linked").symlink_to(outside, target_is_directory=True)
        self.assertTrue(any("hero" in p for p in self.problems()), self.problems())

    def test_a_one_character_reason_is_not_a_reason(self):
        # adv-5
        self.write("critique.md", "FOUNDER-FINDING[hero] x\n- hero: FIXED .\n")
        self.assertTrue(any("no reason" in p for p in self.problems()), self.problems())

    def test_a_hidden_disposition_does_not_count(self):
        # adv-6
        for hidden in ("<!-- - hero: FIXED rewrote it -->\n", "```\n- hero: FIXED rewrote it\n```\n"):
            self.write("critique.md", "FOUNDER-FINDING[hero] x\n" + hidden)
            self.assertTrue(any("no disposition" in p for p in self.problems()), (hidden, self.problems()))

    def test_a_finding_line_does_not_answer_itself(self):
        # adv-9
        self.write("critique.md", "- hero: CARRIED FOUNDER-FINDING[hero] cta is buried\n")
        self.assertTrue(any("no disposition" in p for p in self.problems()), self.problems())

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
