#!/usr/bin/env python3
"""skeleton-memory-hold.py lets the fast-forward through a dirty memory overlap (ASK-3525)."""
import os
import subprocess
import sys
import tempfile
import unittest

HOLD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts",
                    "skeleton-memory-hold.py")
OL = "q-system/memory/open-loops.json"
OT = "q-system/memory/other.json"


def g(cwd, *a):
    return subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *a],
                          cwd=cwd, capture_output=True, text=True)


def w(repo, rel, body):
    os.makedirs(os.path.dirname(os.path.join(repo, rel)), exist_ok=True)
    open(os.path.join(repo, rel), "w").write(body)


def fixture():
    d = tempfile.mkdtemp(prefix="memhold-")
    g(d, "init", "-q", "--bare", "-b", "main", "o.git")
    s, up = os.path.join(d, "s"), os.path.join(d, "w")
    g(d, "init", "-q", "-b", "main", "s")
    g(s, "remote", "add", "origin", "../o.git")
    w(s, OL, "a\n"); w(s, OT, "a\n")
    g(s, "add", "-A"); g(s, "commit", "-qm", "s")
    g(d, "-C", "o.git", "fetch", "-q", "../s", "main:main")
    g(d, "clone", "-q", "o.git", "w")
    w(up, OL, "origin\n"); g(up, "commit", "-qam", "up")
    g(d, "-C", "o.git", "fetch", "-q", "../w", "main:main")
    g(s, "fetch", "-q")
    return s


def hold(s):
    return subprocess.run([sys.executable, HOLD, "--repo", s], capture_output=True, text=True)


class Hold(unittest.TestCase):
    def test_overlap_is_held_and_fast_forward_succeeds(self):
        s = fixture()
        w(s, OL, "local\n")
        self.assertNotEqual(0, g(s, "merge", "--ff-only", "-q", "origin/main").returncode)
        r = hold(s)
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)
        self.assertIn("held: " + OL, r.stdout)
        copy = r.stdout.split("-> ")[1].strip()
        self.assertEqual("local\n", open(copy).read())  # nothing lost
        self.assertEqual(0, g(s, "merge", "--ff-only", "-q", "origin/main").returncode)
        self.assertEqual("origin\n", open(os.path.join(s, OL)).read())

    def test_non_overlap_dirty_file_is_left_alone(self):
        s = fixture()
        w(s, OT, "local\n")
        r = hold(s)
        self.assertEqual("", r.stdout)
        self.assertEqual("local\n", open(os.path.join(s, OT)).read())
        self.assertEqual(0, g(s, "merge", "--ff-only", "-q", "origin/main").returncode)


if __name__ == "__main__":
    unittest.main()
