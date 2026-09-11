"""Tests for disk_janitor.py, all against a fake HOME and temp base under tmp_path.

Nothing here touches a real path: HOME, the temp base, the log and the process
census are all injected through JANITOR_* env vars, and the notify sink is off.
The first test is the negative self-test: --dry with eligible targets must
delete nothing. A mutated copy that applies on --dry fails it (seen red on
2026-09-11 before the suite went green).
"""
import importlib.util
import json
import os
import subprocess
import time

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("disk_janitor", os.path.join(_HERE, "disk_janitor.py"))
dj = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dj)

NOW = 1_800_000_000.0  # fixed "now"; ages are set relative to it


def _age(path, days):
    """Set every mtime in the tree to NOW - days, so newest_mtime agrees."""
    t = NOW - days * dj.DAY
    for root, dirs, files in os.walk(path, followlinks=False):
        for name in dirs + files:
            p = os.path.join(root, name)
            if not os.path.islink(p):
                os.utime(p, (t, t))
    os.utime(path, (t, t))


def _tree(path, nfiles=3, size=1024):
    os.makedirs(path, exist_ok=True)
    for i in range(nfiles):
        with open(os.path.join(path, "f%d" % i), "wb") as fh:
            fh.write(b"x" * size)
    return path


def _git(*args, cwd):
    return subprocess.run(["git"] + list(args), cwd=cwd, capture_output=True, text=True, check=True)


def _repo_with_worktrees(base, wt_dir, names):
    """A real repo plus one linked worktree per name, created IN PLACE under
    wt_dir, so the git gate and `git worktree prune` run against the real thing.
    (First draft created them elsewhere and renamed the folder; git's admin
    entries still pointed at the old paths, so prune dropped the dirty one too
    and the test failed for a reason that had nothing to do with the janitor.)"""
    repo = os.path.join(base, "repo")
    os.makedirs(repo)
    _git("init", "-q", cwd=repo)
    _git("config", "user.email", "t@example.com", cwd=repo)
    _git("config", "user.name", "t", cwd=repo)
    with open(os.path.join(repo, "README"), "w") as fh:
        fh.write("x\n")
    _git("add", "README", cwd=repo)
    _git("commit", "-qm", "init", cwd=repo)
    os.makedirs(wt_dir, exist_ok=True)
    wts = {}
    for n in names:
        p = os.path.join(wt_dir, n)
        _git("worktree", "add", "-q", "-b", "wt-" + n, p, cwd=repo)
        wts[n] = p
    return repo, wts


@pytest.fixture
def env(tmp_path, monkeypatch):
    home = tmp_path / "home"
    tmpbase = tmp_path / "tmpbase"
    (tmpbase / "T").mkdir(parents=True)
    (tmpbase / "X").mkdir(parents=True)
    home.mkdir()
    monkeypatch.setenv("JANITOR_HOME", str(home))
    monkeypatch.setenv("JANITOR_TMPBASE", str(tmpbase))
    monkeypatch.setenv("JANITOR_NOW", str(NOW))
    monkeypatch.setenv("JANITOR_LOG", str(tmp_path / "janitor.log"))
    monkeypatch.setenv("JANITOR_LIVE", "[]")
    monkeypatch.setenv("JANITOR_NO_OPENFILES", "1")
    monkeypatch.setenv("JANITOR_NO_NOTIFY", "1")
    return {"home": str(home), "tmp": str(tmpbase), "log": str(tmp_path / "janitor.log"),
            "root": str(tmp_path)}


def _log_lines(env):
    with open(env["log"]) as fh:
        return [json.loads(l) for l in fh if l.strip()]


# ---------------------------------------------------------------------------

def test_dry_run_deletes_nothing(env):
    """Negative self-test: eligible targets exist, --dry must leave them all."""
    old = _tree(os.path.join(env["tmp"], "T", "tmpabcd1234"))
    _age(old, 5)
    old2 = _tree(os.path.join(env["home"], ".npm", "_npx", "deadbeef"))
    _age(old2, 40)
    rc = dj.main(["--dry"])
    assert rc == 0
    assert os.path.isdir(old) and os.path.isdir(old2)
    acts = [l for l in _log_lines(env) if "action" in l]
    assert sorted(a["action"] for a in acts) == ["would-delete", "would-delete"]
    assert not any(a["action"] == "delete" for a in acts)


def test_apply_removes_only_eligible_tmp_dirs(env):
    T = os.path.join(env["tmp"], "T")
    old = _tree(os.path.join(T, "tmpabcd1234"))
    _age(old, 3)
    young = _tree(os.path.join(T, "tmpyoung123"))
    _age(young, 0.5)
    shell_young = _tree(os.path.join(T, "tmp.ABCdef1234"))
    _age(shell_young, 3)              # shell rule wants 7 days
    other = _tree(os.path.join(T, "notatmpdir"))
    _age(other, 90)
    still_writing = _tree(os.path.join(T, "tmpwriting1"))
    _age(still_writing, 10)
    with open(os.path.join(still_writing, "fresh"), "w") as fh:   # newest file is now
        fh.write("x")
    os.utime(os.path.join(still_writing, "fresh"), (NOW, NOW))
    # a symlink whose NAME matches, pointing at real data elsewhere
    target = _tree(os.path.join(env["root"], "precious"))
    link = os.path.join(T, "tmplinkabcd")
    os.symlink(target, link)

    rc = dj.main(["--apply"])
    assert rc == 0
    assert not os.path.exists(old)
    assert os.path.isdir(young)
    assert os.path.isdir(shell_young)
    assert os.path.isdir(other)
    assert os.path.isdir(still_writing), "newest-mtime age must protect a tree still being written"
    assert os.path.islink(link) and os.path.isdir(target) and len(os.listdir(target)) == 3
    acts = {l["path"]: l["action"] for l in _log_lines(env) if "action" in l}
    assert acts[old] == "delete"
    assert acts[link] == "skip"


def test_git_gate_keeps_dirty_and_young_and_prunes_deleted(env):
    wt_root = os.path.join(env["home"], ".config", "kipi", "worktrees")
    repo, paths = _repo_with_worktrees(env["root"], wt_root, ["clean-old", "dirty-old", "clean-young"])
    with open(os.path.join(paths["dirty-old"], "unsaved.txt"), "w") as fh:
        fh.write("work in progress\n")
    _age(paths["clean-old"], 30)
    _age(paths["dirty-old"], 30)
    _age(paths["clean-young"], 2)

    rc = dj.main(["--apply", "--rules", "kipi-worktrees"])
    assert rc == 0
    assert not os.path.exists(paths["clean-old"])
    assert os.path.isdir(paths["dirty-old"]), "dirty checkout must survive"
    assert os.path.isdir(paths["clean-young"])
    listed = _git("worktree", "list", cwd=repo).stdout
    assert "clean-old" not in listed, "git worktree prune must have run on the parent repo"
    assert "dirty-old" in listed
    reasons = {l["path"]: l.get("reason") for l in _log_lines(env) if l.get("action") == "skip"}
    assert reasons[paths["dirty-old"]] == "dirty git checkout"


def test_live_process_gate(env, monkeypatch):
    """A dir holding any open file or cwd of a live process is skipped."""
    old = _tree(os.path.join(env["tmp"], "T", "tmplive12345"))
    _age(old, 10)
    monkeypatch.setenv("JANITOR_LIVE", json.dumps([os.path.join(old, "sub", "out.log")]))
    rc = dj.main(["--apply", "--rules", "tmp-mkdtemp"])
    assert rc == 0
    assert os.path.isdir(old)
    skips = [l for l in _log_lines(env) if l.get("action") == "skip"]
    assert skips and skips[0]["reason"] == "held by a live process"


def test_refuses_parent_outside_roots(env, monkeypatch):
    outside = _tree(os.path.join(env["root"], "outside", "victim"))
    _age(outside, 100)
    rule = dj.Rule("rogue", [os.path.join(env["root"], "outside")], min_age_days=1)
    monkeypatch.setattr(dj, "RULES", [rule])
    rc = dj.main(["--apply"])
    assert rc == 0
    assert os.path.isdir(outside), "a parent outside HOME/TMP must be refused, never deleted"
    acts = [l for l in _log_lines(env) if "action" in l]
    assert acts and acts[0]["action"] == "refuse"


def test_file_rules_recursive_and_lock_files(env):
    sess = os.path.join(env["home"], ".codex", "sessions", "2026", "07")
    os.makedirs(sess)
    old_f = os.path.join(sess, "a.jsonl")
    young_f = os.path.join(sess, "b.jsonl")
    for p in (old_f, young_f):
        with open(p, "w") as fh:
            fh.write("{}\n")
    os.utime(old_f, (NOW - 45 * dj.DAY,) * 2)
    os.utime(young_f, (NOW - 5 * dj.DAY,) * 2)
    rt = os.path.join(env["home"], ".config", "kipi", "review-trees")
    os.makedirs(rt)
    lock = os.path.join(rt, "pr-9.lock")
    with open(lock, "w") as fh:
        fh.write("1\n")
    os.utime(lock, (NOW - 20 * dj.DAY,) * 2)

    rc = dj.main(["--apply", "--rules", "codex-sessions,review-tree-locks"])
    assert rc == 0
    assert not os.path.exists(old_f)
    assert os.path.exists(young_f)
    assert not os.path.exists(lock)


def test_summary_line_and_unknown_rule(env, capsys):
    old = _tree(os.path.join(env["tmp"], "T", "tmpsummary1"))
    _age(old, 4)
    assert dj.main(["--dry", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["mode"] == "dry" and out["targets"] == 1 and out["errors"] == 0
    last = _log_lines(env)[-1]
    assert "summary" in last and last["summary"]["targets"] == 1
    assert dj.main(["--dry", "--rules", "nope"]) == 2
