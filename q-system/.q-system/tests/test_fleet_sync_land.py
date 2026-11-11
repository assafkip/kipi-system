"""fleet-sync-land.py: divergence check + landing through a worktree (ASK-4431).

Scar: the updater synced a client instance daily into branch a feature branch and
nothing pushed it; origin/main went 32 days without a sync and nothing alerted.
Every fixture here is a throwaway repo under tmp_path; HOME and the state dir are
redirected so no test reaches a live registry, instance or Linear.
"""
import json
import os
import subprocess
import time
from pathlib import Path

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


def commit(repo, env, msg, ts, fname):
    (repo / fname).write_text(msg + str(ts))
    run(["git", "add", "-A"], env, repo)
    stamp = f"@{int(ts)} +0000"
    r = run(["git", "commit", "-q", "-m", msg], env, repo,
            {"GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp})
    assert r.returncode == 0, r.stderr


def fixture(tmp, landed_days_ago):
    """origin carries a sync landed N days ago; the shared checkout sits on a feature
    branch holding a sync made now, plus a human's dirty and untracked files."""
    env = env_for(tmp)
    origin, seed, shared = tmp / "origin.git", tmp / "seed", tmp / "shared"
    run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], env)
    run(["git", "clone", "-q", str(origin), str(seed)], env)
    run(["git", "checkout", "-q", "-b", "main"], env, seed)
    commit(seed, env, "init", time.time() - 40 * 86400, "README")
    commit(seed, env, TAG, time.time() - landed_days_ago * 86400, "synced-old.txt")
    assert run(["git", "push", "-q", "origin", "main"], env, seed).returncode == 0
    run(["git", "clone", "-q", str(origin), str(shared)], env)
    url = "https://github.com/acme/inst.git"
    run(["git", "config", "remote.origin.url", url], env, shared)
    run(["git", "config", f"url.{origin}.insteadOf", url], env, shared)
    run(["git", "checkout", "-q", "-b", "a feature branch"], env, shared)
    commit(shared, env, TAG, time.time(), "synced-new.txt")
    (shared / "README").write_text("human edit, uncommitted")
    (shared / "case-051").mkdir()
    (shared / "case-051" / "notes.md").write_text("untracked human work")
    reg = tmp / "registry.json"
    reg.write_text(json.dumps({"skeleton": {"path": str(tmp)}, "instances": [
        {"name": "inst", "type": "subtree", "subtree_prefix": "q-system", "path": str(shared)}]}))
    notify = tmp / "notify.sh"
    notify.write_text(f'#!/bin/bash\nprintf "%s\\n" "$1" >> "{tmp}/notified.txt"\n')
    return env, origin, shared, {"KIPI_UPDATE_REGISTRY": str(reg), "KIPI_NOTIFY_CMD": str(notify),
                                 "KIPI_SYNC_LAND_STATE": str(tmp / "state")}


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
    # Fake updater: refuses (exit 9) if the registry still points at the shared
    # checkout, which is the defect this lander exists to avoid.
    updater = tmp_path / "fake-update.sh"
    updater.write_text(f"""#!/bin/bash
p=$(python3 -c 'import json,os;print([e["path"] for e in json.load(open(os.environ["KIPI_UPDATE_REGISTRY"]))["instances"] if e["name"]=="inst"][0])')
[ "$p" = "{shared}" ] && exit 9
mkdir -p "$p/q-system" && echo synced > "$p/q-system/new.txt"
git -C "$p" add -A && git -C "$p" commit -q -m "{TAG}"
""")
    gh = tmp_path / "gh"
    gh.write_text(f"""#!/bin/bash
echo "$*" >> "{tmp_path}/gh.log"
case "$1 $2" in "pr list") echo 0;; "pr create") echo https://github.com/acme/inst/pull/7;; esac
""")
    gh.chmod(0o755)
    extra.update(KIPI_UPDATE_SCRIPT=str(updater), KIPI_GH=str(gh))
    r = run(["python3", str(SCRIPT), "land"], env, extra=extra)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "OK inst: https://github.com/acme/inst/pull/7 (auto-merge armed)" in r.stdout
    branches = run(["git", "branch", "--list", "kipi/skeleton-sync-*"], env, origin).stdout.split()
    assert branches, "no landing branch reached origin"
    files = run(["git", "ls-tree", "-r", "--name-only", branches[-1]], env, origin).stdout
    assert "q-system/new.txt" in files and "synced-new.txt" not in files
    after = {k: run(["git", *a], env, shared).stdout for k, a in {
        "head": ["rev-parse", "HEAD"], "branch": ["symbolic-ref", "--short", "HEAD"],
        "status": ["status", "--porcelain"]}.items()}
    assert after == before
    log = (tmp_path / "gh.log").read_text()
    assert "pr create --repo acme/inst --base main" in log and "--auto" in log
    assert len(run(["git", "worktree", "list"], env, shared).stdout.splitlines()) == 1
