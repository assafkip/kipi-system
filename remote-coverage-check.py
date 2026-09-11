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


def is_repo_root(path):
    """True when `path` is the root of a git checkout.

    `.git` is a DIRECTORY in a normal clone but a FILE ("gitdir: ...") in a git
    worktree and in a submodule. Probing with isdir() therefore reported every
    live worktree as "no enclosing git repo", which is the loudest possible
    wrong answer: the gate told you to `git init` a fresh repo inside another
    repo's checkout. Scar 2026-08-08 -- 8 kipi-system worktrees, 24 RED rows.
    """
    return os.path.exists(os.path.join(path, ".git"))


def find_repos(root):
    repos = []
    if not os.path.isdir(root):
        return repos
    if is_repo_root(root):
        repos.append(root)
    for dirpath, dirnames, _ in os.walk(root):
        dirnames[:] = [d for d in dirnames if not skip_dir(d)]
        for d in list(dirnames):
            full = os.path.join(dirpath, d)
            if is_repo_root(full):
                repos.append(full)
    return sorted(set(repos))


# A directory carrying one of these is a real project root, not a subfolder.
PROJECT_MARKERS = ("CLAUDE.md", "package.json", "pyproject.toml", "go.mod",
                   "Cargo.toml", "requirements.txt", "Gemfile", "pom.xml")

# Path segments that are legitimately untracked INSIDE a repo. A candidate whose
# path (relative to its enclosing repo) crosses one of these is build output,
# synced plugin content, or scratch -- not an uncovered project.
NOISE_SEG = {"plugins", "node_modules", ".claude", "dist", "build", "out",
             ".next", "worktrees", "gated", "_archive", "venv", ".venv",
             "sites", ".runs", "output", "__pycache__", "vendor", "tools",
             "template-repo", "_codex-worktrees", "spikes", "fixtures", "test",
             "tests", "examples", "eval", "adoption", "site-packages",
             ".agents", "capture", "videos"}

# Directory names that hold projects rather than being one. A dir sitting in a
# `<container>/<name>` slot is a candidate project even when the parent repo
# ignores the whole container.
PROJECT_CONTAINERS = {"projects", "products", "apps", "packages", "services"}


def enclosing_repo(path, repo_set):
    """Nearest STRICT ancestor that is a git repo."""
    cur = os.path.dirname(path)
    while cur and cur != "/":
        if cur in repo_set:
            return cur
        cur = os.path.dirname(cur)
    return None


def find_uncovered_dirs(root, repo_set, allow):
    """Class (b): project dirs that are not repos and not tracked by a parent.

    Two ways to be uncovered, and the second is the subtle one:
      1. No enclosing repo at all.
      2. An enclosing repo exists but tracks ZERO files under this path --
         e.g. ~/projects/personal/.gitignore line 1 is `projects/`, so every
         nested instance looks covered and is actually invisible. Checking for
         an ancestor .git is NOT enough; we ask git what it actually tracks.
    """
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not skip_dir(d)]
        if dirpath in repo_set or not any(m in filenames for m in PROJECT_MARKERS):
            continue
        if os.path.expanduser(dirpath) in allow:
            continue
        parent = enclosing_repo(dirpath, repo_set)
        if parent is None:
            out.append({"path": dirpath, "parent_repo": None,
                        "why": "no enclosing git repo"})
            continue
        rel = os.path.relpath(dirpath, parent)
        parts = rel.split(os.sep)
        if set(parts) & NOISE_SEG:
            continue
        # An ignored dir inside a repo is USUALLY deliberate: a venv, capture
        # output, generated reports. Flagging all of them buries the one shape
        # that matters, so only a PROJECT-CONTAINER slot counts: `<name>` at the
        # repo root, or `<container>/<name>`. That is exactly the scar --
        # ~/projects/personal/.gitignore line 1 is `projects/`, so every real
        # instance under it is invisible while an ancestor .git says "covered".
        # A venv at skills/osint/face-env is depth 3 and correctly ignored here.
        if not (len(parts) == 1 or
                (len(parts) == 2 and parts[0] in PROJECT_CONTAINERS)):
            continue
        rc, tracked = git_out(["ls-files", "--", rel], parent)
        if rc == 0 and not tracked.strip():
            _, rule = git_out(["check-ignore", "-v", rel], parent)
            why = "parent repo tracks 0 files here"
            if rule.count(":") >= 2:
                bits = rule.split(":")
                why += f" (ignored by {os.path.basename(bits[0])}:{bits[1]})"
            out.append({"path": dirpath, "parent_repo": parent, "why": why})
    return out


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
    """Return (covered, uncovered, allowlisted, nonrepo).

    Two failure classes, both gate failures:
      uncovered = repos with no off-disk remote (class a)
      nonrepo   = project dirs that are not repos and not tracked (class b)
    """
    allow = load_allowlist()
    reg = registry_paths()
    covered, uncovered, allowed = [], [], []
    repos = find_repos(root)
    for repo in repos:
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
    nonrepo = find_uncovered_dirs(root, set(repos), allow)
    return covered, uncovered, allowed, nonrepo


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

        _, unc, _, _ = audit(tmp)
        if len(unc) != 1 or unc[0]["path"] != repo:
            print(f"FAIL: gate did NOT flag a remote-less repo (got {unc})")
            ok = False
        else:
            print("  [a] negative case: remote-less repo correctly FLAGGED")

        git_out(["remote", "add", "origin",
                 "https://github.com/example/fake.git"], repo)
        cov, unc2, _, _ = audit(tmp)
        if unc2:
            print(f"FAIL: gate still flags a repo WITH a remote ({unc2})")
            ok = False
        else:
            print("  [a] positive case: repo with remote correctly PASSES")

        # a filesystem-path remote must NOT count as off-disk coverage
        git_out(["remote", "set-url", "origin", os.path.join(tmp, "bare")], repo)
        _, unc3, _, _ = audit(tmp)
        if len(unc3) != 1:
            print("FAIL: filesystem-path remote wrongly counted as coverage")
            ok = False
        else:
            print("  [a] path-remote case: local path correctly NOT coverage")

    # --- class (b) ---
    with tempfile.TemporaryDirectory() as tmp:
        # b1: a project dir with NO enclosing repo at all
        orphan = os.path.join(tmp, "orphan-app")
        os.makedirs(orphan)
        open(os.path.join(orphan, "package.json"), "w").write("{}")

        # b2: the parent-.gitignore trap -- a project nested inside a repo whose
        # .gitignore excludes the whole container, so an ancestor .git EXISTS
        # but tracks nothing here. This is the case that hid deliverables.
        parent = os.path.join(tmp, "persona")
        nested = os.path.join(parent, "projects", "hidden-app")
        os.makedirs(nested)
        for a in (["init", "-q"], ["config", "user.email", "t@t"],
                  ["config", "user.name", "t"]):
            git_out(a, parent)
        open(os.path.join(parent, ".gitignore"), "w").write("projects/\n")
        open(os.path.join(parent, "CLAUDE.md"), "w").write("persona")
        open(os.path.join(nested, "CLAUDE.md"), "w").write("hidden")
        git_out(["add", "."], parent)
        git_out(["commit", "-qm", "seed"], parent)

        _, _, _, nonrepo = audit(tmp)
        found = {r["path"] for r in nonrepo}
        if orphan not in found:
            print("FAIL: [b] orphan project dir with no enclosing repo NOT flagged")
            ok = False
        else:
            print("  [b] orphan dir (no enclosing repo) correctly FLAGGED")
        if nested not in found:
            print("FAIL: [b] parent-.gitignore case NOT flagged -- an ancestor "
                  ".git made it look covered. This is the deliverables hole.")
            ok = False
        else:
            print("  [b] parent-gitignored nested project correctly FLAGGED")
        # the parent repo itself IS tracked, so it must NOT be flagged
        if parent in found:
            print("FAIL: [b] a properly tracked repo root was flagged")
            ok = False
        else:
            print("  [b] tracked parent repo correctly NOT flagged")

    # b3: a git WORKTREE of a covered repo. Its `.git` is a FILE ("gitdir: ..."),
    # not a directory, so an isdir() probe reports "no enclosing git repo" and
    # the gate demands you seed a new repo inside someone else's checkout.
    # Scar 2026-08-08: 8 live kipi-system worktrees (24 rows) sat RED for a week
    # for this reason alone, and a permanently-red gate is a gate nobody reads.
    with tempfile.TemporaryDirectory() as tmp:
        main_repo = os.path.join(tmp, "main-repo")
        os.makedirs(main_repo)
        for a in (["init", "-q"], ["config", "user.email", "t@t"],
                  ["config", "user.name", "t"]):
            git_out(a, main_repo)
        open(os.path.join(main_repo, "CLAUDE.md"), "w").write("main")
        git_out(["add", "."], main_repo)
        git_out(["commit", "-qm", "seed"], main_repo)
        git_out(["remote", "add", "origin",
                 "https://github.com/example/fake.git"], main_repo)
        wt = os.path.join(tmp, "main-repo-wt-feature")
        git_out(["worktree", "add", "-q", "--detach", wt], main_repo)

        cov, _, _, nonrepo = audit(tmp)
        found = {r["path"] for r in nonrepo}
        if wt in found:
            print("FAIL: [b] a git WORKTREE of a covered repo was flagged as "
                  "'not a git repo' -- .git is a file in a worktree, not a dir")
            ok = False
        else:
            print("  [b] git worktree of a covered repo correctly NOT flagged")
        if wt not in {r["path"] for r in cov}:
            print("FAIL: [b] worktree not counted as a covered repo")
            ok = False
        else:
            print("  [b] git worktree correctly counted as covered")

    print("SELF-TEST PASS" if ok else "SELF-TEST FAIL")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=DEFAULT_ROOT)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--declare", metavar="PATH",
                    help="record PATH as deliberately local-only")
    ap.add_argument("--reason", help="required with --declare")
    args = ap.parse_args()

    if args.self_test:
        return self_test()

    if args.declare:
        # Single-writer chokepoint: every allowlist entry is written HERE, so
        # the reason field can never be skipped by a caller hand-editing JSON.
        if not args.reason or len(args.reason.strip()) < 20:
            print("ERROR: --reason is required and must be a real sentence "
                  "(>=20 chars). An entry without an arguable reason is a mute "
                  "button, not a decision.", file=sys.stderr)
            return 1
        # The allowlist is committed to a PUBLIC repo. Name the data CLASS and
        # the carrier path, never the private content itself.
        import datetime
        with open(ALLOWLIST) as fh:
            data = json.load(fh)
        tgt = args.declare.rstrip("/")
        home = os.path.expanduser("~")
        if tgt.startswith(home):
            tgt = "~" + tgt[len(home):]
        if any(e["path"] == tgt for e in data["local_only"]):
            print(f"already declared: {tgt}")
            return 0
        data["local_only"].append({
            "path": tgt,
            "reason": args.reason.strip(),
            "declared": datetime.date.today().isoformat(),
            "review": "Re-decide when the blocking condition changes.",
        })
        with open(ALLOWLIST, "w") as fh:
            json.dump(data, fh, indent=2)
            fh.write("\n")
        print(f"declared local-only: {tgt}")
        return 0

    covered, uncovered, allowed, nonrepo = audit(args.root)

    if args.json:
        print(json.dumps({"covered": covered, "uncovered": uncovered,
                          "allowlisted": allowed, "not_a_repo": nonrepo},
                         indent=2))
        return 2 if (uncovered or nonrepo) else 0

    print(f"remote-coverage: {len(covered)} covered, "
          f"{len(allowed)} local-only (declared), {len(uncovered)} UNDECLARED, "
          f"{len(nonrepo)} NOT-A-REPO")
    for r in allowed:
        print(f"  local-only  {r['path']}  -- {r['reason']}")
    if uncovered:
        print("\nRED [class a]: repos with no off-disk remote, not declared:")
        for r in sorted(uncovered, key=lambda x: -x["commits"]):
            tag = " [registered instance]" if r["registered_instance"] else ""
            print(f"  {r['path']}{tag}")
            print(f"      {r['commits']} commits, {r['tracked']} tracked files")
    if nonrepo:
        print("\nRED [class b]: project dirs that are not git repos at all:")
        for r in sorted(nonrepo, key=lambda x: x["path"]):
            print(f"  {r['path']}")
            print(f"      {r['why']}")
    if uncovered or nonrepo:
        print("\nFix each one of two ways:")
        print("  track + push:  git -C <path> init && git -C <path> add -A && "
              "git -C <path> commit -m 'Seed'")
        print("                 gh repo create assafkip/<name> --private "
              "--source=<path> --push")
        print(f"  or declare it: add a path + reason to {ALLOWLIST}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
