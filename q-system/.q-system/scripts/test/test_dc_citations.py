#!/usr/bin/env python3
"""dc-12: a cited repo file must have been opened this session, and seal requires that record.

WHY. A craft manifest or proof.md could name any repo file as its source, and nothing checked that
the session that wrote it ever opened the file (RCA 2026-09-18, S3/C4). The gate's PostToolUse
branch now reads the session transcript with read-first-gate.py's opened(), and writes
citations.json keyed to the manifest and proof bytes. No transcript means no record, never a pass.

The REAL gate: its hook fed a fixture transcript on stdin, and one real seal.
"""
import hashlib
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
    spec = importlib.util.spec_from_file_location("dc12_gate", GATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Citations(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="dc12-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo = self.tmp / "repo"
        (self.repo / "canon").mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True, timeout=60)
        (self.repo / "canon" / "pain.md").write_text("the one pain\n")
        (self.repo / "design-chain.json").write_text(json.dumps({"project": "dc12", "owners": []}))
        self.rd = self.repo / "site" / "design" / "r1"
        self.rd.mkdir(parents=True)
        (self.rd / "brief.md").write_text("brief\n")
        self.manifest = self.rd / "craft-manifest.json"
        self.cite("canon/pain.md")

    def cite(self, ref):
        self.manifest.write_text(json.dumps({"techniques": [{"id": "t1", "reference": ref}]}))

    def transcript(self, *read_paths):
        t = self.tmp / "session.jsonl"
        rows = [{"message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": "Read", "input": {"file_path": str(p)}}]}} for p in read_paths]
        t.write_text("".join(json.dumps(r) + "\n" for r in rows))
        return t

    def hook(self, transcript=None, target=None):
        payload = {"hook_event_name": "PostToolUse", "tool_name": "Write", "session_id": "s-dc12",
                   "tool_input": {"file_path": str(target or self.manifest)}}
        if transcript is not None:
            payload["transcript_path"] = str(transcript)
        env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_PROJECT_DIR", "DESIGN_CHAIN_ALLOW")}
        env["DESIGN_CHAIN_STATE"] = str(self.tmp / "state")
        r = subprocess.run([sys.executable, str(GATE)], input=json.dumps(payload), capture_output=True,
                           text=True, env=env, timeout=120)
        return r.returncode, r.stdout + r.stderr

    def problems(self):
        return load_gate().citation_problems(self.rd)

    def test_a_citation_the_session_opened_is_recorded_and_passes(self):
        rc, out = self.hook(self.transcript(self.repo / "canon" / "pain.md"))
        self.assertEqual(rc, 0, out)
        rec = json.loads((self.rd / "citations.json").read_text())
        self.assertEqual(rec["cited"], ["canon/pain.md"])
        self.assertEqual(rec["unopened"], [])
        self.assertEqual(rec["session_id"], "s-dc12")
        self.assertEqual(self.problems(), [])

    def test_a_citation_the_session_never_opened_refuses_by_name(self):
        self.hook(self.transcript(self.repo / "design-chain.json"))
        probs = self.problems()
        self.assertTrue(any("canon/pain.md" in p and "never opened" in p for p in probs), probs)

    def test_no_transcript_is_no_record_never_a_pass(self):
        self.hook(self.transcript(self.repo / "canon" / "pain.md"))
        self.hook(None)                       # a later write the hook cannot read the session for
        self.assertFalse((self.rd / "citations.json").exists())
        self.assertTrue(any("no citation record" in p for p in self.problems()), self.problems())

    def test_a_manifest_edited_after_the_record_is_stale(self):
        self.hook(self.transcript(self.repo / "canon" / "pain.md"))
        self.cite("canon/pain.md + stripe.com")
        self.assertTrue(any("stale" in p for p in self.problems()), self.problems())

    def test_a_round_that_cites_no_repo_file_needs_no_record(self):
        self.cite("stripe.com + figma.com")
        self.assertEqual(self.problems(), [])

    def test_a_path_in_proof_md_counts_as_a_citation(self):
        self.cite("stripe.com")
        (self.rd / "proof.md").write_text("Home-laptop.html: the pain is quoted from canon/pain.md\n")
        # a session that opened something else, not the cited file (an empty transcript is no record)
        rc, out = self.hook(self.transcript(self.repo / "design-chain.json"), target=self.rd / "proof.md")
        self.assertEqual(rc, 0, out)
        self.assertTrue(any("canon/pain.md" in p and "never opened" in p for p in self.problems()), self.problems())

    def tool_transcript(self, *uses):
        t = self.tmp / "session.jsonl"
        rows = [{"message": {"role": "assistant", "content": [{"type": "tool_use", "name": n, "input": i}]}}
                for n, i in uses]
        t.write_text("".join(json.dumps(r) + "\n" for r in rows))
        return t

    def unopened_after(self, *uses):
        self.hook(self.tool_transcript(*uses))
        return json.loads((self.rd / "citations.json").read_text())["unopened"]

    def test_the_write_that_makes_the_citation_does_not_vouch_for_it(self):
        # adv-1: the Write's content holds the cited path
        self.assertEqual(self.unopened_after(("Write", {"file_path": str(self.manifest),
                                                        "content": self.manifest.read_text()})), ["canon/pain.md"])

    def test_mentioning_the_path_is_not_reading_it(self):
        # adv-2
        self.assertEqual(self.unopened_after(("Bash", {"command": "echo canon/pain.md"}),
                                             ("Grep", {"pattern": "canon/pain.md"})), ["canon/pain.md"])

    def test_reading_a_longer_path_is_not_reading_the_cited_one(self):
        # adv-3, std-1
        (self.repo / "canon" / "pain.md.bak").write_text("old\n")
        self.assertEqual(self.unopened_after(("Read", {"file_path": str(self.repo / "canon" / "pain.md.bak")})),
                         ["canon/pain.md"])

    def test_a_line_suffix_is_still_a_citation(self):
        # adv-4
        self.cite("canon/pain.md:40")
        self.assertTrue(any("no citation record" in p for p in self.problems()), self.problems())

    def test_an_absolute_path_inside_the_repo_is_still_a_citation(self):
        # adv-5
        self.cite("stripe.com")
        (self.rd / "proof.md").write_text(f"quoted from {self.repo / 'canon' / 'pain.md'}\n")
        self.assertTrue(any("no citation record" in p for p in self.problems()), self.problems())

    def test_writing_the_cited_file_is_not_reading_it(self):
        # a Write that names the file (authoring the "source") is not opening it (mutant D1 survived)
        self.assertEqual(self.unopened_after(("Write", {"file_path": str(self.repo / "canon" / "pain.md"),
                                                        "content": "a source written to be cited\n"})),
                         ["canon/pain.md"])

    def test_a_repo_between_the_round_and_the_config_does_not_hide_citations(self):
        # git init in site/design made it the toplevel, so canon/pain.md stopped resolving (mutant D4 survived)
        subprocess.run(["git", "init", "-q", str(self.rd.parent)], check=True, timeout=60)
        self.assertTrue(any("no citation record" in p for p in self.problems()), self.problems())

    def test_a_repo_nested_in_the_round_refuses(self):
        # adv-6
        subprocess.run(["git", "init", "-q", str(self.rd)], check=True, timeout=60)
        self.assertTrue(any("holds its own .git" in p for p in self.problems()), self.problems())

    def test_seal_refuses_a_cited_file_with_no_record(self):
        # RED FIRST: seal never asked whether a cited file was opened
        (self.rd / "Home-laptop.html").write_text("<html><body><p>x</p></body></html>")
        env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_PROJECT_DIR", "DESIGN_CHAIN_ALLOW")}
        env["DESIGN_CHAIN_STATE"] = str(self.tmp / "state")
        r = subprocess.run([sys.executable, str(GATE), "seal", str(self.rd)], capture_output=True, text=True,
                           env=env, timeout=600)
        out = r.stdout + r.stderr
        self.assertEqual(r.returncode, 2, out)
        self.assertIn("no citation record", out)


if __name__ == "__main__":
    unittest.main()
