#!/usr/bin/env python3
"""Pairs with fleet-health-daily.py: stranded commits (ASK-773), sweep split (ASK-776).

Every repo here is a throwaway under a temp dir with a throwaway bare remote, and
the sweep history is a temp file. Nothing reads or writes a live repo or the live
history, and nothing is filed: the detectors' pure halves are called directly.

Run: python3 test-fleet-health-stranded-sweep.py   (exit 0 = pass)
"""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HEALTH = Path(__file__).resolve().parents[1] / "fleet-health-daily.py"
_spec = importlib.util.spec_from_file_location("fh", HEALTH)
fh = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fh)

failures = []


def check(name, got, want):
    if got != want:
        failures.append(f"{name}: got {got!r}, want {want!r}")
    else:
        print(f"  ok: {name}")


ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
ENV.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t.t",
           GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t.t")


def git(repo, *args, when=None):
    env = dict(ENV)
    if when is not None:
        env["GIT_COMMITTER_DATE"] = env["GIT_AUTHOR_DATE"] = f"{int(when)} +0000"
    return subprocess.run(["git", "-C", str(repo), "-c", "commit.gpgsign=false", *args],
                          capture_output=True, text=True, check=True, env=env).stdout.strip()


def commit(repo, name, when=None):
    (Path(repo) / name).write_text(name + "\n")
    git(repo, "add", name)
    git(repo, "commit", "-qm", name, when=when)
    return git(repo, "rev-parse", "HEAD")


NOW = time.time()
OLD = NOW - 2 * 86400

tmp = Path(tempfile.mkdtemp())
bare = tmp / "remote.git"
subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True, env=ENV)
repo = tmp / "repo"
subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True, env=ENV)
git(repo, "remote", "add", "origin", str(bare))
pushed = commit(repo, "a", when=OLD)
git(repo, "push", "-q", "origin", "main")
git(repo, "checkout", "-q", "-b", "feat")
git(repo, "push", "-q", "-u", "origin", "feat")

# Someone else advances origin/feat, so this checkout's feat falls BEHIND. That
# is the sp-85446513 scar: a branch 15 behind origin took an unpushed commit.
other = tmp / "other"
subprocess.run(["git", "clone", "-q", "-b", "feat", str(bare), str(other)], check=True, env=ENV)
commit(other, "upstream-moved", when=OLD)
git(other, "push", "-q", "origin", "feat")
git(repo, "fetch", "-q", "origin")
stranded = commit(repo, "b", when=OLD)           # ahead 1, behind 1, old: the case

# Ahead-only: an ordinary pending push (and every instance's local exhaust).
git(repo, "checkout", "-q", "-b", "ahead-only", "main")
git(repo, "push", "-q", "-u", "origin", "ahead-only")
ahead_only = commit(repo, "d", when=OLD)
# Never pushed, or its remote branch deleted after a squash merge: no counterpart.
git(repo, "checkout", "-q", "-b", "no-counterpart", "main")
orphan = commit(repo, "e", when=OLD)

# --- ASK-773 ---------------------------------------------------------------
found = fh.stranded_findings([repo], NOW)
body = found[0]["body"] if found else ""
check("a diverged branch's old unpushed commit is reported", len(found), 1)
check("it names the stranded sha", stranded[:10] in body, True)
check("a pushed commit is not reported", pushed[:10] in body, False)
check("an ahead-only branch is a pending push, not stranded", ahead_only[:10] in body, False)
check("a branch with no remote counterpart is not reported", orphan[:10] in body, False)
check("the branch name is not carried (ASK-204)", "feat" in body, False)
check("one finding per repo, keyed by the repo", found[0]["subject"] if found else None,
      f"stranded-{repo}")

# Fresh unpushed work on a diverged branch is in flight, not stranded.
git(repo, "checkout", "-q", "feat")
fresh = commit(repo, "c", when=NOW - 60)
body = (fh.stranded_findings([repo], NOW) or [{"body": ""}])[0]["body"]
check("a commit inside the grace window is not reported", fresh[:10] in body, False)

lonely = tmp / "lonely"
subprocess.run(["git", "init", "-q", "-b", "main", str(lonely)], check=True, env=ENV)
commit(lonely, "x", when=OLD)
check("a repo with no remote is skipped, not flagged", fh.stranded_findings([lonely], NOW), [])

# An inherited GIT_DIR must not rebind every repo to one answer.
os.environ["GIT_DIR"] = str(lonely / ".git")
try:
    rebound = fh.stranded_findings([repo], NOW)
finally:
    del os.environ["GIT_DIR"]
check("an inherited GIT_DIR does not rebind the repo", len(rebound), 1)

git(repo, "merge", "-q", "--no-edit", "origin/feat")
git(repo, "push", "-q", "origin", "feat")
check("once merged and pushed, silence", fh.stranded_findings([repo], NOW), [])

reg = tmp / "registry.json"
reg.write_text(json.dumps({"instances": [
    {"name": "i1", "path": str(repo)},
    {"name": "gone", "path": str(tmp / "missing")},
    {"name": "old", "path": str(lonely), "status": "merged-into-x"},
]}))
repos = fh.fleet_repos(reg)
check("registry instances are covered", repo in repos, True)
check("merged and missing instances are not", (lonely in repos, tmp / "missing" in repos),
      (False, False))
check("the skeleton checkout is always covered", fh.REPO_ROOT in repos, True)


# --- ASK-776 ---------------------------------------------------------------
def row(mode="real", updated=20, failed=0, names=(), only="", ts="t"):
    return {"ts": ts, "mode": mode, "skeleton_sha": "abc", "updated": updated,
            "failed": failed, "skipped": 0, "only": only, "failed_names": list(names)}


subjects = lambda rows: sorted(f["subject"] for f in fh.sweep_findings(rows))
check("all green is silent", subjects([row(), row()]), [])
check("no history is silent", subjects([]), [])
check("a degraded ratio fires", subjects([row(updated=6, failed=3, names="xyz")]),
      ["sweep-ratio"])
check("a newly failing instance fires, a standing one does not",
      subjects([row(updated=21, failed=1, names=["a"]),
                row(updated=20, failed=2, names=["a", "b"])]),
      ["sweep-regressed-b"])
check("an unchanged standing refusal is silent on day 2",
      subjects([row(updated=21, failed=2, names=["a", "b"]),
                row(updated=21, failed=2, names=["a", "b"])]), [])
check("a dry row is never compared with a real one",
      subjects([row(mode="real"), row(mode="dry", updated=22, failed=1, names=["x"])]), [])
check("an --only run is ignored",
      subjects([row(), row(updated=0, failed=1, names=["x"], only="x")]), [])

hist = tmp / "history.jsonl"
hist.write_text(json.dumps(row()) + "\n{torn\n" + json.dumps(row(ts="t2")) + "\n")
check("a torn line is skipped, the rest are read",
      [r["ts"] for r in fh.read_sweep_history(hist)], ["t", "t2"])
check("a missing history file reads as empty", fh.read_sweep_history(tmp / "nope"), [])

by_id = {d["id"]: d for d in fh.DETECTORS}
check("both detectors are registered",
      ("stranded-commits" in by_id, "sweep-degraded" in by_id), (True, True))
check("the registry still validates", fh.validate_detectors(), [])

if failures:
    print("FAIL:")
    for line in failures:
        print(f"  - {line}")
    sys.exit(1)
print("PASS: stranded commits and sweep degradation are detected")
sys.exit(0)
