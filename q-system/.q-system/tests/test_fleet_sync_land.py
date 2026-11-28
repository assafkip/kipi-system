"""fleet-sync-land.py: divergence check + landing through a worktree (ASK-4431).

Scar: the updater synced a client instance daily into a feature branch and
nothing pushed it; origin/main went 32 days without a sync and nothing alerted.
Every fixture here is a throwaway repo under tmp_path; HOME and the state dir are
redirected so no test reaches a live registry, instance or Linear.
"""
import json
import os
import re
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = Path(os.environ.get("FLEET_SYNC_LAND_UNDER_TEST") or ROOT / "fleet-sync-land.py")
TAG = "chore: sync q-system from skeleton [no-issue: fleet updater skeleton sync]"


def env_for(tmp):
    e = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "KIPI_"))}
    e.update(HOME=str(tmp / "home"), GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
             GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
             GIT_COMMITTER_EMAIL="t@t")
    (tmp / "home").mkdir(exist_ok=True)
    return e


def run(cmd, env, cwd=None, extra=None):
    return subprocess.run(cmd, cwd=cwd, env={**env, **(extra or {})}, capture_output=True, text=True)


def ok(cmd, env, cwd=None):
    # Fixture steps fail loudly: round 1's `checkout -b "a feature branch"` exited
    # 128 on an illegal refname, run() swallowed it, and the scar shape was never built.
    r = run(cmd, env, cwd)
    assert r.returncode == 0, f"{cmd}: {r.stderr}"
    return r


def commit(repo, env, msg, ts, fname):
    (repo / fname).write_text(msg + str(ts))
    run(["git", "add", "-A"], env, repo)
    stamp = f"@{int(ts)} +0000"
    r = run(["git", "commit", "-q", "-m", msg], env, repo,
            {"GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp})
    assert r.returncode == 0, r.stderr


def fixture(tmp, landed_days_ago, made_msg=TAG, entry_extra=None):
    """origin carries a sync landed N days ago; the shared checkout sits on a feature
    branch holding a commit made now (a sync unless made_msg says otherwise), plus a
    human's dirty and untracked files."""
    env = env_for(tmp)
    origin, seed, shared = tmp / "origin.git", tmp / "seed", tmp / "shared"
    ok(["git", "init", "-q", "--bare", "-b", "main", str(origin)], env)
    ok(["git", "clone", "-q", str(origin), str(seed)], env)
    ok(["git", "checkout", "-q", "-b", "main"], env, seed)
    commit(seed, env, "init", time.time() - 40 * 86400, "README")
    commit(seed, env, TAG, time.time() - landed_days_ago * 86400, "synced-old.txt")
    ok(["git", "push", "-q", "origin", "main"], env, seed)
    ok(["git", "clone", "-q", str(origin), str(shared)], env)
    url = "https://github.com/acme/inst.git"
    ok(["git", "config", "remote.origin.url", url], env, shared)
    ok(["git", "config", f"url.{origin}.insteadOf", url], env, shared)
    # A real fleet branch name: a client instance's checkout sat on it.
    ok(["git", "checkout", "-q", "-b", "sync-with-docx"], env, shared)
    # The stranded sync commit also DELETES a tracked file. Real shape, not
    # hypothetical: on one client instance, one of the 19 unlanded updater
    # commits (ca8a02ed, 2026-11-09) carried rule_gate's deletion of 5
    # .claude/rules files that origin/main still has. A lander that pushed the
    # shared branch's commits would land that deletion. This lander cuts from
    # origin and re-runs the updater, so neither the added nor the deleted side
    # can reach the PR.
    ok(["git", "rm", "-q", "synced-old.txt"], env, shared)
    commit(shared, env, made_msg, time.time(), "synced-new.txt")
    (shared / "README").write_text("human edit, uncommitted")
    (shared / "case-051").mkdir()
    (shared / "case-051" / "notes.md").write_text("untracked human work")
    reg = tmp / "registry.json"
    reg.write_text(json.dumps({"skeleton": {"path": str(tmp)}, "instances": [
        {"name": "inst", "type": "subtree", "subtree_prefix": "q-system", "path": str(shared),
         **(entry_extra or {})}]}))
    notify = tmp / "notify.sh"
    notify.write_text(f'#!/bin/bash\nprintf "%s\\n" "$1" >> "{tmp}/notified.txt"\n')
    return env, origin, shared, {"KIPI_UPDATE_REGISTRY": str(reg), "KIPI_NOTIFY_CMD": str(notify),
                                 "KIPI_SYNC_LAND_STATE": str(tmp / "state")}


def fakes(tmp, shared, extra, merge_rc=0):
    """Fake updater (exit 9 if the registry still points at the shared checkout,
    the defect this lander exists to avoid) and a fake gh that logs its calls."""
    updater = tmp / "fake-update.sh"
    updater.write_text(f"""#!/bin/bash
p=$(python3 -c 'import json,os;print([e["path"] for e in json.load(open(os.environ["KIPI_UPDATE_REGISTRY"]))["instances"] if e["name"]=="inst"][0])')
[ "$p" = "{shared}" ] && exit 9
mkdir -p "$p/q-system" && echo synced > "$p/q-system/new.txt"
git -C "$p" add -A && git -C "$p" commit -q -m "{TAG}"
""")
    gh = tmp / "gh"
    gh.write_text(f"""#!/bin/bash
echo "$*" >> "{tmp}/gh.log"
case "$1 $2" in
  "pr list") echo 0;;
  "pr create") echo https://github.com/acme/inst/pull/7;;
  "pr merge") [ {merge_rc} = 0 ] || {{ echo "Auto-merge is not allowed for this repository" >&2; exit {merge_rc}; }};;
esac
""")
    gh.chmod(0o755)
    extra.update(KIPI_UPDATE_SCRIPT=str(updater), KIPI_GH=str(gh))


def test_stale_instance_alerts(tmp_path):
    env, _, _, extra = fixture(tmp_path, landed_days_ago=10)
    r = run(["python3", str(SCRIPT), "check", "--alert"], env, extra=extra)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "stale" in r.stdout and "inst" in r.stdout
    sent = (tmp_path / "notified.txt").read_text()
    assert "fleet-sync-divergence" in sent and "inst" in sent


def test_fresh_instance_does_not_alert(tmp_path):
    env, _, _, extra = fixture(tmp_path, landed_days_ago=0.1)
    r = run(["python3", str(SCRIPT), "check", "--alert"], env, extra=extra)
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.startswith("ok")
    assert not (tmp_path / "notified.txt").exists()


def test_land_goes_through_a_worktree_and_never_touches_the_shared_checkout(tmp_path):
    env, origin, shared, extra = fixture(tmp_path, landed_days_ago=10)
    before = {k: run(["git", *a], env, shared).stdout for k, a in {
        "head": ["rev-parse", "HEAD"], "branch": ["symbolic-ref", "--short", "HEAD"],
        "status": ["status", "--porcelain"]}.items()}
    fakes(tmp_path, shared, extra)
    r = run(["python3", str(SCRIPT), "land"], env, extra=extra)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "OK inst: https://github.com/acme/inst/pull/7 (auto-merge armed)" in r.stdout
    branches = run(["git", "branch", "--list", "kipi/skeleton-sync-*"], env, origin).stdout.split()
    assert branches, "no landing branch reached origin"
    files = run(["git", "ls-tree", "-r", "--name-only", branches[-1]], env, origin).stdout
    # DELETION FIRST, and on its own line. The stranded commit removed
    # synced-old.txt on the shared branch; it is still on the landing branch,
    # because the branch was cut from origin and never merged that history.
    # Asserted before the add-side check because losing a file main still has is
    # the worse outcome, and a combined `and` would short-circuit this away: the
    # worktree-base mutant trips the add-side clause first and this would never
    # be reached.
    assert "synced-old.txt" in files, "a stranded deletion reached the landing branch"
    assert "q-system/new.txt" in files and "synced-new.txt" not in files
    after = {k: run(["git", *a], env, shared).stdout for k, a in {
        "head": ["rev-parse", "HEAD"], "branch": ["symbolic-ref", "--short", "HEAD"],
        "status": ["status", "--porcelain"]}.items()}
    assert after == before
    log = (tmp_path / "gh.log").read_text()
    assert "pr create --repo acme/inst --base main" in log and "--auto" in log
    assert len(run(["git", "worktree", "list"], env, shared).stdout.splitlines()) == 1


def test_fixture_builds_the_feature_branch_scar_shape(tmp_path):
    env, _, shared, _ = fixture(tmp_path, landed_days_ago=10)
    assert run(["git", "symbolic-ref", "--short", "HEAD"], env, shared).stdout.strip() == "sync-with-docx"


SYSTEM_STATE = ("chore: commit system-written state before skeleton sync "
                "[no-issue: fleet updater system-state commit]")


def test_local_only_system_state_commit_is_not_an_unlanded_sync(tmp_path):
    # Review finding 1: the newest tagged commit on HEAD is kipi-update.sh's
    # system-state commit, which a worktree off origin can never reproduce, so
    # land says "nothing to land". check must agree and stay quiet.
    env, _, _, extra = fixture(tmp_path, landed_days_ago=10, made_msg=SYSTEM_STATE)
    r = run(["python3", str(SCRIPT), "check", "--alert"], env, extra=extra)
    assert r.returncode == 0, r.stdout + r.stderr
    assert not (tmp_path / "notified.txt").exists()


def test_default_branch_comes_from_the_remote_not_the_local_cache(tmp_path):
    # Review finding 2: one instance's refs/remotes/origin/HEAD pointed at
    # feat/prd-rollout while GitHub's default was main.
    env, origin, shared, extra = fixture(tmp_path, landed_days_ago=10)
    ok(["git", "push", "-q", "origin", "HEAD:refs/heads/feat/prd-rollout"], env, shared)
    ok(["git", "fetch", "-q", "origin"], env, shared)
    ok(["git", "remote", "set-head", "origin", "feat/prd-rollout"], env, shared)
    fakes(tmp_path, shared, extra)
    r = run(["python3", str(SCRIPT), "land"], env, extra=extra)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "pr create --repo acme/inst --base main " in (tmp_path / "gh.log").read_text()


def test_concurrent_land_waits_and_never_removes_another_runs_tree(tmp_path):
    # Review finding 3: two runs shared one worktree path and force-removed
    # each other's in-flight tree (updater exit 128).
    import fcntl
    env, _, shared, extra = fixture(tmp_path, landed_days_ago=10)
    fakes(tmp_path, shared, extra)
    state = tmp_path / "state"
    other = state / "inst"
    other.mkdir(parents=True)
    (other / "in-flight").write_text("another run's tree")
    with open(state / "inst.lock", "w") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        r = run(["python3", str(SCRIPT), "land"], env, extra=extra)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "WAIT inst" in r.stdout
    assert (other / "in-flight").exists(), "land removed another run's worktree"


def test_land_fails_when_auto_merge_is_not_armed(tmp_path):
    env, _, shared, extra = fixture(tmp_path, landed_days_ago=10)
    fakes(tmp_path, shared, extra, merge_rc=1)
    r = run(["python3", str(SCRIPT), "land"], env, extra=extra)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "FAIL inst" in r.stdout and "auto-merge NOT armed" in r.stdout


@pytest.mark.parametrize("entry_extra", [{"status": "merged-into-consulting"},
                                         {"skeleton_managed": False}])
def test_merged_and_opted_out_entries_are_not_measured(tmp_path, entry_extra):
    env, _, _, extra = fixture(tmp_path, landed_days_ago=10, entry_extra=entry_extra)
    r = run(["python3", str(SCRIPT), "check", "--alert"], env, extra=extra)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "inst" not in r.stdout
    assert not (tmp_path / "notified.txt").exists()


def test_lessons_daily_lands_only_after_a_real_fan_out(tmp_path):
    # Review finding 6: `propagat*` also matched "propagate FAILED". Runs the
    # script's own case pattern against every PROP value lessons-daily.sh sets.
    src = (ROOT / "q-system/.q-system/scripts/lessons-daily.sh").read_text()
    pat = re.search(r'case "\$PROP" in ([^)]+)\)\n\s+python3 "\$SKEL/fleet-sync-land.py" land', src)
    assert pat, "land hook not found in lessons-daily.sh"
    probe = 'case "$1" in ' + pat.group(1) + ') echo LAND;; *) echo SKIP;; esac'
    values = ("propagated to fleet", "propagate FAILED", "propagate FAILED (streak 3)",
              "no propagation (nothing published)")
    got = {v: run(["bash", "-c", probe, "_", v], {}).stdout.strip() for v in values}
    assert got == {"propagated to fleet": "LAND", "propagate FAILED": "SKIP",
                   "propagate FAILED (streak 3)": "SKIP",
                   "no propagation (nothing published)": "SKIP"}, got
