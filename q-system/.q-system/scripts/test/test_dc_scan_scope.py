#!/usr/bin/env python3
"""dc-17: the post-Bash scan walks only roots that hold a design-chain.json.

WHY. After every Bash call the gate walked every registered instance looking for new pages. Measured
2026-09-19: the registry lists 26 instances and 1 holds a design-chain.json, so 25 were walked for
nothing, nested worktrees (.wt-*, .claude/worktrees) included. Now a root counts only when it or a
parent holds the config, and nested worktrees are pruned.
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
from unittest import mock

HERE = Path(__file__).resolve().parent
GATE = HERE.parent / "design-chain-gate.py"


def load_gate():
    spec = importlib.util.spec_from_file_location("dc17_gate", GATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class ScanScope(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="dc17-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.design = self.tmp / "design-inst"
        self.plain = self.tmp / "plain-inst"
        self.hub = self.tmp / "hub"
        for d in (self.design, self.plain, self.hub):
            d.mkdir()
        (self.design / "design-chain.json").write_text(json.dumps({"project": "dc17", "owners": []}))
        for i in range(30):
            (self.plain / f"d{i}").mkdir()
            (self.plain / f"d{i}" / "page.html").write_text("<html><body><p>x</p></body></html>")
        (self.hub / "instance-registry.json").write_text(json.dumps(
            {"instances": [{"path": str(self.design)}, {"path": str(self.plain)}]}))
        self.env = mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": str(self.hub)}, clear=False)
        self.env.start()
        self.addCleanup(self.env.stop)
        os.environ.pop("DESIGN_CHAIN_EXTRA_ROOT", None)
        self.gate = load_gate()

    def test_a_root_without_a_config_is_dropped(self):
        roots = self.gate.scan_roots({"cwd": str(self.tmp)})
        self.assertIn(self.design, roots)
        self.assertNotIn(self.plain, roots)
        self.assertNotIn(self.hub, roots)

    def test_the_non_design_root_is_never_walked(self):
        walked = []
        real_walk = os.walk

        def spy(top, *a, **k):
            walked.append(Path(top).resolve())
            return real_walk(top, *a, **k)
        with mock.patch.object(self.gate.os, "walk", spy):
            self.gate.newer_pages(self.gate.scan_roots({"cwd": str(self.tmp)}), 0)
        self.assertTrue(walked, "nothing was walked at all")
        self.assertFalse(any(w == self.plain or self.plain in w.parents for w in walked), walked)

    def test_a_cwd_inside_a_design_instance_is_kept(self):
        # the cwd is the only way in, and its config is in a parent
        sub = self.design / "site"
        sub.mkdir()
        self.assertEqual(self.gate.scan_roots({"cwd": str(sub)}), [sub])

    def test_nested_worktrees_are_pruned(self):
        since = time.time() - 60
        for rel in (".wt-feature/site/p.html", ".claude/worktrees/w1/site/p.html", "site/p.html",
                    ".wt-shadow/p.html"):
            f = self.design / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("<html><body><p>x</p></body></html>")
        # a nested checkout carries its own .git (a worktree's is a file); a folder that is only NAMED
        # like one does not, and its pages belong to this instance (dc-17 std-2)
        (self.design / ".wt-feature" / ".git").write_text("gitdir: elsewhere\n")
        (self.design / ".claude" / "worktrees" / "w1" / ".git").write_text("gitdir: elsewhere\n")
        found = [Path(p).resolve() for p in self.gate.newer_pages([self.design], since)]
        self.assertIn(self.design / "site" / "p.html", found)
        self.assertIn(self.design / ".wt-shadow" / "p.html", found)
        self.assertFalse(any(".wt-feature" in str(p) or "worktrees" in str(p) for p in found), found)

    def test_a_config_below_the_root_is_scanned(self):
        # std-1: root/frontend/design-chain.json governs root/frontend/, so that folder is scanned.
        # The descent is dc-17's decision and is unchanged by round 7; only which top-level roots
        # feed it narrowed, so the fixture reaches it by cwd rather than by a registry entry.
        nested = self.tmp / "nested-inst"
        (nested / "frontend").mkdir(parents=True)
        (nested / "frontend" / "design-chain.json").write_text("{}")
        self.assertEqual(self.gate.scan_roots({"cwd": str(nested)}), [nested / "frontend"])

    def test_the_instance_registry_is_not_a_way_in(self):
        # a session working in one project enrolled another project's round pages, and Stop refused
        # the end of the turn with a remediation only that other project could perform (round 7)
        (self.hub / "instance-registry.json").write_text(json.dumps(
            {"instances": [{"path": str(self.design)}]}))
        self.assertEqual(self.gate.scan_roots({"cwd": str(self.hub)}), [])


class BashEnrolsOnlyRoundPages(unittest.TestCase):
    """mtime was the whole filter on the post-Bash scan, so a checkout or an install that touched
    src/components/*.tsx enrolled ordinary application source and Stop refused the end of the turn
    over files that were never design pages (PR #374 review round 7, major)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="dc17b-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.inst = self.tmp / "inst"
        self.state = self.tmp / "state"
        self.state.mkdir(parents=True)
        (self.inst).mkdir()
        (self.inst / "design-chain.json").write_text(json.dumps({"project": "dc17b", "owners": []}))
        self.round = self.inst / "site" / "design" / "r1"
        self.round.mkdir(parents=True)
        (self.round / "brief.md").write_text("brief\n")
        self.page = self.round / "Home-laptop.html"
        self.src = self.inst / "src" / "components" / "Button.tsx"
        self.src.parent.mkdir(parents=True)

    def run_bash_scan(self):
        env = {k: v for k, v in os.environ.items() if k not in ("DESIGN_CHAIN_ALLOW",)}
        env.update({"CLAUDE_PROJECT_DIR": str(self.inst), "DESIGN_CHAIN_STATE": str(self.state)})
        payload = {"hook_event_name": "PostToolUse", "tool_name": "Bash", "session_id": "s-scan",
                   "cwd": str(self.inst), "tool_input": {"command": "true"}}
        r = subprocess.run([sys.executable, str(GATE)], input=json.dumps(payload),
                           capture_output=True, text=True, env=env, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        led = json.loads((self.state / "s-scan.json").read_text())
        return set(led.get("pages", {}))

    def test_application_source_a_command_touched_does_not_enrol(self):
        self.src.write_text("export const Button = () => null\n")
        self.assertEqual(self.run_bash_scan(), set())

    def test_a_page_inside_a_round_still_enrols(self):
        self.page.write_text("<html><body><p>x</p></body></html>")
        self.assertIn(str(self.page.resolve()), self.run_bash_scan())


if __name__ == "__main__":
    unittest.main()
