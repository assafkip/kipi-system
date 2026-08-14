#!/usr/bin/env python3
"""Assert every instance's skeleton-owned files hold bytes origin/main actually shipped.

WHY THIS EXISTS (scar, 2026-08-14, ASK-795 / sp-786f1c4b):
PR #142 fanned prd-os 0.27.1 to the fleet from an UNMERGED feature branch. Eleven
instances were left dirty and refused to sync, which is how anyone noticed. But ten
others had the same unreviewed blob (7f42be38) sitting AT HEAD -- already committed,
so `git status` read clean and not one gate ever complained. The visible half got a
week of attention; the silent half was the more dangerous state and was found only by
hand-diffing blobs across all 23 instances.

The missing control was never "detect a dirty tree". It was: CLEAN IS NOT EVIDENCE OF
CORRECT. Nothing anywhere asserted that an instance's skeleton-owned bytes came from
the skeleton's reviewed history. PR #149's preflight stops the recurrence -- it refuses
to fan from a non-main checkout -- but it is blind to drift already on disk.

THE TEST, and why it is not "does this match current main":
Comparing against the CURRENT skeleton blob attributes nothing on a real fleet.
Instances legitimately lag; a lagging file would flag on every scan and the scan would
be switched off. kipi-update.sh's own `fleet_authored_blob` already settled the honest
question -- "was this content EVER shipped at this path" -- by walking `git rev-list
<ship-ref> -- <path>`. This scanner applies that same rule, but proactively across
every instance instead of only to files a sync happened to find dirty.

Deliberately scoped to origin/main. A blob reachable only from an unmerged branch is
exactly the defect, so searching all refs would have called 7f42be38 legitimate and
reported the whole fleet green. That boundary is the entire point.

READ-ONLY. It opens no instance for writing and never stages, commits, or checks out.
Exit 1 on drift so it can later be wired to an alert; today it is a scan you run.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

# Kept byte-identical in meaning to kipi-update.sh's PLUGIN_COPY_EXCLUDES. A file the
# rsync never copies is not skeleton-owned, so flagging it would be a false positive.
PLUGIN_COPY_EXCLUDE_RE = re.compile(
    r"(^|/)\.git/|(^|/)__pycache__/|\.pyc$|(^|/)\.venv/|(^|/)\.pytest_cache/"
    r"|(^|/)\.env$|(^|/)\.env\."
)

# The flat globs the config sync actually copies. NOT recursive, and not `.claude/`
# wholesale -- widening it here would manufacture alarms about files that never ship
# (settings.local.json, worktrees/), which is how a scan earns its own suppression.
CLAUDE_FLAT_DIRS = ("agents", "output-styles", "rules")


def git(repo: str, *args: str) -> str | None:
    r = subprocess.run(
        ["git", "-C", repo, *args], capture_output=True, text=True
    )
    return r.stdout.strip() if r.returncode == 0 else None


def skeleton_owned_paths(skeleton: str, ship_ref: str) -> list[str]:
    """Every path the fan-out writes, read from the ship ref rather than from disk.

    Reading the working tree would let an uncommitted local file define the audit
    scope, which is the same class of mistake the preflight exists to stop.
    """
    listing = git(skeleton, "ls-tree", "-r", "--name-only", ship_ref) or ""
    paths = []
    for rel in listing.splitlines():
        if rel.startswith("plugins/"):
            parts = rel.split("/", 2)
            if len(parts) < 3:
                continue
            if PLUGIN_COPY_EXCLUDE_RE.search(parts[2]):
                continue
            paths.append(rel)
        elif rel == ".claude/settings.json":
            # DELIBERATELY NOT AUDITED. kipi-update.sh does not copy this file, it
            # MERGES it (kipi-settings-merge.py: "preserves instance customizations",
            # instance-added hooks survive). So an instance's settings.json is a
            # per-instance product that by design equals no skeleton blob -- auditing
            # it flags all 23 instances, forever, on the first run.
            #
            # Measured 2026-08-14 while calibrating this scanner against hand-verified
            # truth: it fired on accountant, an instance remediated and confirmed
            # correct minutes earlier. A detector whose first run cries wolf on every
            # healthy instance gets muted, and then the real drift it exists to catch
            # goes unread too. Drift in the MERGED result needs its own check against
            # the template, which is a different question from provenance.
            continue
        else:
            for scope in CLAUDE_FLAT_DIRS:
                prefix = ".claude/" + scope + "/"
                # Flat glob: the copy is `*.md` at depth 1, so a nested file is not
                # shipped and must not be audited as if it were.
                if rel.startswith(prefix) and "/" not in rel[len(prefix):] \
                        and rel.endswith(".md"):
                    paths.append(rel)
    return paths


class ShippedIndex:
    """Blobs the ship ref ever held at a path. Built lazily; rev-list is the cost."""

    def __init__(self, skeleton: str, ship_ref: str) -> None:
        self.skeleton = skeleton
        self.ship_ref = ship_ref
        self._cache: dict[str, set[str]] = {}

    def ever_shipped(self, rel: str, blob: str) -> bool:
        if rel not in self._cache:
            blobs: set[str] = set()
            commits = git(self.skeleton, "rev-list", self.ship_ref, "--", rel) or ""
            for commit in commits.splitlines():
                b = git(self.skeleton, "rev-parse", f"{commit}:{rel}")
                if b:
                    blobs.add(b)
            self._cache[rel] = blobs
        return blob in self._cache[rel]


def scan_instance(inst: dict, skeleton: str, ship_ref: str, paths: list[str],
                  head_blobs: dict[str, str], index: ShippedIndex) -> list[dict]:
    path = inst["path"]
    findings: list[dict] = []
    if not os.path.isdir(path):
        return [{"instance": inst["name"], "path": "-", "kind": "instance-missing",
                 "detail": path}]

    for rel in paths:
        current = head_blobs.get(rel)
        # The instance's COMMITTED content. Worktree dirt is the dirty-tree guard's
        # job; the silent-ten were clean at worktree AND wrong at HEAD, so HEAD is
        # the half nothing was watching.
        actual = git(path, "rev-parse", f"HEAD:{rel}")
        if actual is None:
            continue  # absent in this instance; the sync will add it
        if actual == current:
            continue  # matches main exactly, the common case, cheap
        if index.ever_shipped(rel, actual):
            findings.append({"instance": inst["name"], "path": rel, "kind": "lag",
                             "detail": actual[:8]})
        else:
            findings.append({"instance": inst["name"], "path": rel, "kind": "DRIFT",
                             "detail": actual[:8]})
    return findings


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--skeleton", default=os.path.dirname(os.path.abspath(__file__)))
    ap.add_argument("--ship-ref", default="origin/main")
    ap.add_argument("--only", action="append", help="instance name (repeatable)")
    ap.add_argument("--show-lag", action="store_true",
                    help="also list files that are merely behind main")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-fetch", action="store_true")
    args = ap.parse_args()

    skeleton = args.skeleton
    registry = os.path.join(skeleton, "instance-registry.json")
    if not os.path.exists(registry):
        print(f"ABORT: no instance-registry.json at {skeleton}", file=sys.stderr)
        return 2

    if not args.no_fetch:
        # Fail closed. An unproven ship ref cannot answer "was this ever shipped",
        # and guessing green is worse than refusing.
        if git(skeleton, "fetch", "origin", "main", "--quiet") is None:
            print("ABORT: could not fetch origin/main; cannot prove provenance",
                  file=sys.stderr)
            return 2

    if git(skeleton, "rev-parse", "--verify", args.ship_ref) is None:
        print(f"ABORT: ship ref {args.ship_ref} does not resolve", file=sys.stderr)
        return 2

    paths = skeleton_owned_paths(skeleton, args.ship_ref)
    head_blobs: dict[str, str] = {}
    listing = git(skeleton, "ls-tree", "-r", args.ship_ref) or ""
    for line in listing.splitlines():
        meta, _, rel = line.partition("\t")
        bits = meta.split()
        if len(bits) >= 3:
            head_blobs[rel] = bits[2]

    with open(registry) as fh:
        instances = json.load(fh)["instances"]
    if args.only:
        instances = [i for i in instances if i["name"] in set(args.only)]

    index = ShippedIndex(skeleton, args.ship_ref)
    findings: list[dict] = []
    for inst in instances:
        findings.extend(
            scan_instance(inst, skeleton, args.ship_ref, paths, head_blobs, index)
        )

    drift = [f for f in findings if f["kind"] == "DRIFT"]
    missing = [f for f in findings if f["kind"] == "instance-missing"]
    lag = [f for f in findings if f["kind"] == "lag"]

    if args.json:
        print(json.dumps({"drift": drift, "lag": lag, "missing": missing}, indent=2))
    else:
        print(f"fleet-drift-scan: {len(instances)} instance(s), "
              f"{len(paths)} skeleton-owned path(s), ship ref {args.ship_ref}")
        for f in missing:
            print(f"  MISSING  {f['instance']}: {f['detail']}")
        if args.show_lag:
            for f in lag:
                print(f"  lag      {f['instance']:22} {f['path']} ({f['detail']})")
        for f in drift:
            print(f"  DRIFT    {f['instance']:22} {f['path']} (blob {f['detail']} "
                  f"was never shipped at this path)")
        print(f"  summary: {len(drift)} drift, {len(lag)} lag, {len(missing)} missing")
        if drift:
            print("\nDRIFT means the instance committed bytes origin/main never "
                  "shipped at that path.\nThat is unreviewed content living in a "
                  "repo that reports clean.")

    return 1 if drift else 0


if __name__ == "__main__":
    sys.exit(main())
