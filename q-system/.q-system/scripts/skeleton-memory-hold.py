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
fast-forward can proceed. A copy is saved before anything leaves the tree (an untracked overlap is removed after its copy, since origin adds that path); every held path is printed.
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

# ASK-4647: .prd-os/ is held by auto-commit.py too, so a dirty ledger origin also
# changed would refuse the fast-forward exactly like a memory file.
PREFIXES = ("q-system/memory/", ".prd-os/")
# Authored, never auto-committed (auto-commit.py NEVER_AUTO_COMMIT_DIRS): a local draft
# there is a human's work, so it is never held or removed (PR #760 round 2, finding 2).
AUTHORED = (".prd-os/issues/", ".prd-os/findings/")


def git(repo, *a):
    return subprocess.run(["git", "-C", repo, *a], capture_output=True, text=True)


def overlap(repo, upstream):
    """(path, status) pairs. -z because porcelain C-quotes names with spaces while
    diff --name-only does not, so the two sets never met (PR #760 round 2, finding 4)."""
    # Untracked too (codex P2, PR #760): auto-commit now leaves a NEW .prd-os file
    # uncommitted, and `merge --ff-only` refuses to overwrite an untracked path
    # that origin also adds, exactly as it refuses a modified tracked one.
    dirty = {}
    for e in git(repo, "status", "--porcelain", "-z", "--untracked-files=all",
                 "--", *PREFIXES).stdout.split("\0"):
        if len(e) > 3:
            dirty[e[3:]] = e[:2]
    moved = {x for x in git(repo, "diff", "--name-only", "-z", "HEAD", upstream,
                            "--", *PREFIXES).stdout.split("\0") if x}
    return sorted((p, dirty[p]) for p in dirty if p in moved and not p.startswith(AUTHORED))


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
    for p, st in paths:
        try:
            os.makedirs(os.path.dirname(os.path.join(dest, p)), exist_ok=True)
            shutil.copy2(os.path.join(a.repo, p), os.path.join(dest, p))
        except OSError as e:
            print(f"hold FAILED for {p}: {e}")
            rc = 1
            continue
        if st == "??":
            os.remove(os.path.join(a.repo, p))  # untracked: the copy above is the keeper
        elif git(a.repo, "cat-file", "-e", "HEAD:" + p).returncode != 0:
            # staged-new: removing the file leaves the index entry and the merge still
            # refuses, so report failure like the pre-PR code did (finding 1).
            print(f"hold FAILED: {p} is staged but not in HEAD; copy at {os.path.join(dest, p)}")
            rc = 1
            continue
        elif git(a.repo, "checkout", "HEAD", "--", p).returncode != 0:
            print(f"hold FAILED to restore {p}; copy at {os.path.join(dest, p)}")
            rc = 1
            continue
        print(f"held: {p} -> {os.path.join(dest, p)}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
