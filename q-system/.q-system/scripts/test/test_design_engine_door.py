#!/usr/bin/env python3
"""dc-18: one door. A design engine called outside a /design-chain round is refused.

WHY. The founder named /design-chain the one design command (2026-09-18); the other design skills
stay installed as engines. Nothing stopped a session from calling frontend-design directly, which
is how a round's page got an animation nobody could trace (the copied-animation incident).
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
DOOR = HERE.parent / "design-engine-door.py"
GATE = HERE.parent / "design-chain-gate.py"


class Door(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="dc18-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.state = self.tmp / "state"
        self.state.mkdir()
        self.rd = self.tmp / "inst" / "site" / "design" / "r1"
        self.rd.mkdir(parents=True)
        self.inst = self.tmp / "inst"
        # the chain is opt-in: the door only speaks where a design-chain.json governs the session
        (self.inst / "design-chain.json").write_text(json.dumps({"project": "dc18", "owners": []}))

    def run_door(self, skill, session="s-dc18", door=DOOR, allow=False):
        env = {k: v for k, v in os.environ.items() if k != "DESIGN_CHAIN_ALLOW"}
        env["DESIGN_CHAIN_STATE"] = str(self.state)
        if allow:
            env["DESIGN_CHAIN_ALLOW"] = "1"
        payload = {"hook_event_name": "PreToolUse", "tool_name": "Skill", "session_id": session,
                   "cwd": str(self.inst), "tool_input": {"skill": skill}}
        r = subprocess.run([sys.executable, str(door)], input=json.dumps(payload), capture_output=True,
                           text=True, env=env, timeout=60)
        return r.returncode, r.stderr

    def open_round(self, session="s-dc18"):
        (self.rd / "brief.md").write_text("brief\n")
        (self.state / f"{session}.json").write_text(json.dumps({"pages": {}, "bash_marker": 0,
                                                                "round": str(self.rd)}))

    def test_a_listed_engine_with_no_round_is_refused_naming_the_door(self):
        rc, err = self.run_door("frontend-design")
        self.assertEqual(rc, 2, err)
        self.assertIn("/design-chain", err)

    def test_a_namespaced_engine_is_the_same_engine(self):
        rc, err = self.run_door("kipi-design:brand")
        self.assertEqual(rc, 2, err)

    def test_only_the_skill_tool_is_gated(self):
        env = {**os.environ, "DESIGN_CHAIN_STATE": str(self.state)}
        payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "session_id": "s-dc18",
                   "tool_input": {"skill": "frontend-design", "command": "ls"}}
        r = subprocess.run([sys.executable, str(DOOR)], input=json.dumps(payload), capture_output=True,
                           text=True, env=env, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_an_instance_with_no_config_never_hears_from_the_door(self):
        # an instance that got the hooks and no design-chain.json cannot open a round, so refusing
        # would ban every engine there forever (PR #374 review, major)
        (self.inst / "design-chain.json").unlink()
        self.assertEqual(self.run_door("frontend-design")[0], 0)

    def test_the_founder_override_opens_the_door(self):
        # the gate's refusal advertises DESIGN_CHAIN_ALLOW=1; the door honored no override at all,
        # so an opted-in instance hard-refused every listed engine outside a round with no escape
        # (PR #374 review round 4, major)
        self.assertEqual(self.run_door("frontend-design")[0], 2)          # the control: still refused
        self.assertEqual(self.run_door("frontend-design", allow=True)[0], 0)

    def test_the_override_does_not_disarm_the_recorder(self):
        # an engine the override let through inside an open round is still recorded, or seal would
        # refuse a credit the operator legitimately earned
        self.open_round()
        env = {k: v for k, v in os.environ.items() if k != "DESIGN_CHAIN_ALLOW"}
        env.update({"DESIGN_CHAIN_STATE": str(self.state), "DESIGN_CHAIN_ALLOW": "1"})
        payload = {"hook_event_name": "PostToolUse", "tool_name": "Skill", "session_id": "s-dc18",
                   "cwd": str(self.inst), "tool_input": {"skill": "frontend-design"}}
        r = subprocess.run([sys.executable, str(DOOR)], input=json.dumps(payload), capture_output=True,
                           text=True, env=env, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("frontend-design", (self.rd / "engines.jsonl").read_text())

    def test_an_unlisted_skill_passes(self):
        self.assertEqual(self.run_door("q-debrief")[0], 0)

    def test_inside_an_open_round_the_engine_runs(self):
        self.open_round()
        self.assertEqual(self.run_door("frontend-design")[0], 0)

    def test_a_sealed_round_is_not_open(self):
        self.open_round()
        (self.rd / "receipts.json").write_text("{}")
        self.assertEqual(self.run_door("frontend-design")[0], 2)

    def test_another_sessions_round_does_not_open_this_one(self):
        self.open_round("s-other")
        self.assertEqual(self.run_door("frontend-design", session="s-dc18")[0], 2)

    def gate_write(self, path, session="s-dc18"):
        env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_PROJECT_DIR", "DESIGN_CHAIN_ALLOW")}
        env["DESIGN_CHAIN_STATE"] = str(self.state)
        payload = {"hook_event_name": "PostToolUse", "tool_name": "Write", "session_id": session,
                   "tool_input": {"file_path": str(path)}}
        r = subprocess.run([sys.executable, str(GATE)], input=json.dumps(payload), capture_output=True,
                           text=True, env=env, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_writing_in_a_round_opens_it_for_the_door(self):
        # the real producer of the ledger key: the gate's PostToolUse on a write inside a round
        (self.rd / "brief.md").write_text("brief\n")
        self.gate_write(self.rd / "brief.md")
        self.assertEqual(self.run_door("frontend-design")[0], 0)

    def test_a_write_in_a_round_subfolder_opens_the_round(self):
        # std-1: build output lives below the round folder
        (self.rd / "brief.md").write_text("brief\n")
        cand = self.rd / "directions" / "candidate-a"
        cand.mkdir(parents=True)
        (cand / "index.html").write_text("<html></html>")
        self.gate_write(cand / "index.html")
        self.assertEqual(self.run_door("frontend-design")[0], 0)

    def test_a_folder_with_a_brief_but_no_config_is_not_a_round(self):
        # the round dir alone does not open a round: without the instance config there is no chain,
        # and the door stays out of that instance entirely (PR #374 review)
        (self.inst / "design-chain.json").unlink()
        (self.rd / "brief.md").write_text("brief\n")
        self.gate_write(self.rd / "brief.md")
        state = json.loads((self.state / "s-dc18.json").read_text()) if (self.state / "s-dc18.json").is_file() else {}
        self.assertNotIn("round", state, "a folder with no config above it opened a round")

    def test_a_brief_folder_outside_the_rounds_dir_is_not_a_round(self):
        # adv-1: a template folder holding brief.md under the instance is not a design round
        tpl = self.tmp / "inst" / "q-consult" / "templates" / "content"
        tpl.mkdir(parents=True)
        (tpl / "brief.md").write_text("template\n")
        self.gate_write(tpl / "research.md")
        self.assertEqual(self.run_door("frontend-design")[0], 2)

    def test_the_project_dir_fallback_config_does_not_make_a_round(self):
        # adv-3: a brief.md folder outside the instance, with only the project config
        proj = self.tmp / "proj"
        proj.mkdir()
        (proj / "design-chain.json").write_text(json.dumps({"project": "p", "owners": []}))
        far = self.tmp / "elsewhere" / "y"
        far.mkdir(parents=True)
        (far / "brief.md").write_text("b\n")
        env = {k: v for k, v in os.environ.items() if k != "DESIGN_CHAIN_ALLOW"}
        env.update({"DESIGN_CHAIN_STATE": str(self.state), "CLAUDE_PROJECT_DIR": str(proj)})
        payload = {"hook_event_name": "PostToolUse", "tool_name": "Write", "session_id": "s-dc18",
                   "tool_input": {"file_path": str(far / "note.txt")}}
        subprocess.run([sys.executable, str(GATE)], input=json.dumps(payload), capture_output=True, text=True,
                       env=env, timeout=120)
        self.assertEqual(self.run_door("frontend-design")[0], 2)

    def test_a_round_whose_brief_is_gone_is_not_open(self):
        # adv-4
        self.open_round()
        (self.rd / "brief.md").unlink(missing_ok=True)
        self.assertEqual(self.run_door("frontend-design")[0], 2)

    def test_other_spellings_of_an_engine_are_the_engine(self):
        # adv-5
        for spelling in ("Frontend-Design", " frontend-design ", "frontend-design:", "/frontend-design",
                         "frontend-design/", "frontend_design"):
            self.assertEqual(self.run_door(spelling)[0], 2, spelling)

    def test_installed_design_skills_are_listed(self):
        # adv-6
        for skill in ("anthropic-skills:canvas-design", "hyperframes-core", "nateherk-design:scroll-craft"):
            self.assertEqual(self.run_door(skill)[0], 2, skill)

    def door_copy(self, registry_text):
        d = self.tmp / "bin"
        d.mkdir(exist_ok=True)
        shutil.copy(DOOR, d / DOOR.name)
        (d / "design-engines.json").write_text(registry_text)
        return d / DOOR.name

    def test_a_registry_only_engine_is_refused(self):
        door = self.door_copy(json.dumps({"engines": [{"skill": "made-up-engine", "lane": "site", "stage": "build"}]}))
        self.assertEqual(self.run_door("made-up-engine", door=door)[0], 2)

    def test_an_unreadable_registry_still_refuses_the_core_list(self):
        door = self.door_copy("{not json")
        self.assertEqual(self.run_door("frontend-design", door=door)[0], 2)
        self.assertEqual(self.run_door("made-up-engine", door=door)[0], 0)

    def test_the_no_match_path_is_under_50_ms(self):
        spec = importlib.util.spec_from_file_location("dc18_door", DOOR)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        payload = {"tool_name": "Skill", "session_id": "s", "tool_input": {"skill": "q-debrief"}}
        best = min(self._time(mod, payload) for _ in range(5))
        self.assertLess(best, 0.050, best)

    @staticmethod
    def _time(mod, payload):
        t = time.perf_counter()
        mod.decide(payload)
        return time.perf_counter() - t


if __name__ == "__main__":
    unittest.main()
