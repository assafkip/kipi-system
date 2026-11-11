#!/usr/bin/env python3
"""auto-commit.py never commits a .claude/ deletion, and its commits pass the issue gate.

THE SCAR (ASK-4386, measured 2026-11-10). rule_gate's baseline defect (ASK-4283)
deleted tracked rule files in two unattended worker trees. Each agent left the
deletions UNSTAGED on purpose. The Stop hook staged and committed them anyway:
`70163e63 chore: update rules` on sana/ask-4309 (13 files, -613) and
`f31929ab chore: update rules` on 4 Points sana/case-051-session (-533). A whole
case session then ran without q-investigation.md and evidence-capture-protocol.md.
Those commits carried `[no-issue: auto-commit safety net ...]`, so the linear-first
commit-msg gate waved them through on a branch cut for a named issue.

Pinned here, in throwaway repos with the REAL gate installed as commit-msg:
  * a deletion or line loss of a tracked .claude/ path is held, staged or not;
  * the hook's other work still commits (the safety net is not switched off);
  * a pure .claude/ addition still commits, and a deliberate agent commit of a
    .claude/ deletion still lands (negative self-test: .claude/ is not frozen);
  * on a branch named for an issue, the hook's commit names that issue, and the
    gate refuses a [no-issue:] bypass there.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "..", "auto-commit.py")
GATE = os.path.join(HERE, "..", "..", ".q-system", "scripts", "linear-issue-ref-check.py")


def git(repo, *args, env=None):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True,
                          check=False, env=env)


class Scratch(unittest.TestCase):
    branch = "main"

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="auto-commit-claude-del-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo = os.path.join(self.tmp, "repo")
        self.ledger = os.path.join(self.tmp, "bypass.jsonl")
        os.makedirs(self.repo)
        git(self.repo, "init", "-q", "-b", self.branch)
        for k, v in (("user.email", "t@t.t"), ("user.name", "test"),
                     ("commit.gpgsign", "false")):
            git(self.repo, "config", k, v)
        # The real gate, not a copy of its logic. A local hooksPath so no global
        # hook manager decides what this fixture measures.
        hooks = os.path.join(self.tmp, "hooks")
        os.makedirs(hooks)
        with open(os.path.join(hooks, "commit-msg"), "w") as fh:
            fh.write(f'#!/bin/sh\nexec "{sys.executable}" "{GATE}" "$1"\n')
        os.chmod(os.path.join(hooks, "commit-msg"), 0o755)
        git(self.repo, "config", "core.hooksPath", hooks)
        self.env = {k: v for k, v in os.environ.items() if k != "CLAUDE_CODE_REMOTE"}
        self.env.update(CLAUDE_PROJECT_DIR=self.repo, KIPI_LINEAR_TEAM="ASK",
                        LINEAR_BYPASS_LEDGER=self.ledger, KIPI_NOTIFY="/usr/bin/true")
        self.write(".claude/rules/keep.md", "rule one\nrule two\nrule three\n")
        self.write(".claude/rules/other.md", "a\nb\nc\n")
        self.write("q-system/memory/notes.md", "base\n")
        git(self.repo, "add", "-A")
        r = git(self.repo, "commit", "-q", "-m", "base (ASK-1)", env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.base = self.head()

    def write(self, rel, text):
        path = os.path.join(self.repo, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(text)

    def head(self):
        return git(self.repo, "rev-parse", "HEAD").stdout.strip()

    def at_head(self, rel):
        return git(self.repo, "show", f"HEAD:{rel}").stdout

    def run_hook(self):
        r = subprocess.run([sys.executable, HOOK], cwd=self.repo, env=self.env,
                           capture_output=True, text=True, check=False)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r

    def new_messages(self):
        return git(self.repo, "log", "--format=%B%x00", f"{self.base}..HEAD").stdout


class ClaudeDeletionsAreHeld(Scratch):
    def test_unstaged_rule_deletion_is_never_committed(self):
        os.remove(os.path.join(self.repo, ".claude/rules/keep.md"))
        self.write("q-system/memory/notes.md", "base\nmore\n")
        out = self.run_hook().stdout
        self.assertEqual(self.at_head(".claude/rules/keep.md"),
                         "rule one\nrule two\nrule three\n",
                         "the hook committed a .claude/ deletion:\n" + out)
        status = git(self.repo, "status", "--porcelain", "--", ".claude").stdout
        self.assertIn(" D .claude/rules/keep.md", status, "the deletion was staged")
        # Control: the safety net still commits the rest.
        self.assertEqual(self.at_head("q-system/memory/notes.md"), "base\nmore\n", out)

    def test_staged_rule_deletion_is_left_staged_not_committed(self):
        git(self.repo, "rm", "-q", ".claude/rules/keep.md")
        self.run_hook()
        self.assertIn("rule one", self.at_head(".claude/rules/keep.md"))
        staged = git(self.repo, "diff", "--cached", "--name-status").stdout
        self.assertIn("D\t.claude/rules/keep.md", staged, "the agent's staged state moved")

    def test_rule_line_loss_is_held(self):
        # rule_gate's section revert shape: the file stays, lines go.
        self.write(".claude/rules/other.md", "a\n")
        self.run_hook()
        self.assertEqual(self.at_head(".claude/rules/other.md"), "a\nb\nc\n")

    def test_negative_self_test_claude_is_not_frozen(self):
        # A pure addition under .claude/ still auto-commits.
        self.write(".claude/rules/new.md", "fresh\n")
        self.write(".claude/rules/other.md", "a\nb\nc\nd\n")
        self.run_hook()
        self.assertEqual(self.at_head(".claude/rules/new.md"), "fresh\n")
        self.assertEqual(self.at_head(".claude/rules/other.md"), "a\nb\nc\nd\n")
        # A deliberate agent commit of a .claude/ deletion (the step after
        # apply-claude-changes.sh writes the tree) still lands through the gate.
        git(self.repo, "rm", "-q", ".claude/rules/keep.md")
        r = git(self.repo, "commit", "-q", "-m", "remove keep rule (ASK-7)", env=self.env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("keep.md", git(self.repo, "ls-files").stdout)


class IssueBranchCommitsNameTheIssue(Scratch):
    branch = "sana/ask-4309"

    def test_hook_commit_on_an_issue_branch_names_the_issue(self):
        self.write("q-system/memory/notes.md", "base\nmore\n")
        out = self.run_hook().stdout
        msgs = [m.strip() for m in self.new_messages().split("\0") if m.strip()]
        self.assertTrue(msgs, "control: the hook made no commit at all:\n" + out)
        for m in msgs:
            self.assertIn("ASK-4309", m, "a hook commit on sana/ask-4309 skipped the gate")
            self.assertNotIn("[no-issue:", m)

    def test_gate_refuses_a_bypass_on_an_issue_branch(self):
        self.write("q-system/memory/notes.md", "x\n")
        git(self.repo, "add", "-A")
        r = git(self.repo, "commit", "-q", "-m",
                "chore: update rules\n\n[no-issue: auto-commit safety net]", env=self.env)
        self.assertNotEqual(r.returncode, 0, "the gate let a bypass through on sana/ask-4309")
        self.assertEqual(self.head(), self.base)


class BypassStillWorksOffIssueBranches(Scratch):
    branch = "sana/case-051-session"

    def test_bypass_allowed_when_the_branch_names_no_issue(self):
        self.write("q-system/memory/notes.md", "x\n")
        git(self.repo, "add", "-A")
        r = git(self.repo, "commit", "-q", "-m", "chore: notes\n\n[no-issue: typo]",
                env=self.env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
