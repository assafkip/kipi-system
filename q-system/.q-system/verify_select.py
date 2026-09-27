#!/usr/bin/env python3
"""Pick the test files that own a staged change, for verify.sh --staged (ASK-1795).

Why this exists: verify.sh --staged used to run a manifest suite IN FULL whenever
any staged path sat under it. In the consulting instance that meant every commit
touching q-consult/ ran ~6300 tests, 620s and 788s measured on 2026-09-18. The
founder asked twice the same day for the pre-commit door to stop running every
test for every change. A 10-minute pre-commit is the hook people bypass, and a
bypassed floor protects nothing.

Pre-push and CI still run `verify.sh --full`, so nothing reaches main untested.
This narrows the FASTEST door only.

Selection, per staged path under the suite:
  (a) a staged test file selects itself
  (b) a staged .py module selects every test file that names it (\\bstem\\b,
      or the package name for an __init__.py)
  (c) a staged non-.py file selects every test file that names its basename
  (d) a staged path that owns NO test falls back to the DECLARED fallback:
      `<suite>/.verify-fallback` (one test path per line, relative to the
      suite) if that file exists, else the WHOLE suite. Never nothing: a
      selection that silently comes back empty is a check that cannot fail
      looking like one that passed.
  A staged pytest config file (conftest.py, pytest.ini, pyproject.toml,
  setup.cfg, tox.ini) changes how EVERY test runs, so it selects the full suite.

Known limit, stated so nobody reads more into a green: ownership is by NAME, one
hop. A test that reaches a staged module only through another module is not
selected. --full at pre-push is what catches that.

Protocol (read by verify.sh):
  stdin   the staged paths, repo-relative, one per line (deletions included:
          a deleted module still selects the tests that name it)
  stdout  line 1 `full` or `select`; for `select`, the chosen test paths
          relative to the suite dir, one per line
  stderr  one human line per staged path saying what it selected and why
  exit    0 always on a decision; 2 on a usage error (verify.sh then runs the
          full suite, so a broken selector costs time, never coverage)
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys

CONFIG_NAMES = {"conftest.py", "pytest.ini", "pyproject.toml", "setup.cfg", "tox.ini"}
FALLBACK_FILE = ".verify-fallback"


def is_test_file(path: str) -> bool:
    base = os.path.basename(path)
    return base.endswith(".py") and (base.startswith("test_") or base.endswith("_test.py"))


def tracked_tests(target: str, suite: str) -> list[str]:
    """Test files git tracks under the suite, relative to the suite dir.

    From git, not os.walk: in --staged the target IS a git worktree of the
    snapshot, so this is exactly what the commit contains, and it never walks
    an untracked output/ tree of thousands of files.
    """
    r = subprocess.run(
        ["git", "-C", target, "ls-files", "-z", "--", suite],
        capture_output=True, text=True, check=True,
    )
    prefix = suite.rstrip("/") + "/"
    out = []
    for p in r.stdout.split("\0"):
        if p.startswith(prefix) and is_test_file(p):
            out.append(p[len(prefix):])
    return sorted(out)


def names_for(rel: str, suite: str = "") -> tuple[str, re.Pattern[str]]:
    """The name a test would use to reach this path, and the pattern that finds it."""
    base = os.path.basename(rel)
    if base.endswith(".py"):
        stem = base[:-3]
        if stem == "__init__":
            # The package this file IS. At the suite root the path is bare
            # "__init__.py" and dirname is empty, so the name is the suite's own
            # basename. Reviewer finding on PR #371: without this,
            # voiceloop/__init__.py matched the literal "__init__" and selected
            # 1 test file where all 10 name `voiceloop`.
            parent = os.path.basename(os.path.dirname(rel)) or os.path.basename(suite.rstrip("/"))
            stem = parent or stem
        return stem, re.compile(r"\b" + re.escape(stem) + r"\b")
    # A data file is named by its basename. Word-ish edges so `a.json` does not
    # match inside `data.json`.
    return base, re.compile(r"(?<![\w.-])" + re.escape(base) + r"(?![\w-])")


def read_fallback(target: str, suite: str, tests: list[str]) -> list[str] | None:
    path = os.path.join(target, suite, FALLBACK_FILE)
    if not os.path.isfile(path):
        return None
    wanted = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.split("#", 1)[0].strip()
            if line:
                wanted.append(line)
    present = [w for w in wanted if w in set(tests)]
    # A declared fallback that names nothing runnable is not a fallback. Treat
    # it as absent so the full suite runs instead of an empty selection.
    return present or None


def select(target: str, suite: str, staged: list[str]) -> tuple[str, list[str], list[str]]:
    prefix = suite.rstrip("/") + "/"
    in_suite = [p[len(prefix):] for p in staged if p.startswith(prefix)]
    why: list[str] = []
    if not in_suite:
        return "full", [], ["no staged path under the suite; running it in full"]

    for rel in in_suite:
        if os.path.basename(rel) in CONFIG_NAMES:
            return "full", [], [f"{rel}: pytest config changes every test -> full suite"]

    tests = tracked_tests(target, suite)
    test_set = set(tests)
    texts: dict[str, str] = {}

    def text_of(t: str) -> str:
        if t not in texts:
            try:
                with open(os.path.join(target, suite, t), encoding="utf-8", errors="replace") as fh:
                    texts[t] = fh.read()
            except OSError:
                texts[t] = ""
        return texts[t]

    chosen: set[str] = set()
    unowned: list[str] = []
    for rel in in_suite:
        if is_test_file(rel):
            if rel in test_set:
                chosen.add(rel)
                why.append(f"{rel}: staged test file -> itself")
            else:
                # A deleted test file cannot run; the tests that remain are
                # still graded by whatever else is staged, and by --full.
                why.append(f"{rel}: test file deleted -> nothing to run for it")
            continue
        name, pat = names_for(rel, suite)
        owners = [t for t in tests if t != rel and pat.search(text_of(t))]
        if owners:
            chosen.update(owners)
            why.append(f"{rel}: named as '{name}' by {len(owners)} test file(s)")
        else:
            unowned.append(rel)
            why.append(f"{rel}: no test names '{name}' -> fallback")

    if unowned or not chosen:
        fb = read_fallback(target, suite, tests)
        if fb is None:
            why.append(f"fallback: no {FALLBACK_FILE} declared in {suite} -> full suite")
            return "full", [], why
        chosen.update(fb)
        why.append(f"fallback: {len(fb)} test file(s) from {suite}/{FALLBACK_FILE}")

    return "select", sorted(chosen), why


# --- the pytest side: verify.sh copies this file into a private dir and loads it
# with `-p _kipi_verify_select`, so pytest still runs FROM THE SUITE DIR with no
# file arguments.
#
# why not `pytest file1 file2 ...`: explicit file arguments bypass conftest
# `collect_ignore`. Measured on pytest 9.0.3: a file listed in collect_ignore and
# passed as an argument ran and failed. consulting's automation/conftest.py
# ignores test_linear_project_updates.py on purpose, so a staged change naming it
# would have blocked a commit on a test the full suite never runs. Pruning at
# collection keeps rootdir, conftests and collect_ignore identical to --full; the
# only difference is which test modules get imported.
_SELECTED: set[str] | None = None


def _selected() -> set[str] | None:
    global _SELECTED
    if _SELECTED is None:
        listing = os.environ.get("KIPI_VERIFY_SELECT")
        if not listing:
            return None
        with open(listing, encoding="utf-8") as fh:
            _SELECTED = {os.path.realpath(l.strip()) for l in fh if l.strip()}
    return _SELECTED


def pytest_ignore_collect(collection_path, config):  # noqa: ARG001 - pytest hook signature
    sel = _selected()
    if sel is None:
        return None
    p = os.path.realpath(str(collection_path))
    if os.path.isdir(p):
        inside = p.rstrip(os.sep) + os.sep
        # None, never False: this hook is firstresult, and False would stop
        # conftest collect_ignore from ever being consulted.
        return None if any(s.startswith(inside) for s in sel) else True
    # Only TEST modules are pruned. conftest.py and a package __init__.py are
    # machinery pytest needs for the tests that do run.
    if is_test_file(p) and p not in sel:
        return True
    return None


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--target", required=True, help="tree being graded")
    ap.add_argument("--suite", required=True, help="suite dir, relative to target")
    args = ap.parse_args(argv)
    staged = [l.strip() for l in sys.stdin.read().splitlines() if l.strip()]
    mode, files, why = select(args.target, args.suite, staged)
    for line in why:
        print(f"      {line}", file=sys.stderr)
    print(mode)
    for f in files:
        print(f)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
