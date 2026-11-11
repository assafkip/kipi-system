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


# --- ASK-4390 (disk 4.1 GB free, 2026-11-10) ----------------------------------
# A dry run kept 167 of 168 trees. 27 of those read "not merged and no PR found"
# while GitHub was unreachable, and 8 were review trees whose PR the lookup could
# not see because a later push moved the PR head off the sha they were reviewed at.


def _gh_says(env, body):
    (env.tmp / "bin" / "gh").write_text("#!/bin/sh\n" + body)


@pytest.mark.parametrize("gh_body", [
    "echo 'TLS handshake timeout' >&2\nexit 1\n",   # the 2026-11-10 outage
    "echo 'not json'\n",                            # exit 0, unreadable output
])
def test_a_failed_pr_lookup_is_its_own_keep_reason(env, capsys, gh_body):
    wt = env.make("wip")
    _gh_says(env, gh_body)
    out = mod.run(env.cfg, apply=True, now=LATER)
    assert out["kept"][os.path.realpath(wt)] == "PR lookup failed"
    assert out["pr_lookup_failed"] == 1
    assert "pr_lookup_failed=1" in capsys.readouterr().out


def _review_tree(env, n, key="acme_widget", fetched=True):
    """A pr-review-agent.sh tree, review-trees/<key>__pr-<N>: detached at the head
    it reviewed, which a later push to the PR left behind, so neither the PR's
    headRefOid nor its branch name matches the tree. `fetched` puts that head on
    refs/remotes/pr/<N>, as review_worktree does (pr-review-agent.sh update-ref)."""
    root = env.tmp / "review-trees"
    root.mkdir(exist_ok=True)
    if str(root / "*") not in env.cfg["roots"]:
        env.cfg["roots"].append(str(root / "*"))
    wt = root / f"{key}__pr-{n}"
    git(env.primary, "worktree", "add", "-q", "--detach", str(wt), "origin/main")
    (wt / "reviewed.txt").write_text(str(n))
    git(wt, "add", "reviewed.txt")
    git(wt, "commit", "-qm", f"head reviewed for PR {n}")
    if fetched:
        git(env.primary, "update-ref", f"refs/remotes/pr/{n}", git(wt, "rev-parse", "HEAD"))
    return wt


def _pr(n, state):
    return {"number": n, "state": state, "headRefName": "feat", "headRefOid": "later-push"}


def test_review_tree_of_a_merged_pr_is_found_by_its_number(env):
    wt = _review_tree(env, 12)
    env.prs.write_text(json.dumps([_pr(12, "MERGED")]))
    out = mod.run(env.cfg, apply=True, now=LATER)
    assert out["removed"] == [os.path.realpath(wt)]
    assert not wt.exists()


def test_review_tree_of_an_open_pr_is_kept(env):
    wt = _review_tree(env, 12)
    env.prs.write_text(json.dumps([_pr(12, "OPEN")]))
    out = mod.run(env.cfg, apply=True, now=LATER)
    assert out["kept"][os.path.realpath(wt)] == "PR #12 is open"
    assert wt.exists()


def test_review_tree_is_kept_when_the_lookup_fails(env):
    wt = _review_tree(env, 12)
    _gh_says(env, "exit 1\n")
    out = mod.run(env.cfg, apply=True, now=LATER)
    assert out["kept"][os.path.realpath(wt)] == "PR lookup failed"


def test_review_tree_named_for_another_repo_does_not_borrow_its_number(env):
    # The number in the name is only this repo's PR when the key is this repo's
    # artifact_key; acme/other's PR 12 says nothing about acme/widget's PR 12.
    wt = _review_tree(env, 12, key="acme_other")
    env.prs.write_text(json.dumps([_pr(12, "MERGED")]))
    out = mod.run(env.cfg, apply=True, now=LATER)
    assert out["kept"][os.path.realpath(wt)] == "not merged and no PR found"


def test_a_live_review_lock_keeps_a_finished_review_tree(env):
    wt = _review_tree(env, 12)
    env.prs.write_text(json.dumps([_pr(12, "MERGED")]))
    (wt.parent / (wt.name + ".lock")).write_text(str(os.getpid()))
    out = mod.run(env.cfg, apply=True, now=LATER)
    assert out["kept"][os.path.realpath(wt)] == "a review run holds its lock"
    assert wt.exists()


def test_a_dead_review_lock_does_not_keep_it(env):
    # release_wt_lock deletes the .lock on a clean exit, but a killed run leaves
    # it: 114 of them named a dead PID on 2026-11-10. Only a live holder counts.
    p = subprocess.Popen(["true"])
    p.wait()
    wt = _review_tree(env, 12)
    env.prs.write_text(json.dumps([_pr(12, "CLOSED")]))
    (wt.parent / (wt.name + ".lock")).write_text(str(p.pid))
    out = mod.run(env.cfg, apply=True, now=LATER)
    assert out["removed"] == [os.path.realpath(wt)]


# --- PR #731 round 1 review -------------------------------------------------

@pytest.mark.parametrize("age_s,kept", [(0, True), (3600, False)])
def test_an_empty_review_lock_counts_only_while_fresh(env, age_s, kept):
    # Finding 2. acquire_wt_lock reads an empty lock as a claim mid-create and
    # reclaims it once it stays empty, so it must not pin a merged tree forever.
    wt = _review_tree(env, 12)
    env.prs.write_text(json.dumps([_pr(12, "MERGED")]))
    lock = wt.parent / (wt.name + ".lock")
    lock.write_text("")
    t = time.time() - age_s
    os.utime(lock, (t, t))
    out = mod.run(env.cfg, apply=True, now=LATER)
    if kept:
        assert out["kept"][os.path.realpath(wt)] == "a review run holds its lock"
    else:
        assert out["removed"] == [os.path.realpath(wt)]


def _gh_commit_api(env, api_body):
    """gh stub: `gh api ...` runs api_body, anything else prints the PR list."""
    _gh_says(env, f'if [ "$1" = api ]; then\n{api_body}\nfi\ncat \'{env.prs}\'\n')


def test_a_review_tree_whose_head_is_on_no_remote_ref_is_kept(env):
    # Round 1, finding 3. A detached tree has no branch ref to keep its commits,
    # so "loses no commit" needs HEAD on a remote ref, or on GitHub itself.
    wt = _review_tree(env, 12, fetched=False)
    env.prs.write_text(json.dumps([_pr(12, "MERGED")]))
    _gh_commit_api(env, "echo 'gh: No commit found for SHA (HTTP 422)' >&2\nexit 1")
    out = mod.run(env.cfg, apply=True, now=LATER)
    assert out["kept"][os.path.realpath(wt)] == "detached HEAD is on no remote ref and not on GitHub"
    assert wt.exists()


def test_a_bailed_review_tree_whose_head_github_has_is_removed(env):
    # Round 2, finding 1. _wt_bail deletes refs/remotes/pr/<N> and leaves the
    # tree; its HEAD is a PR head GitHub keeps, so the remote-ref gate alone
    # would keep it forever.
    wt = _review_tree(env, 12, fetched=False)
    env.prs.write_text(json.dumps([_pr(12, "MERGED")]))
    _gh_commit_api(env, f"echo {git(wt, 'rev-parse', 'HEAD')}\nexit 0")
    out = mod.run(env.cfg, apply=True, now=LATER)
    assert out["removed"] == [os.path.realpath(wt)]


def test_a_failed_commit_lookup_keeps_the_tree_under_its_own_reason(env):
    wt = _review_tree(env, 12, fetched=False)
    env.prs.write_text(json.dumps([_pr(12, "MERGED")]))
    _gh_commit_api(env, "echo 'TLS handshake timeout' >&2\nexit 1")
    out = mod.run(env.cfg, apply=True, now=LATER)
    assert out["kept"][os.path.realpath(wt)] == "commit lookup failed"


def test_a_failed_census_at_remove_time_is_not_called_a_process(env, monkeypatch):
    # Round 2, finding 2: lsof failing at the per-tree re-check read as
    # "a process is working in it" when nothing was.
    wt = env.make("done", merged=True)
    censuses = iter([[], None])
    monkeypatch.setattr(mod, "held_dirs", lambda: next(censuses))
    out = mod.run(env.cfg, apply=True, now=LATER)
    assert out["kept"][os.path.realpath(wt)] == "process census failed"
    assert wt.exists()


def test_a_removed_review_tree_loses_no_commit(env):
    wt = _review_tree(env, 12)
    head = git(wt, "rev-parse", "HEAD")
    env.prs.write_text(json.dumps([_pr(12, "MERGED")]))
    out = mod.run(env.cfg, apply=True, now=LATER)
    assert out["removed"] == [os.path.realpath(wt)]
    assert git(env.primary, "for-each-ref", "--contains", head, "refs/remotes")


AGENT = os.path.join(SCRIPTS, "pr-review-agent.sh")
CLAIM = '_wt_lock_path=""; source "$1"; acquire_wt_lock "$2"; echo "$?"'


def _real_acquire_wt_lock(tmp):
    """acquire_wt_lock sliced from pr-review-agent.sh, as test-pr-review-reap-trees.sh
    slices it: the reaper must agree with the review's OWN claim code."""
    body = subprocess.run(["sed", "-n", "/^acquire_wt_lock() {/,/^}/p", AGENT],
                          check=True, capture_output=True, text=True).stdout
    assert body.startswith("acquire_wt_lock() {")
    path = tmp / "lock.sh"
    path.write_text(body)
    return path


def test_a_review_that_claims_before_the_remove_keeps_the_tree(env, monkeypatch):
    # Finding 1. A review that claimed between the verdict and `git worktree
    # remove` lost its tree. Here the REAL acquire_wt_lock claims it at that point
    # and its shell stays alive, the way a running review does.
    wt = _review_tree(env, 12)
    env.prs.write_text(json.dumps([_pr(12, "MERGED")]))
    lock_sh, rc = _real_acquire_wt_lock(env.tmp), env.tmp / "claim.rc"
    real_claim, procs = mod._claim_review_tree, []

    def review_claims_first(path):
        procs.append(subprocess.Popen(
            ["bash", "-c", CLAIM + ' > "$3"; sleep 30', "_", str(lock_sh), path, str(rc)]))
        deadline = time.time() + 20
        while not (rc.exists() and rc.read_text().strip()):
            assert time.time() < deadline, "the review's claim never finished"
            time.sleep(0.05)
        assert rc.read_text().strip() == "0"   # the review won its claim
        return real_claim(path)

    monkeypatch.setattr(mod, "_claim_review_tree", review_claims_first)
    try:
        out = mod.run(env.cfg, apply=True, now=LATER)
    finally:
        for p in procs:
            p.kill()
            p.wait()
    assert out["kept"][os.path.realpath(wt)] == "a review run holds its lock"
    assert wt.exists()


def test_a_review_arriving_after_the_reaper_claim_is_turned_away(env, monkeypatch):
    wt = _review_tree(env, 12)
    env.prs.write_text(json.dumps([_pr(12, "MERGED")]))
    lock_sh, real_remove, seen = _real_acquire_wt_lock(env.tmp), mod.remove, {}

    def late_review_then_remove(path):
        r = subprocess.run(["bash", "-c", CLAIM, "_", str(lock_sh), path],
                           capture_output=True, text=True)
        seen["rc"] = r.stdout.strip()
        return real_remove(path)

    monkeypatch.setattr(mod, "remove", late_review_then_remove)
    out = mod.run(env.cfg, apply=True, now=LATER)
    assert seen["rc"] == "2"   # acquire_wt_lock: busy, a live holder that is not it
    assert out["removed"] == [os.path.realpath(wt)]
    assert not (wt.parent / (wt.name + ".lock")).exists()   # the reaper released it
