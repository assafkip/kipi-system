#!/usr/bin/env python3
"""Tests for design-chain-gate.py. Every test runs on a temp copy: a temp round dir,
temp owner files, a temp ledger dir (DESIGN_CHAIN_STATE). Never a live path.

Negative cases first: a gate is not trusted until it has been seen to fail.
Scar: 2026-09-15, two rounds of first screens shipped past every existing check.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
GATE = HERE / "design-chain-gate.py"

OWNER_LINE = "> **A business where somebody is paid to be accurate, and being wrong costs money"
IDEA_LINE = "**Two records that should agree, and don't.**"
RULE_LINE = "- **RULE-2026-09-15-C [USER-DIRECTED]:** **The public site starts from the visitor's one pain, not from the system; and no three-box card rows.** Founder, verbatim..."
CRAFT_MANIFEST = "craft-manifest.json"
RULE_TITLE = "The public site starts from the visitor's one pain, not from the system; and no three-box card rows."


def run(args, payload=None, env=None):
    e = dict(os.environ)
    e.pop("DESIGN_CHAIN_ALLOW", None)
    e.pop("CLAUDE_PROJECT_DIR", None)
    e.update(env or {})
    r = subprocess.run([sys.executable, str(GATE), *args], input=json.dumps(payload) if payload is not None else None,
                       capture_output=True, text=True, env=e)
    return r.returncode, r.stdout + r.stderr


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="dcg-"))
        self.state = self.tmp / "state"
        self.inst = self.tmp / "instance"
        (self.inst / "canonical").mkdir(parents=True)
        (self.inst / "canonical" / "the-business.md").write_text("# The business\n\n" + OWNER_LINE + "\n> that can be counted.**\n")
        (self.inst / "canonical" / "design-dna.md").write_text("# DNA\n\n" + IDEA_LINE + "\n")
        (self.inst / "canonical" / "decisions.md").write_text(RULE_LINE + "\n")
        (self.inst / "design-chain.json").write_text(json.dumps({
            "exemplars_dir": "site/design/exemplars",
            "owners": [
                {"file": "canonical/the-business.md", "anchors": ["^> \\*\\*A business where somebody is paid"]},
                {"file": "canonical/design-dna.md", "anchors": ["^\\*\\*Two records that should agree"]},
                {"file": "canonical/decisions.md", "anchors": ["RULE-2026-09-15-C \\[USER-DIRECTED\\]:\\*\\* \\*\\*([^*]+)\\*\\*"]},
            ],
            "standard": {"max_words": 80},
        }))
        self.round = self.inst / "site" / "design" / "r1"
        self.round.mkdir(parents=True)
        self.page = self.round / "Pair-laptop.html"
        self.page.write_text("<html><body><h1>You work more hours than you bill.</h1></body></html>")
        self.env = {"DESIGN_CHAIN_STATE": str(self.state)}
        self.sid = "sess-test"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def sha(self, p):
        return hashlib.sha256(p.read_bytes()).hexdigest()

    def complete_chain(self, brief_ok=True):
        rd = self.round
        anchors = [OWNER_LINE, IDEA_LINE, RULE_TITLE]
        if not brief_ok:
            anchors[0] = "A business where someone is paid to be right and mistakes cost money"  # paraphrase
        (rd / "brief.md").write_text("# Brief\n\nReader: a tax practice owner.\nPain: retyping.\nOne thing: hours leak.\n\n" + "\n".join(anchors) + "\n")
        (rd / "directions.md").write_text("# A. The pair\nfrom the idea\n# B. The report\nfrom the idea\n# C. The records\nfrom the idea\n")
        (rd / "critique.md").write_text("".join(f"## {d}\n" + "".join(f"{i}. answer\n" for i in range(1, 10)) for d in "ABC"))
        (rd / "proof.md").write_text("Pair-laptop.html: capability proof, INDEX Alice OSINT sweep\n")
        (rd / "checks").mkdir(exist_ok=True); (rd / "checks" / "bio_gate.txt").write_text("ok\n")
        (rd / "gate").mkdir(exist_ok=True); (rd / "gate" / "icp.md").write_text("answers\n")
        (rd / "standard.json").write_text(json.dumps([{"page": self.page.name, "sha256": self.sha(self.page), "pass": True}]))

    def write_hook(self):
        return run([], {"hook_event_name": "PostToolUse", "tool_name": "Write", "session_id": self.sid,
                        "tool_input": {"file_path": str(self.page)}}, self.env)

    def stop(self):
        return run([], {"hook_event_name": "Stop", "session_id": self.sid, "stop_hook_active": False}, self.env)

    def send(self, files):
        return run([], {"hook_event_name": "PreToolUse", "tool_name": "SendUserFile", "session_id": self.sid,
                        "tool_input": {"files": files}}, self.env)


class TestBlocks(Base):
    def test_written_page_blocks_stop_until_chain(self):
        rc, _ = self.write_hook(); self.assertEqual(rc, 0)
        rc, out = self.stop()
        self.assertEqual(rc, 2, out)
        self.assertIn("missing", out)
        self.assertIn("brief.md", out)

    def test_script_generated_page_is_caught_after_bash(self):
        # PreToolUse Bash stamps the marker, a script writes a page, PostToolUse Bash scans the cwd
        run([], {"hook_event_name": "PreToolUse", "tool_name": "Bash", "session_id": self.sid,
                 "tool_input": {"command": "python3 build.py"}, "cwd": str(self.inst)}, self.env)
        time.sleep(0.05)
        gen = self.round / "Seam-laptop.html"
        gen.write_text("<html><body>generated</body></html>")
        rc, _ = run([], {"hook_event_name": "PostToolUse", "tool_name": "Bash", "session_id": self.sid,
                         "tool_input": {"command": "python3 build.py"}, "cwd": str(self.inst)}, self.env)
        self.assertEqual(rc, 0)
        png = self.round / "Seam-laptop.png"; png.write_bytes(b"png")
        rc, out = self.send([str(png)])
        self.assertEqual(rc, 2, out)
        self.assertIn("Seam-laptop.html", out)

    def test_bash_that_shows_a_page_is_blocked(self):
        """Blocked = a command that puts the page in front of a human. Rendering it for
        the chain's own measurement is a chain step, not a showing (see
        TestChainStepsRun). Scar 2026-09-15: this test used shoot3.py, which made the
        gate block steps 5, 9 and 10 of the command it enforces."""
        self.write_hook()
        for cmd in ("open -a Preview Pair-laptop.png", "vercel deploy --prod",
                    "open Pair-laptop.html"):
            rc, out = run([], {"hook_event_name": "PreToolUse", "tool_name": "Bash", "session_id": self.sid,
                               "tool_input": {"command": cmd}, "cwd": str(self.inst)}, self.env)
            self.assertEqual(rc, 2, f"{cmd} should be blocked: {out}")
        rc, _ = run([], {"hook_event_name": "PreToolUse", "tool_name": "Bash", "session_id": self.sid,
                         "tool_input": {"command": "git status"}, "cwd": str(self.inst)}, self.env)
        self.assertEqual(rc, 0)

    def test_playwright_tool_blocked_while_open(self):
        self.write_hook()
        rc, _ = run([], {"hook_event_name": "PreToolUse", "tool_name": "mcp__playwright__browser_navigate",
                         "session_id": self.sid, "tool_input": {"url": "http://127.0.0.1:1/x.html"}}, self.env)
        self.assertEqual(rc, 2)

    def test_paraphrased_brief_refused(self):
        self.complete_chain(brief_ok=False)
        rc, out = run(["seal", str(self.round)], env=self.env)
        self.assertEqual(rc, 2, out)
        self.assertIn("does not quote verbatim", out)

    def test_stale_receipt_after_edit(self):
        self.complete_chain()
        rc, out = run(["seal", str(self.round)], env=self.env); self.assertEqual(rc, 0, out)
        self.write_hook()
        rc, _ = self.stop(); self.assertEqual(rc, 0)
        self.page.write_text(self.page.read_text() + "<!-- edited -->")
        rc, out = self.stop()
        self.assertEqual(rc, 2, out)
        self.assertIn("stale", out)

    def test_standard_fail_blocks(self):
        self.complete_chain()
        (self.round / "standard.json").write_text(json.dumps([{"page": self.page.name, "sha256": self.sha(self.page), "pass": False}]))
        rc, out = run(["seal", str(self.round)], env=self.env)
        self.assertEqual(rc, 2, out)
        self.assertIn("standard.json", out)

    def test_internal_html_ignored(self):
        internal = self.inst / "q-system" / "output" / "daily-schedule-2026-09-15.html"
        internal.parent.mkdir(parents=True); internal.write_text("<html></html>")
        run([], {"hook_event_name": "PostToolUse", "tool_name": "Write", "session_id": self.sid,
                 "tool_input": {"file_path": str(internal)}}, self.env)
        rc, _ = self.stop(); self.assertEqual(rc, 0)


class TestCraftBar(Base):
    """The BAR half. CHAIN_FILES and the standard block are a FLOOR: they see word
    count, type sizes and the absence of AI-default tells. On 2026-09-15 a round
    cleared every one of them while shipping three wireframes with zero imagery, zero
    motion and zero depth, which is the failure
    q-system/lessons/a-defect-absence-gate-is-a-floor-not-a-finish-line.md already
    named (from cole-gtm's rca-design-room-skipped-premium-tools-2026-06-25). These
    tests exist so a wireframe is NON-COMPLIANT rather than merely less ambitious."""

    def craft_cfg(self, **over):
        """Re-write the instance config with a craft block on."""
        cfg = json.loads((self.inst / "design-chain.json").read_text())
        cfg["craft"] = {"tier": "craft", "require_craft_manifest": True,
                        "require_impeccable": True, **over}
        (self.inst / "design-chain.json").write_text(json.dumps(cfg))

    def test_craft_manifest_required_when_config_asks(self):
        self.complete_chain()
        self.craft_cfg()
        rc, out = run(["seal", str(self.round)], env=self.env)
        self.assertEqual(rc, 2, out)
        self.assertIn("craft-manifest.json", out)

    def test_empty_craft_manifest_is_a_gap_not_a_pass(self):
        """Declaring nothing must not be the cheapest way to comply. cole-gtm's
        check_technique_parity.py takes the same position: a manifest with no
        techniques verified nothing."""
        self.complete_chain()
        self.craft_cfg()
        (self.round / "craft-manifest.json").write_text(json.dumps({"techniques": []}))
        (self.round / "checks" / "impeccable.txt").write_text("ran\n")
        rc, out = run(["seal", str(self.round)], env=self.env)
        self.assertEqual(rc, 2, out)
        self.assertIn("declares no techniques", out)

    def test_impeccable_check_required_when_config_asks(self):
        self.complete_chain()
        self.craft_cfg()
        (self.round / "craft-manifest.json").write_text(json.dumps(
            {"techniques": [{"id": "t", "technique": "x", "role": "hero",
                             "import": ["gsap"], "applied": ["gsap.to"]}]}))
        rc, out = run(["seal", str(self.round)], env=self.env)
        self.assertEqual(rc, 2, out)
        self.assertIn("impeccable", out)

    def test_declared_technique_absent_from_the_page_blocks(self):
        """The TZOREF failure: a technique named in the manifest and used nowhere."""
        self.complete_chain()
        self.craft_cfg()
        (self.round / "craft-manifest.json").write_text(json.dumps(
            {"techniques": [{"id": "scroll-reveal", "technique": "GSAP reveal",
                             "role": "the mismatch", "import": ["gsap"],
                             "applied": ["ScrollTrigger"]}]}))
        (self.round / "checks" / "impeccable.txt").write_text("ran\n")
        rc, out = run(["seal", str(self.round)], env=self.env)
        self.assertEqual(rc, 2, out)
        self.assertIn("scroll-reveal", out)

    def test_wireframe_tier_is_declared_not_assumed(self):
        """A round may be built at wireframe tier for a copy test, but it has to SAY
        so. An undeclared tier defaults to the required one, so silence is not the
        cheap path."""
        self.complete_chain()
        self.craft_cfg(tier="wireframe")
        rc, out = run(["seal", str(self.round)], env=self.env)
        self.assertEqual(rc, 0, out)

    def test_round_may_declare_wireframe_with_a_reason(self):
        """A copy-test round opts out WITHOUT lowering the instance default for every
        future round. The reason is mandatory so it reads as a labelled exception."""
        self.complete_chain()
        self.craft_cfg()
        (self.round / CRAFT_MANIFEST).write_text(json.dumps(
            {"tier": "wireframe", "reason": "structure and copy test; judged by the "
                                            "comprehension gate, never shown as a design"}))
        rc, out = run(["seal", str(self.round)], env=self.env)
        self.assertEqual(rc, 0, out)

    def test_round_wireframe_declaration_without_a_reason_is_refused(self):
        self.complete_chain()
        self.craft_cfg()
        (self.round / CRAFT_MANIFEST).write_text(json.dumps({"tier": "wireframe"}))
        rc, out = run(["seal", str(self.round)], env=self.env)
        self.assertEqual(rc, 2, out)
        self.assertIn("no reason", out)

    def test_technique_citing_an_untorn_down_reference_is_refused(self):
        """The input half. A manifest filled from the builder's own prior passes the parity
        check trivially, because he built what he imagined. Every technique must cite a page
        that was actually opened and written up."""
        self.complete_chain()
        self.craft_cfg(require_grounding="refs/TEARDOWN.md")
        (self.inst / "refs").mkdir(exist_ok=True)
        (self.inst / "refs" / "TEARDOWN.md").write_text("# Teardown\n\n## trailofbits.com\n"
                                                        "mono counter bar of real numbers\n")
        (self.round / "checks" / "impeccable.txt").write_text("ran\n")
        (self.round / CRAFT_MANIFEST).write_text(json.dumps({"techniques": [
            {"id": "invented", "technique": "a move from nowhere", "role": "hero",
             "reference": "my own head", "import": ["gsap"], "applied": ["gsap"]}]}))
        rc, out = run(["seal", str(self.round)], env=self.env)
        self.assertEqual(rc, 2, out)
        self.assertIn("not in TEARDOWN.md", out)

    def test_technique_citing_a_torn_down_reference_passes(self):
        self.complete_chain()
        self.craft_cfg(require_grounding="refs/TEARDOWN.md")
        (self.inst / "refs").mkdir(exist_ok=True)
        (self.inst / "refs" / "TEARDOWN.md").write_text("# Teardown\n\n## trailofbits.com\n"
                                                        "mono counter bar of real numbers\n")
        (self.round / "checks" / "impeccable.txt").write_text("ran\n")
        self.page.write_text(self.page.read_text().replace(
            "</body>", "<script src='gsap.min.js'></script></body>"))
        (self.round / "standard.json").write_text(json.dumps(
            [{"page": self.page.name, "sha256": self.sha(self.page), "pass": True}]))
        (self.round / CRAFT_MANIFEST).write_text(json.dumps({"techniques": [
            {"id": "counter-bar", "technique": "real numbers as chrome", "role": "header",
             "reference": "trailofbits.com", "import": ["gsap"], "applied": ["gsap"]}]}))
        rc, out = run(["seal", str(self.round)], env=self.env)
        self.assertEqual(rc, 0, out)

    def test_missing_teardown_blocks_when_grounding_required(self):
        self.complete_chain()
        self.craft_cfg(require_grounding="refs/TEARDOWN.md")
        (self.round / "checks" / "impeccable.txt").write_text("ran\n")
        (self.round / CRAFT_MANIFEST).write_text(json.dumps({"techniques": [
            {"id": "x", "technique": "y", "role": "z", "reference": "trailofbits.com",
             "import": ["gsap"], "applied": ["gsap"]}]}))
        rc, out = run(["seal", str(self.round)], env=self.env)
        self.assertEqual(rc, 2, out)
        self.assertIn("TEARDOWN.md", out)

    def test_new_exemplar_not_in_the_narrative_blocks(self):
        """Founder: 'you should do that every time I put in more exemplars.' Adding a site
        and not re-reading the group is the forgettable step, so it blocks."""
        self.complete_chain()
        self.craft_cfg(require_grounding="refs/NARRATIVE.md")
        refs = self.inst / "refs"; refs.mkdir(exist_ok=True)
        (refs / "NARRATIVE.md").write_text("# Narrative\n\n## stripe.com\nbig light type\n")
        (refs / "exemplars.json").write_text(json.dumps({"exemplars": [
            {"url": "https://stripe.com"}, {"url": "https://figma.com"}]}))
        (self.round / "checks" / "impeccable.txt").write_text("ran\n")
        (self.round / CRAFT_MANIFEST).write_text(json.dumps({"techniques": [
            {"id": "t", "technique": "x", "role": "hero", "reference": "stripe.com",
             "import": ["gsap"], "applied": ["gsap"]}]}))
        rc, out = run(["seal", str(self.round)], env=self.env)
        self.assertEqual(rc, 2, out)
        self.assertIn("figma.com", out)

    def test_narrative_covering_every_exemplar_passes(self):
        self.complete_chain()
        self.craft_cfg(require_grounding="refs/NARRATIVE.md")
        refs = self.inst / "refs"; refs.mkdir(exist_ok=True)
        (refs / "NARRATIVE.md").write_text(
            "# Narrative\n\nstripe.com and figma.com both set big light type.\n")
        (refs / "exemplars.json").write_text(json.dumps({"exemplars": [
            {"url": "https://stripe.com"}, {"url": "https://www.figma.com"}]}))
        (self.round / "checks" / "impeccable.txt").write_text("ran\n")
        self.page.write_text(self.page.read_text().replace(
            "</body>", "<script src='gsap.min.js'></script></body>"))
        (self.round / "standard.json").write_text(json.dumps(
            [{"page": self.page.name, "sha256": self.sha(self.page), "pass": True}]))
        (self.round / CRAFT_MANIFEST).write_text(json.dumps({"techniques": [
            {"id": "t", "technique": "x", "role": "hero", "reference": "stripe.com",
             "import": ["gsap"], "applied": ["gsap"]}]}))
        rc, out = run(["seal", str(self.round)], env=self.env)
        self.assertEqual(rc, 0, out)

    def test_untagged_weakness_blocks(self):
        """Measured 2026-09-15: three sealed rounds carried 11 findings marked WEAK and
        nothing required an answer. Two of them were the exact defects the founder and the
        reader gate then caught."""
        self.complete_chain()
        self.craft_cfg(require_dispositions=True, require_craft_manifest=False,
                       require_impeccable=False)
        (self.round / "critique.md").write_text(
            "".join(f"## {d}\n" + "".join(f"{i}. answer\n" for i in range(1,10))
                    for d in "ABC") +
            "4. Could this be anyone else's page? WEAK. it could.\n")
        rc, out = run(["seal", str(self.round)], env=self.env)
        self.assertEqual(rc, 2, out)
        self.assertIn("no tag", out)

    def test_tagged_weakness_without_a_disposition_blocks(self):
        self.complete_chain()
        self.craft_cfg(require_dispositions=True, require_craft_manifest=False,
                       require_impeccable=False)
        (self.round / "critique.md").write_text(
            "".join(f"## {d}\n" + "".join(f"{i}. answer\n" for i in range(1,10))
                    for d in "ABC") +
            "4. WEAK[one-column] every round has been a single column.\n")
        rc, out = run(["seal", str(self.round)], env=self.env)
        self.assertEqual(rc, 2, out)
        self.assertIn("one-column", out)

    def test_disposition_without_a_reason_blocks(self):
        self.complete_chain()
        self.craft_cfg(require_dispositions=True, require_craft_manifest=False,
                       require_impeccable=False)
        (self.round / "critique.md").write_text(
            "".join(f"## {d}\n" + "".join(f"{i}. answer\n" for i in range(1,10))
                    for d in "ABC") +
            "4. WEAK[one-column] single column again.\n\n- one-column: DEFERRED\n")
        rc, out = run(["seal", str(self.round)], env=self.env)
        self.assertEqual(rc, 2, out)
        self.assertIn("no\n", out) if False else self.assertIn("reason", out)

    def test_answered_weakness_seals(self):
        self.complete_chain()
        self.craft_cfg(require_dispositions=True, require_craft_manifest=False,
                       require_impeccable=False)
        (self.round / "critique.md").write_text(
            "".join(f"## {d}\n" + "".join(f"{i}. answer\n" for i in range(1,10))
                    for d in "ABC") +
            "4. WEAK[one-column] single column again.\n\n"
            "- one-column: CARRIED to the next round, which varies composition not material.\n")
        rc, out = run(["seal", str(self.round)], env=self.env)
        self.assertEqual(rc, 0, out)

    def test_founder_question_not_in_the_ledger_blocks(self):
        """Same class as the weak finding, found by sweeping for it: 'founder decision'
        appeared 9 times across the chain's artifacts with no executable reading any of
        them back. A gate cannot make him decide; it can refuse to let a question be
        raised and buried."""
        self.complete_chain()
        self.craft_cfg(require_dispositions=True, require_craft_manifest=False,
                       require_impeccable=False)
        (self.round / "critique.md").write_text(
            "".join(f"## {d}\n" + "".join(f"{i}. answer\n" for i in range(1,10))
                    for d in "ABC") +
            "\n9. The typeface is a purchase. FOUNDER[typeface]\n")
        rc, out = run(["seal", str(self.round)], env=self.env)
        self.assertEqual(rc, 2, out)
        self.assertIn("typeface", out)

    def test_founder_question_in_the_ledger_seals(self):
        self.complete_chain()
        self.craft_cfg(require_dispositions=True, require_craft_manifest=False,
                       require_impeccable=False)
        (self.round.parent / "OPEN-DECISIONS.md").write_text(
            "# Open decisions\n\n## typeface\nAll six exemplars bought one. Blocks: the final type pick.\n")
        (self.round / "critique.md").write_text(
            "".join(f"## {d}\n" + "".join(f"{i}. answer\n" for i in range(1,10))
                    for d in "ABC") +
            "\n9. The typeface is a purchase. FOUNDER[typeface]\n")
        rc, out = run(["seal", str(self.round)], env=self.env)
        self.assertEqual(rc, 0, out)

    def test_copied_brief_blocks(self):
        """Measured 2026-09-15: five consecutive rounds carried the identical brief (sha
        c3b247f7b6), so four of them did the read-the-owners step by copying a file. The
        anchor check proves the brief CONTAINS the quotes and cannot tell a written brief
        from a copied one."""
        self.complete_chain()
        self.craft_cfg(require_fresh_brief=True, require_craft_manifest=False,
                       require_impeccable=False)
        prev = self.round.parent / "r0"; prev.mkdir()
        (prev / "brief.md").write_text((self.round / "brief.md").read_text())
        rc, out = run(["seal", str(self.round)], env=self.env)
        self.assertEqual(rc, 2, out)
        self.assertIn("byte-identical", out)

    def test_brief_written_this_round_seals(self):
        self.complete_chain()
        self.craft_cfg(require_fresh_brief=True, require_craft_manifest=False,
                       require_impeccable=False)
        prev = self.round.parent / "r0"; prev.mkdir()
        (prev / "brief.md").write_text("# an earlier round's brief\n")
        rc, out = run(["seal", str(self.round)], env=self.env)
        self.assertEqual(rc, 0, out)

    def test_withdrawn_round_needs_a_reason(self):
        self.complete_chain()
        self.craft_cfg(require_grounding="refs/TEARDOWN.md")
        (self.round / CRAFT_MANIFEST).write_text(json.dumps({"status": "withdrawn"}))
        rc, out = run(["seal", str(self.round)], env=self.env)
        self.assertEqual(rc, 2, out)
        self.assertIn("no reason", out)

    def test_withdrawn_round_with_a_reason_is_out_of_scope(self):
        """The gate stops unfinished work being SHOWN. A round the founder already
        rejected will not be shown, so holding it to the bar only forces a faked receipt."""
        self.complete_chain()
        self.craft_cfg(require_grounding="refs/TEARDOWN.md")
        (self.round / CRAFT_MANIFEST).write_text(json.dumps(
            {"status": "withdrawn", "reason": "founder rejected it; superseded by the next round"}))
        rc, out = run(["seal", str(self.round)], env=self.env)
        self.assertEqual(rc, 0, out)

    def test_craft_block_absent_leaves_the_chain_as_it_was(self):
        """An instance with no craft block is not silently held to the new bar."""
        self.complete_chain()
        rc, out = run(["seal", str(self.round)], env=self.env)
        self.assertEqual(rc, 0, out)

    def test_satisfied_craft_manifest_seals(self):
        self.complete_chain()
        self.craft_cfg()
        self.page.write_text(self.page.read_text().replace(
            "</body>", "<script src='gsap.min.js'></script>"
            "<script>gsap.to('.mark',{opacity:1})</script></body>"))
        (self.round / "standard.json").write_text(json.dumps(
            [{"page": self.page.name, "sha256": self.sha(self.page), "pass": True}]))
        (self.round / "craft-manifest.json").write_text(json.dumps(
            {"techniques": [{"id": "reveal", "technique": "GSAP reveal on the mismatch",
                             "role": "the mismatch", "import": ["gsap"],
                             "applied": [r"gsap\.to"]}]}))
        (self.round / "checks" / "impeccable.txt").write_text("ran, control blocked\n")
        rc, out = run(["seal", str(self.round)], env=self.env)
        self.assertEqual(rc, 0, out)


class TestChainStepsRun(Base):
    """The steps of /design-chain must be runnable WHILE the chain is open, because
    running them is how it closes. Scar 2026-09-15: BASH_SHOW_RE and the
    page-name-in-command clause blocked design-standard-check.py (step 5, which writes
    standard.json), the serve it measures against, shoot/gate_icp (step 9) and `seal`
    itself (step 10). The chain was unreachable from an agent session and no test saw it,
    because test_full_chain_passes_send_and_stop hand-wrote the receipts instead of
    running the steps."""

    def bash(self, cmd):
        return run([], {"hook_event_name": "PreToolUse", "tool_name": "Bash", "session_id": self.sid,
                        "tool_input": {"command": cmd}, "cwd": str(self.inst)}, self.env)

    def test_chain_steps_run_while_chain_is_open(self):
        self.write_hook()
        steps = [
            f"python3 design-standard-check.py {self.page} --url http://127.0.0.1:8793/{self.page.name}",
            "(python3 -m http.server 8793 --directory . >/dev/null 2>&1 &)",
            "python3 shoot.py",
            f"python3 gate_icp.py {self.round} Pair-laptop.png --n 3",
            f"python3 design-chain-gate.py seal {self.round}",
        ]
        for cmd in steps:
            rc, out = self.bash(cmd)
            self.assertEqual(rc, 0, f"chain step must not be blocked: {cmd}\n{out}")

    def test_seal_is_reachable_end_to_end(self):
        """The whole point: with the chain complete but unsealed, the seal command
        survives its own PreToolUse hook and then actually seals."""
        self.write_hook()
        self.complete_chain()
        rc, out = self.bash(f"python3 design-chain-gate.py seal {self.round}")
        self.assertEqual(rc, 0, out)
        rc, out = run(["seal", str(self.round)], env=self.env)
        self.assertEqual(rc, 0, out)
        rc, out = self.stop()
        self.assertEqual(rc, 0, out)


class TestPasses(Base):
    def test_full_chain_passes_send_and_stop(self):
        self.complete_chain()
        rc, out = run(["seal", str(self.round)], env=self.env); self.assertEqual(rc, 0, out)
        self.write_hook()
        png = self.round / "Pair-laptop.png"; png.write_bytes(b"png")
        rc, out = self.send([str(png)]); self.assertEqual(rc, 0, out)
        rc, out = self.stop(); self.assertEqual(rc, 0, out)

    def test_exemplar_must_be_cited_when_present(self):
        self.complete_chain()
        ex = self.inst / "site" / "design" / "exemplars"; ex.mkdir(parents=True)
        (ex / "approved-pair-2026-09-15.png").write_bytes(b"png")
        rc, out = run(["seal", str(self.round)], env=self.env)
        self.assertEqual(rc, 2, out); self.assertIn("exemplars", out)
        d = self.round / "directions.md"; d.write_text(d.read_text() + "\ncites approved-pair-2026-09-15.png\n")
        rc, out = run(["seal", str(self.round)], env=self.env); self.assertEqual(rc, 0, out)

    def test_founder_override_env(self):
        self.write_hook()
        rc, _ = run([], {"hook_event_name": "Stop", "session_id": self.sid}, {**self.env, "DESIGN_CHAIN_ALLOW": "1"})
        self.assertEqual(rc, 0)

    def test_unreadable_payload_fails_open(self):
        e = dict(os.environ); e.update(self.env)
        r = subprocess.run([sys.executable, str(GATE)], input="not json", capture_output=True, text=True, env=e)
        self.assertEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()


class TestSealedRoundsAreHistory(Base):
    """A round that already sealed does not un-seal when the ruleset later tightens.

    Scar 2026-09-15: adding a fifth owner and require_fresh_brief turned the Stop
    gate red on all five rounds that had already sealed, so the session could not
    end at all. A gate red on its own population gets switched off, and a switched
    off gate protects nothing (same lesson as plan-lint's dated grandfather and
    linear-filer-label-lint's measured 8-files-1-compliant).
    """

    def _seal_then_tighten(self):
        """Seal under today's config, then add an owner anchor the brief cannot quote."""
        self.complete_chain()
        rc, out = run(["seal", str(self.round)], env=self.env)
        self.assertEqual(rc, 0, out)
        cfgp = self.inst / "design-chain.json"
        cfg = json.loads(cfgp.read_text())
        (self.inst / "canonical" / "pain-model.md").write_text('"word": "(dribble the data in)"\n')
        cfg["owners"].append({"file": "canonical/pain-model.md", "anchors": ['"word": "\\(dribble the data in\\)"']})
        cfgp.write_text(json.dumps(cfg))

    def test_stop_gate_does_not_unseal_a_round_when_a_new_owner_is_added(self):
        self._seal_then_tighten()
        self.write_hook()
        rc, out = self.stop()
        self.assertEqual(rc, 0, f"a sealed, unedited page was re-litigated by the new anchor:\n{out}")

    def test_an_explicit_reseal_still_runs_todays_full_bar(self):
        self._seal_then_tighten()
        rc, out = run(["seal", str(self.round)], env=self.env)
        self.assertEqual(rc, 2, "re-seal ignored the new owner anchor")
        self.assertIn("pain-model.md", out)

    def test_editing_the_page_after_seal_re_opens_the_whole_chain(self):
        self._seal_then_tighten()
        self.page.write_text("<html><body><h1>Different headline entirely.</h1></body></html>")
        self.write_hook()
        rc, out = self.stop()
        self.assertEqual(rc, 2, "an edited page kept its grandfather")
        self.assertIn("pain-model.md", out)


class TestGapCheck(Base):
    """The design chain had no DISTANCE check, only absence checks, and a deliberately
    bland page passed all three of them (RCA rca-design-chain-passes-bland-2026-09-15.md).
    design-gap-check.py measures a built page against the captured exemplars; this is the
    gate half that makes its verdict block a seal."""

    def enable(self):
        cfgp = self.inst / "design-chain.json"
        cfg = json.loads(cfgp.read_text())
        cfg.setdefault("craft", {})["require_gap_check"] = True
        cfgp.write_text(json.dumps(cfg))

    def gap(self, below=(), sha=None):
        (self.round / "checks").mkdir(exist_ok=True)
        (self.round / "checks" / "gap.json").write_text(json.dumps({
            "_exemplars": ["a", "b", "c"],
            "pages": {self.page.name: {"sha256": sha or self.sha(self.page),
                                       "axes": {}, "below_floor": list(below)}},
        }))

    def test_missing_gap_receipt_blocks(self):
        self.enable(); self.complete_chain()
        rc, out = run(["seal", str(self.round)], env=self.env)
        self.assertEqual(rc, 2)
        self.assertIn("gap.json", out)

    def test_an_axis_below_floor_blocks_and_names_it(self):
        self.enable(); self.complete_chain()
        self.gap(below=["distinct background colours: 0, and the least any exemplar reaches is 3"])
        rc, out = run(["seal", str(self.round)], env=self.env)
        self.assertEqual(rc, 2)
        self.assertIn("background colours", out)

    def test_a_stale_gap_receipt_blocks(self):
        self.enable(); self.complete_chain()
        self.gap(sha="0" * 64)
        rc, out = run(["seal", str(self.round)], env=self.env)
        self.assertEqual(rc, 2)
        self.assertIn("stale", out.lower())

    def test_every_floor_met_and_fresh_seals(self):
        self.enable(); self.complete_chain()
        self.gap()
        rc, out = run(["seal", str(self.round)], env=self.env)
        self.assertEqual(rc, 0, out)

    def test_an_instance_that_has_not_opted_in_is_unaffected(self):
        self.complete_chain()  # no require_gap_check, no gap.json
        rc, out = run(["seal", str(self.round)], env=self.env)
        self.assertEqual(rc, 0, out)


class TestNotARound(Base):
    """Some HTML under the design tree is a TOOL, not a round page: a known-slop control, a
    type specimen, a fixture. The gate treated each as a round of one with no brief and
    blocked, twice in one session, which is the pressure that makes someone route around a
    gate instead of using it. A directory may declare itself not-a-round, with a reason,
    and the declaration is refused where a real round lives."""

    def tool_dir(self, reason="a type specimen for the founder, not a page a visitor reaches"):
        d = self.inst / "site" / "design" / "references"
        d.mkdir(parents=True, exist_ok=True)
        page = d / "type-specimen.html"
        page.write_text("<html><body><h1>Specimen</h1></body></html>")
        if reason is not None:
            (d / ".not-a-round").write_text(reason + "\n")
        return page

    def write_of(self, page):
        return run([], {"hook_event_name": "PostToolUse", "tool_name": "Write",
                        "session_id": self.sid, "tool_input": {"file_path": str(page)}}, self.env)

    def test_a_declared_tool_directory_does_not_block(self):
        page = self.tool_dir()
        self.write_of(page)
        rc, out = self.stop()
        self.assertEqual(rc, 0, out)

    def test_without_the_marker_it_still_blocks(self):
        page = self.tool_dir(reason=None)
        self.write_of(page)
        rc, out = self.stop()
        self.assertEqual(rc, 2)
        self.assertIn("brief.md", out)

    def test_an_empty_marker_is_refused(self):
        page = self.tool_dir(reason="")
        self.write_of(page)
        rc, out = self.stop()
        self.assertEqual(rc, 2)
        self.assertIn("reason", out.lower())

    def test_the_marker_cannot_switch_off_a_real_round(self):
        # brief.md is what makes a directory a round. The first version of this test wrote
        # the marker into a directory that had none, so honouring it was CORRECT and the
        # test was wrong about what it was testing.
        (self.round / "brief.md").write_text("# Brief\n")
        (self.round / ".not-a-round").write_text("trying to skip the chain\n")
        self.write_hook()
        rc, out = self.stop()
        self.assertEqual(rc, 2, "a directory holding brief.md is a round and cannot opt out")
        self.assertIn("cannot declare itself not a round", out)
