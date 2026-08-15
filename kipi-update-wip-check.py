#!/usr/bin/env python3
"""Is this untracked instance file WORK, or exhaust the updater itself wrote?

Exit 0 = the skeleton itself once shipped this exact blob at this exact path,
         so it is the updater's own output and NOT work in progress.
Exit 1 = no such blob in the skeleton's shipped history. Treat it as work.
Exit 2 = the question could not be answered. Treat it as work (fail closed).

WHY (sp-940bcf47, measured 2026-08-15 on a real --dry-run).

kipi-update.sh refuses an instance when an untracked file collides with a
skeleton path, on the reasoning that overwriting somebody's work-in-progress is
unrecoverable. Correct instinct. But `is_instance_wip` could only recognise ONE
kind of non-work: a file byte-identical to the skeleton's CURRENT copy, i.e.
this same sync's own output from a run that died before committing.

An OLDER skeleton blob looks like work to that check and is not. KTLYST_strategy
carried an untracked `q-system/.q-system/scripts/merge-bypass-gate.py` written by
some earlier sync and never committed, differing from the current skeleton copy.
The updater refused it on every run, so the instance could never sync -- and
fleet-reach-audit.py reported WOULD-SYNC for it, because the audit does not model
this check.

THE EXEMPTION IS EXACTLY AS NARROW AS fleet-unblock's `commit` proof, and for the
same reason: a founder hand-edit does not produce bytes that collide with a blob
the skeleton itself once held at the same path. Anything the skeleton never wrote
there is still work, and still refuses.

DERIVED, NOT TRANSCRIBED. SkeletonBlobs is imported from fleet-reach-audit.py,
which is the single definition of "the skeleton wrote this" -- the same one
fleet-unblock imports. A second copy of that rule is how a guard starts
excusing files the real proof would refuse, and this one decides whether a
sync may overwrite a file on disk.

Usage:
  kipi-update-wip-check.py --skeleton DIR --skeleton-path REL --file PATH
"""
import argparse
import importlib.util
import os
import subprocess
import sys


def load_audit(skeleton):
    path = os.path.join(skeleton, "fleet-reach-audit.py")
    if not os.path.isfile(path):
        raise RuntimeError(f"{path} is missing; refusing to re-derive the "
                           "skeleton-authorship rule from a second copy")
    spec = importlib.util.spec_from_file_location("fleet_reach_audit", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--skeleton", required=True)
    ap.add_argument("--skeleton-path", required=True,
                    help="path as the SKELETON repo spells it, e.g. q-system/x.py")
    ap.add_argument("--file", required=True, help="the instance file on disk")
    args = ap.parse_args(argv)

    try:
        if not os.path.isfile(args.file):
            return 2
        blob = subprocess.run(["git", "hash-object", "--", args.file],
                              capture_output=True, text=True)
        if blob.returncode != 0:
            return 2
        sha = blob.stdout.strip()
        if not sha:
            return 2
        audit = load_audit(args.skeleton)
        blobs = audit.SkeletonBlobs(args.skeleton)
        return 0 if blobs.wrote(args.skeleton_path, sha) else 1
    except Exception as exc:                      # fail closed, and say why
        print(f"wip-check could not decide: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
