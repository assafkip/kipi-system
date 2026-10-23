#!/usr/bin/env python3
"""Pins worktree-reaper.py and worktree-disk-floor.py (ASK-2882).

The property that matters: a finished worktree goes, and a worktree holding
anything that is not already safe elsewhere stays. Every case builds real git
repos under tmp_path; `gh` is a stub on PATH; nothing touches a live checkout.
"""
import importlib.util
import json
import os
import subprocess
import sys
import time

import pytest

SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")
REAPER = os.path.join(SCRIPTS, "worktree-reaper.py")
GUARD = os.path.join(SCRIPTS, "worktree-disk-floor.py")
SLUG_URL = "https://github.com/acme/widget.git"
LATER = time.time() + 86400   # every tree reads as idle for a day


def _load():
    spec = importlib.util.spec_from_file_location("worktree_reaper", REAPER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mod = _load()


def git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


@pytest.fixture
def env(tmp_path, monkeypatch):
    for k, v in {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                 "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
                 "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
                 "KIPI_ALERT_CAPTURE": str(tmp_path / "alerts.txt")}.items():
        monkeypatch.setenv(k, v)
    seed = tmp_path / "seed"
    origin = tmp_path / "origin.git"
    primary = tmp_path / "primary"
    subprocess.run(["git", "init", "-q", "-b", "main", str(seed)], check=True)
    (seed / "a.txt").write_text("a\n")
    git(seed, "add", "a.txt")
    git(seed, "commit", "-qm", "base")
    subprocess.run(["git", "clone", "-q", "--bare", str(seed), str(origin)], check=True)
    subprocess.run(["git", "clone", "-q", str(origin), str(primary)], check=True)
    # The PR lookup needs a GitHub-shaped origin; fetches still go to the local bare.
    git(primary, "config", "remote.origin.url", SLUG_URL)
    git(primary, "config", f"url.{origin}.insteadOf", SLUG_URL)
    gh_bin = tmp_path / "bin"
    gh_bin.mkdir()
    prs = tmp_path / "prs.json"
    prs.write_text("[]")
    (gh_bin / "gh").write_text(f"#!/bin/sh\ncat '{prs}'\n")
    (gh_bin / "gh").chmod(0o755)
    monkeypatch.setenv("PATH", f"{gh_bin}{os.pathsep}{os.environ['PATH']}")
    roots = tmp_path / "wt"
    roots.mkdir()
    cfg = {"roots": [str(roots / "*")], "min_idle_hours": 6, "alarm_below_gb": 0,
           "refuse_worktree_below_gb": 0}

    class E:
        pass

    e = E()
    e.tmp, e.primary, e.roots, e.cfg, e.prs = tmp_path, primary, roots, cfg, prs

    def make(name, merged=False):
        wt = roots / name
        git(primary, "worktree", "add", "-q", "-b", name, str(wt), "origin/main")
        (wt / f"{name}.txt").write_text(name)
        git(wt, "add", ".")
        git(wt, "commit", "-qm", name)
        if merged:
            git(wt, "push", "-q", "origin", "HEAD:main")
        return wt

    e.make = make
    return e


def test_merged_clean_idle_tree_is_removed_and_its_branch_survives(env):
    wt = env.make("done", merged=True)
    out = mod.run(env.cfg, apply=True, now=LATER)
    assert out["removed"] == [os.path.realpath(wt)]
    assert not wt.exists()
    assert git(env.primary, "branch", "--list", "done")   # no commit was lost


def test_dry_run_removes_nothing(env):
    wt = env.make("done", merged=True)
    out = mod.run(env.cfg, apply=False, now=LATER)
    assert out["removed"] == [os.path.realpath(wt)]
    assert wt.exists()


def test_untracked_file_keeps_a_merged_tree(env):
    wt = env.make("done", merged=True)
    (wt / "notes.md").write_text("unsaved work")
    out = mod.run(env.cfg, apply=True, now=LATER)
    assert out["removed"] == []
    assert "uncommitted" in out["kept"][os.path.realpath(wt)]
    assert wt.exists()


def test_unmerged_tree_without_a_pr_is_kept(env):
    wt = env.make("wip")
    out = mod.run(env.cfg, apply=True, now=LATER)
    assert out["kept"][os.path.realpath(wt)] == "not merged and no PR found"


def test_squash_merged_pr_removes_a_tree_whose_commits_are_not_on_main(env):
    wt = env.make("feat")
    env.prs.write_text(json.dumps([{"number": 7, "state": "MERGED",
                                    "headRefName": "feat", "headRefOid": "x"}]))
    out = mod.run(env.cfg, apply=True, now=LATER)
    assert out["removed"] == [os.path.realpath(wt)]


def test_an_open_pr_keeps_the_tree_even_beside_a_merged_one(env):
    wt = env.make("feat")
    env.prs.write_text(json.dumps([
        {"number": 7, "state": "MERGED", "headRefName": "feat", "headRefOid": "x"},
        {"number": 9, "state": "OPEN", "headRefName": "feat", "headRefOid": "y"}]))
    out = mod.run(env.cfg, apply=True, now=LATER)
    assert out["kept"][os.path.realpath(wt)] == "PR #9 is open"


def test_recently_touched_tree_is_kept(env):
    wt = env.make("done", merged=True)
    out = mod.run(env.cfg, apply=True, now=time.time())
    assert out["kept"][os.path.realpath(wt)].startswith("touched")


def test_the_status_check_does_not_make_an_idle_tree_look_touched(env):
    wt = env.make("done", merged=True)
    gitdir = git(wt, "rev-parse", "--absolute-git-dir")
    old = time.time() - 7 * 3600
    for name in ("index", "HEAD", os.path.join("logs", "HEAD")):
        os.utime(os.path.join(gitdir, name), (old, old))
    (wt / "done.txt").touch()   # stat change: a plain `git status` rewrites the index
    out = mod.run(env.cfg, apply=True, now=time.time())
    assert out["removed"] == [os.path.realpath(wt)]


@pytest.mark.parametrize("machine_checkout", [
    "~/.local/state/kipi/dispatch-main",          # kipi-dispatch-pinned.sh KIPI_REPO_MAIN
    "~/.local/state/kipi/dispatch/kipi-system",   # kipi-dispatch-pinned.sh PINNED
    "~/.local/state/kipi/dispatch-checkout",
    "~/projects/kipi-scheduled",                  # the launchd jobs' checkout
])
def test_shipped_roots_never_reach_the_fleets_own_checkouts(machine_checkout):
    # These are detached at origin/main, so "already on main" would remove them.
    # Only the roots keep them out; this pins that the roots do.
    import fnmatch
    path = os.path.expanduser(machine_checkout)
    roots = [os.path.expanduser(r) for r in mod.load_config()["roots"]]
    assert not any(fnmatch.fnmatch(path, r) for r in roots)


def test_locked_tree_is_kept(env):
    wt = env.make("done", merged=True)
    git(env.primary, "worktree", "lock", str(wt))
    out = mod.run(env.cfg, apply=True, now=LATER)
    assert out["kept"][os.path.realpath(wt)] == "locked"


def test_a_process_working_inside_keeps_the_tree(env):
    wt = env.make("done", merged=True)
    proc = subprocess.Popen(["sleep", "30"], cwd=str(wt))
    try:
        out = mod.run(env.cfg, apply=True, now=LATER)
    finally:
        proc.kill()
        proc.wait()
    assert out["kept"][os.path.realpath(wt)] == "a process is working in it"


def test_a_process_that_arrives_mid_pass_keeps_the_tree(env, monkeypatch):
    # PR #556 review, finding 1: the first census is empty, an agent resumes the
    # dormant tree before its turn, and only a census taken at remove time sees it.
    wt = env.make("done", merged=True)
    censuses = iter([[], [os.path.realpath(wt)]])
    monkeypatch.setattr(mod, "held_dirs", lambda: next(censuses))
    out = mod.run(env.cfg, apply=True, now=LATER)
    assert out["removed"] == [] and wt.exists()
    assert out["kept"][os.path.realpath(wt)] == "a process is working in it"


def test_failed_process_census_removes_nothing(env, monkeypatch):
    wt = env.make("done", merged=True)
    monkeypatch.setattr(mod, "held_dirs", lambda: None)
    out = mod.run(env.cfg, apply=True, now=LATER)
    assert out["removed"] == [] and wt.exists()


def test_a_primary_checkout_under_a_root_is_never_a_candidate(env):
    subprocess.run(["git", "clone", "-q", str(env.primary), str(env.roots / "clone")],
                   check=True)
    assert mod.candidates(env.cfg["roots"]) == []


def test_alarm_files_one_alert_when_free_space_is_under_the_floor(env):
    env.cfg["alarm_below_gb"] = 10**9
    out = mod.run(env.cfg, apply=True, now=LATER)
    lines = (env.tmp / "alerts.txt").read_text().splitlines()
    assert out["alarmed"] and len(lines) == 1 and lines[0].startswith("[disk-floor]")


def test_no_alarm_above_the_floor_or_on_a_dry_run(env):
    mod.run(env.cfg, apply=True, now=LATER)
    env.cfg["alarm_below_gb"] = 10**9
    mod.run(env.cfg, apply=False, now=LATER)
    assert not (env.tmp / "alerts.txt").exists()


def _guard(tmp_path, payload, floor):
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps({"refuse_worktree_below_gb": floor}))
    raw = payload if isinstance(payload, str) else json.dumps(payload)
    r = subprocess.run([sys.executable, GUARD], input=raw, capture_output=True, text=True,
                       env={**os.environ, "KIPI_WORKTREE_REAPER_CONFIG": str(cfg)})
    assert r.returncode == 0
    return json.loads(r.stdout)["hookSpecificOutput"]["permissionDecision"] if r.stdout else "allow"


BASH_ADD = {"tool_name": "Bash", "tool_input": {"command": "git -C repo worktree add ../x -b y"}}


@pytest.mark.parametrize("payload,floor,want", [
    (BASH_ADD, 10**9, "deny"),
    (BASH_ADD, 0, "allow"),
    ({"tool_name": "Bash", "tool_input": {"command": "git status"}}, 10**9, "allow"),
    ({"tool_name": "Bash", "tool_input": {"command": "git worktree remove ../x"}}, 10**9, "allow"),
    ({"tool_name": "EnterWorktree", "tool_input": {}}, 10**9, "deny"),
    ({"tool_name": "EnterWorktree", "tool_input": {"name": "fix"}}, 10**9, "deny"),
    ({"tool_name": "EnterWorktree", "tool_input": {}}, 0, "allow"),
    # PR #556 review, finding 2: entering an existing tree allocates nothing.
    ({"tool_name": "EnterWorktree", "tool_input": {"path": "/x/wt"}}, 10**9, "allow"),
    ('{"broken": "git worktree add', 0, "deny"),
    ('{"broken": "git status', 10**9, "allow"),
])
def test_guard_refuses_a_new_worktree_only_under_the_floor(tmp_path, payload, floor, want):
    assert _guard(tmp_path, payload, floor) == want


def test_shipped_config_and_job_are_wired():
    cfg = mod.load_config()
    assert cfg["roots"] and cfg["refuse_worktree_below_gb"] < cfg["alarm_below_gb"]
    plist = open(os.path.join(SCRIPTS, "com.kipi.worktree-reaper.plist")).read()
    assert "scripts/worktree-reaper.py" in plist and "<string>--apply</string>" in plist
    # Both files: kipi update builds every instance's settings from the template
    # only, so a hook missing there never reaches the repos that make worktrees.
    root = os.path.join(SCRIPTS, "..", "..", "..")
    for rel in (os.path.join(".claude", "settings.json"), "settings-template.json"):
        settings = json.load(open(os.path.join(root, rel)))
        matchers = {m["matcher"] for m in settings["hooks"]["PreToolUse"]
                    if any("worktree-disk-floor.py" in h["command"] for h in m["hooks"])}
        assert {"Bash", "EnterWorktree"} <= matchers, rel
