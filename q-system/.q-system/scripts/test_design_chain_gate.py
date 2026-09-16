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
