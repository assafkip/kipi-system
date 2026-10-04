#!/usr/bin/env python3
"""Refuse a lessons push whose BRANCH carries a path outside the lessons allowlist.

Called by the weekly lessons cloud routine (chief `cloud/lessons-weekly.md`,
step 5) right before `git push`. Exit 0 = every changed path is a lesson or the
ledger. Exit 2 = refused, offending paths on stderr. Exit 3 = the diff could not
be computed (no origin/main, not a repo); the caller stops on any non-zero.

Why a branch diff and not the staged set (sp-368fb6f6): the routine's old check
was `git diff --cached`. On 2026-10-04 the cloud session's own Stop hook
committed `q-system/memory/.sycophancy-monthly-stamp` onto the lessons branch
AFTER that check ran, and it reached PR #515 on this PUBLIC repo. A path that is
already committed is never staged, so the staged check could not see it. This
reads every commit in `origin/main..HEAD`, not the net diff: a file added then
deleted nets to zero in `origin/main...HEAD`, but the push still publishes the
blob, permanently, on a public repo (chief #81 review, major 1).

`--no-renames`: with rename detection a moved file reports only its new name,
so a non-lesson file renamed INTO q-system/lessons/ would hide the deletion of
its old public path. Deletions count as changes: removing a public file is a
publish too.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys

ALLOWED = re.compile(r"^(q-system/lessons/[^/]+\.md|lesson-candidates/\.processed\.json)$")


def changed_paths(base: str, repo: str) -> list[str]:
    out = subprocess.run(
        ["git", "-C", repo, "log", "-m", "--name-only", "--no-renames", "-z", "--pretty=format:",
         f"{base}..HEAD"],
        capture_output=True, check=True,
    ).stdout.decode("utf-8", "surrogateescape")
    return sorted({p.strip("\n") for p in out.split("\0") if p.strip("\n")})


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", default="origin/main")
    ap.add_argument("--repo", default=".")
    a = ap.parse_args(argv)
    try:
        paths = changed_paths(a.base, a.repo)
    except (subprocess.CalledProcessError, OSError) as e:
        err = getattr(e, "stderr", b"") or b""
        print(f"lessons-push-guard: cannot diff {a.base}...HEAD: "
              f"{err.decode(errors='replace').strip() or e}", file=sys.stderr)
        return 3
    bad = [p for p in paths if not ALLOWED.match(p)]
    if bad:
        print(f"REFUSED: {len(bad)} path(s) on this branch are outside the lessons allowlist:",
              file=sys.stderr)
        for p in bad:
            print(f"  {p}", file=sys.stderr)
        return 2
    print(f"lessons-push-guard: ok, {len(paths)} path(s), all lessons or the ledger")
    return 0


if __name__ == "__main__":
    sys.exit(main())
