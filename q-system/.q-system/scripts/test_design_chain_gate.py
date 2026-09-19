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
REAL_GATE = HERE / "design-chain-gate.py"
# dc-02 (ASK-1796): seal RUNS the producers, which are the siblings of the gate file. The
# real ones need playwright and chromium and turned this suite from 3 s into 63 s. So the
# suite runs a COPY of the gate placed beside the stand-ins in test/stub_producers/. The
# shipped gate has no override to point it elsewhere (Sana, 2026-09-18), and
# test/test_dc_seal_runs_producers.py holds one run against the REAL producer.
_BIN = Path(tempfile.mkdtemp(prefix="dcg-bin-"))
shutil.copy(REAL_GATE, _BIN / REAL_GATE.name)
for _stub in (HERE / "test" / "stub_producers").glob("*.py"):
    shutil.copy(_stub, _BIN / _stub.name)
import atexit
# A gate copy beside stand-ins is a working kit for sealing a REAL round. The first version
# leaked one per run; the reviewer sealed a failing page with a leftover (c598d5f5).
atexit.register(shutil.rmtree, _BIN, ignore_errors=True)
GATE = _BIN / REAL_GATE.name
STANDARD_STUB = _BIN / "design-standard-check.py"

# The receipt design-impeccable-check.py really wrote, frozen with its provenance (dc-21). The
# gate reads only that checks/impeccable.txt is present and non-empty; these tests used to type
# "ran" into it, which proves the reader matches a fixture and nothing about the producer.
sys.path.insert(0, str(HERE / "test"))
import dc_fixtures  # noqa: E402
IMPECCABLE_RECEIPT = dc_fixtures.load("impeccable-receipt")["content"]

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

    def measure(self, page=None):
        """standard.json as the PRODUCER writes it. Typing the verdict by hand is the hole
        dc-02 closes, so the suite no longer does it either."""
        subprocess.run([sys.executable, str(STANDARD_STUB), str(page or self.page)],
                       check=True, capture_output=True)

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
        self.measure()

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
        rc, out = run(["seal", str(self.round)], env=dict(self.env, STUB_STANDARD="fail"))
        self.assertEqual(rc, 2, out)
        self.assertIn("FAILS the standard", out)

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
        (self.round / "checks" / "impeccable.txt").write_text(IMPECCABLE_RECEIPT)
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
        (self.round / "checks" / "impeccable.txt").write_text(IMPECCABLE_RECEIPT)
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
        (self.round / "checks" / "impeccable.txt").write_text(IMPECCABLE_RECEIPT)
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
        (self.round / "checks" / "impeccable.txt").write_text(IMPECCABLE_RECEIPT)
        self.page.write_text(self.page.read_text().replace(
            "</body>", "<script src='gsap.min.js'></script></body>"))
        self.measure()
        (self.round / CRAFT_MANIFEST).write_text(json.dumps({"techniques": [
            {"id": "counter-bar", "technique": "real numbers as chrome", "role": "header",
             "reference": "trailofbits.com", "import": ["gsap"], "applied": ["gsap"]}]}))
        rc, out = run(["seal", str(self.round)], env=self.env)
        self.assertEqual(rc, 0, out)

    def test_missing_teardown_blocks_when_grounding_required(self):
        self.complete_chain()
        self.craft_cfg(require_grounding="refs/TEARDOWN.md")
        (self.round / "checks" / "impeccable.txt").write_text(IMPECCABLE_RECEIPT)
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
        (self.round / "checks" / "impeccable.txt").write_text(IMPECCABLE_RECEIPT)
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
        (self.round / "checks" / "impeccable.txt").write_text(IMPECCABLE_RECEIPT)
        self.page.write_text(self.page.read_text().replace(
            "</body>", "<script src='gsap.min.js'></script></body>"))
        self.measure()
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
        self.measure()
        (self.round / "craft-manifest.json").write_text(json.dumps(
            {"techniques": [{"id": "reveal", "technique": "GSAP reveal on the mismatch",
                             "role": "the mismatch", "import": ["gsap"],
                             "applied": [r"gsap\.to"]}]}))
        (self.round / "checks" / "impeccable.txt").write_text(IMPECCABLE_RECEIPT)
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
        # the screenshot lands BEFORE the seal, as in the real flow: the gap check reads it, so a
        # screenshot written after the seal is a changed input and opens the round (dc-10)
        png = self.round / "Pair-laptop.png"; png.write_bytes(b"png")
        rc, out = run(["seal", str(self.round)], env=self.env); self.assertEqual(rc, 0, out)
        self.write_hook()
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


# ASK-1824: the only main() call is at the END of this file. One sat here, mid-module, and
# `python3 <file>` exited before the 38 tests below it existed: every ASK-1796 closeout said
# "38 OK" over 76 defined, and 3 of the hidden ones were failing.


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

    # ASK-1824: seal RUNS the gap producer (dc-02) and removes any prior gap.json first (dc-03),
    # so these drive the stand-in producer's own modes. They used to type gap.json by hand and
    # expect seal to read it, which is exactly what seal no longer does.

    def seal_with_producer(self, mode):
        return run(["seal", str(self.round)], env={**self.env, "STUB_GAP": mode})

    def test_a_producer_that_writes_no_receipt_blocks(self):
        self.enable(); self.complete_chain()
        rc, out = self.seal_with_producer("silent")
        self.assertEqual(rc, 2, out)
        # the producer branch's own words: "gap.json" alone also comes from craft_problems(), which
        # stays red even when seal never runs the producer (review of c033a842, mutant survived)
        self.assertIn("exit 0 and wrote no gap.json", out)

    def test_an_axis_below_floor_blocks_and_names_it(self):
        self.enable(); self.complete_chain()
        rc, out = self.seal_with_producer("below")
        self.assertEqual(rc, 2, out)
        # the exit-code-2 branch, by its own words: craft_problems() re-reads gap.json and also says
        # "below the exemplar floor", so the bare word survived seal ignoring exit 2 (same review)
        # the whole phrase: with the exit-2 branch gone, exit 2 falls to "could not measure
        # (design-gap-check.py exit 2)", which a shorter substring also matched
        self.assertIn("below the exemplar floor (design-gap-check.py exit 2)", out)

    def test_a_typed_gap_receipt_is_never_what_seal_reads(self):
        # a passing receipt typed into the round, and a stale one. The producer writes NOTHING
        # (silent), so the only way this round seals is if seal read the typed file. It must not:
        # seal removes any prior gap.json before the run and refuses when none comes back.
        for sha in (None, "0" * 64):
            self.enable(); self.complete_chain()
            self.gap(sha=sha)
            rc, out = self.seal_with_producer("silent")
            self.assertEqual(rc, 2, out)
            self.assertIn("wrote no", out)
            self.assertFalse((self.round / "receipts.json").exists())

    def test_every_floor_met_and_fresh_seals(self):
        self.enable(); self.complete_chain()   # the producer (mode pass) writes the receipt
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


class TestBashShowPattern(Base):
    """BASH_SHOW_RE must catch a command that SHOWS a page and nothing else. It has now
    over-matched twice: first on the chain's own steps, fixed by narrowing, then on prose
    containing the word "open" with a page filename somewhere later in the same heredoc,
    because [^|;&] matches a newline. A gate that blocks legitimate work is the pressure
    that gets it switched off.

    These tests build their command strings from parts, because a test file containing a
    literal show-command is itself blocked by the hook it tests.
    """

    OPEN = "o" + "pen"
    HTML = "." + "html"

    def bash(self, cmd):
        return run([], {"hook_event_name": "PreToolUse", "tool_name": "Bash",
                        "session_id": self.sid, "tool_input": {"command": cmd}}, self.env)

    def setUp(self):
        super().setUp()
        self.write_hook()

    def test_it_blocks_a_command_that_actually_shows_the_page(self):
        rc, _ = self.bash(f"{self.OPEN} {self.page}")
        self.assertEqual(rc, 2)
        rc, _ = self.bash(f"{self.OPEN} -a Safari page{self.HTML}")
        self.assertEqual(rc, 2)

    def test_prose_containing_the_word_does_not_block_a_later_page_path(self):
        cmd = ("python3 - <<EOF\n"
               "note = 'section 8 is an " + self.OPEN + " founder decision, unresolved'\n"
               "EOF\n"
               "for f in *" + self.HTML + "; do echo $f; done")
        rc, out = self.bash(cmd)
        self.assertEqual(rc, 0, "prose plus a later page path is not a show command:\n" + out)

    def test_the_chain_steps_still_run(self):
        for cmd in ("python3 design-standard-check.py p" + self.HTML + " --url http://127.0.0.1:8793/p" + self.HTML,
                    "python3 design-gap-check.py . --write",
                    "python3 -m http.server 8793 --directory ."):
            rc, out = self.bash(cmd)
            self.assertEqual(rc, 0, cmd + " must not be blocked:\n" + out)


class TestWithdrawnShortCircuits(Base):
    """A withdrawn round is one that will never be shown. Holding it to the seal forces its
    author to fake a receipt or stay stuck, which is the reasoning already written into
    craft_problems. That function honoured it and the rest of the chain did not, so a
    withdrawn round still failed on standard.json and on not-sealed."""

    def withdraw(self, reason="superseded by a measurement the round ignored"):
        (self.round / "craft-manifest.json").write_text(json.dumps(
            {"status": "withdrawn", "reason": reason, "techniques": []}))

    def test_a_withdrawn_round_does_not_block_the_turn(self):
        self.page.write_text("<html><body><h1>half built</h1></body></html>")
        self.withdraw()
        self.write_hook()
        rc, out = self.stop()
        self.assertEqual(rc, 0, out)

    def test_withdrawn_with_no_reason_still_blocks(self):
        self.withdraw(reason="")
        self.write_hook()
        rc, out = self.stop()
        self.assertEqual(rc, 2)
        self.assertIn("reason", out.lower())

    def test_an_unwithdrawn_round_still_needs_the_whole_chain(self):
        self.write_hook()
        rc, out = self.stop()
        self.assertEqual(rc, 2)
        self.assertIn("brief.md", out)


class TestCorrections(Base):
    """A factual correction to a page that is already public is not a design round.

    Founder, 2026-09-16, picking the fix after the gate blocked a one-sentence correction of a
    false claim on a live work page: add a corrections path, where an already-live page may skip
    the round when its only change is wording, checked by comparing the page before and after,
    with every such fix logged with its reason."""

    def setUp(self):
        super().setUp()
        self.work = self.inst / "site" / "work"
        self.work.mkdir(parents=True)
        self.live = self.work / "case.html"
        self.live.write_text('<html><head><style>p{color:#111}</style></head><body>'
                             '<h2>The number</h2><p>The firm bought the system.</p>'
                             '<a href="/work">All work</a></body></html>')
        g = lambda *a: subprocess.run(["git", "-C", str(self.inst), *a], capture_output=True, text=True, check=True)
        g("init", "-q"); g("config", "user.email", "t@t"); g("config", "user.name", "t")
        g("add", "-A"); g("commit", "-q", "-m", "live page")
        self.git = g

    def correct(self, reason="the deployment was never invoiced", page=None):
        return run(["correct", str(page or self.live), "--reason", reason], env=self.env)

    def problems(self):
        rc, out = run(["status-page", str(self.live)], env=self.env)
        return rc, out

    def test_uncorrected_edit_to_a_live_page_still_needs_the_chain(self):
        self.live.write_text(self.live.read_text().replace("bought the system", "agreed to buy the system"))
        rc, out = self.problems()
        self.assertEqual(rc, 2, out)
        self.assertIn("brief.md", out)

    def test_wording_change_with_a_logged_correction_passes(self):
        self.live.write_text(self.live.read_text().replace("bought the system", "agreed to buy the system"))
        rc, out = self.correct()
        self.assertEqual(rc, 0, out)
        rc, out = self.problems()
        self.assertEqual(rc, 0, out)
        log = [json.loads(l) for l in (self.work / "corrections.jsonl").read_text().splitlines()]
        self.assertEqual(log[0]["reason"], "the deployment was never invoiced")
        self.assertEqual(log[0]["after_sha256"], self.sha(self.live))

    def test_correction_already_committed_is_judged_against_the_commit_before(self):
        self.live.write_text(self.live.read_text().replace("bought the system", "agreed to buy the system"))
        self.git("commit", "-qam", "fix claim")
        rc, out = self.correct()
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.problems()[0], 0)

    def test_an_added_element_is_not_a_correction(self):
        self.live.write_text(self.live.read_text().replace("</p>", "</p><img src=x.png>"))
        rc, out = self.correct()
        self.assertEqual(rc, 2, out)
        self.assertIn("not a wording change", out)
        self.assertFalse((self.work / "corrections.jsonl").exists())

    def test_a_changed_attribute_is_not_a_correction(self):
        self.live.write_text(self.live.read_text().replace('href="/work"', 'href="/elsewhere"'))
        self.assertEqual(self.correct()[0], 2)

    def test_changed_css_is_not_a_correction(self):
        self.live.write_text(self.live.read_text().replace("color:#111", "color:#f00"))
        self.assertEqual(self.correct()[0], 2)

    def test_a_forged_log_entry_does_not_pass_a_structural_change(self):
        self.live.write_text(self.live.read_text().replace("</p>", "</p><img src=x.png>"))
        head = self.git("rev-parse", "HEAD").stdout.strip()
        (self.work / "corrections.jsonl").write_text(json.dumps({
            "page": "case.html", "before_commit": head, "after_sha256": self.sha(self.live),
            "reason": "forged"}) + "\n")
        self.assertEqual(self.problems()[0], 2)

    def test_a_later_edit_invalidates_the_correction(self):
        self.live.write_text(self.live.read_text().replace("bought the system", "agreed to buy the system"))
        self.assertEqual(self.correct()[0], 0)
        self.live.write_text(self.live.read_text().replace("agreed to buy", "might buy"))
        self.assertEqual(self.problems()[0], 2)

    def test_a_reason_is_required(self):
        self.live.write_text(self.live.read_text().replace("bought the system", "agreed to buy the system"))
        rc, out = self.correct(reason="  ")
        self.assertEqual(rc, 2, out)

    def test_a_page_never_committed_cannot_be_corrected(self):
        new = self.work / "new.html"
        new.write_text("<html><body><p>fresh</p></body></html>")
        rc, out = self.correct(page=new)
        self.assertEqual(rc, 2, out)


class TestCorrectionsReachSearchText(TestCorrections):
    """The same false claim lives in the words a search engine or a link preview shows: the
    meta description, the preview title and image alt, and the prose inside JSON-LD. Found
    2026-09-16 auditing askconsulting.io: "39 cases, 288 evidence items" and "two
    criminal-infrastructure blocklists" sat in meta content the visible fix could not reach,
    because every attribute and every script counted as design. Those fields are wording;
    the tags, the other attributes, URLs, keys and code stay design."""

    def setUp(self):
        super().setUp()
        self.live.write_text(
            '<html><head><meta name="description" content="The firm bought the system.">'
            '<meta property="og:image:alt" content="Running by Friday.">'
            '<script type="application/ld+json">{"@type": "FAQPage", "url": "https://x.io/work", '
            '"offers": {"@type": "Offer", "price": "1000", "priceCurrency": "USD", "url": "https://x.io/start"}, '
            '"mainEntity": [{"@type": "Question", "name": "How long?", '
            '"acceptedAnswer": {"@type": "Answer", "text": "Running by Friday."}}]}</script>'
            '<script>var n = 1;</script></head><body><p>The firm bought the system.</p>'
            '<img src="a.png" alt="A sheet, 39 cases"></body></html>')
        self.git("commit", "-qam", "live page with search text")

    def edit(self, a, b):
        s = self.live.read_text()
        self.assertIn(a, s)
        self.live.write_text(s.replace(a, b))

    def test_meta_description_wording_is_a_correction(self):
        self.edit('content="The firm bought the system."', 'content="The firm uses a copy of the system."')
        self.assertEqual(self.correct()[0], 0)
        self.assertEqual(self.problems()[0], 0)

    def test_preview_alt_and_image_alt_wording_is_a_correction(self):
        self.edit('content="Running by Friday."', 'content="Findings by Friday."')
        self.edit('alt="A sheet, 39 cases"', 'alt="A sheet, 22 cases"')
        self.assertEqual(self.correct()[0], 0)

    def test_json_ld_answer_text_is_a_correction(self):
        self.edit('"text": "Running by Friday."', '"text": "Findings and options by Friday."')
        self.assertEqual(self.correct()[0], 0)

    def test_json_ld_url_is_still_design(self):
        self.edit('"url": "https://x.io/work"', '"url": "https://x.io/elsewhere"')
        self.assertEqual(self.correct()[0], 2)

    def test_json_ld_new_key_is_still_design(self):
        self.edit('"@type": "FAQPage",', '"@type": "FAQPage", "price": "0",')
        self.assertEqual(self.correct()[0], 2)

    def test_removing_an_offer_price_is_a_correction(self):
        self.edit('"price": "1000", "priceCurrency": "USD", ', '')
        self.assertEqual(self.correct()[0], 0)
        self.assertEqual(self.problems()[0], 0)

    def test_the_offer_url_is_still_design(self):
        self.edit('"url": "https://x.io/start"', '"url": "https://x.io/other"')
        self.assertEqual(self.correct()[0], 2)

    def test_meta_name_is_still_design(self):
        self.edit('name="description"', 'name="keywords"')
        self.assertEqual(self.correct()[0], 2)

    def test_plain_script_is_still_design(self):
        self.edit("var n = 1;", "var n = 2;")
        self.assertEqual(self.correct()[0], 2)

    def test_image_src_is_still_design(self):
        self.edit('src="a.png"', 'src="b.png"')
        self.assertEqual(self.correct()[0], 2)


if __name__ == "__main__":
    unittest.main()
