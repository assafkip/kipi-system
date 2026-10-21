#!/usr/bin/env python3
"""dc-16: decoration is measured, then removed or re-bound.

WHY. Measured 2026-09-19 over 67 rounds on disk (65 sealed): the critique line count (C5) caught 0
real rounds, and pushed a builder to copy 18 answers forward; it is DELETED. The byte-copy brief
check (C6) caught 4 real copies (2026-09-15) and one changed byte defeats it, because it read a file
the builder writes. Sana 2026-09-19: re-bind it to the session transcript. With require_fresh_brief,
every owner file in design-chain.json was Read in the session that wrote brief.md; the hook records
that in brief-reads.json keyed to the brief's bytes.
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
    spec = importlib.util.spec_from_file_location("dc16_gate", GATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class RefusalNamesWhatItCut(unittest.TestCase):
    def test_a_refusal_longer_than_the_cap_says_how_much_it_cut(self):
        # block() printed the first 40 lines and stopped, which reads as "those 40 are all of it",
        # so with many open pages some were never named to the operator (PR #374 round 4, minor)
        gate = load_gate()
        import io
        from contextlib import redirect_stderr
        buf = io.StringIO()
        with redirect_stderr(buf):
            rc = gate.block([f"page-{i}.html: no brief.md" for i in range(46)])
        self.assertEqual(rc, 2)
        self.assertIn("6 more line(s) not shown", buf.getvalue())
        short = io.StringIO()
        with redirect_stderr(short):
            gate.block(["page-0.html: no brief.md"])
        self.assertNotIn("not shown", short.getvalue())


class RemovedNamesStayGone(unittest.TestCase):
    def test_the_deleted_checks_are_gone(self):
        src = GATE.read_text()
        for name in ("copied_brief_problems", "NINE_QUESTIONS", "numbered answers", "byte-identical"):
            self.assertNotIn(name, src, name)


class BriefReads(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="dc16-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.inst = self.tmp / "inst"
        (self.inst / "canon").mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(self.inst)], check=True, timeout=60)
        (self.inst / "canon" / "pain.md").write_text("the one pain\n")
        (self.inst / "canon" / "voice.md").write_text("the voice\n")
        self.cfg = {"project": "dc16", "craft": {"require_fresh_brief": True},
                    "owners": [{"file": "canon/pain.md", "anchors": []}, {"file": "canon/voice.md", "anchors": []}]}
        self.write_cfg()
        self.rd = self.inst / "site" / "design" / "r1"
        self.rd.mkdir(parents=True)
        self.brief = self.rd / "brief.md"
        self.brief.write_text("brief quoting the owners\n")

    def write_cfg(self):
        self.cfg_path = self.inst / "design-chain.json"
        self.cfg_path.write_text(json.dumps(self.cfg))

    def transcript(self, *read_paths):
        t = self.tmp / "session.jsonl"
        rows = [{"message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": "Read",
             "input": p if isinstance(p, dict) else {"file_path": str(p)}}]}} for p in read_paths]
        t.write_text("".join(json.dumps(r) + "\n" for r in rows))
        return t

    def hook(self, transcript=None):
        payload = {"hook_event_name": "PostToolUse", "tool_name": "Write", "session_id": "s-dc16",
                   "tool_input": {"file_path": str(self.brief)}}
        if transcript is not None:
            payload["transcript_path"] = str(transcript)
        env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_PROJECT_DIR", "DESIGN_CHAIN_ALLOW")}
        env["DESIGN_CHAIN_STATE"] = str(self.tmp / "state")
        r = subprocess.run([sys.executable, str(GATE)], input=json.dumps(payload), capture_output=True,
                           text=True, env=env, timeout=120)
        return r.returncode, r.stdout + r.stderr

    def problems(self):
        return load_gate().brief_read_problems(self.rd, self.cfg, self.cfg_path)

    def test_a_brief_written_after_reading_every_owner_passes(self):
        rc, out = self.hook(self.transcript(self.inst / "canon" / "pain.md", self.inst / "canon" / "voice.md"))
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.problems(), [])

    def test_an_owner_the_session_never_read_refuses_by_name(self):
        self.hook(self.transcript(self.inst / "canon" / "pain.md"))
        probs = self.problems()
        self.assertTrue(any("canon/voice.md" in p and "never read" in p for p in probs), probs)
        self.assertFalse(any("canon/pain.md" in p for p in probs), probs)

    def test_no_transcript_is_no_record_never_a_pass(self):
        self.hook(self.transcript(self.inst / "canon" / "pain.md", self.inst / "canon" / "voice.md"))
        self.hook(None)
        self.assertTrue(any("no brief-reads record" in p for p in self.problems()), self.problems())

    def test_a_brief_edited_after_the_record_is_stale(self):
        self.hook(self.transcript(self.inst / "canon" / "pain.md", self.inst / "canon" / "voice.md"))
        self.brief.write_text("a different brief\n")
        self.assertTrue(any("stale" in p for p in self.problems()), self.problems())

    def test_an_owner_added_after_the_record_is_stale(self):
        self.hook(self.transcript(self.inst / "canon" / "pain.md", self.inst / "canon" / "voice.md"))
        (self.inst / "canon" / "icp.md").write_text("icp\n")
        self.cfg["owners"].append({"file": "canon/icp.md", "anchors": []})
        self.write_cfg()
        self.assertTrue(any("stale" in p for p in self.problems()), self.problems())

    def craft_brief_probs(self):
        page = self.rd / "Home-laptop.html"
        page.write_text("<html><body><p>x</p></body></html>")
        return [p for p in load_gate().craft_problems(self.rd, page, self.cfg, self.cfg_path) if "brief" in p]

    def test_require_fresh_brief_is_what_turns_the_record_on(self):
        self.assertTrue(any("no brief-reads record" in p for p in self.craft_brief_probs()))
        self.cfg["craft"] = {"require_fresh_brief": False, "tier": "craft"}
        self.assertEqual(self.craft_brief_probs(), [])

    def test_the_critique_line_count_is_gone(self):
        # C5 deleted: a critique with no numbered answers no longer draws a count refusal
        (self.rd / "critique.md").write_text("prose only\n")
        (self.rd / "directions.md").write_text("# A\n# B\n# C\n")
        page = self.rd / "Home-laptop.html"
        page.write_text("<html><body><p>x</p></body></html>")
        probs = load_gate().chain_problems(page, honor_seal=False)
        self.assertFalse(any("critique.md has" in p for p in probs), probs)

    def test_a_record_copied_from_another_round_refuses(self):
        # adv-1: the 2026-09-15 copy attack, with the record copied too
        self.hook(self.transcript(self.inst / "canon" / "pain.md", self.inst / "canon" / "voice.md"))
        r2 = self.rd.parent / "r2"
        r2.mkdir()
        for name in ("brief.md", "brief-reads.json"):
            shutil.copy(self.rd / name, r2 / name)
        probs = load_gate().brief_read_problems(r2, self.cfg, self.cfg_path)
        self.assertTrue(any("another round" in p for p in probs), probs)

    def test_a_partial_read_is_not_reading_in_full(self):
        # adv-4
        (self.inst / "canon" / "voice.md").write_text("line\n" * 50)
        self.hook(self.transcript(self.inst / "canon" / "pain.md",
                                  {"file_path": str(self.inst / "canon" / "voice.md"), "limit": 1}))
        self.assertTrue(any("canon/voice.md" in p for p in self.problems()), self.problems())

    def test_chunked_reads_that_cover_the_file_count(self):
        (self.inst / "canon" / "voice.md").write_text("line\n" * 50)
        v = str(self.inst / "canon" / "voice.md")
        self.hook(self.transcript(self.inst / "canon" / "pain.md",
                                  {"file_path": v, "offset": 1, "limit": 30}, {"file_path": v, "offset": 31, "limit": 30}))
        self.assertEqual(self.problems(), [])

    def test_chunked_reads_with_a_gap_do_not_count(self):
        (self.inst / "canon" / "voice.md").write_text("line\n" * 50)
        v = str(self.inst / "canon" / "voice.md")
        self.hook(self.transcript(self.inst / "canon" / "pain.md",
                                  {"file_path": v, "offset": 1, "limit": 10}, {"file_path": v, "offset": 20, "limit": 100}))
        self.assertTrue(any("canon/voice.md" in p for p in self.problems()), self.problems())

    def test_an_owner_entry_with_no_file_refuses(self):
        # adv-7
        self.cfg["owners"] = [{"path": "canon/pain.md"}]
        self.write_cfg()
        self.assertTrue(any("owner" in p and "file" in p for p in self.problems()), self.problems())

    def test_seal_refuses_a_brief_with_no_read_record(self):
        # RED FIRST: seal only compared the brief's bytes with sibling rounds
        (self.rd / "Home-laptop.html").write_text("<html><body><p>x</p></body></html>")
        env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_PROJECT_DIR", "DESIGN_CHAIN_ALLOW")}
        env["DESIGN_CHAIN_STATE"] = str(self.tmp / "state")
        r = subprocess.run([sys.executable, str(GATE), "seal", str(self.rd)], capture_output=True, text=True,
                           env=env, timeout=600)
        out = r.stdout + r.stderr
        self.assertEqual(r.returncode, 2, out)
        self.assertIn("no brief-reads record", out)


if __name__ == "__main__":
    unittest.main()
