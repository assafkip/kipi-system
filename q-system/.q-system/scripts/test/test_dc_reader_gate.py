#!/usr/bin/env python3
"""dc-06: design-reader-gate.py lives in the skeleton, shoots the served page itself, and every
row carries the HTML and PNG shas and a provenance block.

WHY. The only reader gate lived in one instance (consulting's gate_icp.py) and read PNGs the round
supplied, so the readers could be shown a screenshot of a page other than the one being sealed,
and nothing on a row said which page bytes or which image the answers were about. Here the script
renders every page itself from the served round, at the configured viewports, hashes both, and
never opens a PNG from the round.

The REAL script at its tracked path with real playwright; the model call is the injected runner,
so no test spends one. The real-model run is recorded once in the closeout (Sana, 2026-09-19).
"""
import hashlib
import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "design-reader-gate.py"
PAGE = ("<!doctype html><html><head><meta charset='utf-8'><style>body{font:18px/1.6 Georgia,serif;"
        "margin:48px;color:#1a1a1a}</style></head><body><h1>Two records that should agree</h1>"
        "<p>A small firm retypes the same client data into three systems.</p>"
        "<p><a href='#book'>Book a 30-minute call</a></p></body></html>")
ANSWERS = ["yes, retyping", "workflow fixes", "fewer errors", "the example", "a week of fixes",
           "ops consultant", "STAY: clear", "nothing", "unknown"]


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


class Served:
    def __init__(self, directory: Path):
        class Quiet(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *a):
                pass
        handler = lambda *a, **k: Quiet(*a, directory=str(directory), **k)
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


class ReaderGate(unittest.TestCase):
    def setUp(self):
        try:
            import playwright  # noqa: F401
        except ImportError:
            msg = "playwright is not installed: the PRODUCTION path was NOT exercised"
            if os.environ.get("DC_REQUIRE_REAL_PRODUCERS") == "1":
                self.fail(msg)
            self.skipTest(msg)
        self.tmp = Path(tempfile.mkdtemp(prefix="dc06-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.inst = self.tmp / "inst"
        self.rd = self.inst / "site" / "design" / "r1"
        self.rd.mkdir(parents=True)
        self.page = self.rd / "Home-laptop.html"
        self.page.write_bytes(PAGE.encode())
        (self.inst / "canonical").mkdir()
        self.persona = self.inst / "canonical" / "persona.md"
        self.persona.write_text("You run a small tax practice. You are paid to be accurate.\n")
        self.config()
        self.answers = self.tmp / "answers.json"
        self.answers.write_text(json.dumps(ANSWERS))
        self.srv = Served(self.rd)
        self.addCleanup(self.srv.close)
        self.keep = self.tmp / "screens"

    def config(self, **readers):
        (self.inst / "design-chain.json").write_text(json.dumps({"project": "dc06", "owners": [], "readers": {
            "persona_file": "canonical/persona.md", "n": 1, **readers}}))

    def run_gate(self, *extra, url_base=None, env=None, runner="injected"):
        e = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
        e.update(env or {})
        args = [sys.executable, str(SCRIPT), str(self.rd), "--url-base", url_base or self.srv.base,
                "--config", str(self.inst / "design-chain.json"), "--runner", runner,
                "--keep-screens", str(self.keep)]
        if runner == "injected":
            args += ["--answers", str(self.answers)]
        r = subprocess.run(args + list(extra), capture_output=True, text=True, env=e, timeout=300)
        return r.returncode, r.stdout + r.stderr

    def rows(self):
        return [json.loads(l) for l in (self.rd / "gate" / "reader-runs.jsonl").read_text().splitlines()]

    def test_every_row_carries_the_page_sha_the_screenshot_sha_and_provenance(self):
        rc, out = self.run_gate()
        self.assertEqual(rc, 0, out)
        rows = self.rows()
        self.assertEqual(len(rows), 1, rows)
        r = rows[0]
        self.assertEqual(r["page"], "Home-laptop.html")
        self.assertEqual(r["html_sha256"], sha(PAGE.encode()))
        shots = sorted(self.keep.glob("*.png"))
        self.assertEqual(len(shots), 1, shots)
        self.assertEqual(r["png_sha256"], sha(shots[0].read_bytes()))
        self.assertEqual(r["answers"], ANSWERS)
        p = r["_provenance"]
        self.assertEqual(p["runner"], "injected")
        self.assertEqual(p["model"], "injected")
        self.assertEqual(p["persona_sha256"], sha(self.persona.read_bytes()))
        self.assertTrue(p["at"])

    def test_it_never_reads_a_png_the_round_supplied(self):
        decoy = self.rd / "Home-laptop.png"
        decoy.write_bytes(b"\x89PNG\r\n\x1a\n decoy the builder supplied")
        rc, out = self.run_gate()
        self.assertEqual(rc, 0, out)
        r = self.rows()[0]
        self.assertNotEqual(r["png_sha256"], sha(decoy.read_bytes()))
        self.assertEqual(r["png_sha256"], sha(next(self.keep.glob("*.png")).read_bytes()))

    def test_one_row_per_configured_viewport_each_with_its_own_screenshot(self):
        self.config(viewports=[[1440, 900], [390, 844]])
        rc, out = self.run_gate()
        self.assertEqual(rc, 0, out)
        rows = self.rows()
        self.assertEqual(sorted(tuple(r["viewport"]) for r in rows), [(390, 844), (1440, 900)])
        self.assertEqual(len({r["png_sha256"] for r in rows}), 2)

    def test_served_bytes_that_are_not_the_local_page_refuse(self):
        other = self.tmp / "other"
        other.mkdir()
        (other / "Home-laptop.html").write_text(PAGE.replace("agree", "differ"))
        srv = Served(other)
        self.addCleanup(srv.close)
        rc, out = self.run_gate(url_base=srv.base)
        self.assertEqual(rc, 2, out)
        self.assertIn("served bytes differ", out)

    def test_the_real_model_is_never_called_from_a_test(self):
        # PYTEST_CURRENT_TEST is how a test run is recognised; the claude runner refuses under it
        rc, out = self.run_gate(runner="claude", env={"PYTEST_CURRENT_TEST": "test_dc_reader_gate.py::x"})
        self.assertEqual(rc, 2, out)
        self.assertIn("refusing to call a model from a test", out)
        self.assertFalse((self.rd / "gate" / "reader-runs.jsonl").exists())

    def test_a_persona_file_that_is_missing_refuses(self):
        self.persona.unlink()
        rc, out = self.run_gate()
        self.assertEqual(rc, 2, out)
        self.assertIn("persona", out)


if __name__ == "__main__":
    unittest.main()
