#!/usr/bin/env python3
"""Tests for instruction-chars-audit.py (ASK-3689).

Pairs with `q-system/.q-system/scripts/instruction-chars-audit.py`. Every case
builds its own parent/nested-child tree and passes --registry and --user-dir, so no
case writes a real settings file. The loader walks EVERY ancestor of the launch
folder, so the tree is built in a temp dir outside $HOME: under $HOME it picked up
the real ~/.claude files and 2 cases failed by exactly their 16,535 chars (PR 599
review, round 1, reproduced with TMPDIR under $HOME).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "instruction-chars-audit.py"

SHARED = "S" * 20000
USER_MD = "u" * 100
PARENT_MD = "P" * 1000 + "\n@extra.md\n"
CHILD_MD = "C" * 400 + "\n```\n@big.md\n```\n" + "\n@q.md\n"


def write(p, text):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def scratch_root():
    """A fresh temp dir that has no home-folder instruction files above it."""
    home = Path.home().resolve()
    for base in (tempfile.gettempdir(), "/var/tmp", "/tmp"):
        b = Path(base).resolve()
        if b.is_dir() and b != home and home not in b.parents:
            return Path(tempfile.mkdtemp(dir=str(b))).resolve()
    raise unittest.SkipTest("no temp dir outside $HOME to build the fixture tree in")


class AuditCase(unittest.TestCase):
    def setUp(self):
        self.root = scratch_root()
        self.addCleanup(shutil.rmtree, self.root)
        self.user = self.root / "user"
        self.parent = self.root / "parent"
        self.child = self.parent / "projects" / "child"
        write(self.user / "CLAUDE.md", USER_MD)
        self.settings = self.user / "settings.json"
        write(self.settings, json.dumps({
            "permissions": {"allow": ["Bash(ls:*)"]},
            "claudeMdExcludes": ["/elsewhere/hand-written.md"],
        }, indent=2))
        write(self.parent / "CLAUDE.md", PARENT_MD)
        write(self.parent / "extra.md", "E" * 500)
        write(self.parent / ".claude/rules/shared.md", SHARED)
        write(self.parent / ".claude/rules/parent_only.md", "Q" * 300)
        write(self.child / "CLAUDE.md", CHILD_MD)
        write(self.child / "q.md", "I" * 700)
        write(self.child / "big.md", "B" * 99999)
        write(self.child / ".claude/rules/shared.md", SHARED)
        write(self.child / ".claude/rules/child_only.md",
              "---\ndescription: x\n---\n" + "K" * 200 + "<!-- hidden -->")
        write(self.child / ".claude/rules/scoped.md",
              "---\npaths:\n  - '**/*.py'\n---\n" + "Z" * 5000)
        self.registry = self.root / "instance-registry.json"
        write(self.registry, json.dumps({"instances": [
            {"name": "parent", "path": str(self.parent)},
            {"name": "child", "path": str(self.child)},
            {"name": "gone", "path": str(self.root / "gone")},
        ]}))

    def run_audit(self, *extra):
        r = subprocess.run(
            [sys.executable, str(SCRIPT), "--registry", str(self.registry),
             "--user-dir", str(self.user), *extra],
            capture_output=True, text=True)
        return r.returncode, r.stdout + r.stderr

    def report(self, limit):
        rc, out = self.run_audit("--json", "--limit", str(limit))
        data = json.loads(out.strip().splitlines()[0])
        return rc, {r["name"]: r for r in data["rows"]}

    def expected_child_before(self):
        return (len(USER_MD) + len(PARENT_MD) + 500 + 300 + len(SHARED)
                + len(CHILD_MD) + 700 + 200 + len(SHARED))

    def test_loader_counts_what_claude_code_loads(self):
        _, rows = self.report(10**9)
        child = rows["child"]
        # fenced import (big.md) and paths-scoped rule are not counted;
        # frontmatter and the HTML comment in child_only.md are not counted
        self.assertEqual(child["chars"], self.expected_child_before())
        self.assertEqual(child["files"], 9)
        self.assertEqual(rows["gone"]["status"], "SKIP")

    def test_red_when_nested_duplicate_pushes_over_limit(self):
        rc, rows = self.report(40000)
        self.assertEqual(rc, 2)
        self.assertEqual(rows["child"]["status"], "OVER")
        self.assertEqual(rows["child"]["duplicates_not_excluded"], 1)

    def test_apply_excludes_only_identical_nested_copies(self):
        rc, out = self.run_audit("--apply")
        self.assertEqual(rc, 0, out)
        data = json.loads(self.settings.read_text())
        excl = data["claudeMdExcludes"]
        self.assertIn(str(self.child / ".claude/rules/shared.md"), excl)
        self.assertNotIn(str(self.child / ".claude/rules/child_only.md"), excl)
        self.assertNotIn(str(self.parent / ".claude/rules/shared.md"), excl)
        self.assertIn("/elsewhere/hand-written.md", excl)
        self.assertEqual(data["permissions"], {"allow": ["Bash(ls:*)"]})

    def test_green_after_apply_and_drop_is_exactly_the_duplicate(self):
        self.run_audit("--apply")
        rc, rows = self.report(40000)
        self.assertEqual(rc, 0)
        self.assertEqual(rows["child"]["chars"], self.expected_child_before() - len(SHARED))
        self.assertEqual(rows["child"]["duplicates_not_excluded"], 0)

    def test_stale_exclude_fails_then_apply_heals(self):
        self.run_audit("--apply")
        write(self.child / ".claude/rules/shared.md", SHARED + "newer")
        rc, rows = self.report(10**9)
        self.assertEqual(rc, 2)
        self.assertEqual(len(rows["child"]["stale_excludes"]), 1)
        self.run_audit("--apply")
        rc, rows = self.report(10**9)
        self.assertEqual(rc, 0)
        self.assertEqual(rows["child"]["stale_excludes"], [])

    def test_apply_is_idempotent(self):
        self.run_audit("--apply")
        first = self.settings.read_bytes()
        rc, out = self.run_audit("--apply")
        self.assertEqual(rc, 0)
        self.assertIn("unchanged", out)
        self.assertEqual(self.settings.read_bytes(), first)

    def test_apply_refuses_unparseable_settings(self):
        write(self.settings, "{not json")
        rc, out = self.run_audit("--apply")
        self.assertEqual(rc, 2)
        self.assertIn("REFUSED", out)
        self.assertEqual(self.settings.read_text(), "{not json")

    def test_missing_registry_is_a_loud_skip(self):
        r = subprocess.run([sys.executable, str(SCRIPT), "--registry", str(self.root / "none.json"),
                            "--user-dir", str(self.user)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        self.assertIn("SKIP: no instance registry", r.stdout)


if __name__ == "__main__":
    unittest.main()
