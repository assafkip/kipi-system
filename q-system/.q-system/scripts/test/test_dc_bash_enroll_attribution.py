#!/usr/bin/env python3
"""The PostToolUse Bash branch of design-chain-gate.py enrolls a round page only when THIS
session plausibly made it: the page's content changed across the command (or the page is new),
or the command names the page or its round.

Captured case (2026-09-24, provenance: a builder session's result file, adjacent_findings):
a session working in a shared checkout never wrote a page. Its writes all went to worktrees and
a scratchpad. The round `site/design/<round>/` held 26 pages already modified in `git status`
at session start, by another design session. Launchd jobs, git and auto-commit in the same
checkout moved those pages' mtimes during this session's unrelated Bash commands, and mtime was
the whole filter. All 26 enrolled with `via: Bash`, and Stop blocked the session (and its two
read-only subagents) 6+ times over pages it never made.

Every test runs on a temp instance and a temp ledger dir. Never a live path.
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
# DESIGN_CHAIN_GATE_UNDER_TEST lets the reproducer load a pre-fix copy to show red.
GATE = Path(os.environ.get("DESIGN_CHAIN_GATE_UNDER_TEST") or (HERE.parent / "design-chain-gate.py"))


def run(payload, env):
    e = dict(os.environ)
    e.pop("DESIGN_CHAIN_ALLOW", None)
    e.pop("CLAUDE_PROJECT_DIR", None)
    e.update(env)
    r = subprocess.run([sys.executable, str(GATE)], input=json.dumps(payload),
                       capture_output=True, text=True, env=e)
    return r.returncode, r.stdout + r.stderr


class TestBashEnrollAttribution(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="dcg-attr-"))
        self.inst = self.tmp / "instance"
        self.inst.mkdir()
        (self.inst / "design-chain.json").write_text(json.dumps({"owners": []}))
        # the shape of the captured round: a dated folder under site/design, pages made earlier
        self.round = self.inst / "site" / "design" / "2026-09-21b"
        self.round.mkdir(parents=True)
        (self.round / "brief.md").write_text("# Brief\n")
        self.page = self.round / "D1-astro-laptop.html"
        self.page.write_text("<html><body><h1>made by another session</h1></body></html>")
        old = time.time() - 3600
        os.utime(self.page, (old, old))
        self.env = {"DESIGN_CHAIN_STATE": str(self.tmp / "state")}
        self.sid = "sess-attr"

    def tearDown(self):
        subprocess.run(["/bin/rm", "-r", str(self.tmp)], check=False)

    def bash(self, cmd, during):
        base = {"tool_name": "Bash", "session_id": self.sid, "tool_input": {"command": cmd},
                "cwd": str(self.inst)}
        rc, out = run({**base, "hook_event_name": "PreToolUse"}, self.env)
        self.assertEqual(rc, 0, out)
        time.sleep(0.05)
        during()
        rc, out = run({**base, "hook_event_name": "PostToolUse"}, self.env)
        self.assertEqual(rc, 0, out)

    def ledger_pages(self):
        led = json.loads((self.tmp / "state" / f"{self.sid}.json").read_text())
        return set(led.get("pages", {}))

    def stop(self):
        return run({"hook_event_name": "Stop", "session_id": self.sid, "stop_hook_active": False}, self.env)

    def touch(self):
        os.utime(self.page, None)

    # --- the reproducer ------------------------------------------------------------------

    def test_mtime_only_change_under_an_unrelated_command_does_not_enroll(self):
        before = hashlib.sha256(self.page.read_bytes()).hexdigest()
        self.bash("git -C ~/projects/kipi-system log --oneline -3", self.touch)
        self.assertEqual(hashlib.sha256(self.page.read_bytes()).hexdigest(), before,
                         "setup: only the mtime may move")
        self.assertGreater(self.page.stat().st_mtime, time.time() - 5, "setup: the mtime did move")
        self.assertNotIn(str(self.page.resolve()), self.ledger_pages())
        rc, out = self.stop()
        self.assertEqual(rc, 0, out)

    # --- controls: a page this session really made still enrolls -------------------------

    def test_content_rewritten_by_an_unnamed_command_enrolls(self):
        self.bash("python3 build.py", lambda: self.page.write_text("<html><body>rebuilt</body></html>"))
        self.assertIn(str(self.page.resolve()), self.ledger_pages())
        rc, out = self.stop()
        self.assertEqual(rc, 2, out)

    def test_a_new_page_from_an_unnamed_command_enrolls(self):
        gen = self.round / "Seam-laptop.html"
        self.bash("python3 build.py", lambda: gen.write_text("<html><body>new</body></html>"))
        self.assertIn(str(gen.resolve()), self.ledger_pages())

    def test_a_command_naming_the_page_enrolls_even_on_a_touch(self):
        self.bash(f"touch {self.page.name}", self.touch)
        self.assertIn(str(self.page.resolve()), self.ledger_pages())

    def test_a_command_naming_the_round_enrolls_even_on_a_touch(self):
        self.bash("cp -p stash/*.html site/design/2026-09-21b/", self.touch)
        self.assertIn(str(self.page.resolve()), self.ledger_pages())


if __name__ == "__main__":
    unittest.main()
