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
                    # keyed by command too: the live file carries a bare and an isolated Stop entry,
                    # and collapsing them hid one from every assertion (PR #374 review, nit)
                    out[(ev, m.get("matcher"), cmd)] = cmd
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

    def test_both_settings_files_wire_the_gate_and_the_door(self):
        live, template = wired(LIVE), wired(TEMPLATE)
        # by ROLE, not by count: a proposal may only ADD to the live file, so the template replaces
        # its narrow matcher while the live file carries the narrow one plus the wider block
        for name, got in (("live", live), ("template", template)):
            roles = {(ev, matcher == "Skill") for (ev, matcher, _c) in got}
            for ev, is_door in (("PreToolUse", False), ("PreToolUse", True), ("PostToolUse", False),
                                ("PostToolUse", True), ("Stop", False), ("SubagentStop", False)):
                self.assertIn((ev, is_door), roles,
                              f"{name}: no {'door' if is_door else 'gate'} hook on {ev}: {sorted(got)}")
            wide = [m for (ev, m, _c) in got if ev == "PreToolUse" and m and "chrome-devtools" in m]
            self.assertTrue(any(m.endswith("mcp__plugin_chrome-devtools.*") for m in wide),
                            f"{name}: the chrome-devtools surface is narrower than the gate's own prefix")
        # the same scripts in both, which is what settings-template-sync-check compares
        self.assertEqual({GATE in c for c in live.values()}, {GATE in c for c in template.values()})

    def test_the_template_the_fleet_gets_runs_the_hooks_isolated(self):
        # `python3 <script>` runs sitecustomize.py from PYTHONPATH before the gate's first line, so a
        # session could no-op every hook. The gate already gives its own producers -I (dc-24 review)
        for (ev, matcher, _c), cmd in sorted(wired(TEMPLATE).items()):
            self.assertIn("python3 -I ", cmd, f"{ev}/{matcher} is not isolated")

    def test_every_live_surface_has_an_isolated_command(self):
        # a proposal may only ADD, so the bare copies stay; what matters is that each surface also
        # has an isolated one, which still refuses when the bare copy is silenced (PR #374 review)
        by_surface = {}
        for (ev, matcher, _c), cmd in wired(LIVE).items():
            by_surface.setdefault((ev, matcher == "Skill"), []).append(cmd)
        for surface, cmds in sorted(by_surface.items()):
            self.assertTrue(any("python3 -I " in c for c in cmds),
                            f"{surface}: no isolated command, a sitecustomize silences this surface")

    def test_the_gate_will_not_touch_a_ledger_another_process_holds(self):
        """Two gate processes on one event each read the ledger and the second write erases the
        first, so a page one of them registered never reaches Stop. This repo's live settings really
        do carry duplicate entries per surface, which is what made a latency note a correctness one
        (PR #374 review round 4, major). Deterministic in both directions: the test itself holds the
        lock, so an unlocked gate writes immediately and a locked one waits."""
        import fcntl
        import time
        state = self.tmp / "state"
        state.mkdir(exist_ok=True)
        held = open(state / "slock.lock", "a+")
        self.addCleanup(held.close)
        fcntl.flock(held.fileno(), fcntl.LOCK_EX)

        cmd = next(c for (ev, _m, _c), c in wired(TEMPLATE).items() if ev == "PostToolUse" and GATE in c)
        env = {k: v for k, v in os.environ.items() if k != "DESIGN_CHAIN_ALLOW"}
        env.update({"CLAUDE_PROJECT_DIR": str(self.inst), "DESIGN_CHAIN_STATE": str(state)})
        payload = {"hook_event_name": "PostToolUse", "tool_name": "Write", "session_id": "slock",
                   "tool_input": {"file_path": str(self.page)}}
        proc = subprocess.Popen(["bash", "-c", cmd], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, env=env)
        proc.stdin.write(json.dumps(payload))
        proc.stdin.close()
        led = state / "slock.json"
        time.sleep(1.5)
        wrote_while_locked = led.is_file() and self.page.name in led.read_text()
        fcntl.flock(held.fileno(), fcntl.LOCK_UN)
        proc.wait(timeout=120)
        self.assertFalse(wrote_while_locked,
                         "the gate read-modify-wrote the ledger while another process held the lock")
        self.assertTrue(led.is_file() and self.page.name in led.read_text(),
                        "the gate never registered the page after the lock was released")

    def test_a_sitecustomize_cannot_silence_the_isolated_command(self):
        site = self.tmp / "pypath"
        site.mkdir()
        (site / "sitecustomize.py").write_text("import os\nos._exit(0)\n")
        cmd = next(c for (ev, m, _c), c in wired(TEMPLATE).items() if ev == "PreToolUse" and GATE in c)
        self.run_hook(next(c for (ev, m, _c), c in wired(TEMPLATE).items() if ev == "PostToolUse" and GATE in c),
                      {"hook_event_name": "PostToolUse", "tool_name": "Write", "session_id": "s-site",
                       "tool_input": {"file_path": str(self.page)}})
        env_before = os.environ.get("PYTHONPATH")
        os.environ["PYTHONPATH"] = str(site)
        try:
            rc, out = self.run_hook(cmd, {"hook_event_name": "PreToolUse", "tool_name": "SendUserFile",
                                          "session_id": "s-site", "tool_input": {"files": [str(self.page)]}})
        finally:
            os.environ.pop("PYTHONPATH", None)
            if env_before is not None:
                os.environ["PYTHONPATH"] = env_before
        self.assertEqual(rc, 2, out)

    def test_a_missing_script_is_a_silent_no_op_which_is_the_fleet_convention(self):
        # measured, not assumed (dc-24 review): the Pre/Post form exits 1 with no output and the tool
        # proceeds; the Stop form exits 0. An instance that got the switch without the script is open.
        for (ev, matcher, _c), cmd in sorted(wired(TEMPLATE).items()):
            broken = cmd.replace("design-chain-gate.py", "design-chain-gate-absent.py").replace(
                "design-engine-door.py", "design-engine-door-absent.py")
            rc, out = self.run_hook(broken, {"hook_event_name": ev, "tool_name": "Read", "session_id": "s-gone",
                                             "tool_input": {}})
            self.assertEqual(out.strip(), "", f"{ev}/{matcher} said something when its script was missing")
            self.assertIn(rc, (0, 1), f"{ev}/{matcher} exited {rc} with its script missing")

    def test_every_wired_command_runs_and_passes_a_benign_payload(self):
        for (ev, matcher, _c), cmd in sorted(wired(LIVE).items()):
            rc, out = self.run_hook(cmd, {"hook_event_name": ev, "tool_name": "Read", "session_id": "s-dc24",
                                          "tool_input": {"file_path": str(self.inst / "design-chain.json")}})
            self.assertEqual(rc, 0, f"{ev}/{matcher}: {out}")

    def test_the_wired_gate_blocks_showing_an_unsealed_page(self):
        cmd = next(c for (ev, m, _c), c in wired(LIVE).items() if ev == "PreToolUse" and GATE in c)
        self.run_hook(next(c for (ev, m, _c), c in wired(LIVE).items() if ev == "PostToolUse" and GATE in c),
                      {"hook_event_name": "PostToolUse", "tool_name": "Write", "session_id": "s-dc24",
                       "tool_input": {"file_path": str(self.page)}})
        rc, out = self.run_hook(cmd, {"hook_event_name": "PreToolUse", "tool_name": "SendUserFile",
                                      "session_id": "s-dc24", "tool_input": {"files": [str(self.page)]}})
        self.assertEqual(rc, 2, out)
        self.assertIn("design chain", out.lower())

    def test_the_wired_door_refuses_an_engine_outside_a_round(self):
        cmd = next(c for (ev, m, _c), c in wired(LIVE).items() if ev == "PreToolUse" and DOOR in c)
        rc, out = self.run_hook(cmd, {"hook_event_name": "PreToolUse", "tool_name": "Skill",
                                      "session_id": "s-dc24", "tool_input": {"skill": "frontend-design"}})
        self.assertEqual(rc, 2, out)
        self.assertIn("/design-chain", out)

    def test_the_wired_subagent_stop_refuses_the_same_page_stop_refuses(self):
        # the event was wired and the gate had no branch for it, so it returned 0 on the page Stop
        # refuses at 2 (PR #374 review): a string in a settings file is not a hook that runs
        for ev in ("Stop", "SubagentStop"):
            cmd = next(c for (e, m, _c), c in wired(TEMPLATE).items() if e == ev)
            self.run_hook(next(c for (e, m, _c), c in wired(TEMPLATE).items() if e == "PostToolUse" and GATE in c),
                          {"hook_event_name": "PostToolUse", "tool_name": "Write", "session_id": f"s-{ev}",
                           "tool_input": {"file_path": str(self.page)}})
            rc, out = self.run_hook(cmd, {"hook_event_name": ev, "session_id": f"s-{ev}",
                                          "stop_hook_active": False})
            self.assertEqual(rc, 2, f"{ev} let an unsealed page end the turn: {out}")

    def test_an_instance_with_no_config_is_never_blocked(self):
        # the hooks ship to 25 instances that have no design-chain.json. A page written there must
        # not enter the ledger, or Stop refuses it with a remediation nobody can follow, and the
        # chain is opt-in (PR #374 review, major)
        (self.inst / "design-chain.json").unlink()
        plain = self.inst / "notes" / "page.html"
        plain.parent.mkdir(parents=True, exist_ok=True)
        plain.write_text("<html><body><p>x</p></body></html>")
        post = next(c for (e, m, _c), c in wired(TEMPLATE).items() if e == "PostToolUse" and GATE in c)
        self.run_hook(post, {"hook_event_name": "PostToolUse", "tool_name": "Write", "session_id": "s-plain",
                             "tool_input": {"file_path": str(plain)}})
        for ev in ("Stop", "SubagentStop"):
            cmd = next(c for (e, m, _c), c in wired(TEMPLATE).items() if e == ev)
            rc, out = self.run_hook(cmd, {"hook_event_name": ev, "session_id": "s-plain",
                                          "stop_hook_active": False})
            self.assertEqual(rc, 0, f"{ev} blocked an instance that never opted in: {out}")
        show = next(c for (e, m, _c), c in wired(TEMPLATE).items() if e == "PreToolUse" and GATE in c)
        rc, out = self.run_hook(show, {"hook_event_name": "PreToolUse", "tool_name": "SendUserFile",
                                       "session_id": "s-plain", "tool_input": {"files": [str(plain)]}})
        self.assertEqual(rc, 0, out)

    def test_no_claude_commands_copy_of_the_command(self):
        self.assertFalse((ROOT / ".claude" / "commands" / "design-chain.md").exists(),
                         "the command has one home: plugins/kipi-core/commands/design-chain.md")
        self.assertTrue((ROOT / "plugins" / "kipi-core" / "commands" / "design-chain.md").is_file())


if __name__ == "__main__":
    unittest.main()
