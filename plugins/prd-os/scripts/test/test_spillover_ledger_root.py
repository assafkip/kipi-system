#!/usr/bin/env python3
"""Reproducer for sp-bc42f1d3 / sp-10ea7b66: the spillover ledger was per-worktree.

Pairs with `_ledger_root()` / `_spillover_path()` in prd_runner.py.

WHY THIS TEST HAS TEETH. The buggy `_ledger_root` wraps its git lookup in
`except Exception`, so ANY failure inside it -- including the NameError from a
missing `import subprocess` that the first cut of the fix really had -- returns
repo_root silently. A test that only asserted "the function returns a path"
would pass against a completely inert fix. So case 2 asserts the worktree and
the main checkout resolve to the SAME ledger, which is false for every failure
mode of the lookup.

Run: python3 test_spillover_ledger_root.py
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
SCRIPTS = HERE.parent
sys.path.insert(0, str(SCRIPTS))

PASS, FAIL = [], []


def ok(msg):
    PASS.append(msg)
    print("  PASS: %s" % msg)


def bad(msg):
    FAIL.append(msg)
    print("  FAIL: %s" % msg)


def git(args, cwd):
    return subprocess.run(["git"] + args, cwd=str(cwd), capture_output=True, text=True)


def main():
    import prd_runner

    tmp = pathlib.Path(tempfile.mkdtemp())
    main_repo = tmp / "mainrepo"
    main_repo.mkdir()

    # A real repo, because the thing under test asks git a question. A mocked
    # git would let the fix pass while the real command it runs is wrong.
    git(["init", "-q", "-b", "main"], main_repo)
    git(["config", "user.email", "t@example.com"], main_repo)
    git(["config", "user.name", "t"], main_repo)
    (main_repo / "README.md").write_text("x\n")
    git(["add", "-A"], main_repo)
    git(["commit", "-qm", "init"], main_repo)

    wt = tmp / "wt-a"
    r = git(["worktree", "add", "-q", "-b", "feature", str(wt)], main_repo)
    if r.returncode != 0:
        print("cannot create a worktree, cannot test the defect: %s" % r.stderr.strip())
        return 1

    print("== 1. the main checkout resolves to its own root ==")
    main_root = prd_runner._ledger_root(main_repo)
    if pathlib.Path(main_root).resolve() == main_repo.resolve():
        ok("main checkout resolves to itself")
    else:
        bad("main checkout resolved to %s, expected %s" % (main_root, main_repo))

    print()
    print("== 2. THE DEFECT: a worktree must resolve to the MAIN checkout ==")
    # The assertion the buggy version fails, and that every silent-failure mode
    # of the git lookup (NameError, missing git, timeout) also fails.
    prd_runner._SPILLOVER_ROOT_CACHE.clear()
    wt_root = prd_runner._ledger_root(wt)
    if pathlib.Path(wt_root).resolve() == main_repo.resolve():
        ok("worktree resolves to the main checkout (%s)" % main_repo.name)
    else:
        bad("THE DEFECT: worktree resolved to %s, so it would keep a PRIVATE ledger "
            "invisible to the gate (expected %s)" % (wt_root, main_repo))

    print()
    print("== 3. a capture filed from the worktree lands in ONE ledger ==")

    class Cfg:
        pass

    cfg_main, cfg_wt = Cfg(), Cfg()
    cfg_main.repo_root = main_repo
    cfg_wt.repo_root = wt
    prd_runner._SPILLOVER_ROOT_CACHE.clear()
    p_main = prd_runner._spillover_path(cfg_main)
    prd_runner._SPILLOVER_ROOT_CACHE.clear()
    p_wt = prd_runner._spillover_path(cfg_wt)
    if pathlib.Path(p_main).resolve() == pathlib.Path(p_wt).resolve():
        ok("both roots yield the same ledger path")
    else:
        bad("two ledgers: main=%s worktree=%s" % (p_main, p_wt))

    print()
    print("== 4. a non-git directory still gets a usable ledger (no lost capture) ==")
    plain = tmp / "plain"
    plain.mkdir()
    prd_runner._SPILLOVER_ROOT_CACHE.clear()
    plain_root = prd_runner._ledger_root(plain)
    # Outside a repo git answers about tmp's own repo or fails; either way the
    # contract is that a capture is never LOST, so a path must come back.
    if plain_root is not None and str(plain_root):
        ok("non-git directory falls back to a real path (%s)" % plain_root)
    else:
        bad("non-git directory produced no ledger root, so a capture would be lost")

    print()
    print("== 5. the lookup is cached, so the gate does not shell git per row ==")
    prd_runner._SPILLOVER_ROOT_CACHE.clear()
    prd_runner._ledger_root(wt)
    if str(wt) in prd_runner._SPILLOVER_ROOT_CACHE:
        ok("result cached per repo_root")
    else:
        bad("no cache entry: `gates run` would shell out once per ledger read")

    print()
    print("-------- %d passed, %d failed --------" % (len(PASS), len(FAIL)))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
