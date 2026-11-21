#!/usr/bin/env python3
"""Reproducer for ASK-5470: two PRs that each bump the same plugin version.

Hermetic: temp git repos only, no network, no live path.
Run: python3 test_plugin_bump_at_merge.py
"""
import json, os, subprocess, sys, tempfile

TOOL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "plugin-bump-at-merge.py")
PJ = "plugins/p/.claude-plugin/plugin.json"
FAIL = []


def sh(cwd, *a):
    return subprocess.run(a, cwd=cwd, capture_output=True, text=True)


def check(name, ok):
    print("[%s] %s" % ("PASS" if ok else "FAIL", name))
    if not ok:
        FAIL.append(name)


def write_pj(d, version, desc="d"):
    os.makedirs(os.path.dirname(os.path.join(d, PJ)), exist_ok=True)
    json.dump({"name": "p", "description": desc, "version": version}, open(os.path.join(d, PJ), "w"), indent=2)


def commit(d, msg):
    sh(d, "git", "add", "-A"); sh(d, "git", "commit", "-q", "-m", msg)


def repo(root):
    d = os.path.join(root, "w")
    sh(root, "git", "init", "-q", "-b", "main", d)
    sh(d, "git", "config", "user.email", "t@t"); sh(d, "git", "config", "user.name", "t")
    write_pj(d, "1.0.0"); open(os.path.join(d, "plugins/p/a.txt"), "w").write("a\n")
    open(os.path.join(d, "plugins/p/b.txt"), "w").write("b\n"); commit(d, "base")
    sh(d, "git", "update-ref", "refs/remotes/origin/main", "main")
    return d


def branch(d, name, fname, version, desc="d"):
    sh(d, "git", "checkout", "-q", "-b", name, "main")
    open(os.path.join(d, "plugins/p/" + fname), "a").write(name + "\n")
    write_pj(d, version, desc); commit(d, name)
    sh(d, "git", "checkout", "-q", "main")


def land(d, name):
    sh(d, "git", "merge", "-q", "--no-edit", name)
    sh(d, "git", "update-ref", "refs/remotes/origin/main", "main")


def ver(d):
    return json.load(open(os.path.join(d, PJ)))["version"]


def main():
    with tempfile.TemporaryDirectory() as root:
        # Case 1: different version lines is impossible; both write 1.0.1 and differ elsewhere.
        d = repo(root)
        branch(d, "A", "a.txt", "1.0.1"); branch(d, "B", "b.txt", "1.0.1")
        land(d, "A")
        sh(d, "git", "checkout", "-q", "B")
        # Control: the same state without the tool is EQUAL to main (the validate failure).
        check("control: B's version equals main's after A lands (what validate refuses)", ver(d) == "1.0.1")
        r = sh(d, "python3", TOOL, "--tree", d)
        check("equal-version PR: tool exits 0", r.returncode == 0)
        check("equal-version PR: ends strictly above main (1.0.2)", ver(d) == "1.0.2")
        # Case 2: conflict on the version line only (A bumps 1.0.1, C bumps 1.0.2 on a stale base).
        d2 = os.path.join(root, "w2"); os.makedirs(d2)
        d2 = repo(d2)
        branch(d2, "A", "a.txt", "1.0.1"); branch(d2, "C", "b.txt", "1.0.2")
        land(d2, "A")
        sh(d2, "git", "checkout", "-q", "C")
        ctl = sh(d2, "git", "merge", "--no-edit", "origin/main")
        check("control: plain merge of main into C conflicts", ctl.returncode != 0)
        sh(d2, "git", "merge", "--abort")
        r = sh(d2, "python3", TOOL, "--tree", d2)
        check("version-line conflict: tool exits 0", r.returncode == 0)
        check("version-line conflict: C keeps its own higher version (1.0.2)", ver(d2) == "1.0.2")
        # Case 3: conflict on the description too is refused and the tree is left clean.
        d3 = os.path.join(root, "w3"); os.makedirs(d3)
        d3 = repo(d3)
        branch(d3, "A", "a.txt", "1.0.1", desc="from A"); branch(d3, "E", "b.txt", "1.0.1", desc="from E")
        land(d3, "A")
        sh(d3, "git", "checkout", "-q", "E")
        r = sh(d3, "python3", TOOL, "--tree", d3)
        check("non-version conflict: tool exits 2", r.returncode == 2)
        check("non-version conflict: tree left clean", sh(d3, "git", "status", "--porcelain").stdout.strip() == "")
        # Case 4: dirty tree refused (unstaged manifest edit must not ride a version commit).
        d4 = os.path.join(root, "w4"); os.makedirs(d4)
        d4 = repo(d4)
        branch(d4, "G", "b.txt", "1.0.1"); land(d4, "G")
        branch(d4, "H", "a.txt", "1.0.1"); sh(d4, "git", "checkout", "-q", "H")
        write_pj(d4, "1.0.1", desc="WIP")
        r = sh(d4, "python3", TOOL, "--tree", d4)
        check("dirty tree: tool exits 2", r.returncode == 2)
        # Case 5: main deletes the manifest the branch edits (delete/modify): refuse, no merge left open.
        d5 = os.path.join(root, "w5"); os.makedirs(d5)
        d5 = repo(d5)
        branch(d5, "K", "a.txt", "1.0.1")
        sh(d5, "git", "rm", "-q", PJ); commit(d5, "retire"); sh(d5, "git", "update-ref", "refs/remotes/origin/main", "main")
        sh(d5, "git", "checkout", "-q", "K")
        r = sh(d5, "python3", TOOL, "--tree", d5)
        check("delete/modify conflict: tool exits 2", r.returncode == 2)
        check("delete/modify conflict: no merge left in progress", not os.path.exists(os.path.join(d5, ".git", "MERGE_HEAD")))
    print("FAILED: %s" % FAIL if FAIL else "all checks passed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
