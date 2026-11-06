#!/usr/bin/env python3
"""Hold dirty skeleton memory files that origin/main also changed (ASK-3525).

Pairs with q-system/hooks/auto-commit.py, which no longer commits session memory on
the skeleton's default branch, so those files sit modified in the working tree.
Measured on a copy: a dirty memory file origin did NOT touch never blocks
`git merge --ff-only`; one origin DID touch is refused ("local changes would be
overwritten"), and the updater then aborts because HEAD is not at origin/main.

For exactly that overlap (tracked, modified, under q-system/memory/, changed
between HEAD and origin/main) the local copy is saved under
<git-dir>/kipi-memory-held/<stamp>/<path>, then the path is restored to HEAD so the
fast-forward can proceed. Nothing is deleted; every held path is printed.
Prints one `held: <path> -> <copy>` line per file, nothing when there is no overlap.
Exit 0 always except a copy failure (exit 1, nothing restored for that path).
Called by lessons-daily.sh sync_skel_to_main before its fast-forward.
"""
import argparse
import os
import shutil
import subprocess
import sys
import time

PREFIX = "q-system/memory/"


def git(repo, *a):
    return subprocess.run(["git", "-C", repo, *a], capture_output=True, text=True)


def overlap(repo, upstream):
    dirty = {l[3:] for l in git(repo, "status", "--porcelain", "--untracked-files=no",
                                "--", PREFIX).stdout.splitlines()}
    moved = set(git(repo, "diff", "--name-only", "HEAD", upstream, "--", PREFIX).stdout.split())
    return sorted(dirty & moved)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--upstream", default="origin/main")
    a = ap.parse_args(argv)
    paths = overlap(a.repo, a.upstream)
    if not paths:
        return 0
    gitdir = git(a.repo, "rev-parse", "--absolute-git-dir").stdout.strip()
    dest = os.path.join(gitdir, "kipi-memory-held", time.strftime("%Y%m%d-%H%M%S"))
    rc = 0
    for p in paths:
        try:
            os.makedirs(os.path.dirname(os.path.join(dest, p)), exist_ok=True)
            shutil.copy2(os.path.join(a.repo, p), os.path.join(dest, p))
        except OSError as e:
            print(f"hold FAILED for {p}: {e}")
            rc = 1
            continue
        if git(a.repo, "checkout", "HEAD", "--", p).returncode != 0:
            print(f"hold FAILED to restore {p}; copy at {os.path.join(dest, p)}")
            rc = 1
            continue
        print(f"held: {p} -> {os.path.join(dest, p)}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
