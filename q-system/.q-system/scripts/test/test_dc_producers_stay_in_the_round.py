#!/usr/bin/env python3
"""ASK-1837: seal's browser producers refuse any request outside the served round.

WHY. design-standard-check.py and design-gap-check.py rendered the served round in chromium with no
request routing, so a page could pull a stylesheet from another origin that changed what they
measured, while seal's byte compare and receipt saw only round files. Reproduced for the reader gate
in ASK-1836 (three green pages screenshotted red). Here: the round's own stylesheet sets 9px text,
and a stylesheet from another origin sets it to 18px. The standard producer measured 18px and the
round sealed on bytes that fail.

The REAL gate and the REAL producers at their tracked paths, a real browser.
"""
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
sys.path.insert(0, str(HERE))
import dc_fixtures  # noqa: E402

SCRIPTS = HERE.parent
GATE = SCRIPTS / "design-chain-gate.py"
GAP = SCRIPTS / "design-gap-check.py"
PAGE = ("<!doctype html><html><head><meta charset='utf-8'><link rel='stylesheet' href='shared.css'>"
        "<link rel='stylesheet' href='FOREIGN/big.css'></head><body><h1>Two records that should agree</h1>"
        "<p>A small firm retypes the same client data into three systems.</p>"
        "<p><a href='#book'>Book a 30-minute call</a></p></body></html>")
SMALL = "body{font:9px/1.5 Georgia,serif;margin:40px} h1{font-size:9px} a{font-size:9px}"


def foreign_server(test):
    class Big(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = b"body,p,a,h1{font-size:18px !important}"
            self.send_response(200)
            self.send_header("Content-Type", "text/css")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Big)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    test.addCleanup(srv.server_close)
    test.addCleanup(srv.shutdown)
    return f"http://127.0.0.1:{srv.server_address[1]}"


class Base(unittest.TestCase):
    def setUp(self):
        try:
            import playwright  # noqa: F401
        except ImportError:
            msg = "playwright is not installed: the PRODUCTION path was NOT exercised"
            if os.environ.get("DC_REQUIRE_REAL_PRODUCERS") == "1":
                self.fail(msg)
            self.skipTest(msg)
        self.tmp = Path(tempfile.mkdtemp(prefix="dc1837-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.inst = self.tmp / "inst"
        self.rd = self.inst / "site" / "design" / "r1"
        self.rd.mkdir(parents=True)
        self.foreign = foreign_server(self)
        (self.rd / "Home-laptop.html").write_text(PAGE.replace("FOREIGN", self.foreign))
        (self.rd / "shared.css").write_text(SMALL)

    def env(self):
        e = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_PROJECT_DIR", "DESIGN_CHAIN_ALLOW")}
        e["DESIGN_CHAIN_STATE"] = str(self.tmp / "state")
        return e


class TheStandardProducer(Base):
    def test_a_foreign_stylesheet_cannot_carry_a_failing_page_through_seal(self):
        (self.inst / "design-chain.json").write_text(json.dumps(
            {"project": "dc1837", "owners": [], "standard": {"min_body_px": 15}}))
        rd = self.rd
        (rd / "brief.md").write_text("brief\n")
        (rd / "directions.md").write_text("# A\n# B\n# C\n")
        (rd / "critique.md").write_text("".join(f"{i % 9 + 1}. considered\n" for i in range(27)))
        (rd / "proof.md").write_text("Home-laptop.html: proof\n")
        (rd / "checks").mkdir()
        (rd / "checks" / "bio_gate.txt").write_text("ok\n")
        (rd / "gate").mkdir()
        (rd / "gate" / "icp.md").write_text("answers\n")
        r = subprocess.run([sys.executable, str(GATE), "seal", str(rd)], capture_output=True, text=True,
                           env=self.env(), timeout=600)
        out = r.stdout + r.stderr
        self.assertEqual(r.returncode, 2, out)
        self.assertIn("outside the served round", out)
        self.assertIn(self.foreign.split("//", 1)[1], out)
        self.assertFalse((rd / "receipts.json").exists())


class TheGapProducer(Base):
    def test_a_foreign_stylesheet_makes_the_gap_producer_refuse_by_name(self):
        refs = self.tmp / "refs"
        refs.mkdir()
        for name in sorted(p.stem for p in dc_fixtures.FIXTURES.glob("exemplar-*.json")):
            (refs / (name.removeprefix("exemplar-") + ".json")).write_text(dc_fixtures.load(name)["content"])

        class Round(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *a):
                pass
        rd = self.rd
        handler = lambda *a, **k: Round(*a, directory=str(rd), **k)
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        r = subprocess.run([sys.executable, str(GAP), str(rd), "--url-base",
                            f"http://127.0.0.1:{srv.server_address[1]}", "--refs", str(refs)],
                           capture_output=True, text=True, env=self.env(), timeout=600)
        out = r.stdout + r.stderr
        self.assertEqual(r.returncode, 3, out)        # the gap producer's could-not-measure (dc-03)
        self.assertIn("outside the served round", out)
        self.assertIn(self.foreign.split("//", 1)[1], out)


if __name__ == "__main__":
    unittest.main()
