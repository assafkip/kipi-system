"""ASK-4234: the disk janitor reclaims what actually filled the disk.

Every case runs the real script against a temp HOME / TMPBASE / CLAUDETMP, so it
can never touch a live path (fable-discipline). Measured 2026-11-18: six
leaked consulting verify.sh staged snapshots (tmp.*/wt, 466 MB each, 2.8 GB)
sat under the 7-day tmp-mktemp-shell age gate while a commit needed 5 GiB free,
and review-scratch run./ctx. dirs held 0.6 GB that no rule covered.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts", "disk_janitor.py")


def git(*a, cwd=None):
    subprocess.run(["git"] + list(a), cwd=cwd, check=True, capture_output=True, text=True,
                   env=dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                            GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t"))


def age(path, hours):
    t = time.time() - hours * 3600
    for root, dirs, files in os.walk(path, followlinks=False):
        for n in dirs + files:
            try:
                os.utime(os.path.join(root, n), (t, t), follow_symlinks=False)
            except OSError:
                pass
    os.utime(path, (t, t), follow_symlinks=False)


class Env(object):
    def __init__(self):
        self.td = tempfile.TemporaryDirectory()
        base = os.path.realpath(self.td.name)
        self.home = os.path.join(base, "home")
        self.tmpbase = os.path.join(base, "var")
        self.claude = os.path.join(base, "claude-tmp")
        self.T = os.path.join(self.tmpbase, "T")
        for d in (self.home, self.T, self.claude, os.path.join(self.home, ".config", "kipi")):
            os.makedirs(d)
        self.repo = os.path.join(base, "repo")
        os.makedirs(self.repo)
        git("init", "-q", "-b", "main", cwd=self.repo)
        with open(os.path.join(self.repo, "a.txt"), "w") as fh:
            fh.write("x")
        git("add", ".", cwd=self.repo)
        git("commit", "-qm", "c", cwd=self.repo)

    def snapshot(self, name, hours):
        """What verify.sh leaves behind: mktemp -d with a detached worktree at wt/."""
        d = os.path.join(self.T, name)
        os.makedirs(d)
        git("worktree", "add", "-q", "--detach", os.path.join(d, "wt"), "HEAD", cwd=self.repo)
        with open(os.path.join(d, "verify-select-plugin"), "w") as fh:
            fh.write("x")
        age(d, hours)
        return d

    def run(self, rules, live=()):
        env = dict(os.environ, JANITOR_HOME=self.home, JANITOR_TMPBASE=self.tmpbase,
                   JANITOR_CLAUDETMP=self.claude, JANITOR_LIVE=json.dumps(list(live)),
                   JANITOR_NO_NOTIFY="1", JANITOR_FREE_GB="100", JANITOR_NO_OPENFILES="1", JANITOR_NO_UV="1")
        r = subprocess.run([sys.executable, SCRIPT, "--apply", "--rules", rules, "--json"],
                           capture_output=True, text=True, env=env, timeout=120)
        return r

    def worktrees(self):
        return subprocess.run(["git", "-C", self.repo, "worktree", "list"], capture_output=True,
                              text=True).stdout


class StagedSnapshots(unittest.TestCase):
    def setUp(self):
        self.e = Env()
        self.addCleanup(self.e.td.cleanup)

    def test_old_snapshot_is_removed_and_unregistered(self):
        d = self.e.snapshot("tmp.AbCdEf1234", hours=3)
        r = self.e.run("tmp-verify-staged")
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertFalse(os.path.exists(d), "old snapshot must go")
        self.assertNotIn("tmp.AbCdEf1234", self.e.worktrees(), "registration must be pruned")

    def test_week_old_snapshot_is_pruned_not_orphaned(self):
        # codex PR 841 P2: tmp-mktemp-shell (7 d) used to win and leave .git/worktrees behind.
        d = self.e.snapshot("tmp.WeekOld1234", hours=24 * 10)
        r = self.e.run("tmp-mktemp-shell,tmp-verify-staged")
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertFalse(os.path.exists(d))
        self.assertNotIn("tmp.WeekOld1234", self.e.worktrees())
        self.assertFalse(os.path.exists(os.path.join(self.e.repo, ".git", "worktrees", "wt")),
                         "registration must be pruned")

    def test_young_snapshot_is_kept(self):
        d = self.e.snapshot("tmp.YoungYoung1", hours=0.1)
        self.e.run("tmp-verify-staged")
        self.assertTrue(os.path.exists(d), "a commit may still be running in it")

    def test_snapshot_held_by_a_live_process_is_kept(self):
        d = self.e.snapshot("tmp.LiveLive123", hours=3)
        self.e.run("tmp-verify-staged", live=[os.path.join(d, "wt")])
        self.assertTrue(os.path.exists(d))

    def test_mktemp_dir_without_a_worktree_is_not_this_rules_business(self):
        d = os.path.join(self.e.T, "tmp.NotOurs123")
        os.makedirs(d)
        with open(os.path.join(d, "keep.txt"), "w") as fh:
            fh.write("x")
        age(d, 50)
        self.e.run("tmp-verify-staged")
        self.assertTrue(os.path.exists(d), "only a verify.sh snapshot (wt/ linked worktree) is covered")


class ReviewScratch(unittest.TestCase):
    def setUp(self):
        self.e = Env()
        self.addCleanup(self.e.td.cleanup)
        self.base = os.path.join(self.e.home, ".config", "kipi", "review-scratch")
        os.makedirs(self.base)

    def mk(self, name, hours, locked=False):
        d = os.path.join(self.base, name)
        os.makedirs(os.path.join(d, "sub", ".claims"))
        with open(os.path.join(d, "sub", ".claims", "f"), "w") as fh:
            fh.write("x")
        if locked:
            os.chmod(os.path.join(d, "sub", ".claims"), 0)
        age(d, hours)
        return d

    def test_old_run_and_ctx_dirs_go_young_and_hand_dirs_stay(self):
        old_run = self.mk("run.AbC123", 30)
        old_ctx = self.mk("ctx.XyZ789", 30)
        young = self.mk("run.Young1", 2)
        hand = self.mk("sana344", 300)
        r = self.e.run("review-scratch-runs")
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertFalse(os.path.exists(old_run))
        self.assertFalse(os.path.exists(old_ctx))
        self.assertTrue(os.path.exists(young), "a running review owns it")
        self.assertTrue(os.path.exists(hand), "hand-made dirs are not run dirs")

    def test_mode_000_subdir_does_not_block_removal(self):
        # Measured: run.qAyFXZ/.../.claims was mode 000 and `du` hit Permission denied.
        d = self.mk("run.Locked12", 30, locked=True)
        r = self.e.run("review-scratch-runs")
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertFalse(os.path.exists(d))
        summary = json.loads(r.stdout)
        self.assertEqual(summary.get("errors"), 0)

    def test_mode_000_target_itself_is_removed(self):
        d = self.mk("run.TopLock12", 30)
        age(d, 30)
        os.chmod(d, 0)
        r = self.e.run("review-scratch-runs")
        self.assertFalse(os.path.exists(d))
        self.assertEqual(json.loads(r.stdout).get("errors"), 0)

    def test_git_gated_mode_000_checkout_is_not_unlocked_into_deletion(self):
        # review round 3: a mode-000 worktree with work must stay an error, never a delete.
        base = os.path.join(self.e.home, ".config", "kipi", "worktrees")
        os.makedirs(base)
        d = os.path.join(base, "wip")
        git("worktree", "add", "-q", "--detach", d, "HEAD", cwd=self.e.repo)
        with open(os.path.join(d, "unsaved.txt"), "w") as fh:
            fh.write("work")
        age(d, 24 * 40)
        os.chmod(d, 0)
        self.addCleanup(os.chmod, d, 0o700)
        r = self.e.run("kipi-worktrees")
        self.assertEqual(json.loads(r.stdout).get("errors"), 1, "kept and loud, not deleted quietly")
        os.chmod(d, 0o700)
        self.assertTrue(os.path.exists(os.path.join(d, "unsaved.txt")))

    def test_run_dir_held_by_a_live_process_is_kept(self):
        d = self.mk("run.Live1234", 30)
        self.e.run("review-scratch-runs", live=[os.path.join(d, "sub")])
        self.assertTrue(os.path.exists(d))


if __name__ == "__main__":
    unittest.main()
