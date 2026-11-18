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

    def wip(self):
        base = os.path.join(self.e.home, ".config", "kipi", "worktrees")
        os.makedirs(base)
        d = os.path.join(base, "wip")
        git("worktree", "add", "-q", "--detach", d, "HEAD", cwd=self.e.repo)
        return d

    def test_git_gated_mode_000_checkout_is_skipped_not_errored(self):
        # PR 841 round 4, finding 2: a mode-000 git-gated target errored and paged on
        # every run forever. The gate cannot read it, so it is a skip, and quiet.
        d = self.wip()
        with open(os.path.join(d, "unsaved.txt"), "w") as fh:
            fh.write("work")
        age(d, 24 * 40)
        os.chmod(d, 0)
        self.addCleanup(os.chmod, d, 0o700)
        r = self.e.run("kipi-worktrees")
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        summary = json.loads(r.stdout)
        self.assertEqual(summary.get("errors"), 0, "unreadable is a keep, not a page")
        self.assertEqual(summary["rules"]["kipi-worktrees"].get("skip-unreadable"), 1)
        os.chmod(d, 0o700)
        self.assertTrue(os.path.exists(os.path.join(d, "unsaved.txt")))

    def test_unreadable_subdir_is_not_read_as_clean(self):
        # PR 841 round 4, finding 1: git status exits 0 with empty stdout and puts
        # "Permission denied" on stderr when a subdir is mode 000, so git_state said
        # clean and rmtree destroyed every readable file of a worktree with work in it.
        d = self.wip()
        os.makedirs(os.path.join(d, "sub"))
        with open(os.path.join(d, "sub", "unsaved.txt"), "w") as fh:
            fh.write("UNSAVED WORK")
        age(d, 24 * 40)
        os.chmod(os.path.join(d, "sub"), 0)
        self.addCleanup(os.chmod, os.path.join(d, "sub"), 0o700)
        r = self.e.run("kipi-worktrees")
        summary = json.loads(r.stdout)
        self.assertEqual(summary.get("errors"), 0, r.stdout)
        self.assertEqual(summary["rules"]["kipi-worktrees"].get("skip-git-error"), 1, r.stdout)
        self.assertTrue(os.path.exists(os.path.join(d, "a.txt")), "nothing readable was removed either")
        os.chmod(os.path.join(d, "sub"), 0o700)
        self.assertTrue(os.path.exists(os.path.join(d, "sub", "unsaved.txt")))

    def test_run_dir_held_by_a_live_process_is_kept(self):
        d = self.mk("run.Live1234", 30)
        self.e.run("review-scratch-runs", live=[os.path.join(d, "sub")])
        self.assertTrue(os.path.exists(d))


# Birth time, F_LOG2PHYS_EXT and `cp -c` are macOS/APFS only; the janitor runs on
# the Mac mini, and CI is Linux (verify run 44414270275: no st_birthtime). On a
# platform without birth time the gate keeps every clone (skip-procs-unknown).
@unittest.skipUnless(sys.platform == "darwin", "APFS clone mechanics are macOS only")
class ChromeCodeSignClones(unittest.TestCase):
    """ASK-3976. Chrome makes X/<bundle-id>.code_sign_clone/code_sign_clone.<rand>
    at every launch and leaks it when the launch is killed. The old rule targeted
    the parent folder, which always holds the live clone, so it never fired
    (skip open files every day since 2026-09-29). Each clone's main binary is a
    hardlink of the app's, so lsof +D shows an open file in every clone; liveness
    is read from birth time instead: a clone born within seconds of a running main
    process's start is that process's clone."""

    def setUp(self):
        self.e = Env()
        self.addCleanup(self.e.td.cleanup)
        self.parent = os.path.join(self.e.tmpbase, "X", "com.google.Chrome.code_sign_clone")
        os.makedirs(self.parent)
        app = os.path.join(self.e.td.name, "Apps", "Google Chrome.app", "Contents")
        os.makedirs(os.path.join(app, "MacOS"))
        with open(os.path.join(app, "Info.plist"), "wb") as fh:
            import plistlib
            plistlib.dump({"CFBundleIdentifier": "com.google.Chrome"}, fh)
        self.exe = os.path.join(app, "MacOS", "Google Chrome")

    def clone(self, name, hours_ago=0.0):
        d = os.path.join(self.parent, name)
        os.makedirs(os.path.join(d, "Google Chrome.app.bundle", "Contents", "MacOS"))
        with open(os.path.join(d, "Google Chrome.app.bundle", "Contents", "MacOS", "Google Chrome"), "w") as fh:
            fh.write("bin")
        if hours_ago:
            # APFS moves the birth time back when mtime is set before it.
            age(d, hours_ago)
        born = os.stat(d).st_birthtime
        if hours_ago:
            self.assertLess(born, time.time() - hours_ago * 3600 + 60, "fixture could not age the birth time")
        return d, born

    def run_clones(self, procs):
        env = dict(os.environ, JANITOR_HOME=self.e.home, JANITOR_TMPBASE=self.e.tmpbase,
                   JANITOR_CLAUDETMP=self.e.claude, JANITOR_LIVE="[]", JANITOR_NO_NOTIFY="1",
                   JANITOR_FREE_GB="100", JANITOR_NO_UV="1", JANITOR_NOW=str(time.time() + 2 * 3600),
                   JANITOR_PROCS=json.dumps(procs), JANITOR_APPS=os.path.join(self.e.td.name, "Apps"))
        r = subprocess.run([sys.executable, SCRIPT, "--apply", "--rules", "chrome-code-sign-clone", "--json"],
                           capture_output=True, text=True, env=env, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        return json.loads(r.stdout)

    def test_orphan_goes_and_the_live_clone_stays(self):
        live, born = self.clone("code_sign_clone.LowSzi")
        orphan, _ = self.clone("code_sign_clone.jx3zJL", hours_ago=12)
        # Measured: LowSzi born 11:10:54, its Chrome (pid 43484) started 11:10:53.
        s = self.run_clones([{"start": born - 1, "exe": self.exe}])
        self.assertTrue(os.path.exists(live), "the running Chrome's clone must stay")
        self.assertFalse(os.path.exists(orphan), "a clone no running Chrome owns is an orphan")
        self.assertEqual(s["rules"]["chrome-code-sign-clone"].get("skip-live-clone"), 1, s)

    def test_parent_folder_is_never_the_target(self):
        self.clone("code_sign_clone.AAAAAA")
        self.run_clones([])
        self.assertTrue(os.path.isdir(self.parent), "only the code_sign_clone.* children are targets")

    def test_live_main_with_no_clone_born_at_its_start_keeps_every_clone(self):
        # Negative control: a running Chrome whose clone cannot be told apart.
        a, born = self.clone("code_sign_clone.AAAAAA")
        b, _ = self.clone("code_sign_clone.BBBBBB", hours_ago=12)
        s = self.run_clones([{"start": born - 3600, "exe": self.exe}])
        self.assertTrue(os.path.exists(a) and os.path.exists(b), s)

    def test_unreadable_process_table_keeps_every_clone(self):
        a, _ = self.clone("code_sign_clone.AAAAAA")
        s = self.run_clones(None)
        self.assertTrue(os.path.exists(a), s)

    def framework(self, clone_dir, how):
        """A 2 MB framework in the installed app, put into the clone by APFS
        clonefile (cp -c, what Chrome does) or by a real copy (what an app update
        leaves an orphan holding)."""
        rel = os.path.join("Contents", "Frameworks", "F.framework", "F")
        src = os.path.join(self.e.td.name, "Apps", "Google Chrome.app", rel)
        if not os.path.exists(src):
            os.makedirs(os.path.dirname(src))
            with open(src, "wb") as fh:
                fh.write(os.urandom(2 << 20))
        dst = os.path.join(clone_dir, "Google Chrome.app.bundle", rel)
        os.makedirs(os.path.dirname(dst))
        subprocess.run(["cp", "-c" if how == "clone" else "-X", src, dst], check=True)

    def test_clone_sharing_the_apps_blocks_counts_zero_freed(self):
        shared, _ = self.clone("code_sign_clone.Shared", hours_ago=12)
        self.framework(shared, "clone")
        s = self.run_clones([])
        self.assertFalse(os.path.exists(shared))
        self.assertEqual(s["bytes"], 0, "a clone of the app frees about nothing")
        self.assertGreater(s["shared_bytes_not_freed"]["chrome-code-sign-clone"], 2 << 20 - 1)

    def test_clone_that_owns_its_blocks_counts_as_freed(self):
        # Negative control for the probe: after an update the orphan's blocks are its own.
        owned, _ = self.clone("code_sign_clone.Owned1", hours_ago=12)
        self.framework(owned, "copy")
        s = self.run_clones([])
        self.assertFalse(os.path.exists(owned))
        self.assertGreaterEqual(s["bytes"], 2 << 20)
        self.assertEqual(s["shared_bytes_not_freed"], {})

    def test_helper_processes_are_not_main_processes(self):
        # A helper started at an orphan's birth must not make it look live, and a
        # helper with no clone must not freeze the rule.
        a, born = self.clone("code_sign_clone.AAAAAA")
        helper = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(self.exe))), "Contents",
                              "Frameworks", "X.framework", "Helpers", "Google Chrome Helper.app",
                              "Contents", "MacOS", "Google Chrome Helper")
        # Real helpers carry com.google.Chrome.helper; give this one the main id so
        # the test pins the structural exclusion, not the id difference.
        hplist = os.path.join(os.path.dirname(os.path.dirname(helper)), "Info.plist")
        os.makedirs(os.path.dirname(helper))
        with open(hplist, "wb") as fh:
            import plistlib
            plistlib.dump({"CFBundleIdentifier": "com.google.Chrome"}, fh)
        self.run_clones([{"start": born - 1, "exe": helper}])
        self.assertFalse(os.path.exists(a))


if __name__ == "__main__":
    unittest.main()
