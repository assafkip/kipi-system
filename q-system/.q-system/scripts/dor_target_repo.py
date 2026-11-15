#!/usr/bin/env python3
"""Does an issue's DoR scope its files to a repo this worker is not running in?

ASK-4899. The worker cuts every issue worktree from $TARGET_REPO, which comes
only from `--repo` or $KIPI_TARGET_REPO and is never derived from the issue
(linear-worker.sh L423, L3184). An issue whose DoR scopes its allowed files to a
different repo is handed a worktree where none of those files exist, the harness
working-directory pin makes the real target unreachable, and the issue burns a
dispatch through no fault of its DoR. Measured on ASK-4323 (2026-11-14) and
again on ASK-4899 itself (2026-11-15).

This module answers one question and takes no action: given an issue body, the
repo the worker is running in, and the set of repo names that exist, does the
DoR name a repo and is that repo somewhere else? The picker refuses on a
mismatch BEFORE a worktree is cut and before the claim, which is the whole point
-- a refusal after the claim has already spent the dispatch it was meant to save.

WHY A REPO NAME AND NOT A PATH PREFIX
-------------------------------------
sp-a1ad6a51 proposed deriving the target from "the DoR allowed-files prefix".
That cannot work, and the reason is worth keeping: `q-system/.q-system/scripts/`
exists in kipi-system AND in every instance created from it, so a prefix is
ambiguous by construction and would route half the fleet's issues to the wrong
repo with full confidence. The only unambiguous signal a DoR carries is the repo
NAME its Files section already writes out, e.g.

    * `q-system/.q-system/scripts/linear-worker.sh` (in `kipi-system`) -- ...

so that name, resolved against the repo names that actually exist, is what this
reads.

NO HARDCODED ALLOWLIST. `known_repos` is passed in by the caller from
instance-registry.json plus the skeleton project name. A hardcoded allowlist
would refuse client engagement repos and break RULE-2026-10-30-A, which is the
blast radius the DoR names explicitly.

HONEST BOUNDARY
---------------
1. ABSENCE OF A SIGNAL IS NOT A MISMATCH. No Files section, or a Files section
   naming no known repo, returns None -> the caller proceeds exactly as it does
   today. Most issues are not promoted spillover and must not regress. This is
   the fail-open direction on purpose: too strict here is a silent full stop on
   autonomous throughput, which is worse than the burn it would prevent.
2. It reads the FILES SECTION ONLY, not the whole body. A repo named in prose
   ("the ktlyst-saas-product instance is stale") is not a scope declaration, and
   treating it as one would refuse issues whose DoR merely mentions a sibling.
3. It cannot tell a CORRECT repo name from a TYPO. An unrecognised word is
   treated as no signal (boundary 1), never as a mismatch.
4. It proves nothing about whether the named repo is reachable. That is the
   caller's problem and a separate failure.
"""

import argparse
import json
import re
import sys

# The DoR headings that open and close the Files block. The drafter writes
# `**Files:**`; the closers are every other bold heading it emits, plus a
# markdown rule. Kept as data so a new heading is a one-line change.
_FILES_HEADING = re.compile(r"^\s*\*\*Files:?\*\*", re.MULTILINE)
_SECTION_END = re.compile(
    r"^\s*(?:\*\*[A-Z][^*]*:?\*\*|---\s*$|##\s)",
    re.MULTILINE,
)


def files_section(body):
    """The text of the DoR's Files block, or "" when the body has none.

    Returns "" rather than the whole body on purpose: falling back to the body
    would make boundary 2 above collapse and every passing mention of a sibling
    repo would read as a scope declaration.
    """
    if not body:
        return ""
    opened = _FILES_HEADING.search(body)
    if not opened:
        return ""
    rest = body[opened.end():]
    closed = _SECTION_END.search(rest)
    return rest[: closed.start()] if closed else rest


def named_repos(body, known_repos):
    """Every known repo name the Files section names, as a set.

    Matched on word boundaries so `product` does not match `products` and a
    longer name is not shadowed by a shorter one it contains.
    """
    section = files_section(body)
    if not section:
        return set()
    found = set()
    for repo in known_repos:
        if not repo:
            continue
        if re.search(r"(?<![\w-])" + re.escape(repo) + r"(?![\w-])", section):
            found.add(repo)
    return found


def mismatch(body, launch_repo, known_repos):
    """None when the worker may proceed; a one-line reason when it must not.

    Proceeds (returns None) when the Files section names no known repo, or when
    it names the repo the worker is running in. Refuses only when every repo it
    names is a known repo and none of them is the launch repo -- the one case
    where the files provably do not exist in the tree about to be cut.
    """
    if not launch_repo:
        # Nothing to compare against. Fail open (boundary 1).
        return None
    found = named_repos(body, known_repos)
    if not found or launch_repo in found:
        return None
    targets = ", ".join(sorted(found))
    return (
        f"DoR scopes its files to {targets}, but this worker runs in "
        f"{launch_repo}. No scoped file exists in the tree that would be cut, "
        f"so the dispatch would be spent on an unreachable target. "
        f"Re-dispatch with --repo pointed at {targets}."
    )


def _known_from_registry(path, skeleton_project):
    """Repo names from instance-registry.json plus the skeleton's own name.

    Tolerant by design: an unreadable or malformed registry yields whatever is
    known (possibly just the skeleton), and the caller then sees "no signal" and
    proceeds. A registry outage must not become a fleet-wide refusal.
    """
    known = set()
    if skeleton_project:
        known.add(skeleton_project)
    if not path:
        return known
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return known
    rows = data.get("instances") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        return known
    for row in rows:
        if isinstance(row, dict):
            for key in ("project", "name", "slug"):
                if row.get(key):
                    known.add(str(row[key]))
    return known


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--body-file", required=True, help="file holding the issue body")
    ap.add_argument("--launch-repo", required=True, help="repo the worker runs in")
    ap.add_argument("--known", default="", help="comma-separated known repo names")
    ap.add_argument("--registry", default="", help="instance-registry.json path")
    ap.add_argument("--skeleton-project", default="", help="skeleton repo name")
    args = ap.parse_args(argv)

    with open(args.body_file, encoding="utf-8") as fh:
        body = fh.read()

    known = {n.strip() for n in args.known.split(",") if n.strip()}
    known |= _known_from_registry(args.registry, args.skeleton_project)

    reason = mismatch(body, args.launch_repo, known)
    if reason:
        print(reason)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
