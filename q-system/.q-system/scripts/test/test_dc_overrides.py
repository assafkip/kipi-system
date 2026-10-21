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
        self.transcript = self.tmp / "transcript.jsonl"
        self.transcript.write_text("")
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

    def wired_stop(self, active):
        """One logical Stop event as the harness actually delivers it.

        `.claude/settings.json` wires design-chain-gate.py as TWO independent Stop entries, so the
        harness runs it twice per end-of-turn with the same payload and the same transcript bytes.
        The transcript grows between real events (the model answered), never between the two
        sub-invocations of one. Returns both return codes.
        """
        self.transcript.write_text(self.transcript.read_text() + json.dumps({"turn": active}) + "\n")
        p = {"hook_event_name": "Stop", "session_id": self.sid, "stop_hook_active": active,
             "cwd": str(self.inst), "transcript_path": str(self.transcript)}
        return run(p, self.state)[0], run(p, self.state)[0]

    def test_a_wired_double_invocation_counts_one_stop_event_once(self):
        # the deployed topology: 3 real events must each be refused by BOTH sub-invocations, and
        # only the 4th releases. Pre-fix the second sub-invocation of event 2 released (rc 2,0).
        self.assertEqual(self.wired_stop(False), (2, 2), "event 1")
        self.assertEqual(self.wired_stop(True), (2, 2), "event 2")
        self.assertEqual(self.wired_stop(True), (2, 2), "event 3")
        self.assertEqual(self.wired_stop(True), (0, 0), "event 4 releases, idempotently")

    def test_a_new_open_page_gets_its_own_strikes_after_a_release(self):
        for active in (False, True, True, True):
            self.wired_stop(active)
        led = json.loads((self.state / f"{self.sid}.json").read_text())
        self.assertTrue(led.get("unsealed_at_stop"), "the first episode must have released")
        page2 = self.page.parent / "D2.html"
        rc, out = run({"hook_event_name": "PostToolUse", "tool_name": "Write", "session_id": self.sid,
                       "cwd": str(self.inst), "tool_input": {"file_path": str(page2)}}, self.state)
        page2.write_text("<html><body><h1>y</h1></body></html>")
        run({"hook_event_name": "PostToolUse", "tool_name": "Write", "session_id": self.sid,
             "cwd": str(self.inst), "tool_input": {"file_path": str(page2)}}, self.state)
        # a different set of unsealed pages is a different episode: it earns the full cap again
        self.assertEqual(self.wired_stop(True), (2, 2), "second episode, strike 1")
        self.assertEqual(self.wired_stop(True), (2, 2), "second episode, strike 2")

    def test_a_stalled_event_key_still_releases(self):
        # a model turn that writes no transcript bytes leaves the key unchanged, so dedupe cannot
        # advance. The invocation ceiling is the loop exit: the session must still be able to end.
        self.transcript.write_text("x\n")
        p = {"hook_event_name": "Stop", "session_id": self.sid, "stop_hook_active": True,
             "cwd": str(self.inst), "transcript_path": str(self.transcript)}
        codes = [run(p, self.state)[0] for _ in range(14)]
        self.assertIn(0, codes, f"a stalled key must not block forever: {codes}")

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
