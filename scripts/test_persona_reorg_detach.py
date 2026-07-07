#!/usr/bin/env python3
"""Integration tests for persona-reorg.py's detach/promote-to-standalone path.

Reproducer-first (fable-discipline): builds a HERMETIC throwaway git repo in a
tempfile dir — main repo + a linked worktree on a branch — and exercises the real
git detach. Isolation is the whole point: every path is under TemporaryDirectory,
never a live fleet path (that is the graded-good "verify against a copy" habit the
fable-discipline lint enforces).

The two checks that matter:
  * 2.2 KILLER: the standalone clone still works AFTER the source repo is deleted.
  * 2.5 GUARD: salvage_check flags a file that lives only on the old line (would be
    lost by archiving) — the negative self-test.

Run: python3 scripts/test_persona_reorg_detach.py   (exit 0 = pass)
"""
import importlib.util as ilu
import os
import shutil
import subprocess
import sys
import tempfile

_PR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "persona-reorg.py")
_spec = ilu.spec_from_file_location("persona_reorg", _PR)
pr = ilu.module_from_spec(_spec)
_spec.loader.exec_module(pr)

FAILS = []


def check(name, cond):
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    if not cond:
        FAILS.append(name)


def git(cwd, *args):
    """Run git in a hermetic repo with test identity (no dependence on global config)."""
    return subprocess.run(
        ["git", "-C", cwd, "-c", "user.email=test@test", "-c", "user.name=test",
         "-c", "commit.gpgsign=false", *args],
        capture_output=True, text=True)


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


def build_fixture(root):
    """main repo on `main` + a linked worktree on branch `successor`.
    Mirrors product (old, main) + product-baseline (successor worktree)."""
    main_repo = os.path.join(root, "product")            # 'product' == old line, git main
    os.makedirs(main_repo)
    git(main_repo, "init", "-q", "-b", "main")
    # local identity so the production detach's internal commit (which uses the
    # repo's own config, not the test's -c flags) works in this hermetic repo
    git(main_repo, "config", "user.email", "test@test")
    git(main_repo, "config", "user.name", "test")
    git(main_repo, "config", "commit.gpgsign", "false")
    write(os.path.join(main_repo, "shared.py"), "# shared history\n")
    git(main_repo, "add", "-A"); git(main_repo, "commit", "-q", "-m", "base")
    # a real product file that lives ONLY on old main (the salvage-check target)
    write(os.path.join(main_repo, "old_only.py"), "# stranded on the old line\n")
    # a SKELETON file synced onto main after the fork (must be SKIPPED by salvage)
    write(os.path.join(main_repo, "q-system", "synced.md"), "# skeleton sync, re-heals\n")
    git(main_repo, "add", "-A"); git(main_repo, "commit", "-q", "-m", "old-only + skeleton sync")
    # the successor branch forks BEFORE old_only, then diverges
    git(main_repo, "branch", "successor", "HEAD~1")
    wt = os.path.join(root, "product-baseline")          # the successor worktree
    git(main_repo, "worktree", "add", "-q", wt, "successor")
    write(os.path.join(wt, "v5_feature.py"), "# the real successor work\n")
    git(wt, "add", "-A"); git(wt, "commit", "-q", "-m", "v5 successor feature")
    # leave one uncommitted change in the worktree (must be preserved on detach)
    write(os.path.join(wt, "pending.py"), "# in-flight, not yet committed\n")
    return main_repo, wt


def tree_files(repo, ref):
    r = git(repo, "ls-tree", "-r", "--name-only", ref)
    return set(l for l in r.stdout.splitlines() if l.strip())


# --- surface checks (fail loud if the functions are not implemented yet) ---------
for fn in ("promote_worktree_to_standalone", "verify_repo_independent", "salvage_check"):
    check(f"{fn} exists on module", hasattr(pr, fn))
if FAILS:
    print(f"\nFAIL (not implemented yet): {FAILS}")
    sys.exit(1)

work = tempfile.mkdtemp(prefix="persona-detach-test-")
try:
    main_repo, wt = build_fixture(work)

    # 2.5 GUARD (negative self-test): old_only.py lives only on the old main line.
    strands = pr.salvage_check(main_repo, keep_branch="successor", drop_ref="main")
    check("2.5 salvage_check FLAGS a file stranded on the old line",
          any("old_only.py" in s for s in strands))
    # positive: a file on the successor is NOT reported as stranded
    check("2.5 salvage_check does not flag successor-only work",
          not any("v5_feature.py" in s for s in strands))
    # skeleton files re-sync via kipi update — must be SKIPPED (not real loss)
    check("2.5 salvage_check SKIPS skeleton-managed paths (q-system/)",
          not any("q-system/synced.md" in s for s in strands))
    check("2.5 include_skeleton=True DOES see the skeleton delta",
          any("q-system/synced.md" in s
              for s in pr.salvage_check(main_repo, keep_branch="successor",
                                        drop_ref="main", include_skeleton=True)))

    # promote the successor worktree into a standalone repo
    new_repo = os.path.join(work, "ktlyst-saas-product")
    ok, msg = pr.promote_worktree_to_standalone(
        worktree_dir=wt, main_repo=main_repo, branch="successor", new_repo=new_repo)
    check("promote returns ok", ok)

    # 2.1 independence: own .git DIR + full branch history
    check("2.1 standalone has its own .git directory",
          os.path.isdir(os.path.join(new_repo, ".git")))
    check("2.1 branch renamed to main in the standalone",
          git(new_repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == "main")
    check("2.1 standalone carries the successor work",
          "v5_feature.py" in tree_files(new_repo, "HEAD"))

    # 2.3 pending work preserved (committed on detach, present in the clone)
    check("2.3 in-flight file preserved into the standalone",
          "pending.py" in tree_files(new_repo, "HEAD"))

    # 2.4 no symlinked alt-user path recorded in the standalone
    check("2.4 no foreign /Users/<other> path in standalone worktree list",
          git(new_repo, "worktree", "list").stdout.count("/Users/") <= 1)

    # 2.2 KILLER: delete the whole source, the standalone must still work
    shutil.rmtree(main_repo)
    shutil.rmtree(wt, ignore_errors=True)
    indep = pr.verify_repo_independent(new_repo)
    log_ok = git(new_repo, "log", "-1", "--oneline").returncode == 0
    check("2.2 verify_repo_independent True after source deleted", indep)
    check("2.2 git log still works with source gone (KILLER)", log_ok)
finally:
    shutil.rmtree(work, ignore_errors=True)

# --- 2.6 REGRESSION: detach commit bypasses a blocking pre-commit hook ------------
# Scar 2026-07-07: the live product repo's lefthook pre-commit (advisory-promote
# kind OVERDUE) REJECTED promote's mechanical detach commit, aborting the whole
# dissolution at PHASE 3. Fix = --no-verify on that commit. This reproduces it with
# a fixture repo whose pre-commit hook ALWAYS fails: a normal commit is blocked
# (negative control), but promote must still succeed.
work_hook = tempfile.mkdtemp(prefix="persona-hook-test-")
try:
    main_repo_h, wt_h = build_fixture(work_hook)
    hook_path = os.path.join(main_repo_h, ".git", "hooks", "pre-commit")
    write(hook_path, "#!/bin/sh\necho 'gate: BLOCKED' >&2\nexit 1\n")
    os.chmod(hook_path, 0o755)
    # negative control: a normal (verified) commit in the worktree IS blocked
    pr.sh(["git", "-C", wt_h, "add", "-A"])
    ctrl_code, _ = pr.sh(["git", "-C", wt_h, "commit", "-m", "control (hook should block)"])
    check("2.6 control: failing pre-commit hook DOES block a normal commit", ctrl_code != 0)
    # the fix: promote's detach commit uses --no-verify, so it succeeds anyway
    new_repo_h = os.path.join(work_hook, "standalone")
    ok_h, _ = pr.promote_worktree_to_standalone(wt_h, main_repo_h, "successor", new_repo_h)
    check("2.6 promote succeeds despite the blocking hook (--no-verify fix)", ok_h)
    check("2.6 in-flight work still preserved into the standalone",
          ok_h and "pending.py" in tree_files(new_repo_h, "HEAD"))
finally:
    shutil.rmtree(work_hook, ignore_errors=True)

# --- 3.x ROLLBACK INTEGRATION: apply-then-rollback restores BEFORE topology -------
# run_dissolve PHASE 3 (promote successor -> standalone, archive old line) is
# reversible via run_rollback's promotions loop. This drives the REAL rollback
# code against a FRESH hermetic fixture (the 2.2 KILLER destroyed the first one).
# manifest_path is monkeypatched so the manifest lands in the temp dir, never next
# to the script — same "verify against a copy, touch no live path" isolation.
import json as _json  # noqa: E402

_orig_manifest_path = pr.manifest_path
work2 = tempfile.mkdtemp(prefix="persona-rollback-test-")
try:
    main_repo2, wt2 = build_fixture(work2)
    new_repo2 = os.path.join(work2, "ktlyst-saas-product")
    archived2 = os.path.join(work2, "_archive", "product-old")

    # mirror run_dissolve PHASE 3 apply end-state: promote -> remove worktree ->
    # archive (move, never rm) the old main line
    prom_ok, _ = pr.promote_worktree_to_standalone(wt2, main_repo2, "successor", new_repo2)
    check("3.0 promote succeeded (rollback precondition)", prom_ok)
    git(main_repo2, "worktree", "remove", "--force", wt2)
    os.makedirs(os.path.dirname(archived2), exist_ok=True)
    shutil.move(main_repo2, archived2)
    check("3.0 apply end-state: old line archived, orig path gone",
          os.path.isdir(archived2) and not os.path.isdir(main_repo2))

    # write the manifest in the exact shape run_dissolve records (line ~1417)
    man_file2 = os.path.join(work2, "manifest.json")
    pr.manifest_path = lambda persona: man_file2
    with open(man_file2, "w") as f:
        _json.dump({"moves": [], "baks": [], "created": [], "promotions": [
            {"new_repo": new_repo2, "archived": archived2, "orig_main": main_repo2,
             "orig_worktree": wt2, "branch": "successor"}]}, f)

    pr.run_rollback("ktlyst-hub")

    # 3.1 BEFORE topology restored: old main back + successor worktree re-linked
    check("3.1 rollback restored the old product main line",
          os.path.isdir(main_repo2)
          and git(main_repo2, "log", "-1", "--oneline").returncode == 0)
    check("3.1 rollback re-added the successor worktree at its original path",
          os.path.exists(wt2))
    wt_branch2 = (git(wt2, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
                  if os.path.exists(wt2) else "")
    check("3.1 re-added worktree is on the successor branch", wt_branch2 == "successor")

    # 3.2 non-destructive: the standalone clone is KEPT and still independent
    check("3.2 rollback KEEPS the standalone clone (never destroys post-detach work)",
          os.path.isdir(new_repo2))
    check("3.2 kept clone is still independent after rollback",
          pr.verify_repo_independent(new_repo2))
finally:
    pr.manifest_path = _orig_manifest_path
    shutil.rmtree(work2, ignore_errors=True)

print()
if FAILS:
    print(f"FAIL: {len(FAILS)} check(s) failed: {FAILS}")
    sys.exit(1)
print("PASS: detach/promote-to-standalone reproducer green.")
sys.exit(0)
