"""The vision stage of the design chain, proved in both directions.

Founder, 2026-09-18: "add this process into the design chain tool we built so it is forced
into the process." The process: say the VISION first, keep a notebook of the key points and
reasons, break it into components, spec each, review the specs, then build.

WHY A TEST AND NOT A README. On 2026-09-17/18 the chain produced three fully specced,
measured, critiqued and SEALED directions that were all wrong, with 51 negative reader
statements against 1 "it helped" across 23 gate runs. Nothing was skipped. Every brief was
assembled from CONSTRAINTS and none of them said what the page was trying to BE.

Each case below was seen to FAIL before the check existed. A check never seen red is
decoration.
"""
import json, pathlib, subprocess, sys, tempfile, shutil, unittest

GATE = str(pathlib.Path(__file__).resolve().parents[1] / "design-chain-gate.py")


class VisionStage(unittest.TestCase):
    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp())
        self.rd = self.root / "design" / "r1"
        self.rd.mkdir(parents=True)
        (self.rd / "brief.md").write_text("# brief\nTHE ANCHOR LINE.\n")
        for f in ("directions.md", "standard.json", "critique.md", "proof.md"):
            (self.rd / f).write_text("x\n")
        for d in ("checks", "gate"):
            (self.rd / d).mkdir(); (self.rd / d / "x.txt").write_text("x\n")
        (self.rd / "craft-manifest.json").write_text(
            json.dumps({"tier": "craft", "component": "hero", "techniques": []}))
        self.page = self.rd / "Home-astro-laptop.html"
        self.page.write_text("<html></html>")
        (self.root / "owner.md").write_text("THE ANCHOR LINE.\n")
        self.cfg = {"project": "t", "owners": [{"file": "owner.md", "anchors": ["^THE ANCHOR LINE"]}]}

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def status(self):
        (self.root / "design-chain.json").write_text(json.dumps(self.cfg))
        return subprocess.run([sys.executable, GATE, "status-page", str(self.page)],
                              capture_output=True, text=True).stdout

    def adopt(self):
        self.cfg["vision"] = {"file": "design/VISION.md", "specs_dir": "design/specs",
                              "min_founder_quotes": 3}

    def write_vision(self):
        (self.root / "design" / "VISION.md").write_text(
            "# Vision\n"
            '**Founder, 2026-09-18:** "They already have the automation and do not trust the output."\n'
            '**Founder, 2026-09-18:** "I want them to feel caught, not sold to, in four seconds."\n'
            '**Founder, 2026-09-18:** "Nothing on this page may be a picture of an idea."\n')

    def test_an_instance_that_never_adopted_the_stage_is_left_alone(self):
        """Non-adoption is a config fact, not a silent pass: an instance with no vision block
        and no vision file hears nothing from this stage."""
        self.assertNotIn("VISION", self.status().upper())

    def test_declaring_the_stage_without_writing_the_vision_fails(self):
        self.adopt()
        self.assertIn("VISION.md", self.status())

    def test_a_vision_with_none_of_the_founders_words_fails(self):
        """The failure this exists to stop: the builder writes the vision and then builds to
        his own aim."""
        self.adopt(); (self.root / "design" / "VISION.md").write_text("# Vision\nBe good.\n")
        self.assertIn("founder block", self.status())

    def test_a_brief_that_does_not_quote_the_vision_fails(self):
        self.adopt(); self.write_vision()
        self.assertIn("quotes no line", self.status())

    def test_a_declared_component_without_a_spec_fails(self):
        self.adopt(); self.write_vision()
        (self.rd / "brief.md").write_text(
            '# brief\nTHE ANCHOR LINE.\n**Founder, 2026-09-18:** '
            '"Nothing on this page may be a picture of an idea."\n')
        self.assertIn("hero.md", self.status())

    def test_a_spec_the_founder_has_not_reviewed_fails(self):
        self.adopt(); self.write_vision()
        (self.rd / "brief.md").write_text(
            '# brief\nTHE ANCHOR LINE.\n**Founder, 2026-09-18:** '
            '"Nothing on this page may be a picture of an idea."\n')
        (self.root / "design" / "specs").mkdir(parents=True)
        (self.root / "design" / "specs" / "hero.md").write_text("# hero spec\ntext\n")
        self.assertIn("REVIEWED BY FOUNDER", self.status())

    def test_the_stage_is_silent_once_it_is_satisfied(self):
        """The green half. A gate that cannot go quiet gets switched off."""
        self.adopt(); self.write_vision()
        (self.rd / "brief.md").write_text(
            '# brief\nTHE ANCHOR LINE.\n**Founder, 2026-09-18:** '
            '"Nothing on this page may be a picture of an idea."\n')
        (self.root / "design" / "specs").mkdir(parents=True)
        (self.root / "design" / "specs" / "hero.md").write_text(
            "# hero spec\nREVIEWED BY FOUNDER: 2026-09-18\ntext\n")
        out = self.status()
        self.assertNotIn("VISION", out.upper())
        self.assertNotIn("hero.md", out)


if __name__ == "__main__":
    unittest.main()
