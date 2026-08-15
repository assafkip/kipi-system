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

IT MODELS ONE PRECONDITION AND SAYS SO (ASK-831). The updater can abandon an
instance at 25 different sites; this script reads the input of exactly one of
them. So "not blocked by the guard I model" is NOT "will sync", and printing it
as WOULD-SYNC is how this file reported "REACH: 22 of 22" on 2026-08-15 while a
real --dry-run refused KTLYST_strategy over an untracked-WIP collision. Instead
the refusal sites are PARSED out of the updater, checked against
MODELLED_REFUSALS, and anything unmodelled downgrades the optimistic verdict to
UNKNOWN. The pessimistic verdicts are untouched: a BLOCKED answer is a positive
finding about state this script did read.

The registry does not hold the audit honest by itself -- an unrun claim never
does. `q-system/.q-system/tests/test_reach_audit_divergence.py` runs the real
`kipi-update.sh --dry-run` against fixture instances and fails whenever an
outcome disagrees with a verdict here.

Writes nothing anywhere. Every git call is a read.
"""

import argparse
import json
import pathlib
import re
import subprocess
import sys

SKELETON = pathlib.Path(__file__).resolve().parent

# Every way kipi-update.sh gives up on one instance, as it spells the message.
# Two shapes reach the same place: `abandon_instance "  ERROR: ..."`, and an
# `echo "  ERROR: ..."` whose caller abandons a few lines later. Both are
# quoted strings carrying an indented ERROR:, which is what this matches.
REFUSAL_RE = re.compile(r'"\s{2,}ERROR: ([^"]*)"')

# The refusal sites this script actually reads the input of. ONE, today.
#
# Membership is a claim that an instance tripping that site comes back BLOCKED
# here rather than green -- not that the message was noticed. Adding a line
# without adding the read is how the audit would go back to being optimistic
# in exactly the cases that matter, so the divergence test is what admits new
# entries: it runs the real updater and compares.
MODELLED_REFUSALS = frozenset({
    "dirty working tree; refusing to commit unrelated work",
})


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


def never_commit_paths(updater):
    """SYSTEM_NEVER_COMMIT, parsed from kipi-update.sh.

    Feeds --after. Parsed rather than transcribed for the same reason the
    subtree list is: a second copy is how the projection would start crediting
    a fix the updater does not actually apply.
    """
    text = updater.read_text(encoding="utf-8")
    match = re.search(r"^SYSTEM_NEVER_COMMIT=\(\n(.*?)^\)", text, re.S | re.M)
    if not match:
        raise RuntimeError(f"SYSTEM_NEVER_COMMIT not found in {updater}")
    paths = []
    for line in match.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        paths.append(line.strip('"').strip("'"))
    return paths


def refusal_sites(updater):
    """Every per-instance refusal message in kipi-update.sh, in file order.

    Derived, never transcribed, for the same reason INSTANCE_OWNED_SUBTREES is:
    a hand-kept list would go stale the moment somebody adds a precondition,
    and going stale here means going OPTIMISTIC, which is the whole defect.

    The `$` truncation makes the identity stable: half these messages end in an
    interpolated path, and the site is the same site whichever file tripped it.
    """
    sites = []
    for line in updater.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("#"):
            continue
        for match in REFUSAL_RE.finditer(line):
            message = match.group(1).split("$")[0].strip().rstrip(":").strip()
            if message and message not in sites:
                sites.append(message)
    if not sites:
        raise RuntimeError(
            f"no refusal sites parsed from {updater}; the audit cannot tell "
            "what it fails to model and refuses to assume the answer is none"
        )
    return sites


def unmodelled_refusals(updater):
    """Refusal sites with nothing behind them here. Empty means full coverage.

    Also fails loudly when a MODELLED entry no longer exists in the updater. A
    reworded message would otherwise leave the registry claiming coverage of a
    site that is gone while the real, renamed one sits unmodelled and silent --
    the same blind spot with a fresh coat of paint.
    """
    sites = refusal_sites(updater)
    missing = sorted(MODELLED_REFUSALS - set(sites))
    if missing:
        raise RuntimeError(
            f"MODELLED_REFUSALS names sites absent from {updater}: {missing}. "
            "They were renamed or removed; re-point the registry before "
            "trusting any verdict from this script."
        )
    return [site for site in sites if site not in MODELLED_REFUSALS]


def guard_pathspec(prefix, owned, cleared=()):
    """The exact pathspec the dirty-tree guard uses.

    `cleared` is how --after models the one-time untrack migration. Excluding a
    path from the pathspec makes git answer the question the migration creates
    -- "would this instance sync if that path were not tracked?" -- and GIT
    answers it, against the real repo. Subtracting the paths by hand from the
    blocking list would be arithmetic on my own classifier instead, which is
    the part most likely to be wrong.
    """
    spec = [f"{prefix}/", ".claude/", "plugins/"] if prefix else [".claude/", "plugins/"]
    if prefix:
        spec += [f":(exclude){prefix}/{sub}/" for sub in owned]
    spec += [f":(exclude){path}" for path in cleared]
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
            # HEAD, NOT --all (PR #165 review round 5, major).
            #
            # `--all` is EVERY local ref: unmerged feature branches, remote-
            # tracking refs, tags, the review worktrees. This repo carries dozens
            # of in-flight sana/* branches at any moment. So a blob that never
            # shipped -- one living only on somebody's experiment -- counted as
            # "the skeleton wrote this", and fleet-unblock would commit it over
            # founder content in an instance. The next real sync then overwrites
            # it with what the shipped line actually says, so the founder's bytes
            # are gone and the thing that replaced them was never skeleton
            # content either.
            #
            # HEAD is the line the updater actually syncs from (`git archive
            # HEAD`), and its ancestry is every version this skeleton could
            # legitimately have written into an instance. An unrelated branch is
            # not in that ancestry and now proves nothing.
            #
            # Reproducer: test_a_blob_that_only_exists_on_an_unmerged_branch_is_not_fleet_authored
            # Control:    test_a_blob_on_the_shipped_line_is_still_fleet_authored
            commits = git(self.skeleton, "rev-list", "HEAD", "--", path).split()
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


def audit_instance(entry, owned, skel_blobs, cleared=(), unmodelled=None):
    """One verdict per instance, and the optimistic one is conditional.

    `unmodelled` is the refusal sites this script does not read the input of.
    Non-empty (or None, meaning the caller never established coverage) turns
    the clean answer into UNKNOWN: nothing here looked at those sites, so
    "clean by the guard I model" is the only claim available and WOULD-SYNC is
    a bigger one. None defaults to the pessimistic side on purpose -- an
    optimistic default is exactly the failure this parameter exists to stop.
    """
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

    spec = guard_pathspec(prefix, owned, cleared)
    rows = ([(s, p, True) for s, p in name_status(path, spec, cached=True)] +
            [(s, p, False) for s, p in name_status(path, spec, cached=False)])
    if not rows:
        fully_modelled = unmodelled is not None and not unmodelled
        result["verdict"] = "WOULD-SYNC" if fully_modelled else "UNKNOWN"
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
    parser.add_argument(
        "--after", action="store_true",
        help="model the SYSTEM_NEVER_COMMIT untrack migration: report reach "
             "as if those paths were no longer tracked in each instance")
    parser.add_argument(
        "--assume-full-coverage", action="store_true",
        help="pretend every refusal site in kipi-update.sh is modelled here, "
             "so a clean instance reports WOULD-SYNC again. This is the "
             "overclaim of 2026-08-15 and exists only so the divergence test "
             "can provoke it and prove the guard bites. Never use it to read "
             "a reach number.")
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
    cleared = never_commit_paths(updater) if args.after else ()
    if cleared:
        print("MODE: --after, modelling the untrack migration for:")
        for path in cleared:
            print(f"  {path}")
        print()
    unmodelled = [] if args.assume_full_coverage else unmodelled_refusals(updater)
    results = [audit_instance(e, owned, skel_blobs, cleared, unmodelled)
               for e in entries]

    if args.json:
        print(json.dumps(results, indent=2))
        return 0

    order = {"WOULD-SYNC": 0, "UNKNOWN": 1, "BLOCKED-FLEET": 2,
             "BLOCKED-FOUNDER": 3}
    counts = {}
    for row in results:
        counts[row["verdict"]] = counts.get(row["verdict"], 0) + 1

    print(f"registered, skeleton-managed : {len(results)}")
    for verdict in sorted(counts, key=lambda v: order.get(v, 9)):
        print(f"  {verdict:16s} {counts[verdict]}")
    print()

    unknown = counts.get("UNKNOWN", 0)
    if unknown:
        # NOT a bare reach line while anything is unknown. "REACH: 22 of 22"
        # is precisely what got quoted into commits and PR bodies all session
        # on 2026-08-15 while one instance was in fact refused. A reader who
        # takes one line from this output has to take the caveat with it.
        print(f"REACH: {counts.get('WOULD-SYNC', 0)} of {len(results)} would "
              f"sync now; {unknown} cannot tell from here")
    else:
        print(f"REACH: {counts.get('WOULD-SYNC', 0)} of {len(results)} would sync now")
    print()

    if unmodelled:
        # Named, not counted. A count says "trust me less"; the names say which
        # refusal the next reader has to go model to shrink the unknown bucket.
        print(f"UNMODELLED PRECONDITIONS ({len(unmodelled)}) -- any instance "
              "clean by the guard above is UNKNOWN, not green, because none of "
              "these was read:")
        for site in unmodelled:
            print(f"  {site}")
        print()

    for row in sorted(results, key=lambda r: (order.get(r["verdict"], 9), r["name"])):
        if row["verdict"] in ("WOULD-SYNC", "UNKNOWN"):
            continue
        print(f"{row['name']}  [{row['verdict']}]")
        for item in row["blocked_by"]:
            where = "index " if item["staged"] else "wtree "
            print(f"    {item['status']:2s} {where} {item['kind']:14s} {item['path']}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
