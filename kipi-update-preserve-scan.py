#!/usr/bin/env python3
"""Preflight guard for kipi-update.sh: find TRACKED instance-only files that the
skeleton sync's `rsync --delete` would silently delete, so the updater can snapshot
+ restore them and warn (policy: warn + preserve).

The updater already snapshots UNTRACKED instance files. The gap this closes: a file
the instance COMMITTED inside the synced tree (e.g. a launchd runner script) is not
untracked, so it was deleted with no protection. Scar 2026-06-24: the fractional-cxo
income scanners died this way for 6 days.

A file is a preserve-candidate when ALL hold:
  1. It exists in the instance under <prefix>/ but NOT in the skeleton archive
     (so `rsync --delete` would remove it), and not under an excluded dir.
  2. It is git-tracked in the instance (untracked files are already handled).
  3. The skeleton git has NEVER tracked the corresponding path -- i.e. it is
     genuinely instance-added, not a file the skeleton deliberately deleted (which
     SHOULD propagate as a deletion).

Prints the instance-relative paths (one per line) to stdout; warnings to stderr.
Exit 0 always (advisory; the updater decides what to do with the list).

Usage:
  kipi-update-preserve-scan.py --skeleton-archive DIR --instance DIR \
      --prefix q-system --skeleton-git DIR
"""
import argparse
import os
import subprocess
import sys

# Mirror the --exclude list in kipi-update.sh exactly (relative to <prefix>/).
# "q-system/" is NOT an rsync exclude: it is the forbidden nested shadow tree (a
# stale skeleton copy from the old `git subtree add` creation path). Listing it
# here stops this scanner from flagging shadow-tree files as preserve-candidates,
# so the updater's rsync --delete can actually remove them (fleet cleanup 2026-07-01).
EXCLUDED_PREFIXES = (
    "my-project/",
    "canonical/",
    "memory/",
    "output/",
    ".q-system/agent-pipeline/bus/",
    "q-system/",
)


def is_excluded(rel):
    # Bytecode is never a preserve-candidate, even when an instance accidentally
    # committed it -- preserving a tracked .pyc kept it immortal across syncs.
    if rel.endswith(".pyc") or "__pycache__" in rel:
        return True
    return any(rel == p.rstrip("/") or rel.startswith(p) for p in EXCLUDED_PREFIXES)


def skeleton_files(archive_dir):
    """Relative paths (under q-system/) present in the extracted skeleton archive."""
    root = os.path.join(archive_dir, "q-system") if os.path.isdir(
        os.path.join(archive_dir, "q-system")) else archive_dir
    present = set()
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            present.add(os.path.relpath(os.path.join(dirpath, name), root))
    return present


def git_tracked(repo, path):
    return subprocess.run(
        ["git", "-C", repo, "ls-files", "--error-unmatch", "--", path],
        capture_output=True,
    ).returncode == 0


def skeleton_ever_tracked(skeleton_git, skeleton_path):
    out = subprocess.run(
        ["git", "-C", skeleton_git, "log", "--all", "--oneline", "-1", "--", skeleton_path],
        capture_output=True, text=True,
    ).stdout.strip()
    return bool(out)


def find_preserve_candidates(skeleton_archive, instance, prefix, skeleton_git):
    skel = skeleton_files(skeleton_archive)
    base = os.path.join(instance, prefix)
    candidates = []
    for dirpath, _dirs, files in os.walk(base):
        for name in files:
            abs_path = os.path.join(dirpath, name)
            rel = os.path.relpath(abs_path, base)             # path under <prefix>/
            if is_excluded(rel):
                continue
            if rel in skel:
                continue                                       # skeleton has it; not deleted
            inst_path = os.path.join(prefix, rel)              # <prefix>/<rel>
            if not git_tracked(instance, inst_path):
                continue                                       # untracked: already handled
            if skeleton_ever_tracked(skeleton_git, os.path.join("q-system", rel)):
                continue                                       # skeleton deleted it: let it go
            candidates.append(inst_path)
    return sorted(candidates)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skeleton-archive", required=True)
    ap.add_argument("--instance", required=True)
    ap.add_argument("--prefix", default="q-system")
    ap.add_argument("--skeleton-git", required=True)
    args = ap.parse_args()

    found = find_preserve_candidates(
        args.skeleton_archive, args.instance, args.prefix, args.skeleton_git
    )
    for path in found:
        print(path)
    if found:
        print(f"  WARNING: {len(found)} tracked instance-only file(s) would be deleted by "
              f"the skeleton sync -- preserving them:", file=sys.stderr)
        for path in found:
            print(f"    + {path}", file=sys.stderr)
        print("  These live inside the synced tree. Move them to a repo-root dir "
              "(outside q-system/) so the updater never touches them.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
