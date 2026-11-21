#!/usr/bin/env python3
"""Merge-time plugin version bump: the PR's number is a floor, main's is the truth (ASK-5470).

WHY. Every kipi-core PR bumps plugins/*/.claude-plugin/plugin.json by one patch
at authoring time. Two open PRs pick the same next number. Whichever merges
second either CONFLICTS on that line or, when both wrote the identical line,
merges clean and EQUALS main, which plugin-version-bump-check.py refuses. Measured
2026-11-18: four times in one night (#839, #847, #851, #858), two of them rebuilt
as new PRs at the review cap for a one-line version change.

WHAT. Run this on the PR branch at merge time, after the last review round:
  1. merge origin/main in (never rebase, never force);
  2. if the only conflict is a plugin.json version line, take main's file;
  3. for each plugin this branch changed, if its version is not strictly above
     main's, set it to main's version plus one patch;
  4. commit; with --push, push the branch.
The gate stays "strictly greater than main" (instances read the version to tell
copies apart). Only WHO computes the number moves, from authoring time to merge
time. The commit is version-only, so receipt-carry-approval.sh --reattest-version
carries the approval onto it (--carry wires that call) and it costs no review round.

Refuses (exit 2, tree left as found) on any other conflict.
"""
from __future__ import annotations
import argparse, json, os, re, subprocess, sys

SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
HERE = os.path.dirname(os.path.abspath(__file__))


def git(tree, *a, check=False):
    r = subprocess.run(["git", "-C", tree, *a], capture_output=True, text=True)
    if check and r.returncode != 0:
        sys.exit("git %s failed: %s" % (" ".join(a), (r.stderr or r.stdout).strip()))
    return r


def parse(v):
    m = SEMVER.match(v or "")
    return tuple(int(x) for x in m.groups()) if m else None


def version_above(branch_v, main_v):
    """Version this branch must carry: its own if strictly above main's, else main's + 1 patch."""
    b, m = parse(branch_v), parse(main_v)
    if m is None:
        sys.exit("main version %r is not plain x.y.z; refusing to guess" % main_v)
    if b is not None and b > m:
        return branch_v
    return "%d.%d.%d" % (m[0], m[1], m[2] + 1)


def read_version(tree, ref, rel):
    r = git(tree, "show", "%s:%s" % (ref, rel))
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout).get("version")
    except ValueError:
        return None


def run(tree, main, push_ref=None):
    # Refuse a dirty tree: git add of a manifest carrying unstaged work puts unreviewed
    # content in a "version-only" commit (same scar as plugin-version-bump-check.py, PR #253).
    if git(tree, "status", "--porcelain").stdout.strip():
        sys.stderr.write("refusing: working tree has uncommitted changes\n")
        sys.exit(2)
    # A stale origin/main makes "main's number" equal the branch's, the collision this tool
    # exists to prevent. Fetch when an origin remote exists; a failed fetch refuses.
    if main.startswith("origin/") and git(tree, "remote").stdout.split():
        fr = git(tree, "fetch", "-q", "origin", main.split("/", 1)[1])
        if fr.returncode != 0:
            sys.stderr.write("refusing: could not fetch %s: %s\n" % (main, fr.stderr.strip()))
            sys.exit(2)
    start = git(tree, "rev-parse", "HEAD", check=True).stdout.strip()
    mb = git(tree, "merge-base", main, "HEAD", check=True).stdout.strip()
    changed = git(tree, "diff", "--name-only", mb, "HEAD").stdout.split()
    m = git(tree, "merge", "--no-edit", main)
    if m.returncode != 0:
        files = git(tree, "diff", "--name-only", "--diff-filter=U").stdout.split()
        ok = bool(files) and all(f.endswith(".claude-plugin/plugin.json") for f in files)
        if ok:
            for f in files:
                if git(tree, "show", ":2:" + f).returncode != 0 or git(tree, "show", ":3:" + f).returncode != 0:
                    ok = False  # delete/modify conflict: one side has no file to compare
                    break
                o = json.loads(git(tree, "show", ":2:" + f, check=True).stdout)
                t = json.loads(git(tree, "show", ":3:" + f, check=True).stdout)
                if {k for k in set(o) | set(t) if o.get(k) != t.get(k)} != {"version"}:
                    ok = False
        if not ok:
            git(tree, "merge", "--abort")
            # exit 2 is the repo's refuse contract; sys.exit(str) would exit 1 and read as a crash.
            sys.stderr.write("refusing: conflict beyond a plugin.json version line: %s %s\n" % (files, m.stderr.strip()[-200:]))
            sys.exit(2)
        for f in files:
            git(tree, "checkout", "--theirs", "--", f, check=True)
            git(tree, "add", "--", f, check=True)
        git(tree, "commit", "--no-verify", "--no-edit", check=True)
    plugins = sorted({f.rsplit("/.claude-plugin/", 1)[0] if "/.claude-plugin/" in f
                      else "/".join(f.split("/")[:2])
                      for f in changed if f.startswith("plugins/")})
    bumped = []
    for pdir in plugins:
        rel = pdir + "/.claude-plugin/plugin.json"
        mv = read_version(tree, main, rel)
        if mv is None:
            continue
        hv = read_version(tree, "HEAD", rel)
        if hv is None:
            continue  # this branch retires the plugin; nothing to bump
        want = version_above(hv, mv)
        if want == hv:
            continue
        path = os.path.join(tree, rel)
        d = json.load(open(path))
        d["version"] = want
        with open(path, "w") as fh:
            json.dump(d, fh, indent=2); fh.write("\n")
        git(tree, "add", "--", rel, check=True)
        bumped.append("%s %s -> %s" % (rel, hv, want))
    if bumped:
        git(tree, "commit", "--no-verify", "-m",
            "Bump plugin version at merge time (ASK-5470)\n\n" + "\n".join(bumped), check=True)
    head = git(tree, "rev-parse", "HEAD", check=True).stdout.strip()
    moved = head != start
    if push_ref:
        git(tree, "push", "origin", "HEAD:refs/heads/" + push_ref, check=True)
    return head, bumped, start, moved


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tree", required=True)
    ap.add_argument("--main", default="origin/main")
    ap.add_argument("--push", metavar="BRANCH")
    ap.add_argument("--carry", nargs=2, metavar=("REVIEWED_SHA", "OWNER/REPO"),
                    help="after the push, carry the approval onto the version-only head")
    a = ap.parse_args()
    if a.carry and not a.push:
        sys.exit("--carry needs --push")
    head, bumped, start, moved = run(a.tree, a.main, a.push)
    print("head %s; bumped: %s" % (head[:8], bumped or "none needed"))
    # moved, not bumped: a merge-only head is also a head the reviewer never saw.
    if a.carry and moved:
        r = subprocess.run(["bash", os.path.join(HERE, "receipt-carry-approval.sh"),
                            "--reattest-version", a.tree, a.carry[0], head, a.carry[1], a.main])
        sys.exit(r.returncode)


if __name__ == "__main__":
    main()
