#!/usr/bin/env python3
"""The PostToolUse Bash branch of design-chain-gate.py enrolls a round page only when THIS
session plausibly made it: the page's content changed across the command, or the page is new.
Naming the page or its round in the command is not authorship (a read-only `ls` of another
session's round must not enroll it), and a RETIRED round enrolls nothing.

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

    def payload(self, cmd, tid=None):
        base = {"tool_name": "Bash", "session_id": self.sid, "tool_input": {"command": cmd},
                "cwd": str(self.inst)}
        if tid:
            base["tool_use_id"] = tid
        return base

    def hook(self, base, ev):
        rc, out = run({**base, "hook_event_name": ev}, self.env)
        self.assertEqual(rc, 0, out)

    def bash(self, cmd, during, tid=None, posts=1):
        base = self.payload(cmd, tid)
        self.hook(base, "PreToolUse")
        time.sleep(0.05)
        during()
        # settings.json wires this gate twice per event, so the real Post fires twice
        for _ in range(posts):
            self.hook(base, "PostToolUse")

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

    def test_duplicate_post_invocation_does_not_enroll_a_touch(self):
        # PR #445 review round 1, major: the first version popped the snapshot, so the second of
        # the two wired Post hooks found none and enrolled the touched page
        self.bash("git -C ~/projects/kipi-system log --oneline -3", self.touch, tid="toolu_a", posts=2)
        self.assertNotIn(str(self.page.resolve()), self.ledger_pages())
        rc, out = self.stop()
        self.assertEqual(rc, 0, out)

    def test_parallel_calls_keep_their_own_snapshot(self):
        # Pre A, Pre B, A rewrites the page, Post B, Post A: B's snapshot was taken before A wrote,
        # A's own must still show the change
        a, b = self.payload("python3 build.py", "toolu_a"), self.payload("git status", "toolu_b")
        self.hook(a, "PreToolUse")
        time.sleep(0.05)
        self.page.write_text("<html><body>rebuilt by A</body></html>")
        self.hook(b, "PreToolUse")
        self.hook(b, "PostToolUse")
        self.assertNotIn(str(self.page.resolve()), self.ledger_pages(),
                         "B snapshotted after A wrote; B did not make the page")
        self.hook(a, "PostToolUse")
        self.assertIn(str(self.page.resolve()), self.ledger_pages())

    def test_a_read_only_command_naming_the_round_does_not_enroll_a_touch(self):
        # PR #445 review round 1, minor: naming is not authorship, content change is
        for cmd in (f"ls -la site/design/{self.round.name}", f"grep -rn hero site/design/{self.round.name}",
                    f"cat site/design/{self.round.name}/{self.page.name}"):
            self.bash(cmd, self.touch, tid="toolu_ro")
            self.assertNotIn(str(self.page.resolve()), self.ledger_pages(), cmd)

    def test_a_command_naming_the_round_that_rewrites_a_page_enrolls(self):
        self.bash(f"cp stash/new.html site/design/{self.round.name}/{self.page.name}",
                  lambda: self.page.write_text("<html><body>copied in</body></html>"), tid="toolu_cp")
        self.assertIn(str(self.page.resolve()), self.ledger_pages())

class TestRetiredRound(TestBashEnrollAttribution):
    """A round with a RETIRED file (date, reason, who decided) is skipped completely.
    Captured case: 2026-09-21b was published by hand; founder ruling 2026-09-24."""

    def retire(self, text="2026-09-24 published; founder ruling 2026-09-24 (<owner>)"):
        (self.round / "RETIRED").write_text(text + "\n")

    def write(self):
        return run({"hook_event_name": "PostToolUse", "tool_name": "Write", "session_id": self.sid,
                    "tool_input": {"file_path": str(self.page)}}, self.env)

    def test_an_active_round_still_blocks(self):
        self.write()
        rc, out = self.stop()
        self.assertEqual(rc, 2, out)
        self.assertIn(self.page.name, out)

    def test_a_retired_round_does_not_enroll_or_block(self):
        self.retire()
        self.write()
        self.bash("python3 build.py", lambda: self.page.write_text("<html><body>rebuilt</body></html>"),
                  tid="toolu_r")
        self.assertEqual(self.ledger_pages(), set())
        rc, out = self.stop()
        self.assertEqual(rc, 0, out)
        self.assertNotIn(self.page.name, out)

    def test_retiring_silences_a_page_already_enrolled(self):
        self.write()
        self.retire()
        rc, out = self.stop()
        self.assertEqual(rc, 0, out)
        self.assertNotIn(self.page.name, out)

    def test_an_empty_retired_file_retires_nothing(self):
        self.write()
        self.retire(text="")
        rc, out = self.stop()
        self.assertEqual(rc, 2, out)
        self.assertIn("RETIRED carries no reason", out)


if __name__ == "__main__":
    unittest.main()
