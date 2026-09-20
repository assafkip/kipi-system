#!/usr/bin/env python3
"""covers-lint.py -- a declared `covers` glob must match a tracked file (ASK-1918).

PAIRS WITH: the `covers` key on a `q-system/.q-system/capability/expected_tests/*.json`
fragment, read by change-size.py's read_declared(). No skill; this is the
deterministic half of a declaration, per skill-hook-pairing.md's decision rule
(a glob either matches a tracked path or it does not -- that is a file
inspection, so it gets a hook rather than a judgement).

WHY IT HAS TO EXIST. `covers` takes a test OFF the always-run floor. That is the
whole point and it is also the whole danger: a scanner that declared
`**/*.plst` would stop running on every diff and start running on none, and
nothing else in the system would notice, because a test that is never selected
is indistinguishable from a test that is never needed. The floor was the thing
keeping an untyped guess safe; once a fragment can opt out of it, the opt-out
needs a check that can fail.

What it checks, per fragment that declares `covers`:
  1. `covers` is a list of non-empty strings.
  2. every glob matches at least one path in `git ls-files`.
  3. the declaring test is one change-size.py calls a SCANNER. A `covers` on a
     non-scanner is inert (change-size.py ignores it), so a fragment carrying
     one is a misunderstanding worth naming rather than silently dropping.

EXIT: 0 clean, 2 a declaration is wrong (blocks, per the PostToolUse contract).

Usage:  covers-lint.py [--repo-root .] [paths...]
        With paths, only fragments among them are checked (hook mode). With
        none, every fragment is checked (sweep mode, for CI).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

FRAG_DIR = "q-system/.q-system/capability/expected_tests"


def load_classifier(root: Path):
    spec = importlib.util.spec_from_file_location(
        "kipi_change_size", root / "q-system/.q-system/scripts/change-size.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def tracked_paths(root: Path) -> list[str]:
    r = subprocess.run(["git", "-C", str(root), "ls-files"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"git ls-files: {r.stderr.strip()[:200]}")
    return r.stdout.splitlines()


def check(root: Path, frags: list[Path]) -> list[str]:
    cs = load_classifier(root)
    paths = tracked_paths(root)
    problems = []
    for frag in frags:
        rel_frag = frag.relative_to(root) if frag.is_absolute() else frag
        try:
            entry = json.loads(Path(root / rel_frag).read_text())
        except (OSError, ValueError) as exc:
            problems.append(f"{rel_frag}: cannot read ({exc})")
            continue
        if "covers" not in entry:
            continue
        pats = entry["covers"]
        if not isinstance(pats, list) or not pats:
            problems.append(f"{rel_frag}: `covers` must be a non-empty list of globs, got {pats!r}. "
                            "Remove the key to keep the test on the always-run floor.")
            continue
        test_rel = entry.get("path", "")
        full = root / test_rel
        if not test_rel or not full.is_file():
            problems.append(f"{rel_frag}: declares `covers` but its `path` {test_rel!r} is not a file")
            continue
        if not cs.scans_the_tree(full.read_text(errors="ignore")):
            problems.append(
                f"{rel_frag}: `covers` is INERT here -- change-size.py does not call "
                f"{test_rel} a scanner, and `covers` only ever takes a scanner OFF the "
                "always-run floor. It never selects. Remove the key.")
            continue
        for p in pats:
            if not isinstance(p, str) or not p:
                problems.append(f"{rel_frag}: glob {p!r} is not a non-empty string")
                continue
            if not any(cs.covers_matches(p, path) for path in paths):
                problems.append(
                    f"{rel_frag}: glob {p!r} matches no tracked file. A glob that matches "
                    f"nothing silently narrows {test_rel} to never running. Fix the glob, "
                    "or remove `covers` to put the test back on the floor.")
    return problems


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("paths", nargs="*")
    args = ap.parse_args(argv)
    root = Path(args.repo_root).resolve()

    if args.paths:
        frags = [Path(p) for p in args.paths
                 if FRAG_DIR in str(p).replace("\\", "/") and str(p).endswith(".json")]
        if not frags:
            return 0                      # fast-exit: nothing in scope (token discipline)
        frags = [p if p.is_absolute() else root / p for p in frags]
        frags = [p for p in frags if p.is_file()]
    else:
        frags = sorted((root / FRAG_DIR).glob("*.json"))

    try:
        problems = check(root, frags)
    except (RuntimeError, OSError) as exc:
        print(f"covers-lint: could not check ({exc})", file=sys.stderr)
        return 2
    if problems:
        print("covers-lint: a coverage declaration is wrong (ASK-1918)", file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        return 2
    declared = sum(1 for f in frags if "covers" in json.loads(f.read_text()))
    print(f"covers-lint: PASS -- {declared} of {len(frags)} checked fragment(s) declare coverage")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
