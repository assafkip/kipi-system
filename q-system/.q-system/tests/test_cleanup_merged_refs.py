#!/usr/bin/env python3
"""Pins cleanup-merged-refs.sh (ASK-4650).

The property that matters: a branch or tree goes only when LIVE state proves it is
finished, and the list alone never deletes anything. Every case builds a throwaway
repo plus a bare "remote" under tmp_path; `gh` is a stub on PATH; HOME and the receipt
dir are tmp_path. Nothing touches the real remote or a live checkout.
"""
import json
import os
import shutil
import subprocess
import time

import pytest

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts",
                      "cleanup-merged-refs.sh")
OLD = "2020-01-01T00:00:00Z"

GH_STUB = """#!/bin/bash
[ -n "${STUB_GH_FAIL:-}" ] && exit 1
case "$*" in
  *"--state open"*) jq '[.[] | select(.state == "OPEN")]' "$STUB_PRS" ;;
  *) cat "$STUB_PRS" ;;
esac
"""


def git(cwd, *args, date=None, check=True):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@t")
    if date:
        env["GIT_COMMITTER_DATE"] = env["GIT_AUTHOR_DATE"] = date
    r = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, env=env)
    if check:
        assert r.returncode == 0, r.stderr
    return r.stdout.strip()


class Env:
    pass


@pytest.fixture
def env(tmp_path):
    e = Env()
    e.tmp = tmp_path
    remote, work = tmp_path / "remote.git", tmp_path / "work"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    subprocess.run(["git", "clone", "-q", str(remote), str(work)], check=True, capture_output=True)
    git(work, "checkout", "-q", "-b", "main")
    (work / "a.txt").write_text("a\n")
    git(work, "add", "a.txt"); git(work, "commit", "-qm", "base", date=OLD)
    git(work, "push", "-q", "origin", "main")
    e.work, e.remote = work, remote
    e.prs = []

    def branch(name, files=None, date=OLD, base="main"):
        git(work, "checkout", "-q", "-b", name, base)
        (work / (name.replace("/", "_") + ".txt")).write_text(name)
        git(work, "add", "-A"); git(work, "commit", "-qm", name, date=date)
        git(work, "push", "-q", "origin", name)
        tip = git(work, "rev-parse", "HEAD")
        git(work, "checkout", "-q", "main")
        return tip

    e.branch = branch
    e.pr = lambda name, state, oid: e.prs.append(
        {"number": len(e.prs) + 1, "headRefName": name, "headRefOid": oid, "state": state})

    def land_main():
        # a squash merge: main gets a NEW commit, the branch tips never become ancestors.
        (work / "m.txt").write_text(str(time.time()))
        git(work, "add", "-A"); git(work, "commit", "-qm", "squash", date=OLD)
        git(work, "push", "-q", "origin", "main")
    e.land_main = land_main

    bin_ = tmp_path / "bin"; bin_.mkdir()
    (bin_ / "gh").write_text(GH_STUB); (bin_ / "gh").chmod(0o755)
    e.env = dict(os.environ, PATH=f"{bin_}:{os.environ['PATH']}", HOME=str(tmp_path),
                 KIPI_CLEANUP_RECEIPT_DIR=str(tmp_path / "receipts"),
                 STUB_PRS=str(tmp_path / "prs.json"))
    e.env.pop("STUB_GH_FAIL", None)

    def run(batch, listing, *extra, script=SCRIPT, env_extra=None):
        (tmp_path / "list.md").write_text(listing)
        (tmp_path / "prs.json").write_text(json.dumps(e.prs))
        r = subprocess.run(["bash", script, str(tmp_path / "list.md"), "--batch", batch,
                            "--repo", str(work), "--min-age-hours", "24", *extra],
                           capture_output=True, text=True, env=dict(e.env, **(env_extra or {})))
        return r
    e.run = run
    e.heads = lambda: set(l.split("refs/heads/")[1] for l in
                          git(work, "ls-remote", "--heads", "origin").splitlines())
    e.receipt = lambda: [json.loads(l) for f in sorted((tmp_path / "receipts").iterdir())
                         for l in f.read_text().splitlines()]
    return e


def listing(section, *names):
    return f"## {section}. x\n\n" + "".join(f"- origin/{n}\n" for n in names)


def test_dry_run_deletes_nothing_and_says_what_it_would_do(env):
    env.branch("old"); env.land_main()
    git(env.work, "merge", "-q", "--ff-only", "origin/main")
    tip = env.branch("squashed"); env.pr("squashed", "MERGED", tip)
    before = env.heads()
    r = env.run("D", listing("D", "squashed"))
    assert r.returncode == 0, r.stderr
    assert env.heads() == before
    assert "would delete  squashed" in r.stdout
    assert [x["action"] for x in env.receipt()] == ["would-delete"]


def test_apply_deletes_a_merged_pr_head_and_records_the_sha(env):
    tip = env.branch("squashed"); env.pr("squashed", "MERGED", tip); env.land_main()
    r = env.run("D", listing("D", "squashed"), "--apply")
    assert r.returncode == 0, r.stderr
    assert "squashed" not in env.heads()
    rows = [x for x in env.receipt() if x["action"] == "deleted"]
    assert rows and rows[0]["name"] == "squashed"
    assert [x["sha"] for x in env.receipt() if x["action"] == "queued"] == [tip]


def test_ancestor_branch_goes_in_batch_a_but_an_open_pr_keeps_it(env):
    env.branch("anc"); env.branch("openpr")
    git(env.work, "merge", "-q", "--no-ff", "-m", "m", "origin/anc", "origin/openpr", date=OLD)
    git(env.work, "push", "-q", "origin", "main")
    env.pr("openpr", "OPEN", git(env.work, "rev-parse", "origin/openpr"))
    r = env.run("A", listing("A", "anc", "openpr"), "--apply")
    assert r.returncode == 0, r.stderr
    assert env.heads() == {"main", "openpr"}
    assert "head of an open PR" in r.stdout


def test_a_branch_pushed_to_after_the_merge_is_kept(env):
    old = env.branch("reused"); env.pr("reused", "MERGED", old); env.land_main()
    git(env.work, "checkout", "-q", "reused")
    (env.work / "late.txt").write_text("late")
    git(env.work, "add", "-A"); git(env.work, "commit", "-qm", "late", date=OLD)
    git(env.work, "push", "-q", "origin", "reused"); git(env.work, "checkout", "-q", "main")
    r = env.run("D", listing("D", "reused"), "--apply")
    assert "reused" in env.heads()
    assert "pushed to after the merge" in r.stdout


def test_a_branch_with_no_pr_and_unmerged_is_kept_even_if_listed(env):
    env.branch("never"); env.land_main()
    r = env.run("D", listing("D", "never"), "--apply")
    assert "never" in env.heads() and r.returncode == 0


def test_protected_names_survive_even_when_listed(env):
    env.branch("backup/keep")
    r = env.run("A", listing("A", "main", "backup/keep"), "--apply")
    assert {"main", "backup/keep"} <= env.heads(), r.stdout


def test_a_young_tip_is_kept_unless_the_age_floor_is_lowered(env):
    young = env.branch("young", date=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    env.pr("young", "MERGED", young); env.land_main()
    env.run("D", listing("D", "young"), "--apply")
    assert "young" in env.heads()
    env.run("D", listing("D", "young"), "--apply", "--min-age-hours", "0")
    assert "young" not in env.heads()


def test_a_failed_pr_lookup_deletes_nothing(env):
    tip = env.branch("squashed"); env.pr("squashed", "MERGED", tip); env.land_main()
    r = env.run("D", listing("D", "squashed"), "--apply", env_extra={"STUB_GH_FAIL": "1"})
    assert r.returncode == 3 and "squashed" in env.heads()


def test_chunk_of_one_still_deletes_every_proven_branch(env):
    for n in ("b1", "b2", "b3"):
        env.pr(n, "MERGED", env.branch(n))
    env.land_main()
    r = env.run("D", listing("D", "b1", "b2", "b3"), "--apply", "--chunk", "1")
    assert r.returncode == 0 and env.heads() == {"main"}


def test_only_the_named_batch_section_is_read(env):
    tip = env.branch("squashed"); env.pr("squashed", "MERGED", tip); env.land_main()
    env.run("A", listing("D", "squashed"), "--apply")
    assert "squashed" in env.heads()


def test_the_script_carries_no_bypass():
    text = open(SCRIPT).read()
    assert "ALLOW_" + "DESTRUCTIVE" not in text and "--force" not in text


def test_mutant_without_the_merged_head_check_deletes_the_reused_branch(env, tmp_path):
    # Negative self-test: the "pushed to after the merge" keep must come from the
    # headRefOid comparison. Remove it and the same fixture must go red.
    old = env.branch("reused"); env.pr("reused", "MERGED", old); env.land_main()
    git(env.work, "checkout", "-q", "reused")
    (env.work / "late.txt").write_text("late")
    git(env.work, "add", "-A"); git(env.work, "commit", "-qm", "late", date=OLD)
    git(env.work, "push", "-q", "origin", "reused"); git(env.work, "checkout", "-q", "main")
    mutant = tmp_path / "mutant.sh"
    src = open(SCRIPT).read()
    assert ' and .headRefOid == $t' in src
    mutant.write_text(src.replace(' and .headRefOid == $t', ''))
    env.run("D", listing("D", "reused"), "--apply", script=str(mutant))
    assert "reused" not in env.heads()


def test_there_is_no_tree_batch_and_the_script_never_removes_a_worktree(env):
    # RCA 2026-11-12: a second tree remover re-learned the reaper's rules one review round
    # at a time. Trees have one owner, worktree-reaper.py; B is refused, not served.
    r = env.run("B", "## B. x\n\n- /anywhere\n", "--apply")
    assert r.returncode == 2 and "worktree-reaper" in r.stderr
    text = open(SCRIPT).read()
    assert "worktree remove" not in text and "lsof" not in text


def test_help_prints_the_usage_comment_and_no_code():
    # Round 1 nit: a fixed line range printed two lines of source. Print the comment block.
    out = subprocess.run(["bash", SCRIPT, "--help"], capture_output=True, text=True).stdout
    assert "Usage: cleanup-merged-refs.sh" in out and "set -u" not in out and "LIST=" not in out


def test_a_flag_without_a_value_or_an_empty_number_is_refused_not_hung(env):
    for extra in (["--chunk"], ["--min-age-hours", ""]):
        r = env.run("A", listing("A", "x"), *extra)
        assert r.returncode == 2


def test_a_failed_ls_remote_is_a_failure_not_already_gone(env, tmp_path):
    env.branch("live")
    real = shutil.which("git")
    stub = tmp_path / "bin" / "git"
    stub.write_text(f'#!/bin/bash\ncase "$*" in *ls-remote*) exit 1;; esac\nexec {real} "$@"\n')
    stub.chmod(0o755)
    r = env.run("A", listing("A", "live"), "--apply")
    assert r.returncode != 0 and "already gone" not in r.stdout and "live" in env.heads()
