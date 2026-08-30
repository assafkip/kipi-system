#!/usr/bin/env python3
"""Self-test for merge-bypass-gate.py.

Every case asserts the SPECIFIC decision it expects, never merely "something
happened". An assertion that accepts any refusal cannot tell the branch it means
to test from an unrelated crash.

Hermetic: builds real git repos in a temp dir and points their `origin` at a
github.com URL that is never contacted (the gate only reads `remote get-url`).
No live data path, no network.

Run: python3 test_merge_bypass_gate.py
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# Same loader shape as test_blocked_claim_evidence_lint.py: the module under test
# has a hyphenated filename, so it is loaded by path rather than imported.
GATE = Path(__file__).resolve().parent / "merge-bypass-gate.py"
_spec = importlib.util.spec_from_file_location("merge_bypass_gate", GATE)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
classify = _mod.classify


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args],
                   check=True, capture_output=True, text=True)


def _make_repo(root: Path, name: str, origin: str, branch: str) -> Path:
    repo = root / name
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", branch)
    _git(repo, "config", "user.email", "t@t.test")
    _git(repo, "config", "user.name", "t")
    (repo / "f.txt").write_text("x\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "seed")
    _git(repo, "remote", "add", "origin", origin)
    return repo


GH = "https://github.com/example/repo.git"
# The push deny is scoped to protected remotes (sp-9154c64d). Pin the fixture
# repo into the set so every existing deny case still exercises the deny path;
# the scoping itself is tested against GH_OTHER / GH_WEIRD below.
os.environ["MERGE_GATE_PROTECTED_REPOS"] = "example/repo"
GH_OTHER = "https://github.com/other/standalone.git"
GH_WEIRD = "https://github.com/justowner"

FAILURES: list[str] = []
CHECKS = 0


def check(name: str, command: str, cwd: Path, want: str) -> None:
    global CHECKS
    CHECKS += 1
    got, reason = classify(command, str(cwd))
    if got != want:
        FAILURES.append(
            f"{name}\n    command : {command}\n    want    : {want}\n"
            f"    got     : {got}\n    reason  : {reason}")


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        # A repo that looks like ours: github origin, sitting on a feature branch.
        gh_feature = _make_repo(root, "gh_feature", GH, "sana/feature")
        # Same, but checked out ON main -- the bare `git push` case.
        gh_main = _make_repo(root, "gh_main", GH, "main")
        # The shape every test script in this repo uses: origin is a local path.
        local_origin = _make_repo(root, "local", str(root / "bare.git"), "main")
        # A GitHub repo OUTSIDE the protected set (a personal standalone repo):
        # no required checks exist there, so the push deny must not fire.
        gh_other = _make_repo(root, "gh_other", GH_OTHER, "main")
        # A GitHub URL the owner/name parser cannot read: stays protected.
        gh_weird = _make_repo(root, "gh_weird", GH_WEIRD, "main")
        # A FLEET INSTANCE: unlisted remote, but q-system/ in the tree. The
        # hook ships to every instance, so the marker must deny on its own
        # (PR #226 review, major).
        gh_fleet = _make_repo(root, "gh_fleet", GH_OTHER, "main")
        (gh_fleet / "q-system").mkdir()
        # Same protected repo under different URL casing and a .git suffix:
        # GitHub treats these as one repo, so must the set.
        gh_cased = _make_repo(root, "gh_cased",
                              "https://github.com/EXAMPLE/REPO.git", "main")

        # --- the bypass forms: must DENY ---
        check("admin flag last", "gh pr merge 999 --squash --admin", gh_feature, "deny")
        check("admin flag first", "gh pr merge --admin --squash 999", gh_feature, "deny")
        check("admin flag middle", "gh pr merge 12 --admin -s", gh_feature, "deny")
        check("push main", "git push origin main", gh_feature, "deny")
        check("push -u main", "git push -u origin main", gh_feature, "deny")
        check("push HEAD:main", "git push origin HEAD:main", gh_feature, "deny")
        check("push master", "git push origin master", gh_feature, "deny")
        check("push refspec main:main", "git push origin main:main", gh_feature, "deny")
        check("bare push while on main", "git push", gh_main, "deny")
        check("push by URL", f"git push {GH} main", gh_feature, "deny")
        check("admin after a chained cd",
              f"cd {gh_feature} && gh pr merge 3 --admin", root, "deny")
        check("push main via git -C",
              f"git -C {gh_feature} push origin main", root, "deny")
        check("env prefix does not hide it",
              "FOO=1 git push origin main", gh_feature, "deny")

        # --- the autonomous path and not-applicable: must ALLOW ---
        check("auto merge", "gh pr merge --auto --squash 999", gh_feature, "allow")
        check("auto merge, no admin", "gh pr merge 999 --auto -s", gh_feature, "allow")
        check("feature branch push",
              "git push -u origin sana/some-branch", gh_feature, "allow")
        check("bare push while on a feature branch", "git push", gh_feature, "allow")
        check("local git merge", "git merge origin/main", gh_feature, "allow")
        check("gh pr create", "gh pr create --title x --body y", gh_feature, "allow")
        check("pr list", "gh pr list --state open", gh_feature, "allow")

        # The false positive that would make this gate get switched off: the flag
        # appears only inside a quoted argument, so argv never contains it.
        check("admin quoted in a body string",
              "gh pr create --title x --body 'never use --admin here'",
              gh_feature, "allow")
        # DENY under the allowlist. --body takes a value, and admitting
        # value-taking flags is where grammar modelling creeps back in on the
        # side that can produce a bypass. Keeping the permitted set minimal
        # costs a rare rephrase; the deny message names the shape to use.
        check("body flag on a merge is not in the permitted set",
              "gh pr merge 9 --auto --body 'do not --admin this'",
              gh_feature, "deny")

        # THE carve-out that keeps this repo's own test scripts green: a local
        # origin is not GitHub, so pushing main there is nobody's bypass.
        check("push main to a local origin",
              "git push origin main", local_origin, "allow")
        # GitHub, but outside the protected set: the checks the deny protects do
        # not exist there, so the push is allowed (sp-9154c64d).
        check("push main to an unprotected github repo",
              "git push origin main", gh_other, "allow")
        check("push master to an unprotected github repo",
              "git push origin master", gh_other, "allow")
        # GitHub URL the parser cannot read: fail closed, still denied.
        check("push main to an unparseable github url",
              "git push origin main", gh_weird, "deny")
        # Fleet marker alone denies, remote set not consulted.
        check("push main in a fleet-marker tree with an unlisted remote",
              "git push origin main", gh_fleet, "deny")
        # The marker lives at the WORKTREE ROOT: a push from a subdirectory
        # must still see it (PR #226 review round 2, major).
        (gh_fleet / "sub").mkdir()
        check("push main from a subdirectory of a fleet-marker tree",
              "git push origin main", gh_fleet / "sub", "deny")
        # The shipped default set is load-bearing when no override is set and
        # no marker is in the tree: mutating it to garbage must kill this.
        gh_kipi = _make_repo(root, "gh_kipi",
                             "https://github.com/assafkip/kipi-system.git", "main")
        saved_env = os.environ.pop("MERGE_GATE_PROTECTED_REPOS")
        check("default set protects kipi-system with no env override",
              "git push origin main", gh_kipi, "deny")
        os.environ["MERGE_GATE_PROTECTED_REPOS"] = saved_env
        # Case-folded, .git-tolerant set matching.
        check("push main under different URL casing of a protected repo",
              "git push origin main", gh_cased, "deny")
        # An explicit override that parses to zero valid entries fails CLOSED,
        # same direction as the URL parser (PR #226 review, minor).
        os.environ["MERGE_GATE_PROTECTED_REPOS"] = "  ,garbage,no-slash-here/"
        check("malformed explicit override fails closed",
              "git push origin main", gh_other, "deny")
        os.environ["MERGE_GATE_PROTECTED_REPOS"] = "example/repo"
        check("push main to a local origin via -C",
              f"git -C {local_origin} push origin main", root, "allow")
        # A script-local variable this process never had: unresolvable, so allow
        # rather than guess. This is the `cd "$WORK/seed" && git push` shape.
        check("unresolvable cd target",
              'cd "$WORK/seed" && git push origin HEAD:main', root, "allow")

        # --- degenerate input ---
        check("empty command", "", gh_feature, "allow")
        check("unbalanced quote hiding admin",
              "gh pr merge 9 --admin --body 'oops", gh_feature, "deny")

    if FAILURES:
        print(f"FAIL {len(FAILURES)}/{CHECKS}\n")
        for f in FAILURES:
            print("  " + f + "\n")
        return 1
    print(f"ok  {CHECKS}/{CHECKS} checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
