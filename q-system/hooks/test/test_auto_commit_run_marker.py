#!/usr/bin/env python3
"""auto-commit.py commits nothing while the fleet updater's run marker is live.

On 2026-09-06 the consulting checkout's Stop-hook auto-commit fired at every
peer message while kipi-update.sh was mid-delivery, committed the updater's
rules, settings and plugins under its own generic messages, and held
index.lock through its 445 s verify so the founder's guarded re-run tripped
and did nothing (sp-9306036e). The updater now writes
<git-common-dir>/kipi-update.run for the duration of one instance apply; this
pins the hook's half of the handshake:

  live marker  (pid alive)  -> exit 0, one STDOUT line, no commit, marker kept

  THE CHANNEL IS STDOUT, NOT STDERR (PR #321 review round 2, major). This file
  asserted stderr, and it was the only thing pinning that. settings-template.json
  wires the hook as `... auto-commit.py 2>/dev/null || true` (line 395), so the
  copy the fleet updater installs on every instance THROWS STDERR AWAY. A refusal
  nobody can see turns the safety net off in silence, which is the whole defect
  PR #321 exists to remove. The positive assertions now read stdout; the negative
  ones read BOTH channels, so they cannot pass merely because a message moved.
  stale marker (pid dead)   -> marker removed, hook proceeds as before
  no marker                 -> unchanged behaviour

Runs against a throwaway repo only; never the checkout it lives in.
"""
import os
import subprocess
import sys
import tempfile
import time
import unittest

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "auto-commit.py")


def git(repo, *args):
    return subprocess.run(
        ["git", "-c", "user.email=t@t.t", "-c", "user.name=test",
         "-c", "commit.gpgsign=false", *args],
        cwd=repo, capture_output=True, text=True, check=False)


def run_hook(repo, cwd=None):
    # The hook resolves its repo through CLAUDE_PROJECT_DIR, the way Claude
    # Code invokes it; the process cwd is whatever the harness happens to be
    # in. Both are set here so the two can be pulled apart on purpose.
    env = dict(os.environ, CLAUDE_PROJECT_DIR=repo)
    return subprocess.run([sys.executable, HOOK], cwd=cwd or repo, env=env,
                          capture_output=True, text=True, check=False)


def head_count(repo):
    return int(git(repo, "rev-list", "--count", "HEAD").stdout.strip() or 0)


def dead_pid():
    child = subprocess.Popen(["true"])
    child.wait()
    return child.pid


class RunMarker(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix="auto-commit-marker-")
        git(self.repo, "init", "-q", "-b", "main")
        # IDENTITY ON THE REPO, NOT ON OUR OWN `git -c` CALLS.
        #
        # `git()` above passes -c user.email/-c user.name, which covers the
        # commands THIS FILE runs and nothing else. The subject under test is a
        # subprocess -- run_hook spawns auto-commit.py, which runs its own
        # `git commit` -- and that inherits whatever identity the RUNNER happens
        # to have. Measured 2026-09-07: `validate.yml` sets a global identity and
        # `verify.yml` does not, so the moment this suite was named in
        # .verify-suites two cases went red in one job and stayed green in the
        # other, with the failure reading "the hook did not commit" as if the
        # hook were broken. Writing the identity into the repo config puts it
        # where the child git will find it, and makes the suite hermetic instead
        # of dependent on which workflow happens to run it.
        git(self.repo, "config", "user.email", "t@t.t")
        git(self.repo, "config", "user.name", "test")
        git(self.repo, "config", "commit.gpgsign", "false")
        # A path the hook classifies as committable, so the "no marker" and
        # "stale marker" cases have something to commit and the live case has
        # something it must NOT commit.
        os.makedirs(os.path.join(self.repo, "q-system", "memory"))
        with open(os.path.join(self.repo, "q-system", "memory", "last-handoff.md"), "w") as fh:
            fh.write("v1\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "init")
        with open(os.path.join(self.repo, "q-system", "memory", "last-handoff.md"), "w") as fh:
            fh.write("v2\n")
        self.marker = os.path.join(self.repo, ".git", "kipi-update.run")

    def test_live_marker_commits_nothing_and_says_so(self):
        # A fresh stamp, generated now: a fixed date went stale two hours after
        # it was written and failed this case in CI (PR #314 round 2).
        stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with open(self.marker, "w") as fh:
            fh.write(f"{os.getpid()} {stamp}\n")
        before = head_count(self.repo)
        result = run_hook(self.repo)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("fleet updater run in progress", result.stdout)
        self.assertEqual(head_count(self.repo), before, "the hook committed under a live marker")
        self.assertTrue(os.path.exists(self.marker), "the hook removed a LIVE marker")

    def test_stale_marker_is_removed_and_the_hook_proceeds(self):
        with open(self.marker, "w") as fh:
            fh.write(f"{dead_pid()} 2026-09-06T21:30:00Z\n")
        result = run_hook(self.repo)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("fleet updater run in progress",
                            result.stdout + result.stderr)
        self.assertFalse(os.path.exists(self.marker), "a stale marker survived")

    def test_live_marker_is_seen_when_cwd_is_not_the_project_dir(self):
        # PR #314 round 2: the marker path was resolved against the process
        # cwd; with cwd elsewhere the guard found no marker and failed open.
        stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with open(self.marker, "w") as fh:
            fh.write(f"{os.getpid()} {stamp}\n")
        before = head_count(self.repo)
        result = run_hook(self.repo, cwd=tempfile.gettempdir())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("fleet updater run in progress", result.stdout)
        self.assertEqual(head_count(self.repo), before, "the guard failed open from a foreign cwd")

    def test_live_pid_with_an_old_stamp_is_stale(self):
        # A recycled pid after a crash or reboot is alive and unrelated; the
        # stamp is what says the run is long over (PR #314 review, round 1).
        with open(self.marker, "w") as fh:
            fh.write(f"{os.getpid()} 2026-01-01T00:00:00Z\n")
        before = head_count(self.repo)
        result = run_hook(self.repo)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("fleet updater run in progress",
                            result.stdout + result.stderr)
        self.assertFalse(os.path.exists(self.marker), "an old-stamp marker with a live pid survived")
        self.assertEqual(head_count(self.repo), before + 1, "the hook did not proceed past a stale marker")

    def test_malformed_marker_is_treated_as_stale(self):
        with open(self.marker, "w") as fh:
            fh.write("not-a-pid\n")
        result = run_hook(self.repo)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("fleet updater run in progress",
                            result.stdout + result.stderr)
        self.assertFalse(os.path.exists(self.marker))

    def test_no_marker_is_the_old_behaviour(self):
        before = head_count(self.repo)
        result = run_hook(self.repo)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("fleet updater run in progress",
                            result.stdout + result.stderr)
        # The floor that makes the live case meaningful: without a marker the
        # same dirty file DOES get committed, so "no commit" above is the marker's
        # doing and not the classifier's.
        self.assertEqual(head_count(self.repo), before + 1,
                         f"control failed: the hook did not commit without a marker: {result.stdout} {result.stderr}")


if __name__ == "__main__":
    unittest.main()
