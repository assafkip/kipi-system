#!/usr/bin/env python3
"""auto-commit.py commits nothing and publishes nothing while a merge is paused.

2026-09-29, cole-gtm: a founder-directed `git merge origin/master` stopped on 5
conflicts. The Stop-hook autosave fired at the end of that turn, staged every
file -- conflict markers included -- and committed them as 9e563be "session
autosave (231 files)", which also swept in files the founder had asked to leave
alone. git sees a paused merge as "all changes staged", so nothing in the hook
noticed. With notes-publish (ASK-2190) called from the same hook, a paused merge
would also push conflict-marked notes to origin's kipi/notes.

Pinned here: with MERGE_HEAD present the hook exits 0, prints one STDOUT line
(the channel the fleet wiring keeps), makes no commit, leaves the merge paused,
and skips the notes publish. Throwaway repos only.
"""
import os
import subprocess
import sys
import tempfile
import unittest

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "auto-commit.py")


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=False)


def run_hook(repo):
    env = dict(os.environ, CLAUDE_PROJECT_DIR=repo)
    return subprocess.run([sys.executable, HOOK], cwd=repo, env=env,
                          capture_output=True, text=True, check=False)


class PausedMerge(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix="auto-commit-midmerge-")
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "config", "user.email", "t@t.t")
        git(self.repo, "config", "user.name", "test")
        git(self.repo, "config", "commit.gpgsign", "false")
        os.makedirs(os.path.join(self.repo, "q-system", "memory"))
        self.handoff = os.path.join(self.repo, "q-system", "memory", "last-handoff.md")
        self._write("base\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "base")
        git(self.repo, "checkout", "-q", "-b", "side")
        self._write("side\n")
        git(self.repo, "commit", "-q", "-am", "side")
        git(self.repo, "checkout", "-q", "main")
        self._write("main\n")
        git(self.repo, "commit", "-q", "-am", "main")
        merge = git(self.repo, "merge", "side")
        self.assertNotEqual(merge.returncode, 0, "fixture must stop on a conflict")

    def _write(self, text):
        with open(self.handoff, "w") as fh:
            fh.write(text)

    def _head(self):
        return git(self.repo, "rev-parse", "HEAD").stdout.strip()

    def test_a_paused_merge_is_never_committed(self):
        before = self._head()
        r = run_hook(self.repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self._head(), before, "the hook committed during a paused merge")
        self.assertTrue(os.path.exists(os.path.join(self.repo, ".git", "MERGE_HEAD")),
                        "the merge is no longer paused")
        self.assertIn("merge in progress", r.stdout)

    def test_a_paused_merge_publishes_no_notes(self):
        r = run_hook(self.repo)
        self.assertNotIn("notes-publish", r.stdout + r.stderr)
        self.assertIn("notes not published", r.stdout)

    def test_control_without_a_merge_the_hook_still_commits(self):
        git(self.repo, "merge", "--abort")
        self._write("edited\n")
        before = self._head()
        run_hook(self.repo)
        self.assertNotEqual(self._head(), before, "control: a normal edit must still be committed")


if __name__ == "__main__":
    unittest.main()
