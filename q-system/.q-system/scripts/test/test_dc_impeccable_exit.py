#!/usr/bin/env python3
"""dc-04: design-impeccable-check.py's exit code says what the pages did, and seal runs it.

WHY. The script computed `worst = max(worst, rc)` over the pages and never used it: it exited 0
whenever the negative control fired, so a page that raised an anti-pattern produced exit 0 and
a receipt, and the gate read only that checks/impeccable.txt was non-empty. Any text in that
file sealed, "ran" included (dc-21 replaced the typed ones in the suite; the gate still
trusted whatever was there). It also defaulted --url-base to a fixed port, so it could measure
a leftover server's round, the dc-03 finding-4 shape.

Exit contract after this change: 0 control fired and every page clean; 1 the control did not
fire; 2 could not run (no detector, no node, a detector crash, served bytes that are not the
local file); 3 at least one page flagged.

The script tests drive the REAL script at its tracked path with a stub DETECTOR (a node file
written here); the seal tests drive the REAL gate, the real producers and the real detector.
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
SCRIPTS = HERE.parent
SCRIPT = SCRIPTS / "design-impeccable-check.py"
REAL_GATE = SCRIPTS / "design-chain-gate.py"
REAL_DETECTOR = Path("~/projects/cole-gtm/.agents/skills/impeccable/scripts/detector/detect-antipatterns.mjs").expanduser()

STUB_DETECTOR = r"""
const t = process.argv[2] || '';
const env = process.env;
if (t.includes('impeccable-control')) {
  if (env.STUB_CONTROL === 'dead') { console.error('0 anti-patterns found.'); process.exit(0); }
  console.error('[gradient-text]\n2 anti-patterns found.'); process.exit(2);
}
const m = env.STUB_PAGES || 'clean';
if (m === 'flag') { console.error('[gradient-text] background-clip: text\n1 anti-pattern found.'); process.exit(2); }
if (m === 'crash') { console.error('TypeError: boom'); process.exit(1); }
process.exit(0);
"""
CLEAN = ("<!doctype html><html><head><meta charset='utf-8'><style>body{font:18px/1.6 Georgia,serif;"
         "margin:48px;color:#1a1a1a}</style></head><body><h1>Two records that should agree</h1>"
         "<p>A small firm retypes the same client data into three systems.</p>"
         "<p><a href='#book'>Book a 30-minute call</a></p></body></html>")
SLOP = ("<!doctype html><html><head><meta charset='utf-8'><style>body{font:18px/1.6 Georgia,serif;margin:48px}"
        "h1{background:linear-gradient(90deg,#7c3aed,#4f46e5);-webkit-background-clip:text;"
        "-webkit-text-fill-color:transparent;font-size:48px}</style></head><body>"
        "<h1>Unlock the power of AI for your business</h1><p>Transform your workflow.</p>"
        "<p><a href='#book'>Book a call</a></p></body></html>")


class Served:
    """A directory on a loopback port the OS picks."""

    def __init__(self, directory: Path):
        handler = lambda *a, **k: http.server.SimpleHTTPRequestHandler(*a, directory=str(directory), **k)
        http.server.SimpleHTTPRequestHandler.log_message = lambda *a: None
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


class TheScript(unittest.TestCase):
    def setUp(self):
        if not shutil.which("node"):
            self.fail("node is not on PATH: the detector cannot run")
        self.tmp = Path(tempfile.mkdtemp(prefix="dc04-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.rd = self.tmp / "r1"
        self.rd.mkdir()
        (self.rd / "Home-laptop.html").write_text(CLEAN)
        self.det = self.tmp / "stub-detector.mjs"
        self.det.write_text(STUB_DETECTOR)
        self.srv = Served(self.rd)
        self.addCleanup(self.srv.close)

    def run_script(self, *extra, url_base=None, **stub):
        env = {**os.environ, **{f"STUB_{k.upper()}": v for k, v in stub.items()}}
        args = [sys.executable, str(SCRIPT), str(self.rd), "--detector", str(self.det)]
        if url_base is not False:
            args += ["--url-base", url_base or self.srv.base]
        r = subprocess.run(args + list(extra), capture_output=True, text=True, env=env, timeout=300)
        return r.returncode, r.stdout + r.stderr

    def test_control_fired_and_pages_clean_is_0(self):
        rc, out = self.run_script()
        self.assertEqual(rc, 0, out)
        self.assertIn("control fired: YES", (self.rd / "checks" / "impeccable.txt").read_text())

    def test_a_dead_control_is_1(self):
        rc, out = self.run_script(control="dead")
        self.assertEqual(rc, 1, out)

    def test_a_flagged_page_is_3(self):
        rc, out = self.run_script(pages="flag")
        self.assertEqual(rc, 3, out)

    def test_a_detector_crash_on_a_page_is_2(self):
        rc, out = self.run_script(pages="crash")
        self.assertEqual(rc, 2, out)

    def test_no_url_base_is_refused(self):
        rc, out = self.run_script(url_base=False)
        self.assertEqual(rc, 2, out)
        self.assertIn("--url-base", out)

    def test_served_bytes_that_are_not_the_local_file_is_2(self):
        other = self.tmp / "other"
        other.mkdir()
        (other / "Home-laptop.html").write_text(CLEAN.replace("agree", "differ"))
        srv = Served(other)
        self.addCleanup(srv.close)
        rc, out = self.run_script(url_base=srv.base)
        self.assertEqual(rc, 2, out)
        self.assertIn("served bytes differ", out)

    def test_the_control_goes_through_the_url_engine(self):
        # served on the script's own port, never written into the round
        rc, out = self.run_script()
        rec = (self.rd / "checks" / "impeccable.txt").read_text()
        self.assertRegex(rec, r"control: http://127\.0\.0\.1:\d+/\.impeccable-control\.html")
        self.assertFalse((self.rd / ".impeccable-control.html").exists())


class SealRunsIt(unittest.TestCase):
    """The real gate, real producers, the real detector."""

    def setUp(self):
        try:
            import playwright  # noqa: F401
            ok = REAL_DETECTOR.is_file() and shutil.which("node")
        except ImportError:
            ok = False
        if not ok:
            msg = "playwright, node or the impeccable detector is missing: the PRODUCTION path was NOT exercised"
            if os.environ.get("DC_REQUIRE_REAL_PRODUCERS") == "1":
                self.fail(msg)
            self.skipTest(msg)
        self.tmp = Path(tempfile.mkdtemp(prefix="dc04s-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        inst = self.tmp / "inst"
        self.rd = inst / "site" / "design" / "r1"
        self.rd.mkdir(parents=True)
        (inst / "design-chain.json").write_text(json.dumps(
            {"project": "dc04", "owners": [], "craft": {"tier": "craft", "require_impeccable": True}}))
        rd = self.rd
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
        r = subprocess.run([sys.executable, str(REAL_GATE), "seal", str(self.rd)], capture_output=True,
                           text=True, env=env, timeout=900)
        return r.returncode, r.stdout + r.stderr

    def test_a_clean_page_seals_with_a_receipt_the_producer_wrote(self):
        (self.rd / "Home-laptop.html").write_text(CLEAN)
        rc, out = self.seal()
        self.assertEqual(rc, 0, out)
        self.assertIn("control fired: YES", (self.rd / "checks" / "impeccable.txt").read_text())

    def test_a_page_with_an_anti_pattern_is_refused_whatever_receipt_the_round_carries(self):
        (self.rd / "Home-laptop.html").write_text(SLOP)
        (self.rd / "checks" / "impeccable.txt").write_text("ran\n")      # the receipt the gate used to trust
        rc, out = self.seal()
        self.assertEqual(rc, 2, out)
        self.assertIn("raised an anti-pattern", out)
        self.assertFalse((self.rd / "receipts.json").exists())


if __name__ == "__main__":
    unittest.main()
