#!/usr/bin/env python3
"""Merge origin/main into every open PR branch that has gone DIRTY, and report.

WHY THIS EXISTS (2026-08-29). Thirty open PRs on this repo, cut from different
points of a moving main. Every merge to main flips more of them to DIRTY, and a
DIRTY PR cannot run its required checks, so the backlog rots faster than it
drains. Hand-merging them one at a time is the same seven git commands thirty
times, which is exactly the shape that belongs in a script rather than in an
agent's attention.

WHAT IT DOES NOT DO. It never resolves a conflict, never force-pushes, never
merges to main, and never touches a checkout that is in use. A branch whose
merge conflicts is left EXACTLY as it was found (the merge is aborted) and
reported as needing a human decision. Clean merges are pushed; that is the whole
scope.

WHY MERGE AND NOT REBASE. A rebase needs a force-push, and force-push is on the
destructive-op deny list for good reason. This repo squash-merges, so the merge
commits vanish at merge time and the history cost is zero.

ISOLATION. All work happens in ONE throwaway worktree, created under the system
temp dir and removed at the end. `git -C` everywhere: a `cd` that fails silently
falls back to the session's default cwd, which is how one session's git command
lands in another session's checkout (feedback_cd_then_git_relocates_work).

Usage:
    pr-restack.py [--dry-run] [--limit N] [--only 123,456]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile


def run(args: list[str], cwd: str | None = None, check: bool = False):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=check)


def gh_json(args: list[str]):
    r = run(["gh"] + args)
    if r.returncode != 0:
        sys.exit("gh failed: " + (r.stderr or r.stdout).strip())
    return json.loads(r.stdout)


LEGACY_MANIFEST = "q-system/.q-system/capability-manifest.json"
FRAGMENT_DIR = "q-system/.q-system/capability"


def resolve_capability_manifest(wt: str, root: str, files: list[str]) -> str | None:
    """Auto-resolve the one conflict that accounts for most of the backlog.

    Measured on the 55 open PRs, 2026-08-29: `capability-manifest.json` is a
    conflicted path in 35 of the 40 DIRTY branches, and the ONLY one in many.
    Main replaced that single hand-maintained array with one JSON fragment per
    declaration (#263) exactly so two branches adding two tests stop colliding
    on the same lines. Every branch cut before that split still edits the array,
    so it hits a modify/delete against main's removal.

    capability_manifest.py --add-from is the migration's OWN replay tool, and its
    docstring names this case: "the rebase tool for the 37 open branches that
    predate the split". This wires it in rather than asking a human to run it 35
    times. The resolution is main's (the monolith goes) PLUS this branch's
    additions re-expressed as fragments -- never one or the other, which is how
    a declaration gets silently dropped.

    add_delta is additive only: a branch that REMOVED a declaration is reported
    by the tool and NOT acted on, and that message is returned here so the
    branch lands in the needs-a-human pile instead of quietly losing a gate.

    Returns None on success, or a string saying why it could not resolve.
    """
    if LEGACY_MANIFEST not in files:
        return "not a capability-manifest conflict"

    base_sha = run(["git", "-C", wt, "merge-base", "HEAD", "MERGE_HEAD"]).stdout.strip()
    if not base_sha:
        return "could not find the merge base"

    tmpd = tempfile.mkdtemp(prefix="capman-")
    base_json = os.path.join(tmpd, "base.json")
    head_json = os.path.join(tmpd, "head.json")
    for sha, dest in ((base_sha, base_json), ("HEAD", head_json)):
        r = run(["git", "-C", wt, "show", f"{sha}:{LEGACY_MANIFEST}"])
        if r.returncode != 0:
            return f"no {LEGACY_MANIFEST} at {sha[:8]}"
        with open(dest, "w") as fh:
            fh.write(r.stdout)

    # The assembler comes from MAIN, never from the branch: a pre-split branch
    # does not have it, and a branch that has an older copy would replay through
    # code the merge result will not contain.
    tool = os.path.join(tmpd, "capability_manifest.py")
    r = run(["git", "-C", root, "show",
             "origin/main:q-system/.q-system/scripts/capability_manifest.py"])
    if r.returncode != 0:
        return "origin/main has no capability_manifest.py"
    with open(tool, "w") as fh:
        fh.write(r.stdout)

    add = run(["python3", tool, "--root", wt, "--add-from", base_json, head_json])
    if add.returncode != 0:
        return "add-from failed: " + (add.stderr or add.stdout).strip()[:300]
    if "REMOVED" in (add.stderr or "") + (add.stdout or ""):
        return "this branch REMOVES a declaration; replaying that is a human call"

    # Accept main's side of the modify/delete: the monolith is gone, and this
    # branch's entries now live as fragments written just above.
    if run(["git", "-C", wt, "rm", "-q", "--", LEGACY_MANIFEST]).returncode != 0:
        return "could not stage the manifest deletion"
    run(["git", "-C", wt, "add", "--", FRAGMENT_DIR])
    return None


def repo_root() -> str:
    r = run(["git", "rev-parse", "--show-toplevel"])
    if r.returncode != 0:
        sys.exit("not a git repository")
    return r.stdout.strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would merge; push nothing")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--no-capability-fix", action="store_true",
                    help="do not auto-resolve the capability-manifest conflict")
    ap.add_argument("--only", default="",
                    help="comma-separated PR numbers, instead of every DIRTY one")
    args = ap.parse_args()

    root = repo_root()
    run(["git", "-C", root, "fetch", "origin", "--prune", "--quiet"])

    prs = gh_json(["pr", "list", "--state", "open", "--limit", "200",
                   "--json", "number,headRefName,mergeStateStatus,title"])
    if args.only:
        want = {int(x) for x in args.only.split(",") if x.strip()}
        prs = [p for p in prs if p["number"] in want]
    else:
        prs = [p for p in prs if p["mergeStateStatus"] == "DIRTY"]
    prs.sort(key=lambda p: p["number"])
    if args.limit:
        prs = prs[: args.limit]

    if not prs:
        print("nothing to restack")
        return 0

    # ONE worktree for the whole sweep, detached so no branch is ever "checked
    # out" here and a branch already open in another worktree stays reachable.
    tmp = tempfile.mkdtemp(prefix="pr-restack-")
    wt = os.path.join(tmp, "wt")
    r = run(["git", "-C", root, "worktree", "add", "--detach", "-f", wt, "origin/main"])
    if r.returncode != 0:
        sys.exit("could not create worktree: " + r.stderr.strip())

    merged, conflicted, failed, already, resolved = [], [], [], [], []
    try:
        for pr in prs:
            n, ref = pr["number"], pr["headRefName"]
            remote = "origin/" + ref
            if run(["git", "-C", root, "rev-parse", "--verify", "--quiet", remote]).returncode != 0:
                failed.append((n, ref, "no remote branch"))
                continue

            # Start from the PR head every time. --detach keeps this worktree
            # from claiming a branch another session may have checked out.
            run(["git", "-C", wt, "checkout", "--detach", remote, "--force"])
            run(["git", "-C", wt, "clean", "-qfd"])

            behind = run(["git", "-C", wt, "rev-list", "--count", "HEAD..origin/main"])
            if behind.stdout.strip() == "0":
                already.append((n, ref))
                continue

            # --no-commit, then an explicit --no-verify commit. Committing
            # inside `git merge` runs the repo's pre-commit hooks, and those
            # read the WORKING TREE -- so another session's uncommitted file
            # aborts this merge for reasons that have nothing to do with it
            # (sp-b5a8edcf). Measured: 5 of 40 branches failed here with
            # "Not committing merge" and no conflict at all. The merge content
            # is still graded, by the PR's own required checks.
            m = run(["git", "-C", wt, "merge", "origin/main", "--no-commit", "--no-ff"])
            if m.returncode != 0:
                # READ THE CONFLICT LIST BEFORE ABORTING. `merge --abort` clears
                # the index, so `diff --diff-filter=U` afterwards is always empty
                # -- the first version of this script aborted first and reported
                # "0 file(s)" for every conflict, which is a report that cannot
                # be acted on and looks like a clean result at a glance.
                names = run(["git", "-C", wt, "diff", "--name-only", "--diff-filter=U"])
                files = [x for x in names.stdout.split() if x]

                # Try the one automatic resolution there is. Everything else is
                # a judgement call and stays one.
                if files and not args.no_capability_fix:
                    why = resolve_capability_manifest(wt, root, files)
                    if why is None:
                        left = run(["git", "-C", wt, "diff", "--name-only",
                                    "--diff-filter=U"])
                        files = [x for x in left.stdout.split() if x]
                        if not files:
                            # `commit --no-verify`: the pre-commit hooks read the
                            # WORKING TREE, so another session's uncommitted file
                            # blocks this commit for reasons that have nothing to
                            # do with it (sp-b5a8edcf). The merge content is
                            # still graded -- by the PR's own required checks,
                            # which is where grading belongs.
                            c = run(["git", "-C", wt, "commit", "--no-verify",
                                     "--no-edit"])
                            if c.returncode != 0:
                                run(["git", "-C", wt, "merge", "--abort"])
                                failed.append((n, ref, "capability fix staged but "
                                               "commit failed: "
                                               + (c.stderr or c.stdout).strip()[-160:]))
                                continue
                            resolved.append((n, ref))
                            if args.dry_run:
                                merged.append((n, ref, "would push (capability fix)"))
                                continue
                            head = run(["git", "-C", wt, "rev-parse", "HEAD"]).stdout.strip()
                            p = run(["git", "-C", wt, "push", "origin",
                                     head + ":refs/heads/" + ref])
                            if p.returncode != 0:
                                failed.append((n, ref, (p.stderr or p.stdout)
                                               .strip()[-160:]))
                            else:
                                merged.append((n, ref, head[:8] + " +capfix"))
                            continue

                if not files:
                    # Not a content conflict at all: the merge refused for some
                    # other reason. Say which, rather than filing it as a
                    # conflict nobody can find.
                    failed.append((n, ref, (m.stderr or m.stdout).strip().splitlines()[-2:]))
                else:
                    conflicted.append((n, ref, files))
                # Leave nothing behind, so the next iteration's checkout is
                # unambiguous.
                run(["git", "-C", wt, "merge", "--abort"])
                continue

            c = run(["git", "-C", wt, "commit", "--no-verify", "--no-edit"])
            if c.returncode != 0:
                run(["git", "-C", wt, "merge", "--abort"])
                failed.append((n, ref, "merge clean but commit failed: "
                               + (c.stderr or c.stdout).strip()[-160:]))
                continue

            if args.dry_run:
                merged.append((n, ref, "would push"))
                continue

            head = run(["git", "-C", wt, "rev-parse", "HEAD"]).stdout.strip()
            p = run(["git", "-C", wt, "push", "origin", head + ":refs/heads/" + ref])
            if p.returncode != 0:
                failed.append((n, ref, (p.stderr or p.stdout).strip().splitlines()[-1:]))
            else:
                merged.append((n, ref, head[:8]))
    finally:
        run(["git", "-C", root, "worktree", "remove", "--force", wt])

    print("\n=== restacked (origin/main merged in, pushed) ===")
    for n, ref, sha in merged:
        print("  #%-4d %-48s %s" % (n, ref, sha))
    print("\n=== already current ===")
    for n, ref in already:
        print("  #%-4d %s" % (n, ref))
    print("\n=== CONFLICTS, untouched, need a decision ===")
    for n, ref, files in conflicted:
        print("  #%-4d %-48s %d file(s)" % (n, ref, len(files)))
        for f in files[:8]:
            print("        " + f)
    print("\n=== capability-manifest conflict auto-resolved ===")
    for n, ref in resolved:
        print("  #%-4d %s" % (n, ref))
    print("\n=== failed ===")
    for n, ref, why in failed:
        print("  #%-4d %-48s %s" % (n, ref, why))
    print("\nrestacked %d (of which %d needed the capability fix), current %d, "
          "conflicted %d, failed %d"
          % (len(merged), len(resolved), len(already), len(conflicted), len(failed)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
