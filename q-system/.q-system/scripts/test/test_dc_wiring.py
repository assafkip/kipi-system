#!/usr/bin/env python3
"""dc-24: the wiring ships last, and it is run the way the harness runs it.

WHY. The gate and the door are only enforcement if the harness calls them. Wiring ships after every
other issue so the fleet never receives the trusting version of the gate (order, ASK-1796). This test
reads both settings files, and RUNS each wired command the way Claude Code does, with the payload on
stdin and CLAUDE_PROJECT_DIR set, against a temp instance: a grep for the command string proves a
string, not a hook that runs.
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
LIVE = ROOT / ".claude" / "settings.json"
TEMPLATE = ROOT / "settings-template.json"
GATE = "q-system/.q-system/scripts/design-chain-gate.py"
DOOR = "q-system/.q-system/scripts/design-engine-door.py"


def wired(path: Path) -> dict:
    """{(event, matcher): command} for every design-chain hook in a settings file."""
    out = {}
    for ev, arr in (json.loads(path.read_text()).get("hooks") or {}).items():
        for m in arr:
            for h in m.get("hooks", []):
                cmd = h.get("command", "")
                if GATE in cmd or DOOR in cmd:
                    out[(ev, m.get("matcher"))] = cmd
    return out


class Wiring(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="dc24-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.inst = self.tmp / "inst"
        (self.inst / "q-system" / ".q-system" / "scripts").mkdir(parents=True)
        for name in ("design-chain-gate.py", "design-engine-door.py", "design-engines.json",
                     "read-first-gate.py", "design-reader-gate.py"):
            shutil.copy(ROOT / "q-system" / ".q-system" / "scripts" / name,
                        self.inst / "q-system" / ".q-system" / "scripts" / name)
        (self.inst / "design-chain.json").write_text(json.dumps({"project": "dc24", "owners": []}))
        self.round = self.inst / "site" / "design" / "r1"
        self.round.mkdir(parents=True)
        self.page = self.round / "Home-laptop.html"
        self.page.write_text("<html><body><p>x</p></body></html>")

    def run_hook(self, cmd: str, payload: dict):
        env = {k: v for k, v in os.environ.items() if k != "DESIGN_CHAIN_ALLOW"}
        env.update({"CLAUDE_PROJECT_DIR": str(self.inst), "DESIGN_CHAIN_STATE": str(self.tmp / "state")})
        r = subprocess.run(["bash", "-c", cmd], input=json.dumps(payload), capture_output=True,
                           text=True, env=env, timeout=300)
        return r.returncode, r.stdout + r.stderr

    def test_both_settings_files_wire_the_same_five_hooks(self):
        live, template = wired(LIVE), wired(TEMPLATE)
        self.assertEqual(len(live), 5, sorted(live))
        self.assertEqual(sorted(live), sorted(template), "the two settings files disagree")
        self.assertEqual(sorted(k[0] for k in live), ["PostToolUse", "PostToolUse", "PreToolUse", "PreToolUse", "Stop"])

    def test_every_wired_command_runs_and_passes_a_benign_payload(self):
        for (ev, matcher), cmd in sorted(wired(LIVE).items()):
            rc, out = self.run_hook(cmd, {"hook_event_name": ev, "tool_name": "Read", "session_id": "s-dc24",
                                          "tool_input": {"file_path": str(self.inst / "design-chain.json")}})
            self.assertEqual(rc, 0, f"{ev}/{matcher}: {out}")

    def test_the_wired_gate_blocks_showing_an_unsealed_page(self):
        cmd = next(c for (ev, m), c in wired(LIVE).items() if ev == "PreToolUse" and GATE in c)
        self.run_hook(next(c for (ev, m), c in wired(LIVE).items() if ev == "PostToolUse" and GATE in c),
                      {"hook_event_name": "PostToolUse", "tool_name": "Write", "session_id": "s-dc24",
                       "tool_input": {"file_path": str(self.page)}})
        rc, out = self.run_hook(cmd, {"hook_event_name": "PreToolUse", "tool_name": "SendUserFile",
                                      "session_id": "s-dc24", "tool_input": {"files": [str(self.page)]}})
        self.assertEqual(rc, 2, out)
        self.assertIn("design chain", out.lower())

    def test_the_wired_door_refuses_an_engine_outside_a_round(self):
        cmd = next(c for (ev, m), c in wired(LIVE).items() if ev == "PreToolUse" and DOOR in c)
        rc, out = self.run_hook(cmd, {"hook_event_name": "PreToolUse", "tool_name": "Skill",
                                      "session_id": "s-dc24", "tool_input": {"skill": "frontend-design"}})
        self.assertEqual(rc, 2, out)
        self.assertIn("/design-chain", out)

    def test_no_claude_commands_copy_of_the_command(self):
        self.assertFalse((ROOT / ".claude" / "commands" / "design-chain.md").exists(),
                         "the command has one home: plugins/kipi-core/commands/design-chain.md")
        self.assertTrue((ROOT / "plugins" / "kipi-core" / "commands" / "design-chain.md").is_file())


if __name__ == "__main__":
    unittest.main()
