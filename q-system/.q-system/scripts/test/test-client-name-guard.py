#!/usr/bin/env python3
"""Paired test for client-name-guard.py (ASK-747).

WHY THIS FILE EXISTS. The guard shipped with no test, and its own introducing
commit was the defect: that message DOCUMENTED the bypass token, `if SKIP in
text` read the mention as an invocation, both stages printed `bypassed`, and the
guard never scanned the commit that introduced it.

DRIVEN THROUGH REAL `git commit`, NOT THROUGH A HAND-BUILT ARGV.

That is the whole point of this rewrite. The first attempt (PR #194) had a case
that passed only because it set LEFTHOOK_COMMIT_MSG_FILE -- a variable NOTHING in
this repo sets -- so a green suite hid a production path that could not work. So
every case here installs a real `.git/hooks/commit-msg` that calls the guard with
"$1" exactly as lefthook's `--message {1}` does, then runs a real `git commit`.
The producer of the message file is git itself. If the production path is broken,
these cases go red.

Each case also uses a real HOME with a real token list, because TOKENS_FILE is
resolved from Path.home() at import time.

NEGATIVE SELF-TEST:
    test-client-name-guard.py --against <path-to-other-guard>
points the same cases at another implementation. Against the pre-fix guard the
cases marked REGRESSION must FAIL. A case that passes against both versions is
not measuring this fix.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
GUARD = HERE.parent / "client-name-guard.py"

# Synthetic. NOT a real client name: this repo is public, which is the premise of
# the guard under test, and validate-separation Gate 1.2 refuses a shipped file
# that names a live instance.
CLIENT = "Zorptech"
SKIP_TOKEN = "client-name-guard-skip"

results = []


def record(name, ok, detail=""):
    results.append((name, ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))


def make_repo(tmp, guard, armed=True):
    """A real git repo whose commit-msg hook calls the guard the way lefthook does.

    THE HOOK IS THE PRODUCTION WIRING, not a stand-in. lefthook.yml runs
    `client-name-guard.py --message {1}` in commit-msg; git passes the message
    file as $1. Nothing here invents a slot.
    """
    home = Path(tmp) / "home"
    (home / ".config" / "kipi").mkdir(parents=True)
    if armed:
        (home / ".config" / "kipi" / "client-tokens").write_text(
            f"# one token per line\n{CLIENT}\n")
    repo = Path(tmp) / "repo"
    repo.mkdir()
    for cmd in (["init", "-q"], ["config", "user.email", "t@t"],
                ["config", "user.name", "t"], ["config", "commit.gpgsign", "false"]):
        subprocess.run(["git"] + cmd, cwd=repo, check=True, capture_output=True)
    hook = repo / ".git" / "hooks" / "commit-msg"
    hook.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{guard}" --message "$1"\n')
    hook.chmod(0o755)
    return home, repo


def commit(repo, home, message, files=None):
    """Run a REAL `git commit -m`. Returns (rc, output). No --no-verify, ever."""
    for name, body in (files or {}).items():
        (repo / name).write_text(body)
        subprocess.run(["git", "add", name], cwd=repo, check=True, capture_output=True)
    env = dict(os.environ, HOME=str(home))
    env.pop("LEFTHOOK_COMMIT_MSG_FILE", None)   # nothing may depend on this
    p = subprocess.run(["git", "commit", "-m", message], cwd=repo,
                       capture_output=True, text=True, env=env)
    return p.returncode, p.stdout + p.stderr


def head_count(repo):
    p = subprocess.run(["git", "rev-list", "--count", "HEAD"], cwd=repo,
                       capture_output=True, text=True)
    return int(p.stdout.strip()) if p.returncode == 0 else 0


def git(repo, *args, check=True, env=None):
    return subprocess.run(["git", *args], cwd=repo, check=check,
                          capture_output=True, text=True, env=env)


def add_public_remote(tmp, repo):
    """A bare repo as `origin`, so `git push` creates refs/remotes/origin/*.

    "Public" in the guard means "a remote-tracking branch contains it". A local
    bare remote is the real mechanism, not a stand-in: push writes the same
    remote-tracking ref it writes against GitHub.
    """
    bare = Path(tmp) / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True,
                   capture_output=True)
    git(repo, "remote", "add", "origin", str(bare))


def merge(repo, home, branches, message, resolve=None):
    """A REAL `git merge --no-ff --no-commit`, then a real `git commit`.

    --no-commit so MERGE_HEAD holds every parent (an octopus lists several) and
    `resolve` can write files the way a conflict resolution does. The commit is
    made by git, so the commit-msg hook is the production one. Returns (rc, out).
    """
    env = dict(os.environ, HOME=str(home))
    env.pop("LEFTHOOK_COMMIT_MSG_FILE", None)
    p = subprocess.run(["git", "merge", "--no-ff", "--no-commit", *branches],
                       cwd=repo, capture_output=True, text=True, env=env)
    for name, body in (resolve or {}).items():
        (repo / name).write_text(body)
        git(repo, "add", name)
    c = subprocess.run(["git", "commit", "-m", message], cwd=repo,
                       capture_output=True, text=True, env=env)
    return c.returncode, p.stdout + p.stderr + c.stdout + c.stderr


def run_ci(guard, repo, base, head, env_extra):
    env = {k: v for k, v in os.environ.items()
           if k not in ("PRIVATE_TERMS", "PR_TITLE", "PR_BODY", "FORK_PR")}
    env["HOME"] = str(Path(repo).parent / "ci-home")   # a runner has no ~/.config/kipi
    env.update(env_extra)
    p = subprocess.run([sys.executable, str(guard), "--ci", "--base", base,
                        "--head", head], cwd=repo, capture_output=True, text=True,
                       env=env)
    return p.returncode, p.stdout + p.stderr


def main(guard):
    print(f"client-name-guard self-test against: {guard}\n")

    # --- 1. REGRESSION: staged content is STILL scanned after the stage move ---
    # The check most likely to be silently lost by consolidating stages. A clean
    # message must not launder a client name sitting in the staged file.
    with tempfile.TemporaryDirectory() as tmp:
        home, repo = make_repo(tmp, guard)
        rc, out = commit(repo, home, "ordinary commit message",
                         {"notes.md": f"internal note about {CLIENT}\n"})
        record("staged content still BLOCKS when the message is clean",
               rc != 0 and CLIENT.lower() in out.lower() and head_count(repo) == 0,
               f"rc={rc}")

    # --- 2. REGRESSION: a message that MENTIONS the token is still SCANNED -----
    # The originally reported hole, and the guard's own origin story.
    with tempfile.TemporaryDirectory() as tmp:
        home, repo = make_repo(tmp, guard)
        rc, out = commit(
            repo, home,
            f"Add the guard\n\nAuthors bypass with the {SKIP_TOKEN} token when a\n"
            f"case study has recorded permission. Rolled out for {CLIENT}.\n",
            {"a.md": "clean\n"})
        record("prose mentioning the token is still SCANNED and BLOCKS",
               rc != 0 and head_count(repo) == 0, f"rc={rc}")

    # --- 3. `git commit -m` HAS a working bypass path -------------------------
    # The major that killed PR #194: its bypass did not exist for -m at all, so
    # the only way through was --no-verify. No --no-verify anywhere in this file.
    with tempfile.TemporaryDirectory() as tmp:
        home, repo = make_repo(tmp, guard)
        rc, out = commit(
            repo, home,
            f"Publish the case study\n\nPermission recorded.\n\n"
            f"{SKIP_TOKEN}: case study, permission on file\n",
            {"study.md": f"# Case study\n\n{CLIENT} shipped it.\n"})
        record("a trailer bypasses on a real `git commit -m`",
               rc == 0 and head_count(repo) == 1, f"rc={rc}")

    # --- 4. REGRESSION: THE CROSS-COMMIT LEAK IS CLOSED -----------------------
    # The blocker that killed PR #194. Commit N bypasses legitimately; commit N+1
    # stages a client name with a CLEAN message and no bypass of its own. Under
    # #194 the bypass persisted in $GIT_DIR/COMMIT_EDITMSG and authorised N+1.
    with tempfile.TemporaryDirectory() as tmp:
        home, repo = make_repo(tmp, guard)
        rc1, _ = commit(repo, home,
                        f"Publish case study\n\n{SKIP_TOKEN}: permission on file\n",
                        {"study.md": f"{CLIENT} shipped it.\n"})
        rc2, out2 = commit(repo, home, "unrelated follow-up, no bypass here",
                           {"leak.md": f"internal note about {CLIENT}\n"})
        record("a bypass in commit N does NOT authorise commit N+1",
               rc1 == 0 and rc2 != 0 and head_count(repo) == 1,
               f"N rc={rc1}, N+1 rc={rc2}")

    # --- 5. REGRESSION: the guard scans ITS OWN file --------------------------
    # "The guard cannot see itself": its source contains the skip token, and the
    # old pre-commit stage tested that token against its own staged diff.
    with tempfile.TemporaryDirectory() as tmp:
        home, repo = make_repo(tmp, guard)
        planted = Path(guard).read_text() + f'\n# engagement notes for {CLIENT}\n'
        rc, out = commit(repo, home, "edit the guard",
                         {"client-name-guard.py": planted})
        record("a client name planted in client-name-guard.py itself BLOCKS",
               rc != 0 and head_count(repo) == 0, f"rc={rc}")

    # --- 6. a client name in the MESSAGE alone still blocks -------------------
    with tempfile.TemporaryDirectory() as tmp:
        home, repo = make_repo(tmp, guard)
        rc, _ = commit(repo, home, f"work done for {CLIENT} today",
                       {"a.md": "clean content\n"})
        record("a client name in the message alone BLOCKS", rc != 0, f"rc={rc}")

    # --- 7. an INDENTED trailer is not an invocation --------------------------
    # Quoting the guard's own usage docstring inside a message must not bypass.
    with tempfile.TemporaryDirectory() as tmp:
        home, repo = make_repo(tmp, guard)
        rc, _ = commit(repo, home,
                       f"Document the bypass\n\nThe usage block reads:\n\n"
                       f"    {SKIP_TOKEN}: some reason\n\nMentioned for {CLIENT}.\n",
                       {"a.md": "clean\n"})
        record("an INDENTED quote of the trailer does not bypass", rc != 0,
               f"rc={rc}")

    # --- 8. the ordinary path still works -------------------------------------
    with tempfile.TemporaryDirectory() as tmp:
        home, repo = make_repo(tmp, guard)
        rc, _ = commit(repo, home, "an ordinary clean commit", {"a.md": "clean\n"})
        record("a clean commit passes", rc == 0 and head_count(repo) == 1,
               f"rc={rc}")

    # --- 9. no token list => WARN and pass, never block ------------------------
    # A fresh clone by someone who is not the founder has no clients to protect.
    with tempfile.TemporaryDirectory() as tmp:
        home, repo = make_repo(tmp, guard, armed=False)
        rc, out = commit(repo, home, "ordinary", {"a.md": f"{CLIENT}\n"})
        record("no token list => WARN and pass, never block",
               rc == 0 and "no token list" in out, f"rc={rc}")

    # --- 10. REGRESSION: a merge does not re-block what a PUBLIC parent carries -
    # ASK-2058 / sp-7156177c, measured 2026-09-23: `git diff --cached` during a
    # merge diffs against HEAD only, so every line from the merged branch read as
    # ADDED and the guard refused ANY merge of origin/main into ANY branch. A
    # name already on a pushed branch of a public repo is already out; blocking
    # it only routes the author to --no-verify.
    with tempfile.TemporaryDirectory() as tmp:
        home, repo = make_repo(tmp, guard)
        add_public_remote(tmp, repo)
        commit(repo, home, "base", {"base.md": "base\n"})
        git(repo, "checkout", "-q", "-b", "pub")
        rc0, _ = commit(repo, home,
                        f"Publish the case study\n\n{SKIP_TOKEN}: permission on file\n",
                        {"study.md": f"# Case study\n\n{CLIENT} shipped it.\n"})
        git(repo, "push", "-q", "origin", "pub")
        git(repo, "checkout", "-q", "-")
        commit(repo, home, "diverge on the main line", {"other.md": "other\n"})
        before = head_count(repo)
        rc, out = merge(repo, home, ["pub"], "Merge branch 'pub'")
        record("a merge does NOT block on a name a PUBLIC parent already carries",
               rc0 == 0 and rc == 0 and head_count(repo) == before + 2,
               f"branch rc={rc0}, merge rc={rc}")

    # --- 11. a name added BY the merge resolution still BLOCKS -----------------
    with tempfile.TemporaryDirectory() as tmp:
        home, repo = make_repo(tmp, guard)
        add_public_remote(tmp, repo)
        commit(repo, home, "base", {"base.md": "base\n"})
        git(repo, "checkout", "-q", "-b", "side")
        commit(repo, home, "side work", {"side.md": "side\n"})
        git(repo, "push", "-q", "origin", "side")
        git(repo, "checkout", "-q", "-")
        commit(repo, home, "main work", {"other.md": "other\n"})
        before = head_count(repo)
        rc, out = merge(repo, home, ["side"], "Merge branch 'side'",
                        resolve={"resolved.md": f"note about {CLIENT}\n"})
        record("a client name added BY the merge resolution still BLOCKS",
               rc != 0 and head_count(repo) == before, f"rc={rc}")

    # --- 12. REGRESSION (PR #435 review blocker): a LOCAL parent excuses nothing
    # PR #435 excused any line already on any parent. A branch that was never
    # pushed is not public, so merging it is the step that makes its content
    # publishable. Here the name entered the local branch under a bypass; the
    # merge carries no bypass of its own and must be scanned.
    with tempfile.TemporaryDirectory() as tmp:
        home, repo = make_repo(tmp, guard)
        add_public_remote(tmp, repo)
        commit(repo, home, "base", {"base.md": "base\n"})
        git(repo, "checkout", "-q", "-b", "local-only")
        rc0, _ = commit(repo, home,
                        f"draft notes\n\n{SKIP_TOKEN}: private branch, never pushed\n",
                        {"notes.md": f"engagement notes for {CLIENT}\n"})
        git(repo, "checkout", "-q", "-")
        commit(repo, home, "main work", {"other.md": "other\n"})
        before = head_count(repo)
        rc, out = merge(repo, home, ["local-only"], "Merge branch 'local-only'")
        record("a merge of a LOCAL, unpushed parent carrying a name BLOCKS",
               rc0 == 0 and rc != 0 and head_count(repo) == before,
               f"branch rc={rc0}, merge rc={rc}")

    # --- 13. REGRESSION (PR #435 review minor): octopus, both parent orders ----
    # MERGE_HEAD lists every parent. Reading only the first made the verdict
    # depend on order. One public clean parent, one local parent with a name.
    for order in (("pubclean", "localname"), ("localname", "pubclean")):
        with tempfile.TemporaryDirectory() as tmp:
            home, repo = make_repo(tmp, guard)
            add_public_remote(tmp, repo)
            commit(repo, home, "base", {"base.md": "base\n"})
            git(repo, "checkout", "-q", "-b", "pubclean")
            commit(repo, home, "clean public work", {"p.md": "clean\n"})
            git(repo, "push", "-q", "origin", "pubclean")
            git(repo, "checkout", "-q", "-")
            git(repo, "checkout", "-q", "-b", "localname")
            commit(repo, home, f"notes\n\n{SKIP_TOKEN}: local only\n",
                   {"n.md": f"call with {CLIENT}\n"})
            git(repo, "checkout", "-q", "-")
            commit(repo, home, "main work", {"other.md": "other\n"})
            before = head_count(repo)
            rc, out = merge(repo, home, list(order), "octopus")
            record(f"octopus merge {order[0]}+{order[1]} with a local name BLOCKS",
                   rc != 0 and head_count(repo) == before, f"rc={rc}")

    # --- 14. REGRESSION (ASK-2058): the list is read from the registries -------
    # Ten hand-typed tokens missed every name the registries held. The sources
    # file points at a registry; the guard reads it at call time.
    with tempfile.TemporaryDirectory() as tmp:
        home, repo = make_repo(tmp, guard, armed=False)
        reg = Path(tmp) / "clients.json"
        reg.write_text(json.dumps({"clients": [
            {"name": "Quexwell Labs", "slug": "quexwell-labs", "stage": "active",
             "contacts": [{"name": "Morwen Tallis", "email": "mtallis@quexwell.example"}]},
            {"name": "Vintrope Group", "slug": "vintrope", "stage": "prospect",
             "contacts": []},
            {"name": "Ordinaryword", "slug": "ordinaryword", "stage": "active",
             "contacts": []}]}))
        (home / ".config" / "kipi" / "private-terms.json").write_text(json.dumps({
            "json_sources": [{"path": str(reg), "records": "clients",
                              "keys": ["name", "slug"], "people": "contacts",
                              "skip_when": {"stage": ["prospect"]}}],
            "exclude": ["ordinaryword"]}))
        cases = [("org from the registry", "quexwell_labs notes\n", False),
                 ("contact full name", "met Morwen Tallis today\n", False),
                 ("contact email", "cc mtallis@quexwell.example\n", False),
                 ("prospect skipped by skip_when", "Vintrope Group posted a job\n", True),
                 ("excluded term", "an ordinaryword here\n", True)]
        for label, body, should_pass in cases:
            rc, _ = commit(repo, home, "ordinary", {"f.md": body})
            ok = (rc == 0) if should_pass else (rc != 0)
            record(f"registry source: {label} {'passes' if should_pass else 'BLOCKS'}",
                   ok, f"rc={rc}")
            git(repo, "reset", "-q", "--mixed", check=False)

    # --- 15. separator spellings of one token all block -----------------------
    with tempfile.TemporaryDirectory() as tmp:
        home, repo = make_repo(tmp, guard, armed=False)
        (home / ".config" / "kipi" / "client-tokens").write_text("zorp_tech\n")
        blocked = 0
        for i, spelling in enumerate(("Zorp Tech", "ZorpTech", "zorp-tech")):
            rc, _ = commit(repo, home, "ordinary", {f"v{i}.md": f"{spelling}\n"})
            blocked += rc != 0
            git(repo, "reset", "-q", "--mixed", check=False)
        record("token zorp_tech blocks 'Zorp Tech', 'ZorpTech', 'zorp-tech'",
               blocked == 3, f"blocked {blocked}/3")

    # --- 16. the CI backstop: scans the range, never prints the term -----------
    # A squash merge writes its message on GitHub from the PR title and body, so
    # no local hook sees it. CI logs of a public repo are public, so the output
    # must name the file and the KIND, never the matched term.
    with tempfile.TemporaryDirectory() as tmp:
        home, repo = make_repo(tmp, guard, armed=False)
        commit(repo, home, "base", {"base.md": "base\n"})
        base = git(repo, "rev-parse", "HEAD").stdout.strip()
        commit(repo, home, "add notes", {"notes.md": f"x\nnote about {CLIENT}\n"})
        head = git(repo, "rev-parse", "HEAD").stdout.strip()
        secret = json.dumps({"terms": {"org": [CLIENT.lower()]}})
        rc, out = run_ci(guard, repo, base, head, {"PRIVATE_TERMS": secret})
        record("CI: a name on an added line FAILS and points at the file",
               rc != 0 and "notes.md" in out, f"rc={rc}")
        record("CI: the output never contains the term",
               CLIENT.lower() not in out.lower(), "term printed" if CLIENT.lower() in out.lower() else "")
        rc, out = run_ci(guard, repo, base, base, {"PRIVATE_TERMS": secret,
                                                   "PR_TITLE": f"work for {CLIENT}"})
        record("CI: a name in the PR title FAILS", rc != 0, f"rc={rc}")
        rc, out = run_ci(guard, repo, base, base, {"PRIVATE_TERMS": secret,
                                                   "PR_TITLE": "clean title"})
        record("CI: a clean range and title pass", rc == 0, f"rc={rc}")
        rc, out = run_ci(guard, repo, base, head, {})
        record("CI: a missing secret on this repo's own event FAILS closed",
               rc != 0, f"rc={rc}")
        rc, out = run_ci(guard, repo, base, head, {"FORK_PR": "true"})
        record("CI: a fork PR without secrets passes with a notice",
               rc == 0 and "fork" in out, f"rc={rc}")

    failed = [n for n, ok in results if not ok]
    print()
    if failed:
        print(f"client-name-guard self-test: {len(failed)} FAILED")
        return 1
    print(f"client-name-guard self-test: all {len(results)} cases passed")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    # RESOLVED, not taken as given. The hook runs with the temp repo as cwd, so
    # a relative --against path points nowhere from there and every case reads
    # rc=1: a negative self-test that reports on a guard it never ran.
    ap.add_argument("--against", type=lambda p: Path(p).resolve(), default=GUARD,
                    help="guard implementation to test (for the negative self-test)")
    sys.exit(main(ap.parse_args().against))
