#!/usr/bin/env python3
"""Every test file is EXECUTED BY A GATE, or it is named in the baseline.

THE PREDICATE, STATED EXACTLY, because a looser word here is the same defect
this file exists to catch. "Reached" is measured as: declared in
expected_tests/, OR named by a pytest/python3 invocation in .github/workflows/,
OR under a directory a CI step runs wholesale. That is the set of ways a test
can fail a merge.

It is NOT the same as "collects under pytest". A bare root `pytest` collects
plenty that CI never runs -- the four voiceloop suites collect 84 tests and
gate nothing. Reachable and never reached is the shape that survives a casual
audit: someone greps, sees them collect, and moves on. So the baselined entries
are not dead code and must not be deleted on sight; the fix for one is almost
always to DECLARE it, which is why the file that lists them says so in its own
header.

THE GAP THIS CLOSES. The capability gate answers one direction: a test DECLARED
in the manifest must actually execute (that is the silent-absence gate,
prd-silent-absence-capability-gate-2026-07-23, and it works). Nothing answered
the other direction: a test file that is present, green, and declared NOWHERE.

Measured on main at 569b0ec0: 176 tracked `test_*.py`, 108 of them undeclared.
Ten of those, all in `q-system/.q-system/tests/`, were executed by nothing that
gates a merge -- not the manifest, not a CI pytest path, not the separation
harness. They pass. 174 assertions, green, and no run that could go red on
them. A capability gate whose whole job is
catching a check that does not run could not see ten whole files of them,
because it only ever looked at what someone had already declared.

WHY A BASELINE AND NOT A BLANKET RULE. Failing on all 108 would paint the gate
red on its own population the day it shipped, and a gate that is red by default
gets switched off -- the same reason 39 of 57 existing plans are grandfathered
in plan-lint. So the unreached set is FROZEN here and allowed only to shrink:

  - a NEW unreached test file fails the check (the hole cannot reopen)
  - a baseline entry that is now reached ALSO fails, demanding its removal, so
    the file cannot rot into a list of names nobody prunes

WHAT "REACHED" MEANS, precisely, because a vague predicate is how the first gate
went blind: reached = declared in expected_tests/, OR named/prefixed by a pytest
or python3 invocation in .github/workflows/, OR under a directory a CI step runs
wholesale. Nothing here claims a reached test is a GOOD test. It claims only
that some runner would notice if it started failing.
"""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

MANIFEST_DIR = "q-system/.q-system/capability/expected_tests"
BASELINE = "q-system/.q-system/test-reachability-baseline.json"
WORKFLOWS = ".github/workflows"

# A path-shaped token in a CI run: step, and the runner that would execute it.
_RUNNER_LINE = re.compile(r"(?:pytest|python3\s+-m\s+pytest|python3|bash)\s+([^\n]*)")
_PATHISH = re.compile(r"^[A-Za-z0-9_.\-/]+$")


def tracked_tests(root):
    out = subprocess.run(["git", "-C", str(root), "ls-files"],
                         capture_output=True, text=True, check=True).stdout.split()
    return sorted(f for f in out
                  if os.path.basename(f).startswith("test_") and f.endswith(".py"))


def declared_paths(root):
    d = root / MANIFEST_DIR
    if not d.is_dir():
        return set()
    paths = set()
    for f in sorted(d.glob("*.json")):
        try:
            paths.add(json.loads(f.read_text())["path"])
        except (ValueError, KeyError):
            continue  # a malformed fragment is the capability gate's problem, not ours
    return paths


def ci_targets(root):
    """Path prefixes any workflow hands to a test runner.

    Comment lines are stripped first. A commented-out `pytest <dir>` is exactly
    the shape that would make this check claim coverage that does not run --
    verify.yml carries one in a comment today.
    """
    d = root / WORKFLOWS
    targets = set()
    if not d.is_dir():
        return targets
    for wf in sorted(list(d.glob("*.yml")) + list(d.glob("*.yaml"))):
        for raw in wf.read_text().splitlines():
            line = raw.split("#", 1)[0]
            for m in _RUNNER_LINE.finditer(line):
                for tok in m.group(1).split():
                    if tok.startswith("-") or not _PATHISH.match(tok):
                        continue
                    if "/" in tok and (root / tok).exists():
                        targets.add(tok.rstrip("/"))
    return targets


def separation_targets(root):
    """validate-separation.py runs the separation suite wholesale."""
    if (root / "validate-separation.py").exists():
        return {"q-system/.q-system/tests/separation"}
    return set()


def reached(path, declared, targets):
    if path in declared:
        return True
    for t in targets:
        if path == t or path.startswith(t.rstrip("/") + "/"):
            return True
    return False


def load_baseline(root):
    p = root / BASELINE
    if not p.exists():
        return None
    return json.loads(p.read_text())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--write-baseline", action="store_true",
                    help="freeze the CURRENT unreached set (bootstrap only)")
    args = ap.parse_args()
    root = Path(args.repo_root).resolve()

    declared = declared_paths(root)
    targets = ci_targets(root) | separation_targets(root)
    tests = tracked_tests(root)
    unreached = [t for t in tests if not reached(t, declared, targets)]

    if args.write_baseline:
        (root / BASELINE).write_text(json.dumps(
            {"_what_this_list_is":
                 "Test files that NO GATE EXECUTES: not declared in "
                 "q-system/.q-system/capability/expected_tests/, and not named "
                 "or covered by any pytest/python3 invocation in "
                 ".github/workflows/. Several of them PASS and several collect "
                 "fine under a bare root `pytest` -- they are live tests that "
                 "gate nothing, NOT dead code.",
             "_how_to_remove_an_entry":
                 "Declare the file in expected_tests/ (or add it to a CI step), "
                 "and delete its path from this array in the SAME change. "
                 "reachability-check.py fails while a listed file has become "
                 "reached, which is how this list drains instead of rotting. "
                 "Deleting the TEST FILE is almost never the right move: check "
                 "whether it passes first.",
             "_why": "This set may only SHRINK. A new unreached test fails the "
                     "check. See reachability-check.py.",
             "unreached": unreached}, indent=1) + "\n")
        print(f"baseline written: {len(unreached)} unreached test files frozen")
        return 0

    base = load_baseline(root)
    if base is None:
        print(f"reachability-check: no baseline at {BASELINE}", file=sys.stderr)
        print("  bootstrap it with --write-baseline", file=sys.stderr)
        return 1
    frozen = set(base.get("unreached", []))

    new = sorted(set(unreached) - frozen)
    stale = sorted(frozen - set(unreached))
    # A baseline naming a file that no longer exists is also stale.
    gone = sorted(f for f in stale if not (root / f).exists())
    fixed = [f for f in stale if f not in gone]

    if not new and not stale:
        print(f"reachability-check: OK ({len(tests)} test files, "
              f"{len(frozen)} baselined as executed by no gate, 0 new)")
        return 0

    rc = 0
    if new:
        rc = 2
        print("reachability-check: FAIL -- new test file that no gate executes:",
              file=sys.stderr)
        for f in new:
            print(f"  {f}", file=sys.stderr)
        print("  Declare it in %s (one JSON fragment: path + runner)," % MANIFEST_DIR,
              file=sys.stderr)
        print("  or add it to a CI step. A test nothing runs cannot fail.",
              file=sys.stderr)
    if fixed:
        rc = rc or 2
        print("reachability-check: FAIL -- baselined file is now reached; "
              "remove it from the baseline:", file=sys.stderr)
        for f in fixed:
            print(f"  {f}", file=sys.stderr)
    if gone:
        rc = rc or 2
        print("reachability-check: FAIL -- baseline names a file that no longer "
              "exists:", file=sys.stderr)
        for f in gone:
            print(f"  {f}", file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main())
