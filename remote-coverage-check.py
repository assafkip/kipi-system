#!/usr/bin/env python3
"""Fleet remote-coverage gate: no repo's only copy lives on one disk.

Scar (2026-07-29): `kipi new` ran `git init` + local commits and NEVER created a
remote, so an instance's only copy was the laptop. The audit that found it turned
up 12 real remote-less repos, the oldest with 219 commits -- including client
engagements. Nothing detected it for months because inflow (kipi new) was
automated and outflow (gh repo create) was manual.

Why a gate and not auto-create-on-new: two of those repos MUST stay local
(a child's medical/education record, family travel data). An always-on
`gh repo create` would have published them. So creation stays opt-in and this
gate makes the remote-less state VISIBLE and DECIDED rather than silent.

Exit codes: 0 = every repo covered or explicitly allowlisted, 2 = at least one
undeclared remote-less repo (the gate's whole point), 1 = usage/internal error.
"""
import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REGISTRY = os.path.join(HERE, "instance-registry.json")
ALLOWLIST = os.path.join(HERE, "remote-coverage-allow.json")
DEFAULT_ROOT = os.path.expanduser("~/projects")

# Dirs never descended into. The .pr*rev* pattern is kipi-system's own PR-review
# worktree scratch, which creates throwaway repos by design.
SKIP = {"node_modules", "_archive", "_codex-worktrees", ".git", "venv", ".venv",
        "__pycache__", "dist", "build", ".next", "_archived", ".runs", "sites"}


def skip_dir(name):
    return name in SKIP or (name.startswith(".pr") and "rev" in name)


def git_out(args, cwd):
    try:
        p = subprocess.run(["git"] + args, cwd=cwd, capture_output=True,
                           text=True, timeout=30)
        return p.returncode, p.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return 1, ""


def find_repos(root):
    repos = []
    if not os.path.isdir(root):
        return repos
    if os.path.isdir(os.path.join(root, ".git")):
        repos.append(root)
    for dirpath, dirnames, _ in os.walk(root):
        dirnames[:] = [d for d in dirnames if not skip_dir(d)]
        for d in list(dirnames):
            full = os.path.join(dirpath, d)
            if os.path.isdir(os.path.join(full, ".git")):
                repos.append(full)
    return sorted(set(repos))


def load_allowlist():
    if not os.path.isfile(ALLOWLIST):
        return {}
    with open(ALLOWLIST) as fh:
        data = json.load(fh)
    return {os.path.expanduser(e["path"]): e for e in data.get("local_only", [])}


def registry_paths():
    if not os.path.isfile(REGISTRY):
        return set()
    with open(REGISTRY) as fh:
        data = json.load(fh)
    out = set()
    for e in data.get("instances", []):
        out.add(os.path.expanduser(e["path"]))
    return out


def audit(root):
    """Return (covered, uncovered, allowlisted). Uncovered = the gate failures."""
    allow = load_allowlist()
    reg = registry_paths()
    covered, uncovered, allowed = [], [], []
    for repo in find_repos(root):
        rc, remotes = git_out(["remote"], repo)
        # A repo with a filesystem-path remote (test sandbox origin) is NOT
        # off-disk coverage; treat only a real URL as covered.
        url = ""
        if remotes:
            _, url = git_out(["remote", "get-url", remotes.split()[0]], repo)
        offdisk = bool(url) and not url.startswith("/")
        _, ncommits = git_out(["rev-list", "--count", "HEAD"], repo)
        _, files = git_out(["ls-files"], repo)
        rec = {
            "path": repo,
            "remote": url or None,
            "commits": int(ncommits) if ncommits.isdigit() else 0,
            "tracked": len([x for x in files.splitlines() if x]),
            "registered_instance": repo in reg,
        }
        if offdisk:
            covered.append(rec)
        elif repo in allow:
            rec["reason"] = allow[repo].get("reason", "(no reason recorded)")
            allowed.append(rec)
        else:
            uncovered.append(rec)
    return covered, uncovered, allowed


# --- negative self-test ---------------------------------------------------

def self_test():
    """Prove the gate FAILS on a synthetic remote-less repo and PASSES once a
    remote exists. A gate never seen to fail is not a gate."""
    import tempfile
    ok = True
    with tempfile.TemporaryDirectory() as tmp:
        repo = os.path.join(tmp, "fake-instance")
        os.makedirs(repo)
        for a in (["init", "-q"], ["config", "user.email", "t@t"],
                  ["config", "user.name", "t"]):
            git_out(a, repo)
        open(os.path.join(repo, "f.txt"), "w").write("x")
        git_out(["add", "."], repo)
        git_out(["commit", "-qm", "seed"], repo)

        _, unc, _ = audit(tmp)
        if len(unc) != 1 or unc[0]["path"] != repo:
            print(f"FAIL: gate did NOT flag a remote-less repo (got {unc})")
            ok = False
        else:
            print("  negative case: remote-less repo correctly FLAGGED")

        git_out(["remote", "add", "origin",
                 "https://github.com/example/fake.git"], repo)
        cov, unc2, _ = audit(tmp)
        if unc2:
            print(f"FAIL: gate still flags a repo WITH a remote ({unc2})")
            ok = False
        else:
            print("  positive case: repo with remote correctly PASSES")

        # a filesystem-path remote must NOT count as off-disk coverage
        git_out(["remote", "set-url", "origin", os.path.join(tmp, "bare")], repo)
        _, unc3, _ = audit(tmp)
        if len(unc3) != 1:
            print("FAIL: filesystem-path remote wrongly counted as coverage")
            ok = False
        else:
            print("  path-remote case: local path correctly NOT coverage")
    print("SELF-TEST PASS" if ok else "SELF-TEST FAIL")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=DEFAULT_ROOT)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        return self_test()

    covered, uncovered, allowed = audit(args.root)

    if args.json:
        print(json.dumps({"covered": covered, "uncovered": uncovered,
                          "allowlisted": allowed}, indent=2))
        return 2 if uncovered else 0

    print(f"remote-coverage: {len(covered)} covered, "
          f"{len(allowed)} local-only (declared), {len(uncovered)} UNDECLARED")
    for r in allowed:
        print(f"  local-only  {r['path']}  -- {r['reason']}")
    if uncovered:
        print("\nRED: repos with no off-disk remote and no allowlist entry:")
        for r in sorted(uncovered, key=lambda x: -x["commits"]):
            tag = " [registered instance]" if r["registered_instance"] else ""
            print(f"  {r['path']}{tag}")
            print(f"      {r['commits']} commits, {r['tracked']} tracked files")
        print("\nFix each one of two ways:")
        print("  push it:   gh repo create assafkip/<name> --private "
              "--source=<path> --push")
        print(f"  declare it: add a path + reason to {ALLOWLIST}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
