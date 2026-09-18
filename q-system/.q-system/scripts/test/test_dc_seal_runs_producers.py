#!/usr/bin/env python3
"""dc-02: `seal` runs the standard and gap producers itself and uses their exit codes.

Before this, `seal` read standard.json and gap.json as trusted inputs, so a verdict typed
by hand sealed a round (RCA rca-design-chain-trusts-its-own-account-2026-09-18, C3 and C7).

HOW THE STAND-INS GET SELECTED (Sana, 2026-09-18): the gate resolves producers as siblings
of its own file. These tests copy the gate into a temp bin directory next to the stand-ins
in test/stub_producers/ and run THAT copy. Shipped code has no override to widen, and
the NoOverride class reads the gate's AST and goes red if one is added.

Temp directories only. Touches no real round.
"""
import ast
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


class ExitCodeIsNotEvidence(Base):
    """Adversarial review of c598d5f5, each reproduced by the reviewer against the real gate."""

    def test_exit_0_with_no_fresh_output_is_not_a_pass(self):
        # A sitecustomize.py on PYTHONPATH made the real producer exit 0 before measuring, and
        # seal then re-read the verdict typed by hand. A bare exit code is not evidence.
        self.typed_pass()
        rc, out = self.seal(STUB_STANDARD="silent")
        self.assertEqual(rc, 2, out)
        self.assertIn("could not measure", out)
        self.assertFalse((self.round / "receipts.json").exists())

    def test_a_crashed_producer_is_could_not_measure_not_a_failed_page(self):
        self.typed_pass()
        rc, out = self.seal(STUB_STANDARD="crash")
        self.assertEqual(rc, 2, out)
        self.assertIn("could not measure", out)
        self.assertNotIn("FAILS the standard", out)

    def test_the_child_interpreter_ignores_PYTHONPATH(self):
        evil = self.tmp / "evil"
        evil.mkdir()
        (evil / "sitecustomize.py").write_text(
            "import os, sys\n"
            "if sys.argv and sys.argv[0].endswith('design-standard-check.py'):\n"
            "    os._exit(0)\n")
        self.typed_pass()
        rc, out = self.seal(STUB_STANDARD="fail", PYTHONPATH=str(evil))
        self.assertEqual(rc, 2, out)
        self.assertIn("FAILS the standard", out, "the producer was hijacked before it could judge")

    def test_a_missing_module_names_the_user_base_tradeoff(self):
        rc, out = self.seal(STUB_STANDARD="nomodule")
        self.assertEqual(rc, 2, out)
        self.assertIn("could not measure", out)
        self.assertIn("PYTHONUSERBASE", out)

    def test_one_failure_is_reported_once(self):
        rc, out = self.seal(STUB_STANDARD="fail")
        self.assertEqual(rc, 2, out)
        self.assertNotIn("standard.json for", out)


class WithdrawnRound(Base):
    def test_a_withdrawn_round_gets_no_receipt(self):
        # Reviewer: withdraw, seal, delete the manifest -> the page read COMPLETE on a receipt
        # nothing measured. A withdrawn round has nothing to seal.
        self.typed_pass()
        (self.round / "craft-manifest.json").write_text(json.dumps({"status": "withdrawn", "reason": "parked"}))
        rc, out = self.seal()
        self.assertFalse((self.round / "receipts.json").exists(), out)
        self.assertIn("withdrawn", out)
        (self.round / "craft-manifest.json").unlink()
        e = {k: v for k, v in os.environ.items() if k not in ("DESIGN_CHAIN_ALLOW", "CLAUDE_PROJECT_DIR")}
        r = subprocess.run([sys.executable, str(self.gate), "status-page", str(self.page)],
                           capture_output=True, text=True, env=e)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)


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

    def test_a_round_declared_wireframe_is_not_gap_measured(self):
        # craft_problems() already honors a round-local wireframe declaration with a reason.
        # The producer step has to honor the same declaration or the round is stuck.
        (self.round / "craft-manifest.json").write_text(json.dumps(
            {"tier": "wireframe", "reason": "copy test, layout only"}))
        rc, out = self.seal(STUB_GAP="below")
        self.assertEqual(rc, 0, out)

    def test_a_silent_gap_producer_is_not_a_pass(self):
        self.typed_clean_gap()
        rc, out = self.seal(STUB_GAP="silent")
        self.assertEqual(rc, 2, out)

    def test_gap_is_not_run_when_the_instance_did_not_declare_it(self):
        self.cfg.pop("craft")
        self.write_cfg()
        rc, out = self.seal(STUB_GAP="cannot")
        self.assertEqual(rc, 0, out)


class NoOverride(unittest.TestCase):
    """A REVIEW AID, NOT A GUARANTEE. It catches an honest future change that adds a producer
    override to the gate. It cannot stop someone who edits the gate, because they can edit
    this file too: round 2 evaded it by rebinding subprocess.run at module scope, the same
    class as round 1's evasion, and a third pattern would only be found by the next reviewer.
    What binds a receipt to the real gate and the real producers is dc-10 (path + sha that
    matches now or appears in git history). Sana, 2026-09-18: do not call this a guarantee.

    Refused by Sana: any producer-directory override production can honor. The first
    version of this class was a five-token blocklist, and the adversarial reviewer evaded all
    five with `HERE = Path(os.environ.get('DC_BIN') or Path(__file__).resolve().parent)` while
    the suite stayed green. So this reads the STRUCTURE: what HERE is, and what gets executed."""

    @classmethod
    def setUpClass(cls):
        cls.tree = ast.parse(REAL_GATE.read_text())

    def run_producer_fn(self):
        return next(n for n in ast.walk(self.tree)
                    if isinstance(n, ast.FunctionDef) and n.name == "run_producer")

    def test_HERE_is_assigned_once_and_only_from_the_gate_file(self):
        values = []
        for node in ast.walk(self.tree):
            targets = []
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
                targets = [node.target]
            for t in targets:
                if isinstance(t, ast.Name) and t.id == "HERE":
                    values.append(ast.unparse(node.value))
        self.assertEqual(values, ["Path(__file__).resolve().parent"])

    def test_nothing_rebinds_HERE_another_way(self):
        for node in ast.walk(self.tree):
            if isinstance(node, (ast.Global, ast.Nonlocal)):
                self.assertNotIn("HERE", node.names)
            if isinstance(node, ast.Call) and ast.unparse(node.func) in ("globals", "setattr", "vars"):
                self.fail(f"{ast.unparse(node)} can rebind a module name")

    def test_run_producer_executes_only_a_sibling_of_the_gate(self):
        fn = self.run_producer_fn()
        scripts = [ast.unparse(n.value) for n in ast.walk(fn)
                   if isinstance(n, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == "script" for t in n.targets)]
        self.assertEqual(scripts, ["HERE / name"])
        calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call) and ast.unparse(n.func) == "subprocess.run"]
        self.assertEqual(len(calls), 1)
        self.assertEqual(ast.unparse(calls[0].args[0]), "[sys.executable, '-E', str(script), *args]")

    def test_the_child_runs_in_a_cleaned_environment(self):
        call = next(n for n in ast.walk(self.run_producer_fn())
                    if isinstance(n, ast.Call) and ast.unparse(n.func) == "subprocess.run")
        self.assertEqual({k.arg: ast.unparse(k.value) for k in call.keywords}.get("env"), "clean_env()")


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
        self.assertTrue(entry["pass"], f"the real producer failed a 9-word page: {entry.get('failures')}")
        self.assertEqual(rc, 0, out)

    def test_the_real_producer_FAILS_a_page_built_to_break_the_standard(self):
        # The input that makes it red: 400 words against max_words 80. Without this the real
        # producer only ever walked the PASS path, and one regressed to always-pass stayed green.
        try:
            import playwright  # noqa: F401
        except ImportError:
            msg = "playwright is not installed: the REAL producer's FAIL path was NOT exercised"
            if os.environ.get("DC_REQUIRE_REAL_PRODUCERS") == "1":
                self.fail(msg)
            self.skipTest(msg)
        self.cfg["standard"] = {"max_words": 80}
        self.write_cfg()
        self.page.write_text("<html><body><h1>Too many words</h1><p>" + "word " * 400
                             + "</p><a href='#'>Book</a></body></html>")
        rc, out = self.seal(gate=REAL_GATE)
        self.assertEqual(rc, 2, out)
        entry = json.loads((self.round / "standard.json").read_text())[0]
        self.assertIs(entry["pass"], False)
        self.assertIn("measurements", entry)
        self.assertFalse((self.round / "receipts.json").exists())


if __name__ == "__main__":
    unittest.main()
