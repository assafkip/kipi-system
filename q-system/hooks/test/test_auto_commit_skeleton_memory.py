#!/usr/bin/env python3
"""The skeleton's default branch never receives session-memory auto-commits (ASK-3525).

THE SCAR. The Stop hook committed q-system/memory/ onto whatever branch was checked
out and never pushed it. On the skeleton that branch is main, so local main drifted
ahead of origin/main, lessons-daily's sync_skel_to_main left it alone and
kipi-update.sh refused ("Check out main and pull"): `propagate FAILED` on 2026-10-05,
10-12 and 10-19. PR #573 tried to undo the drift after the fact and stopped at its
3-round cap; this is the structural pick: stop the memory half of the drift
(other auto-commit areas are unchanged).

Skeleton = instance-registry.json at the repo root (the self-detection notes-publish
and instance-automation-guard use). Instances and non-default branches keep the old
behaviour. Throwaway repos only.
"""
import os
import subprocess
import sys
import tempfile
import unittest

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "auto-commit.py")
MEM = "q-system/memory/open-loops.json"
BIG = "q-system/canonical/decisions.md"


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=False)


def run_hook(repo):
    env = dict(os.environ, CLAUDE_PROJECT_DIR=repo)
    env.pop("CLAUDE_CODE_REMOTE", None)
    return subprocess.run([sys.executable, HOOK], cwd=repo, env=env,
                          capture_output=True, text=True, check=False)


def make_repo(skeleton=True, branch="main"):
    repo = tempfile.mkdtemp(prefix="auto-commit-skel-mem-")
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "t@t.t")
    git(repo, "config", "user.name", "test")
    hooks = tempfile.mkdtemp(prefix="no-hooks-")
    git(repo, "config", "core.hooksPath", hooks)
    for rel, body in ((MEM, "[]\n"), ("q-system/canonical/c.md", "c\n"),
                      (BIG, "".join(f"line {i}\n" for i in range(200)))):
        os.makedirs(os.path.join(repo, os.path.dirname(rel)), exist_ok=True)
        with open(os.path.join(repo, rel), "w") as f:
            f.write(body)
    if skeleton:
        with open(os.path.join(repo, "instance-registry.json"), "w") as f:
            f.write("{}\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "seed")
    if branch != "main":
        git(repo, "checkout", "-q", "-b", branch)
    return repo


def touch(repo, rel, body):
    with open(os.path.join(repo, rel), "w") as f:
        f.write(body)


def head(repo):
    return git(repo, "rev-parse", "HEAD").stdout.strip()


class SkeletonMemoryRouting(unittest.TestCase):
    def test_skeleton_main_does_not_commit_memory(self):
        repo = make_repo()
        before = head(repo)
        touch(repo, MEM, '["live"]\n')
        r = run_hook(repo)
        self.assertEqual(before, head(repo), r.stdout + r.stderr)
        self.assertIn(MEM, git(repo, "status", "--porcelain").stdout)
        self.assertIn("memory", r.stdout)  # one STDOUT line says why

    def test_skeleton_main_commits_no_other_area_either(self):
        # ASK-5583: canonical and RCA commits stranded local main 3 ahead (ffc287ff,
        # cb9c8846, 170d0ecd), so the skeleton's main takes no unattended commit at all.
        repo = make_repo()
        before = head(repo)
        touch(repo, MEM, '["live"]\n')
        touch(repo, "q-system/canonical/c.md", "changed\n")
        r = run_hook(repo)
        self.assertEqual(before, head(repo), r.stdout + r.stderr)
        status = git(repo, "status", "--porcelain").stdout
        self.assertIn(MEM, status)
        self.assertIn("q-system/canonical/c.md", status)
        self.assertIn("held content q-system/canonical/c.md", r.stdout)

    def test_the_shrink_check_still_runs_on_skeleton_main(self):
        # PR #879 review round 1, major: the hold emptied the groups before the
        # ASK-1515 shrink check read them, so a 198-line loss went unpaged.
        repo = make_repo()
        touch(repo, BIG, "line 0\nline 1\n")
        r = run_hook(repo)
        self.assertIn("REFUSED", r.stdout, r.stdout + r.stderr)

    def test_instance_still_commits_memory(self):  # control: behaviour unchanged
        repo = make_repo(skeleton=False)
        before = head(repo)
        touch(repo, MEM, '["live"]\n')
        run_hook(repo)
        self.assertNotEqual(before, head(repo))

    def test_skeleton_feature_branch_still_commits_memory(self):  # default branch only
        repo = make_repo(branch="feat/x")
        before = head(repo)
        touch(repo, MEM, '["live"]\n')
        run_hook(repo)
        self.assertNotEqual(before, head(repo))


if __name__ == "__main__":
    unittest.main()
