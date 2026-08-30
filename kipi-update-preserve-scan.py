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
import hashlib
import json
import os
import subprocess
import sys

# Mirror the --exclude list in kipi-update.sh exactly (relative to <prefix>/).
# "q-system/" is NOT an rsync exclude: it is the forbidden nested shadow tree (a
# stale skeleton copy from the old `git subtree add` creation path). Listing it
# here stops this scanner from flagging shadow-tree files as preserve-candidates,
# so the updater's rsync --delete can actually remove them (fleet cleanup 2026-07-01).
def _owned_subtrees():
    """INSTANCE_OWNED_SUBTREES, parsed out of kipi-update.sh.

    DERIVED, NOT TRANSCRIBED (sp-3d5a247e). The comment above has always claimed
    this list mirrors the updater's excludes "exactly"; measured 2026-08-14 it
    was missing `research` and `.q-system/data`, so the claim had been false for
    as long as those two entries had existed. A hand-kept second copy of a list
    that lives somewhere else drifts the moment anyone adds an entry, and a
    comment asserting the mirror is worse than no comment: it is read as
    coverage, so nobody goes looking.

    Refuses loudly rather than falling back to a literal. A silent fallback here
    would preserve a file the updater is about to delete, or skip one it is not
    permitted to touch, with nothing on screen either way.
    """
    import re
    updater = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "kipi-update.sh")
    with open(updater, encoding="utf-8") as handle:
        text = handle.read()
    match = re.search(r"^INSTANCE_OWNED_SUBTREES=\(\n(.*?)^\)", text, re.S | re.M)
    if not match:
        raise RuntimeError(
            f"INSTANCE_OWNED_SUBTREES not found in {updater}; the preserve scan "
            "cannot mirror the updater's excludes and refuses to guess them"
        )
    subs = [line.strip() for line in match.group(1).splitlines() if line.strip()]
    if not subs:
        raise RuntimeError(f"INSTANCE_OWNED_SUBTREES parsed empty from {updater}")
    return tuple(f"{sub}/" for sub in subs)


# The updater's own instance-owned subtrees, plus one entry that is NOT an rsync
# exclude: "q-system/" is the forbidden nested shadow tree described above, and
# it is excluded here for a different reason. Kept separate so the derived half
# stays a faithful mirror.
EXCLUDED_PREFIXES = _owned_subtrees() + ("q-system/",)


def is_excluded(rel):
    # Bytecode is never a preserve-candidate, even when an instance accidentally
    # committed it -- preserving a tracked .pyc kept it immortal across syncs.
    if rel.endswith(".pyc") or "__pycache__" in rel:
        return True
    return any(rel == p.rstrip("/") or rel.startswith(p) for p in EXCLUDED_PREFIXES)


def raise_walk_error(error):
    raise error


def skeleton_files(archive_dir):
    """Relative paths (under q-system/) present in the extracted skeleton archive."""
    root = os.path.join(archive_dir, "q-system") if os.path.isdir(
        os.path.join(archive_dir, "q-system")) else archive_dir
    present = set()
    if not os.path.isdir(root):
        raise OSError(f"skeleton archive root is missing: {root}")
    for dirpath, dirs, files in os.walk(root, onerror=raise_walk_error):
        entries = files + [
            name for name in dirs if os.path.islink(os.path.join(dirpath, name))
        ]
        for name in entries:
            present.add(os.path.relpath(os.path.join(dirpath, name), root))
    return present


def git_tracked(repo, path):
    result = subprocess.run(
        ["git", "-C", repo, "ls-files", "--error-unmatch", "--", path],
        capture_output=True,
    )
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    raise RuntimeError(
        f"git tracked-state lookup failed for {path}: rc={result.returncode}"
    )


def skeleton_ever_tracked(skeleton_git, skeleton_path):
    result = subprocess.run(
        ["git", "-C", skeleton_git, "log", "--all", "--oneline", "-1", "--", skeleton_path],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"skeleton history lookup failed for {skeleton_path}: "
            f"rc={result.returncode}"
        )
    return bool(result.stdout.strip())


def find_preserve_candidates(skeleton_archive, instance, prefix, skeleton_git):
    skel = skeleton_files(skeleton_archive)
    base = os.path.join(instance, prefix)
    if not os.path.isdir(base):
        raise OSError(f"instance prefix is missing: {base}")
    candidates = []
    for dirpath, dirs, files in os.walk(base, onerror=raise_walk_error):
        entries = files + [
            name for name in dirs if os.path.islink(os.path.join(dirpath, name))
        ]
        for name in entries:
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
    ap.add_argument("--receipt")
    args = ap.parse_args()

    found = find_preserve_candidates(
        args.skeleton_archive, args.instance, args.prefix, args.skeleton_git
    )
    output = "".join(f"{path}\n" for path in found).encode()
    sys.stdout.buffer.write(output)
    sys.stdout.buffer.flush()
    if args.receipt:
        receipt = {
            "candidate_count": len(found),
            "complete": True,
            "schema_version": 1,
            "stdout_sha256": hashlib.sha256(output).hexdigest(),
        }
        temporary = f"{args.receipt}.tmp.{os.getpid()}"
        with open(temporary, "x", encoding="utf-8") as handle:
            json.dump(receipt, handle, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, args.receipt)
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
