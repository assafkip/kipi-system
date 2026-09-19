#!/usr/bin/env python3
"""ASK-1838: the served round never hands the browser a file the seal does not bind.

WHY. Seal's served round served every file in the round, including the ones seal writes itself and
leaves out of its compare and digest (standard.json, checks/gap.json, checks/impeccable.txt,
receipts.json, corrections.jsonl). A page fetched 18px CSS it had hidden in standard.json, the
standard producer measured 18px and then overwrote standard.json with its verdict, and a 9px page
sealed COMPLETE (adversarial review of 14e1a54b, finding-2). Through checks/impeccable.txt the file
could even be emptied after the seal with the round still COMPLETE (finding-3). And a 404 at seal
time is not enough on its own: if the built site ships those files, a visitor's fetch succeeds, so a
page that references one refuses (Sana).

The REAL gate and producers, and the REAL reader gate, at their tracked paths; injected reader runner.
"""
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
READER = HERE.parent / "design-reader-gate.py"
SMALL = "body{font:9px/1.5 Georgia,serif;margin:40px} h1,p,a{font-size:9px}"
BIG = "body,p,a,h1{font-size:18px !important}"


def fetching_page(path, expr=None):
    return ("<!doctype html><html><head><meta charset='utf-8'><link rel='stylesheet' href='shared.css'>"
            "<script>fetch(" + (expr or "'" + path + "'") + ").then(r=>r.text()).then(t=>{var s=document.createElement('style');"
            "s.textContent=t;document.head.appendChild(s)})</script></head><body>"
            "<h1>Two records that should agree</h1><p>A small firm retypes the same client data.</p>"
            "<p><a href='#book'>Book a call</a></p></body></html>")


class Round(unittest.TestCase):
    def setUp(self):
        try:
            import playwright  # noqa: F401
        except ImportError:
            msg = "playwright is not installed: the PRODUCTION path was NOT exercised"
            if os.environ.get("DC_REQUIRE_REAL_PRODUCERS") == "1":
                self.fail(msg)
            self.skipTest(msg)
        self.tmp = Path(tempfile.mkdtemp(prefix="dc1838-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.inst = self.tmp / "inst"
        self.rd = self.inst / "site" / "design" / "r1"
        self.rd.mkdir(parents=True)
        (self.inst / "design-chain.json").write_text(json.dumps(
            {"project": "dc1838", "owners": [], "standard": {"min_body_px": 15}}))
        rd = self.rd
        (rd / "shared.css").write_text(SMALL)
        (rd / "brief.md").write_text("brief\n")
        (rd / "directions.md").write_text("# A\n# B\n# C\n")
        (rd / "critique.md").write_text("".join(f"{i % 9 + 1}. considered\n" for i in range(27)))
        (rd / "proof.md").write_text("Home-laptop.html: proof\n")
        (rd / "checks").mkdir()
        (rd / "checks" / "bio_gate.txt").write_text("ok\n")
        (rd / "gate").mkdir()
        (rd / "gate" / "icp.md").write_text("answers\n")

    def seal(self):
        env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_PROJECT_DIR", "DESIGN_CHAIN_ALLOW")}
        env["DESIGN_CHAIN_STATE"] = str(self.tmp / "state")
        r = subprocess.run([sys.executable, str(GATE), "seal", str(self.rd)], capture_output=True, text=True,
                           env=env, timeout=600)
        return r.returncode, r.stdout + r.stderr


class SealDoesNotServeWhatItDoesNotBind(Round):
    def test_css_hidden_in_standard_json_does_not_seal_a_failing_page(self):
        (self.rd / "standard.json").write_text(BIG)
        (self.rd / "Home-laptop.html").write_text(fetching_page("standard.json"))
        rc, out = self.seal()
        self.assertEqual(rc, 2, out)
        self.assertIn("standard.json", out)
        self.assertFalse((self.rd / "receipts.json").exists())

    def test_css_hidden_in_a_check_file_does_not_seal_a_failing_page(self):
        (self.rd / "checks" / "impeccable.txt").write_text(BIG)
        (self.rd / "Home-laptop.html").write_text(fetching_page("checks/impeccable.txt"))
        rc, out = self.seal()
        self.assertEqual(rc, 2, out)
        self.assertIn("checks/impeccable.txt", out)
        self.assertFalse((self.rd / "receipts.json").exists())

    def test_a_path_built_at_runtime_is_still_not_served(self):
        # the reference scan reads text, so a path assembled in JS passes it; only not serving the file holds
        (self.rd / "standard.json").write_text(BIG)
        (self.rd / "Home-laptop.html").write_text(fetching_page(None, "'stand'+'ard.'+'json'"))
        rc, out = self.seal()
        self.assertEqual(rc, 2, out)
        self.assertFalse((self.rd / "receipts.json").exists())

    def test_a_page_that_references_a_file_the_seal_writes_refuses_even_unfetched(self):
        # the deploy side: the built site ships the round, so a visitor's fetch would succeed
        (self.rd / "shared.css").write_text("body{font:18px/1.5 Georgia,serif;margin:40px}")
        (self.rd / "Home-laptop.html").write_text(
            "<!doctype html><html><head><meta charset='utf-8'><link rel='stylesheet' href='shared.css'>"
            "<script type='text/plain'>fetch('receipts.json')</script></head><body><h1>Two records</h1>"
            "<p><a href='#book'>Book a call</a></p></body></html>")
        rc, out = self.seal()
        self.assertEqual(rc, 2, out)
        self.assertIn("receipts.json", out)

    def test_a_comment_that_names_a_check_file_is_not_a_reference(self):
        # 8 real consulting stylesheets explain a choice with "(checks/gap.json)" inside a comment
        (self.rd / "shared.css").write_text(
            "body{font:18px/1.5 Georgia,serif;margin:40px} /* leaves 3 type sizes in the fold "
            "(checks/gap.json). */")
        (self.rd / "Home-laptop.html").write_text(
            "<!doctype html><html><head><meta charset='utf-8'><link rel='stylesheet' href='shared.css'>"
            "<!-- measured in standard.json --></head><body><h1>Two records</h1>"
            "<p><a href='#book'>Book a call</a></p></body></html>")
        rc, out = self.seal()
        self.assertEqual(rc, 0, out)

    def test_an_honest_page_still_seals(self):
        (self.rd / "shared.css").write_text("body{font:18px/1.5 Georgia,serif;margin:40px}")
        (self.rd / "standard.json").write_text("[]")
        (self.rd / "Home-laptop.html").write_text(
            "<!doctype html><html><head><meta charset='utf-8'><link rel='stylesheet' href='shared.css'>"
            "</head><body><h1>Two records</h1><p><a href='#book'>Book a call</a></p></body></html>")
        rc, out = self.seal()
        self.assertEqual(rc, 0, out)


class TheReaderGateFollowsTheSameList(Round):
    def test_the_reader_gate_does_not_serve_a_file_the_seal_does_not_bind(self):
        (self.rd / "standard.json").write_text(BIG)
        (self.rd / "Home-laptop.html").write_text(fetching_page("standard.json"))
        (self.inst / "persona.md").write_text("You run a small tax practice.\n")
        cfg = json.loads((self.inst / "design-chain.json").read_text())
        cfg["readers"] = {"persona_file": "persona.md", "n": 1}
        (self.inst / "design-chain.json").write_text(json.dumps(cfg))
        answers = self.tmp / "answers.json"
        answers.write_text(json.dumps({str(i): ("unknown" if i == 9 else "x") for i in range(1, 10)}))
        r = subprocess.run([sys.executable, str(READER), str(self.rd), "--config", str(self.inst / "design-chain.json"),
                            "--runner", "injected", "--answers", str(answers)],
                           capture_output=True, text=True, timeout=600)
        out = r.stdout + r.stderr
        self.assertEqual(r.returncode, 2, out)
        self.assertIn("standard.json", out)


if __name__ == "__main__":
    unittest.main()
