#!/usr/bin/env python3
"""dc-13: proof.md has a shape the gate reads.

WHY. proof.md only had to exist: round A sealed with a one-character proof.md (RCA 2026-09-18).
With a `proof` block in design-chain.json naming the proof index, every artifact block (a `##`
block carrying a "Proof kind:" line) names a kind from the closed list and a record id that
resolves in that index, and proof.md holds at least one such block.

The shape follows real consulting rounds: `**Proof kind: reliability**` inside `##` blocks, and
index records written as bold list items ("- **Client A, Record 7.** ...").
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
INDEX = """# Proof Index

## Problem proof

- **Client A, Record 7.** A pasted clipboard overwrote the header. Strength: strong.
- **Client B, Record 3.** Two feeds disagreed on the same order. Strength: medium.
"""


def load_gate():
    spec = importlib.util.spec_from_file_location("dc13_gate", GATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Proof(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="dc13-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.inst = self.tmp / "inst"
        (self.inst / "audit").mkdir(parents=True)
        (self.inst / "audit" / "INDEX.md").write_text(INDEX)
        self.cfg_path = self.inst / "design-chain.json"
        self.cfg = {"project": "dc13", "owners": [], "proof": {"index": "audit/INDEX.md"}}
        self.cfg_path.write_text(json.dumps(self.cfg))
        self.rd = self.inst / "site" / "design" / "r1"
        self.rd.mkdir(parents=True)
        (self.rd / "brief.md").write_text("brief\n")

    def proof(self, text):
        (self.rd / "proof.md").write_text(text)
        return load_gate().proof_problems(self.rd, self.cfg, self.cfg_path)

    def test_a_block_with_a_kind_and_a_record_that_resolves_passes(self):
        self.assertEqual(self.proof("## The hero\n\n**Proof kind: problem.** Client A, Record 7 shows it.\n"), [])

    def test_a_one_character_proof_refuses(self):
        probs = self.proof("x\n")
        self.assertTrue(any("no artifact block" in p for p in probs), probs)

    def test_a_kind_outside_the_closed_list_refuses(self):
        probs = self.proof("## The hero\n\n**Proof kind: vibes.** Client A, Record 7.\n")
        self.assertTrue(any("'vibes'" in p and "closed list" in p for p in probs), probs)

    def test_a_record_the_index_does_not_hold_refuses(self):
        probs = self.proof("## The hero\n\n**Proof kind: problem.** Client A, Record 99.\n")
        self.assertTrue(any("The hero" in p and "no record" in p for p in probs), probs)

    def test_commentary_blocks_without_a_kind_are_not_artifacts(self):
        self.assertEqual(self.proof("# Proof\n\n## What this means\n\nNothing to cite here.\n\n"
                                    "## The hero\n\n**Proof kind: problem.** Client B, Record 3.\n"), [])

    def test_every_artifact_block_is_checked_not_only_the_first(self):
        probs = self.proof("## A\n\n**Proof kind: problem.** Client A, Record 7.\n\n"
                           "## B\n\n**Proof kind: capability.** no record named\n")
        self.assertTrue(any("'B'" in p for p in probs), probs)
        self.assertFalse(any("'A'" in p for p in probs), probs)

    def test_an_index_inside_the_round_refuses(self):
        (self.rd / "INDEX.md").write_text(INDEX)
        self.cfg["proof"] = {"index": "site/design/r1/INDEX.md"}
        probs = self.proof("## The hero\n\n**Proof kind: problem.** Client A, Record 7.\n")
        self.assertTrue(any("inside the round" in p for p in probs), probs)

    def test_without_a_proof_block_the_shape_is_not_required(self):
        self.cfg.pop("proof")
        self.assertEqual(self.proof("x\n"), [])

    def test_seal_refuses_a_one_character_proof(self):
        # RED FIRST: proof.md only had to exist
        (self.rd / "proof.md").write_text("x\n")
        (self.rd / "Home-laptop.html").write_text("<html><body><p>x</p></body></html>")
        env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_PROJECT_DIR", "DESIGN_CHAIN_ALLOW")}
        env["DESIGN_CHAIN_STATE"] = str(self.tmp / "state")
        r = subprocess.run([sys.executable, str(GATE), "seal", str(self.rd)], capture_output=True, text=True,
                           env=env, timeout=600)
        out = r.stdout + r.stderr
        self.assertEqual(r.returncode, 2, out)
        self.assertIn("no artifact block", out)


if __name__ == "__main__":
    unittest.main()
