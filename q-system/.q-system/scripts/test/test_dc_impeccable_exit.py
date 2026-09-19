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
if (env.STUB_LOG) (await import('fs')).appendFileSync(env.STUB_LOG, JSON.stringify({argv: process.argv.slice(2), cwd: process.cwd()}) + '\n');
if (t.includes('impeccable-control')) {
  if (env.STUB_CONTROL === 'dead') { console.error('0 anti-patterns found.'); process.exit(0); }
  if (env.STUB_CONTROL === 'nobrowser' && t.startsWith('http')) { console.error('puppeteer is required for URL scanning'); process.exit(0); }
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


class ThePageListAndTheDetectorsOwnConfig(TheScript):
    """Review of d0492b36, Sana's triage (findings 1-3)."""

    def test_a_page_in_the_round_it_was_not_given_is_2(self):
        (self.rd / "Offer.htm").write_text(CLEAN)
        rc, out = self.run_script("--page", "Home-laptop.html")
        self.assertEqual(rc, 2, out)
        self.assertIn("Offer.htm", out)

    def test_a_page_it_cannot_scan_as_html_is_2(self):
        (self.rd / "Home.astro").write_text("---\n---\n<h1>x</h1>")
        rc, out = self.run_script("--page", "Home-laptop.html", "--page", "Home.astro")
        self.assertEqual(rc, 2, out)
        self.assertIn("cannot scan Home.astro", out)

    def test_an_htm_page_given_is_scanned(self):
        (self.rd / "Offer.htm").write_text(CLEAN)
        rc, out = self.run_script("--page", "Home-laptop.html", "--page", "Offer.htm", pages="flag")
        self.assertEqual(rc, 3, out)
        self.assertIn("Offer.htm", (self.rd / "checks" / "impeccable.txt").read_text())

    def calls(self, **stub):
        log = self.tmp / "calls.jsonl"
        rc, out = self.run_script(log=str(log), **stub)
        self.assertEqual(rc, 0, out)
        return [json.loads(l) for l in log.read_text().splitlines()]

    def test_every_detector_call_passes_no_config(self):
        calls = self.calls()
        self.assertTrue(calls)
        self.assertTrue(all("--no-config" in c["argv"] for c in calls), calls)

    def test_every_detector_call_runs_from_an_empty_directory(self):
        # a .impeccable/config.json in the caller's cwd switched rules off (finding-3)
        for c in self.calls():
            self.assertNotEqual(os.path.realpath(c["cwd"]), os.path.realpath(os.getcwd()), c)
            self.assertEqual(os.listdir(c["cwd"]) if os.path.isdir(c["cwd"]) else [], [], c)

    def test_the_browser_unavailable_fallback_leaves_no_temp_dir(self):
        before = set(Path(tempfile.gettempdir()).glob("impeccable-control-*"))
        self.run_script(control="nobrowser")
        after = set(Path(tempfile.gettempdir()).glob("impeccable-control-*"))
        self.assertEqual(after - before, set())


class EveryRecordedStageIsBelievable(unittest.TestCase):
    """ASK-1845 happened because dc-04 recorded a stage the receipt check (dc-10) had no script for.
    The census is taken from the gate's own source, not from a list typed here."""

    def test_every_stage_seal_records_has_a_script_the_receipt_check_believes(self):
        import importlib.util
        import re
        src = REAL_GATE.read_text()
        names = sorted(set(re.findall(r'stage_record\("([a-z]+)"', src)))
        self.assertGreaterEqual(len(names), 3, names)          # the parse found the stages at all
        spec = importlib.util.spec_from_file_location("dc1845_gate", REAL_GATE)
        g = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(g)
        for n in names:
            with self.subTest(stage=n):
                self.assertIsNotNone(g._stage_script(n), f"seal records a {n!r} stage no receipt can believe")
        for c in g.CHECKS:
            self.assertIsNotNone(g._stage_script(f"check:{c}"))


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

    def seal(self, cwd=None):
        env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_PROJECT_DIR", "DESIGN_CHAIN_ALLOW")}
        env["DESIGN_CHAIN_STATE"] = str(self.tmp / "state")
        r = subprocess.run([sys.executable, str(REAL_GATE), "seal", str(self.rd)], capture_output=True,
                           text=True, env=env, timeout=900, cwd=cwd)
        return r.returncode, r.stdout + r.stderr

    def test_a_clean_page_seals_with_a_receipt_the_producer_wrote(self):
        (self.rd / "Home-laptop.html").write_text(CLEAN)
        rc, out = self.seal()
        self.assertEqual(rc, 0, out)
        self.assertIn("control fired: YES", (self.rd / "checks" / "impeccable.txt").read_text())

    def test_a_round_sealed_with_impeccable_reads_sealed_afterwards(self):
        # ASK-1845: the impeccable stage had no producer on record for dc-10's receipt check, so a
        # round sealed with require_impeccable read OPEN on every passive read afterwards
        (self.rd / "Home-laptop.html").write_text(CLEAN)
        rc, out = self.seal()
        self.assertEqual(rc, 0, out)
        env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_PROJECT_DIR", "DESIGN_CHAIN_ALLOW")}
        env["DESIGN_CHAIN_STATE"] = str(self.tmp / "state")
        r = subprocess.run([sys.executable, str(REAL_GATE), "status-page", str(self.rd / "Home-laptop.html")],
                           capture_output=True, text=True, env=env, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("impeccable producer that is neither", r.stdout + r.stderr)

    def test_a_slop_page_named_htm_beside_a_clean_one_is_refused(self):
        # finding-2: the producer scanned *.html only, and seal seals every page
        (self.rd / "Home-laptop.html").write_text(CLEAN)
        (self.rd / "Offer.htm").write_text(SLOP)
        rc, out = self.seal()
        self.assertEqual(rc, 2, out)
        self.assertIn("raised an anti-pattern", out)

    def test_a_detector_config_in_the_callers_directory_does_not_switch_rules_off(self):
        (self.rd / "Home-laptop.html").write_text(SLOP)
        cwd = self.tmp / "caller"
        (cwd / ".impeccable").mkdir(parents=True)
        (cwd / ".impeccable" / "config.json").write_text(json.dumps(
            {"detector": {"ignoreRules": ["gradient-text", "ai-color-palette", "low-contrast"]}}))
        rc, out = self.seal(cwd=cwd)
        self.assertEqual(rc, 2, out)
        self.assertIn("raised an anti-pattern", out)

    def test_a_page_with_an_anti_pattern_is_refused_whatever_receipt_the_round_carries(self):
        (self.rd / "Home-laptop.html").write_text(SLOP)
        (self.rd / "checks" / "impeccable.txt").write_text("ran\n")      # the receipt the gate used to trust
        rc, out = self.seal()
        self.assertEqual(rc, 2, out)
        self.assertIn("raised an anti-pattern", out)
        self.assertFalse((self.rd / "receipts.json").exists())


if __name__ == "__main__":
    unittest.main()
