#!/usr/bin/env python3
"""control-file-propagate: bring ONE named control file in ONE named repo up to
skeleton HEAD, hash-classified, without `kipi update` and without any delete.

WHY THIS EXISTS (ASK-755)
-------------------------
repo-preflight.sh refuses a repo whose `linear-worker.sh` differs from the
skeleton, and its refusal text says "run kipi update on this repo first". That is
the wrong instrument for the job. `kipi update` is a fleet rsync WITH a delete
flag: to move two files in two repos it walks every registered instance and can
remove anything on the way. The blast radius of the tool is three orders of
magnitude larger than the change, and the direction of a mistake is unrecoverable.

So: same classification, one file at a time, copy only, never delete.

CLASSIFICATION, against git history rather than against a guess. Mirrors
plugin-fanout.py, which classifies a whole plugin TREE; this classifies a single
FILE, because a preflight blocker names a file.

  NEW      target is byte-identical to skeleton HEAD          -> nothing to do
  OLD      target is byte-identical to some ANCESTOR blob of
           that path in skeleton history                      -> safe to write
  OTHER    neither                                            -> REFUSED
  DIRTY    the target path has uncommitted changes            -> REFUSED
  MISSING  the target has no such file                        -> REFUSED

OTHER AND DIRTY REFUSE, AND THAT IS THE WHOLE POINT. OTHER means "this content is
not something this skeleton ever shipped" -- a local edit, a hand-patch, or a tree
from another lineage. Overwriting it destroys work nobody can recover from a copy
that leaves no trace. DIRTY is the same argument one level out: a file with
uncommitted changes has an owner who is mid-thought, and git cannot give it back
after a copy lands on top. Both get a human instead of a write.

SURVEY IS THE DEFAULT. --apply writes only to OLD, and re-runs the identical
classification immediately before each write rather than trusting the survey pass
-- the tree can change between the two, and a stale classification is exactly how
a copy lands on a file that went dirty in between.

Exit: 0 on survey always. On --apply, 1 if any target that classified OLD failed
to be written, or if anything classified OTHER/DIRTY/MISSING (a refusal the caller
asked to act on is a failure of the run, not a quiet skip).
"""
import argparse
import hashlib
import os
import shutil
import subprocess
import sys


def sha256_file(path):
    try:
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        return None


def git(repo, *args):
    """Return stdout, or None when git itself failed.

    Never raises. A repo that is not a git repo, a path git does not know, and a
    git that is not installed all have to reach the caller as "cannot tell",
    because every one of them classifies as a refusal here rather than a write.
    """
    try:
        p = subprocess.run(
            ["git", "-C", repo] + list(args),
            capture_output=True, text=True, check=False,
        )
    except OSError:
        return None
    if p.returncode != 0:
        return None
    return p.stdout


def git_blob_sha256(repo, rev, rel):
    """sha256 of the file CONTENT at <rev>:<rel>, not git's own blob id.

    Deliberately the content hash: repo-preflight.sh reports a sha256 of the file
    on disk, and a classification that cannot be compared by eye against the gate
    that motivated it is a second source of truth. Same number, same units.
    """
    try:
        p = subprocess.run(
            ["git", "-C", repo, "show", "%s:%s" % (rev, rel)],
            capture_output=True, check=False,
        )
    except OSError:
        return None
    if p.returncode != 0:
        return None
    return hashlib.sha256(p.stdout).hexdigest()


def ancestor_hashes(skeleton, rel, limit=200):
    """Every content hash this path has ever held in skeleton history -> rev."""
    out = git(skeleton, "rev-list", "--max-count=%d" % limit, "HEAD", "--", rel)
    seen = {}
    for rev in (out or "").split():
        h = git_blob_sha256(skeleton, rev, rel)
        if h and h not in seen:
            seen[h] = rev
    return seen


def path_is_dirty(repo, rel):
    """True when <rel> has uncommitted changes; True also when git cannot say.

    FAIL CLOSED, same posture as repo-preflight.sh. "I could not determine whether
    somebody is editing this file" is not permission to overwrite it.
    """
    out = git(repo, "status", "--porcelain", "--", rel)
    if out is None:
        return True
    return bool(out.strip())


def classify(skeleton, target, rel, head_hash, ancestors):
    tgt = os.path.join(target, rel)
    if not os.path.isfile(tgt):
        return "MISSING", None
    if path_is_dirty(target, rel):
        return "DIRTY", None
    have = sha256_file(tgt)
    if have is None:
        return "OTHER", None
    if have == head_hash:
        return "NEW", None
    if have in ancestors:
        return "OLD", ancestors[have]
    return "OTHER", None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--skeleton", default=None,
                    help="skeleton repo root (default: derived from this script)")
    ap.add_argument("--target", action="append", default=[], required=True,
                    help="target repo path (repeatable)")
    ap.add_argument("--file", action="append", default=[], required=True,
                    help="repo-relative control file (repeatable)")
    ap.add_argument("--apply", action="store_true",
                    help="write OLD targets; without it this only surveys")
    args = ap.parse_args(argv)

    # Derived from the script's own location, never $PWD. Same reason
    # repo-preflight.sh does it: the reference has to follow the CODE, or standing
    # in a directory changes what "the skeleton" means (guard-tests scar).
    skeleton = args.skeleton or os.path.abspath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
    )

    rc = 0
    for rel in args.file:
        skel_file = os.path.join(skeleton, rel)
        if not os.path.isfile(skel_file):
            print("REFUSED %s: not present in the skeleton %s" % (rel, skeleton))
            rc = 1
            continue
        head_hash = sha256_file(skel_file)
        if git(skeleton, "status", "--porcelain", "--", rel) is None:
            print("REFUSED %s: skeleton is not a readable git repo" % rel)
            rc = 1
            continue
        if (git(skeleton, "status", "--porcelain", "--", rel) or "").strip():
            # A dirty SOURCE would propagate uncommitted skeleton work into other
            # repos, where it has no commit to trace it back to.
            print("REFUSED %s: skeleton copy is uncommitted; commit it first" % rel)
            rc = 1
            continue
        ancestors = ancestor_hashes(skeleton, rel)

        for target in args.target:
            status, rev = classify(skeleton, target, rel, head_hash, ancestors)
            note = ("ancestor %s" % rev[:8]) if rev else ""
            if status == "NEW":
                print("NEW      %s :: %s (already at skeleton HEAD)" % (target, rel))
                continue
            if status in ("OTHER", "DIRTY", "MISSING"):
                print("REFUSED  %s :: %s (%s)" % (target, rel, status))
                rc = 1
                continue
            if not args.apply:
                print("OLD      %s :: %s (%s) [survey only]" % (target, rel, note))
                continue
            # Re-classify immediately before the write. See the module docstring.
            status2, _ = classify(skeleton, target, rel, head_hash, ancestors)
            if status2 != "OLD":
                print("REFUSED  %s :: %s (became %s between survey and write)"
                      % (target, rel, status2))
                rc = 1
                continue
            dst = os.path.join(target, rel)
            try:
                shutil.copyfile(skel_file, dst)
                shutil.copymode(skel_file, dst)
            except OSError as exc:
                print("FAILED   %s :: %s (%s)" % (target, rel, exc))
                rc = 1
                continue
            wrote = sha256_file(dst)
            if wrote != head_hash:
                print("FAILED   %s :: %s (post-write hash %s != %s)"
                      % (target, rel, (wrote or "?")[:12], head_hash[:12]))
                rc = 1
                continue
            print("WROTE    %s :: %s (%s -> %s)"
                  % (target, rel, note or "old", head_hash[:12]))
    return rc


if __name__ == "__main__":
    sys.exit(main())
