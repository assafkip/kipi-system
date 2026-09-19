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
        roots = self.gate.scan_roots({"cwd": str(self.hub)})
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
            self.gate.newer_pages(self.gate.scan_roots({"cwd": str(self.hub)}), 0)
        self.assertTrue(walked, "nothing was walked at all")
        self.assertFalse(any(w == self.plain or self.plain in w.parents for w in walked), walked)

    def test_a_cwd_inside_a_design_instance_is_kept(self):
        # the registry does not list it: the cwd is the only way in, and its config is in a parent
        (self.hub / "instance-registry.json").write_text(json.dumps({"instances": [{"path": str(self.plain)}]}))
        sub = self.design / "site"
        sub.mkdir()
        self.assertEqual(self.gate.scan_roots({"cwd": str(sub)}), [sub])

    def test_nested_worktrees_are_pruned(self):
        since = time.time() - 60
        for rel in (".wt-feature/site/p.html", ".claude/worktrees/w1/site/p.html", "site/p.html"):
            f = self.design / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("<html><body><p>x</p></body></html>")
        found = [Path(p).resolve() for p in self.gate.newer_pages([self.design], since)]
        self.assertIn(self.design / "site" / "p.html", found)
        self.assertFalse(any(".wt-feature" in str(p) or "worktrees" in str(p) for p in found), found)


if __name__ == "__main__":
    unittest.main()
