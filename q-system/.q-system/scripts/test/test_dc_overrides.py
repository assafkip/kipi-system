#!/usr/bin/env python3
"""ASK-1876: the two ways design-chain-gate.py's Stop went quiet with an unsealed page in the ledger.

1. DESIGN_CHAIN_STATE relocates the ledger, so a relocated dir is an override as real as
   DESIGN_CHAIN_ALLOW=1. block() must name it, and a quiet exit under it must say so.
2. `stop_hook_active` was honored on the first repeat, so Stop refused once and the session ended
   unsealed. Stop now refuses STOP_BLOCK_CAP times, then releases and records the unsealed page.

Every test runs on a temp instance and a temp ledger dir. Never a live path.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
# DESIGN_CHAIN_GATE_UNDER_TEST lets the reproducer load a pre-fix copy to show red.
GATE = Path(os.environ.get("DESIGN_CHAIN_GATE_UNDER_TEST") or (HERE.parent / "design-chain-gate.py"))


def run(payload, state):
    e = dict(os.environ)
    e.pop("DESIGN_CHAIN_ALLOW", None)
    e.pop("CLAUDE_PROJECT_DIR", None)
    e["DESIGN_CHAIN_STATE"] = str(state)
    r = subprocess.run([sys.executable, str(GATE)], input=json.dumps(payload),
                       capture_output=True, text=True, env=e)
    return r.returncode, r.stdout + r.stderr


class TestOverrides(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="dcg-ovr-"))
        self.inst = self.tmp / "instance"
        rnd = self.inst / "site" / "design" / "r1"
        rnd.mkdir(parents=True)
        (self.inst / "design-chain.json").write_text(json.dumps({"owners": []}))
        (rnd / "brief.md").write_text("# Brief\n")
        self.page = rnd / "D1.html"
        self.state = self.tmp / "state"
        self.sid = "sess-ovr"
        # enroll the page the way the gate does: a Write PostToolUse
        rc, out = run({"hook_event_name": "PostToolUse", "tool_name": "Write", "session_id": self.sid,
                       "cwd": str(self.inst), "tool_input": {"file_path": str(self.page)}}, self.state)
        self.page.write_text("<html><body><h1>x</h1></body></html>")
        rc, out = run({"hook_event_name": "PostToolUse", "tool_name": "Write", "session_id": self.sid,
                       "cwd": str(self.inst), "tool_input": {"file_path": str(self.page)}}, self.state)
        self.assertEqual(rc, 0, out)

    def tearDown(self):
        subprocess.run(["/bin/rm", "-r", str(self.tmp)], check=False)

    def stop(self, active, state=None):
        return run({"hook_event_name": "Stop", "session_id": self.sid, "stop_hook_active": active,
                    "cwd": str(self.inst)}, state or self.state)

    def test_control_stop_blocks_with_the_page_in_the_ledger(self):
        rc, out = self.stop(False)
        self.assertEqual(rc, 2, out)

    def test_block_message_names_the_state_override(self):
        rc, out = self.stop(False)
        self.assertIn("DESIGN_CHAIN_STATE", out)

    def test_relocated_ledger_passes_but_says_so(self):
        rc, out = self.stop(False, state=self.tmp / "elsewhere")
        self.assertEqual(rc, 0, out)
        self.assertIn("DESIGN_CHAIN_STATE", out, "a relocated ledger must not pass silently")

    def test_second_stop_still_blocks(self):
        self.assertEqual(self.stop(False)[0], 2)
        rc, out = self.stop(True)
        self.assertEqual(rc, 2, out)

    def test_stop_releases_after_the_cap_and_records_the_page(self):
        self.assertEqual(self.stop(False)[0], 2)
        self.assertEqual(self.stop(True)[0], 2)
        self.assertEqual(self.stop(True)[0], 2)
        rc, out = self.stop(True)
        self.assertEqual(rc, 0, out)
        led = json.loads((self.state / f"{self.sid}.json").read_text())
        self.assertEqual([Path(p).name for p in led["unsealed_at_stop"]], ["D1.html"])


if __name__ == "__main__":
    unittest.main()
