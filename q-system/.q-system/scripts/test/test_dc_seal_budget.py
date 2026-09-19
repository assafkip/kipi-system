#!/usr/bin/env python3
"""dc-05: every producer run has a timeout read from config, and seal prints how long each took.

WHY. The producer timeout was a constant (600 s) nobody could lower for a round that should
fail fast, and seal said nothing about where its time went: a seal that took minutes gave no
line saying which stage took them. A timeout is a refusal that names the stage.

The spec asked for a sleeping stub producer. A stub cannot sit beside the gate at its tracked
path (the gate's producers are its siblings, and no override exists in shipped code, dc-02), so
these drive the REAL gate and the REAL producers and make the timeout, not the producer, small.
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
REAL_GATE = HERE.parent / "design-chain-gate.py"
PAGE = ("<!doctype html><html><head><meta charset='utf-8'><style>body{font:18px/1.6 Georgia,serif;"
        "margin:48px;color:#1a1a1a}</style></head><body><h1>Two records that should agree</h1>"
        "<p>A small firm retypes the same client data into three systems.</p>"
        "<p><a href='#book'>Book a 30-minute call</a></p></body></html>")


class Budget(unittest.TestCase):
    def setUp(self):
        try:
            import playwright  # noqa: F401
        except ImportError:
            msg = "playwright is not installed: the PRODUCTION path was NOT exercised"
            if os.environ.get("DC_REQUIRE_REAL_PRODUCERS") == "1":
                self.fail(msg)
            self.skipTest(msg)
        self.tmp = Path(tempfile.mkdtemp(prefix="dc05-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.inst = self.tmp / "inst"
        self.rd = self.inst / "site" / "design" / "r1"
        self.rd.mkdir(parents=True)
        rd = self.rd
        (rd / "Home-laptop.html").write_text(PAGE)
        (rd / "brief.md").write_text("brief\n")
        (rd / "directions.md").write_text("# A\n# B\n# C\n")
        (rd / "critique.md").write_text("".join(f"{i % 9 + 1}. considered\n" for i in range(27)))
        (rd / "proof.md").write_text("Home-laptop.html: proof\n")
        (rd / "checks").mkdir()
        (rd / "checks" / "bio_gate.txt").write_text("ok\n")
        (rd / "gate").mkdir()
        (rd / "gate" / "icp.md").write_text("answers\n")

    def config(self, **extra):
        (self.inst / "design-chain.json").write_text(json.dumps({"project": "dc05", "owners": [], **extra}))

    def seal(self):
        env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_PROJECT_DIR", "DESIGN_CHAIN_ALLOW")}
        env["DESIGN_CHAIN_STATE"] = str(self.tmp / "state")
        r = subprocess.run([sys.executable, str(REAL_GATE), "seal", str(self.rd)], capture_output=True,
                           text=True, env=env, timeout=900)
        return r.returncode, r.stdout + r.stderr

    def test_a_producer_past_the_configured_timeout_refuses_naming_the_stage(self):
        self.config(seal={"producer_timeout_s": 0.05})
        rc, out = self.seal()
        self.assertEqual(rc, 2, out)
        self.assertIn("stage 'standard'", out)
        self.assertIn("timed out after 0.05s", out)
        self.assertFalse((self.rd / "receipts.json").exists())

    def test_an_honest_seal_prints_one_duration_line_per_stage(self):
        self.config()
        rc, out = self.seal()
        self.assertEqual(rc, 0, out)
        lines = [l for l in out.splitlines() if l.startswith("stage ")]
        self.assertEqual(len(lines), 1, out)                  # one page, one stage (standard)
        self.assertRegex(lines[0], r"^stage standard Home-laptop\.html: \d+\.\d\ds \(exit 0\)$")

    def test_a_timeout_that_is_not_a_positive_number_refuses(self):
        for bad in (0, -1, "10", None, True):
            with self.subTest(value=bad):
                self.config(seal={"producer_timeout_s": bad})
                rc, out = self.seal()
                self.assertEqual(rc, 2, out)
                self.assertIn("producer_timeout_s", out)

    def test_no_config_value_keeps_the_coded_default(self):
        # the default is the coded constant; a round that names none seals as before
        self.config(seal={})
        rc, out = self.seal()
        self.assertEqual(rc, 0, out)


if __name__ == "__main__":
    unittest.main()
