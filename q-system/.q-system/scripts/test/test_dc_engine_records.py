#!/usr/bin/env python3
"""dc-19: engines leave a record, and a technique that names an engine needs one.

WHY. The copied-animation incident: a round's craft manifest credited an animation to the
hyperframes-animation engine, and the engine was never run; the motion was copied from a reference.
Nothing recorded which engines a round called. Now design-engine-door.py's PostToolUse on the Skill
tool appends {skill, session, at} to the open round's engines.jsonl, and seal refuses a technique
whose `engine` has no record.
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
DOOR = HERE.parent / "design-engine-door.py"
GATE = HERE.parent / "design-chain-gate.py"


def load_gate():
    spec = importlib.util.spec_from_file_location("dc19_gate", GATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class EngineRecords(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="dc19-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.state = self.tmp / "state"
        self.state.mkdir()
        self.inst = self.tmp / "inst"
        self.inst.mkdir()
        (self.inst / "design-chain.json").write_text(json.dumps({"project": "dc19", "owners": []}))
        self.rd = self.inst / "site" / "design" / "r1"
        self.rd.mkdir(parents=True)
        (self.rd / "brief.md").write_text("brief\n")

    def open_round(self, session="s-dc19"):
        (self.state / f"{session}.json").write_text(json.dumps({"pages": {}, "bash_marker": 0, "round": str(self.rd)}))

    def post_skill(self, skill, session="s-dc19"):
        env = {**os.environ, "DESIGN_CHAIN_STATE": str(self.state)}
        payload = {"hook_event_name": "PostToolUse", "tool_name": "Skill", "session_id": session,
                   "tool_input": {"skill": skill}}
        # run from a scratch folder: a record must land in the round or nowhere, never in the cwd
        self.cwd = self.tmp / "cwd"
        self.cwd.mkdir(exist_ok=True)
        r = subprocess.run([sys.executable, str(DOOR)], input=json.dumps(payload), capture_output=True,
                           text=True, env=env, timeout=60, cwd=self.cwd)
        self.assertEqual(r.returncode, 0, r.stderr)

    def rows(self):
        p = self.rd / "engines.jsonl"
        return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.is_file() else []

    def manifest(self, *engines):
        (self.rd / "craft-manifest.json").write_text(json.dumps({"techniques": [
            {"id": f"t{i}", "reference": "stripe.com", "engine": e} for i, e in enumerate(engines)]}))

    def test_an_engine_run_in_an_open_round_is_recorded(self):
        self.open_round()
        self.post_skill("kipi-design:brand")
        rows = self.rows()
        self.assertEqual(len(rows), 1, rows)
        self.assertEqual(rows[0]["skill"], "brand")
        self.assertEqual(rows[0]["session"], "s-dc19")
        self.assertIn("at", rows[0])

    def test_no_open_round_no_record(self):
        self.post_skill("frontend-design")
        self.assertEqual(self.rows(), [])
        self.assertEqual(list(self.cwd.iterdir()), [])

    def test_a_record_that_cannot_be_written_is_a_quiet_no_op(self):
        # std-2: the hook's exit contract is 0 or 2, never a traceback
        self.open_round()
        (self.rd / "engines.jsonl").mkdir()
        self.post_skill("frontend-design")          # asserts exit 0

    def test_an_unlisted_skill_is_not_recorded(self):
        self.open_round()
        self.post_skill("q-debrief")
        self.assertEqual(self.rows(), [])

    def test_a_technique_crediting_an_engine_that_never_ran_refuses(self):
        # the copied-animation case
        self.manifest("hyperframes-animation")
        probs = load_gate().engine_problems(self.rd)
        self.assertTrue(any("hyperframes-animation" in p for p in probs), probs)

    def test_a_technique_whose_engine_ran_passes(self):
        self.open_round()
        self.post_skill("hyperframes-animation")
        self.manifest("hyperframes-animation")
        self.assertEqual(load_gate().engine_problems(self.rd), [])

    def test_a_manifest_without_engine_fields_needs_no_record(self):
        (self.rd / "craft-manifest.json").write_text(json.dumps({"techniques": [{"id": "t1", "reference": "x.com"}]}))
        self.assertEqual(load_gate().engine_problems(self.rd), [])

    def raw_manifest(self, text):
        (self.rd / "craft-manifest.json").write_text(text)
        return load_gate().engine_problems(self.rd)

    def test_an_engine_credit_under_another_key_is_seen(self):
        # adv-1
        for key in ("Engine", "engines", "engine_used"):
            probs = self.raw_manifest(json.dumps({"techniques": [{"id": "m", key: "hyperframes-animation"}]}))
            self.assertTrue(any("hyperframes-animation" in p for p in probs), (key, probs))

    def test_a_list_of_engines_needs_a_run_of_each(self):
        self.open_round()
        self.post_skill("brand")
        probs = self.raw_manifest(json.dumps({"techniques": [{"id": "m", "engines": ["brand", "hyperframes-animation"]}]}))
        self.assertEqual(len(probs), 1, probs)
        self.assertIn("'hyperframes-animation'", probs[0])
        self.assertNotIn("brand", probs[0])

    def test_a_duplicate_key_refuses(self):
        # adv-2
        probs = self.raw_manifest('{"techniques": [{"id": "m", "engine": "hyperframes-animation", "engine": ""}]}')
        self.assertTrue(any("duplicate" in p for p in probs), probs)

    def test_a_nested_credit_is_seen(self):
        # adv-3
        for shape in ({"directions": [{"techniques": [{"engine": "hyperframes-animation"}]}]},
                      {"techniques": {"m": {"engine": "hyperframes-animation"}}},
                      [{"engine": "hyperframes-animation"}]):
            probs = self.raw_manifest(json.dumps(shape))
            self.assertTrue(any("hyperframes-animation" in p for p in probs), (shape, probs))

    def test_the_gate_folds_names_as_the_door_does(self):
        # adv-7: a run recorded, credit written with a trailing colon
        self.open_round()
        self.post_skill("hyperframes-animation")
        self.assertEqual(self.raw_manifest(json.dumps({"techniques": [{"engine": "hyperframes-animation:"}]})), [])

    def test_seal_refuses_a_copied_animation(self):
        # RED FIRST: nothing recorded which engines a round ran
        self.manifest("hyperframes-animation")
        (self.rd / "Home-laptop.html").write_text("<html><body><p>x</p></body></html>")
        env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_PROJECT_DIR", "DESIGN_CHAIN_ALLOW")}
        env["DESIGN_CHAIN_STATE"] = str(self.state)
        r = subprocess.run([sys.executable, str(GATE), "seal", str(self.rd)], capture_output=True, text=True,
                           env=env, timeout=600)
        out = r.stdout + r.stderr
        self.assertEqual(r.returncode, 2, out)
        self.assertIn("hyperframes-animation", out)


if __name__ == "__main__":
    unittest.main()
