#!/usr/bin/env python3
"""dc-02: `seal` runs the standard and gap producers itself and uses their exit codes.

Before this, `seal` read standard.json and gap.json as trusted inputs, so a verdict typed
by hand sealed a round (RCA rca-design-chain-trusts-its-own-account-2026-09-18, C3 and C7).

HOW THE STAND-INS GET SELECTED (Sana, 2026-09-18): the gate resolves producers as siblings
of its own file. These tests copy the gate into a temp bin directory next to the stand-ins
in test/stub_producers/ and run THAT copy. Shipped code has no override to widen, and
test_no_producer_override_exists_in_the_gate goes red if one is added.

Temp directories only. Touches no real round.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
REAL_GATE = SCRIPTS / "design-chain-gate.py"
STUBS = Path(__file__).resolve().parent / "stub_producers"
OWNER = "> **A business where somebody is paid to be accurate, and being wrong costs money"
PAGE = "<html><body><h1>You work more hours than you bill.</h1><a href='#'>Book</a></body></html>"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="dc02-"))
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        shutil.copy(REAL_GATE, self.bin / REAL_GATE.name)
        for stub in STUBS.glob("*.py"):
            shutil.copy(stub, self.bin / stub.name)
        self.gate = self.bin / REAL_GATE.name
        self.inst = self.tmp / "instance"
        (self.inst / "canonical").mkdir(parents=True)
        (self.inst / "canonical" / "the-business.md").write_text("# B\n\n" + OWNER + "\n")
        self.cfg = {"owners": [{"file": "canonical/the-business.md",
                                "anchors": ["^> \\*\\*A business where somebody is paid"]}]}
        self.round = self.inst / "site" / "design" / "r1"
        self.round.mkdir(parents=True)
        self.page = self.round / "Pair-laptop.html"
        self.page.write_text(PAGE)
        self.write_cfg()
        self.floor_chain()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_cfg(self):
        (self.inst / "design-chain.json").write_text(json.dumps(self.cfg))

    def floor_chain(self):
        rd = self.round
        (rd / "brief.md").write_text("# Brief\n\n" + OWNER + "\n")
        (rd / "directions.md").write_text("# A\nx\n# B\nx\n# C\nx\n")
        (rd / "critique.md").write_text("".join(f"## {d}\n" + "".join(f"{i}. a\n" for i in range(1, 10)) for d in "ABC"))
        (rd / "proof.md").write_text("Pair-laptop.html: capability proof\n")
        (rd / "checks").mkdir(exist_ok=True)
        (rd / "checks" / "bio_gate.txt").write_text("ok\n")
        (rd / "gate").mkdir(exist_ok=True)
        (rd / "gate" / "icp.md").write_text("answers\n")

    def typed_pass(self):
        sha = hashlib.sha256(self.page.read_bytes()).hexdigest()
        (self.round / "standard.json").write_text(json.dumps([{"page": self.page.name, "sha256": sha, "pass": True}]))

    def seal(self, gate=None, **env):
        e = {k: v for k, v in os.environ.items() if k not in ("DESIGN_CHAIN_ALLOW", "CLAUDE_PROJECT_DIR")}
        e["DESIGN_CHAIN_STATE"] = str(self.tmp / "state")
        e.update(env)
        r = subprocess.run([sys.executable, str(gate or self.gate), "seal", str(self.round)],
                           capture_output=True, text=True, env=e)
        return r.returncode, r.stdout + r.stderr


class StandardProducer(Base):
    def test_a_typed_pass_does_not_seal_when_the_producer_says_fail(self):
        self.typed_pass()
        rc, out = self.seal(STUB_STANDARD="fail")
        self.assertEqual(rc, 2, out)
        self.assertFalse((self.round / "receipts.json").exists(), "sealed on a verdict typed by hand")

    def test_could_not_measure_is_a_refusal_never_a_pass(self):
        self.typed_pass()
        rc, out = self.seal(STUB_STANDARD="cannot")
        self.assertEqual(rc, 2, out)
        self.assertIn("could not measure", out)
        self.assertFalse((self.round / "receipts.json").exists())

    def test_a_missing_producer_is_a_refusal_that_names_its_path(self):
        self.typed_pass()
        (self.bin / "design-standard-check.py").unlink()
        rc, out = self.seal()
        self.assertEqual(rc, 2, out)
        self.assertIn(str(self.bin / "design-standard-check.py"), out)

    def test_the_producer_passing_seals_with_no_typed_verdict_at_all(self):
        rc, out = self.seal()
        self.assertEqual(rc, 0, out)
        std = json.loads((self.round / "standard.json").read_text())
        self.assertTrue(std[0]["_stub"], "standard.json was not written by the producer seal ran")
        self.assertTrue((self.round / "receipts.json").is_file())

    def test_every_page_is_measured_not_only_the_first(self):
        second = self.round / "Clock-laptop.html"
        second.write_text(PAGE.replace("bill", "count"))
        rc, out = self.seal()
        self.assertEqual(rc, 0, out)
        names = {e["page"] for e in json.loads((self.round / "standard.json").read_text())}
        self.assertEqual(names, {self.page.name, second.name})


class GapProducer(Base):
    def setUp(self):
        super().setUp()
        self.cfg["craft"] = {"tier": "craft", "require_gap_check": True}
        self.write_cfg()

    def typed_clean_gap(self):
        sha = hashlib.sha256(self.page.read_bytes()).hexdigest()
        (self.round / "checks" / "gap.json").write_text(json.dumps(
            {"pages": {self.page.name: {"sha256": sha, "below_floor": []}}}))

    def test_a_typed_clean_gap_does_not_seal_when_the_producer_says_below_floor(self):
        self.typed_clean_gap()
        rc, out = self.seal(STUB_GAP="below")
        self.assertEqual(rc, 2, out)
        self.assertFalse((self.round / "receipts.json").exists())

    def test_gap_could_not_measure_is_a_refusal(self):
        self.typed_clean_gap()
        rc, out = self.seal(STUB_GAP="cannot")
        self.assertEqual(rc, 2, out)
        self.assertIn("could not measure", out)

    def test_gap_is_not_run_when_the_instance_did_not_declare_it(self):
        self.cfg.pop("craft")
        self.write_cfg()
        rc, out = self.seal(STUB_GAP="cannot")
        self.assertEqual(rc, 0, out)


class NoOverride(unittest.TestCase):
    def test_no_producer_override_exists_in_the_gate(self):
        # Refused by Sana: any producer-directory override production can honor. An env var,
        # a flag, or a temp-dir-conditional is the gate trusting an account of itself again.
        src = REAL_GATE.read_text()
        for token in ("--producers-dir", "PRODUCER_DIR", "PRODUCERS_DIR", "gettempdir", "STUB_"):
            self.assertNotIn(token, src, f"design-chain-gate.py carries an override token: {token}")

    def test_producers_are_resolved_beside_the_gate_file(self):
        self.assertIn("Path(__file__).resolve().parent", REAL_GATE.read_text())


class RealProducer(Base):
    """One run that is not a stand-in, so the suite is not 100% stubs (RCA root cause #2)."""

    def test_the_real_gate_runs_the_real_standard_producer(self):
        try:
            import playwright  # noqa: F401
        except ImportError:
            msg = "playwright is not installed: the REAL producer was NOT exercised by this run"
            if os.environ.get("DC_REQUIRE_REAL_PRODUCERS") == "1":
                self.fail(msg)
            self.skipTest(msg)
        rc, out = self.seal(gate=REAL_GATE)
        std_path = self.round / "standard.json"
        self.assertTrue(std_path.is_file(), out)
        entry = json.loads(std_path.read_text())[0]
        self.assertNotIn("_stub", entry)
        self.assertIn("measurements", entry, "standard.json was not written by the real producer")
        self.assertEqual(rc, 0 if entry["pass"] else 2, out)


if __name__ == "__main__":
    unittest.main()
