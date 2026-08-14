#!/usr/bin/env python3
"""Why the fleet cannot receive an update, per instance, read-only.

`kipi update` reports "Failed: N" without saying whether the blocker is founder
work (correct refusal) or the updater's own abandoned exhaust (a defect). Four
of 23 instances received the 2026-08-14 skeleton; this answers WHY for the
other 19 in one pass, and gives the before/after number that any fix has to
move.

REPLICATES THE GUARD, DOES NOT APPROXIMATE IT. The refusal at kipi-update.sh
"Refuse tracked work in progress" is two `git diff --quiet` calls over the
pathspec `<prefix>/ .claude/ plugins/` minus the instance-owned subtrees. A
`git status` grep answers a DIFFERENT question -- it counts untracked files and
paths outside the sync scope, neither of which the guard reads -- so this runs
the same two commands with the same pathspec instead. INSTANCE_OWNED_SUBTREES
is parsed out of kipi-update.sh rather than transcribed, because a
hand-transcribed copy is how the audit and the guard would come to disagree
about what is blocking.

Writes nothing anywhere. Every git call is a read.
"""

import argparse
import json
import pathlib
import re
import subprocess
import sys

SKELETON = pathlib.Path(__file__).resolve().parent


def git(repo, *args, check=False):
    """Read-only git. Returns stdout, or "" when the call fails."""
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} in {repo}: {proc.stderr.strip()}")
    return proc.stdout


def instance_owned_subtrees(updater):
    """Parse INSTANCE_OWNED_SUBTREES out of kipi-update.sh.

    Derived, never transcribed. A second hand-written copy of this list is how
    the audit would start naming a path as "blocking" that the real guard
    excludes, and the audit exists to be trusted about exactly that.
    """
    text = updater.read_text(encoding="utf-8")
    match = re.search(r"^INSTANCE_OWNED_SUBTREES=\(\n(.*?)^\)", text, re.S | re.M)
    if not match:
        raise RuntimeError(
            f"INSTANCE_OWNED_SUBTREES not found in {updater}; the audit cannot "
            "build the guard's pathspec and refuses to guess it"
        )
    subs = [line.strip() for line in match.group(1).splitlines() if line.strip()]
    if not subs:
        raise RuntimeError(f"INSTANCE_OWNED_SUBTREES parsed empty from {updater}")
    return subs


def guard_pathspec(prefix, owned):
    """The exact pathspec the dirty-tree guard uses."""
    spec = [f"{prefix}/", ".claude/", "plugins/"] if prefix else [".claude/", "plugins/"]
    if prefix:
        spec += [f":(exclude){prefix}/{sub}/" for sub in owned]
    return spec


def name_status(repo, pathspec, cached):
    """Blocking paths as (status, path), from the guard's own diff."""
    args = ["diff", "--name-status"]
    if cached:
        args.append("--cached")
    out = git(repo, *args, "--", *pathspec)
    rows = []
    for line in out.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) >= 2:
            rows.append((parts[0], parts[-1]))
    return rows


class SkeletonBlobs:
    """Was this exact blob ever written by the skeleton at this exact path?

    The proof that a change is fleet-written rather than founder-written. A
    founder hand-edit does not produce bytes that collide with a blob the
    skeleton itself once held at the same path, so a hit here is evidence the
    updater wrote the file and never committed it.

    Scoped per path and memoised: a single file's own history is short, while
    walking every commit in the skeleton to build one big index is not.
    """

    def __init__(self, skeleton):
        self.skeleton = skeleton
        self._cache = {}

    def shas_for(self, path):
        if path not in self._cache:
            shas = set()
            commits = git(self.skeleton, "rev-list", "--all", "--", path).split()
            for commit in commits:
                sha = git(self.skeleton, "rev-parse", "-q", "--verify",
                          f"{commit}:{path}").strip()
                if sha:
                    shas.add(sha)
            self._cache[path] = shas
        return self._cache[path]

    def wrote(self, path, sha):
        return bool(sha) and sha in self.shas_for(path)


def blob_sha(repo, path, source):
    """Blob sha of a path in the index or the worktree. "" when absent."""
    if source == "index":
        out = git(repo, "ls-files", "-s", "--", path).split()
        return out[1] if len(out) >= 2 else ""
    full = pathlib.Path(repo) / path
    if not full.is_file():
        return ""
    return git(repo, "hash-object", "--", str(full)).strip()


def classify(repo, path, staged, skel_blobs):
    """Why this path is blocking, and whether a fix may touch it.

    Three answers, and the distinction is the point of the audit:

    fleet-written   the blob is one the skeleton itself once held at this path.
                    Provably updater exhaust, never committed by its writer.
    staged-only     staged, and the worktree agrees with the index. Unstaging
                    restores the HEAD index entry and leaves the file on disk
                    byte-for-byte, so it cannot lose work.
    founder         everything else. Not ours to clear, and named in the report
                    so a refusal over it is legible rather than mysterious.
    """
    index_sha = blob_sha(repo, path, "index")
    work_sha = blob_sha(repo, path, "worktree")
    if skel_blobs.wrote(path, index_sha) or skel_blobs.wrote(path, work_sha):
        return "fleet-written"
    if staged and index_sha and index_sha == work_sha:
        return "staged-only"
    return "founder"


def audit_instance(entry, owned, skel_blobs):
    path = pathlib.Path(entry["path"])
    prefix = entry.get("subtree_prefix") or ""
    result = {
        "name": entry["name"],
        "path": str(path),
        "prefix": prefix,
        "blocked_by": [],
        "verdict": None,
    }
    if not path.exists():
        result["verdict"] = "MISSING"
        return result
    if not (path / ".git").exists():
        result["verdict"] = "NOT-A-REPO"
        return result

    spec = guard_pathspec(prefix, owned)
    rows = ([(s, p, True) for s, p in name_status(path, spec, cached=True)] +
            [(s, p, False) for s, p in name_status(path, spec, cached=False)])
    if not rows:
        result["verdict"] = "WOULD-SYNC"
        return result

    seen = {}
    for status, rel, staged in rows:
        kind = classify(path, rel, staged, skel_blobs)
        # A path dirty in BOTH index and worktree keeps the stricter answer:
        # a founder edit riding on top of fleet-written bytes is founder work.
        if seen.get(rel) != "founder":
            seen[rel] = kind
        result["blocked_by"].append(
            {"status": status, "path": rel, "staged": staged, "kind": seen[rel]}
        )
    kinds = {row["kind"] for row in result["blocked_by"]}
    result["verdict"] = "BLOCKED-FOUNDER" if "founder" in kinds else "BLOCKED-FLEET"
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="machine-readable")
    parser.add_argument("--skeleton", default=str(SKELETON))
    args = parser.parse_args()

    skeleton = pathlib.Path(args.skeleton).resolve()
    updater = skeleton / "kipi-update.sh"
    registry = skeleton / "instance-registry.json"
    owned = instance_owned_subtrees(updater)
    skel_blobs = SkeletonBlobs(skeleton)

    entries = [
        i for i in json.loads(registry.read_text())["instances"]
        if not str(i.get("status", "")).startswith("merged")
        and i.get("skeleton_managed") is not False
    ]
    results = [audit_instance(e, owned, skel_blobs) for e in entries]

    if args.json:
        print(json.dumps(results, indent=2))
        return 0

    order = {"WOULD-SYNC": 0, "BLOCKED-FLEET": 1, "BLOCKED-FOUNDER": 2}
    counts = {}
    for row in results:
        counts[row["verdict"]] = counts.get(row["verdict"], 0) + 1

    print(f"registered, skeleton-managed : {len(results)}")
    for verdict in sorted(counts, key=lambda v: order.get(v, 9)):
        print(f"  {verdict:16s} {counts[verdict]}")
    print()
    print(f"REACH: {counts.get('WOULD-SYNC', 0)} of {len(results)} would sync now")
    print()

    for row in sorted(results, key=lambda r: (order.get(r["verdict"], 9), r["name"])):
        if row["verdict"] == "WOULD-SYNC":
            continue
        print(f"{row['name']}  [{row['verdict']}]")
        for item in row["blocked_by"]:
            where = "index " if item["staged"] else "wtree "
            print(f"    {item['status']:2s} {where} {item['kind']:14s} {item['path']}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
