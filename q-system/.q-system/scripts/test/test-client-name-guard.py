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
import importlib.util
import io
import json
import os
import re
import zipfile
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
    add_remote(tmp, repo, "origin")


def add_remote(tmp, repo, name):
    """A bare repo configured as remote `name`, with its real fetch refspec.

    `git remote add` writes `remote.<name>.fetch`, which is the config the guard
    DERIVES its public ref patterns from (PR #559 review round 6). Hand-writing
    the ref instead of configuring the remote is the untrusted case, and it has
    its own case below.
    """
    bare = Path(tmp) / f"{name}.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True,
                   capture_output=True)
    git(repo, "remote", "add", name, str(bare))


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
        # PR #554 review round 1: FORK_PR was set by nothing and the workflow
        # skips forks, so the old "fork passes with a notice" case tested only
        # itself. The variable now changes nothing: still fails closed.
        rc, out = run_ci(guard, repo, base, head, {"FORK_PR": "true"})
        record("CI: FORK_PR is not an escape hatch; no secret still FAILS",
               rc != 0, f"rc={rc}")
        rc, out = run_ci(guard, repo, base, head, {"PRIVATE_TERMS": secret})
        record("CI: BLOCK text points at file:line, not at a command that cannot show the term",
               rc != 0 and "notes.md:2" in out and "Run the local guard" not in out,
               f"rc={rc}")

    # --- 17. REGRESSION (ASK-2058 review blocker 1): binaries and path names ---
    # Neither is an added TEXT line, so the line scan passed both. The review's
    # reproducer: a NUL-prefixed payload and a client-named directory.
    def zip_bytes(member_text):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("word/document.xml", member_text)
        return buf.getvalue()

    with tempfile.TemporaryDirectory() as tmp:
        home, repo = make_repo(tmp, guard)
        cases = [("raw bytes in a binary", "blob.bin", b"\0\x01" + f"{CLIENT} payload".encode()),
                 ("text inside a zip member (.docx)", "report.docx",
                  zip_bytes(f"<w:t>prepared for {CLIENT}</w:t>")),
                 ("a path name", f"{CLIENT.lower()}-notes/plan.md", b"clean payload\n")]
        for label, name, data in cases:
            path = repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            git(repo, "add", name)
            env = dict(os.environ, HOME=str(home))
            c = subprocess.run(["git", "commit", "-m", "ordinary"], cwd=repo,
                               capture_output=True, text=True, env=env)
            record(f"local: a name in {label} BLOCKS", c.returncode != 0,
                   f"rc={c.returncode}")
            git(repo, "reset", "-q", "--mixed", check=False)
            path.unlink()

    # --- 18. CI: the same three, and the log still never names the term -------
    with tempfile.TemporaryDirectory() as tmp:
        home, repo = make_repo(tmp, guard, armed=False)
        commit(repo, home, "base", {"base.md": "base\n"})
        base = git(repo, "rev-parse", "HEAD").stdout.strip()
        (repo / "blob.bin").write_bytes(b"\0" + f"{CLIENT} payload".encode())
        (repo / "report.docx").write_bytes(zip_bytes(f"prepared for {CLIENT}"))
        (repo / f"{CLIENT.lower()}-notes").mkdir()
        (repo / f"{CLIENT.lower()}-notes" / "plan.md").write_text("clean\n")
        git(repo, "add", "-A")
        commit(repo, home, "binaries")
        head = git(repo, "rev-parse", "HEAD").stdout.strip()
        secret = json.dumps({"terms": {"org": [CLIENT.lower()]}})
        rc, out = run_ci(guard, repo, base, head, {"PRIVATE_TERMS": secret})
        record("CI: binary, zip member and path name all FAIL",
               rc != 0 and "blob.bin" in out and "report.docx" in out
               and "path name" in out, f"rc={rc}")
        record("CI: no term in the output, a term-bearing path is masked",
               CLIENT.lower() not in out.lower(), "term printed" if CLIENT.lower() in out.lower() else "")

    # --- 19. REGRESSION (review blocker 2): no base => the WHOLE tree ----------
    # The workflow used to fall back to HEAD^..HEAD, so a name added two commits
    # back in the same push passed. --tree reads every file the push left.
    with tempfile.TemporaryDirectory() as tmp:
        home, repo = make_repo(tmp, guard, armed=False)
        commit(repo, home, "first", {"early.md": f"note about {CLIENT}\n"})
        commit(repo, home, "second", {"late.md": "clean\n"})
        secret = json.dumps({"terms": {"org": [CLIENT.lower()]}})
        rc, out = run_ci(guard, repo, "HEAD^", "HEAD", {"PRIVATE_TERMS": secret})
        missed_by_range = rc == 0
        env = {k: v for k, v in os.environ.items()
               if k not in ("PRIVATE_TERMS", "PUSH_COMMITS", "PUSH_SIZE")}
        # This block is about CONTENT, so the push declares the smallest honest
        # payload: no listed commits and a size that matches (case 30 is where
        # the payload-vs-size cross-check itself is exercised).
        env.update(HOME=str(Path(tmp) / "ci-home"), PRIVATE_TERMS=secret, PUSH_SIZE="0")
        t = subprocess.run([sys.executable, str(guard), "--ci", "--tree", "--head", "HEAD"],
                           cwd=repo, capture_output=True, text=True, env=env)
        record("CI --tree catches a name the HEAD^..HEAD range misses",
               missed_by_range and t.returncode != 0 and "early.md" in t.stdout,
               f"range rc={rc}, tree rc={t.returncode}")
        # Exemptions are PINNED to a blob (review round 2): the reviewed version
        # is skipped, any other version of the same path is scanned again.
        (repo / ".github").mkdir()
        pin = git(repo, "rev-parse", "HEAD:early.md").stdout.strip()
        exempt = repo / ".github" / "private-terms-exempt.txt"
        exempt.write_text(f"# reason\nearly.md {pin}\n")
        t = subprocess.run([sys.executable, str(guard), "--ci", "--tree", "--head", "HEAD"],
                           cwd=repo, capture_output=True, text=True, env=env)
        record("CI --tree skips a file pinned at its exact blob", t.returncode == 0,
               f"rc={t.returncode}")
        exempt.write_text("# a path alone exempts nothing\nearly.md\n")
        t = subprocess.run([sys.executable, str(guard), "--ci", "--tree", "--head", "HEAD"],
                           cwd=repo, capture_output=True, text=True, env=env)
        record("CI --tree: a path-only exempt line exempts nothing", t.returncode != 0,
               f"rc={t.returncode}")
        exempt.write_text(f"early.md {pin}\n")
        commit(repo, home, "edit the exempt file", {"early.md": f"note about {CLIENT}\nmore\n"})
        t = subprocess.run([sys.executable, str(guard), "--ci", "--tree", "--head", "HEAD"],
                           cwd=repo, capture_output=True, text=True, env=env)
        record("CI --tree: a CHANGED version of a pinned file is scanned again",
               t.returncode != 0 and "early.md" in t.stdout, f"rc={t.returncode}")

    # --- 19b. REGRESSION (review round 2): every pushed message, not HEAD's ----
    with tempfile.TemporaryDirectory() as tmp:
        home, repo = make_repo(tmp, guard, armed=False)
        commit(repo, home, "base", {"base.md": "base\n"})
        commit(repo, home, f"notes from the {CLIENT} call", {"a.md": "clean\n"})
        early = git(repo, "rev-parse", "HEAD").stdout.strip()
        commit(repo, home, "tidy", {"b.md": "clean\n"})
        head = git(repo, "rev-parse", "HEAD").stdout.strip()
        secret = json.dumps({"terms": {"org": [CLIENT.lower()]}})

        def tree(pushed, size=None):
            # PUSH_SIZE is the push's own commit count (github.event.size). The
            # payload lists at most 20, so the count is what proves the list is
            # complete (case 30); these cases declare a size that matches.
            env = {k: v for k, v in os.environ.items()
                   if k not in ("PRIVATE_TERMS", "PUSH_COMMITS", "PUSH_SIZE")}
            env.update(HOME=str(Path(tmp) / "ci-home"), PRIVATE_TERMS=secret,
                       PUSH_COMMITS=json.dumps(pushed),
                       PUSH_SIZE=str(len(pushed) if size is None else size))
            return subprocess.run([sys.executable, str(guard), "--ci", "--tree", "--head", "HEAD"],
                                  cwd=repo, capture_output=True, text=True, env=env)
        t1, t2 = tree([early, head]), tree([head])
        record("CI --tree scans every message the push lists, not only HEAD's",
               t1.returncode != 0 and t2.returncode == 0,
               f"listed rc={t1.returncode}, head-only rc={t2.returncode}")
        t3 = tree(["0" * 40])
        record("CI --tree: a pushed commit missing from the clone fails closed",
               t3.returncode != 0, f"rc={t3.returncode}")
        t4 = tree([head] * 2048)
        record("CI --tree: a push list at the payload cap fails closed",
               t4.returncode != 0, f"rc={t4.returncode}")

    # --- 19c. an author identity is a person's name too -------------------------
    with tempfile.TemporaryDirectory() as tmp:
        home, repo = make_repo(tmp, guard, armed=False)
        commit(repo, home, "base", {"base.md": "base\n"})
        base = git(repo, "rev-parse", "HEAD").stdout.strip()
        git(repo, "-c", f"user.name={CLIENT} Staffer", "commit", "-q", "--allow-empty",
            "-m", "empty", env=dict(os.environ, HOME=str(home)))
        head = git(repo, "rev-parse", "HEAD").stdout.strip()
        secret = json.dumps({"terms": {"org": [CLIENT.lower()]}})
        rc, out = run_ci(guard, repo, base, head, {"PRIVATE_TERMS": secret})
        record("CI: a name in a commit's AUTHOR fails", rc != 0, f"rc={rc}")

    # --- 20. an excluded spelling cannot regrow in CI ---------------------------
    # CI re-expands every spelling; without the shipped exclusions "the lab"
    # regrew from "the_lab" (measured on this branch's first full-tree run).
    # The payload is EXPORTED by the guard under test from a real private config
    # (the laptop side), then read back by CI: the defect was in the export.
    with tempfile.TemporaryDirectory() as tmp:
        home, repo = make_repo(tmp, guard, armed=False)
        kipi = home / ".config" / "kipi"
        (kipi / "lab-tokens").write_text("the_lab\n")
        (kipi / "private-terms.json").write_text(json.dumps({
            "token_files": [str(kipi / "lab-tokens")], "exclude": ["the lab"]}))
        exp = subprocess.run(
            [sys.executable, "-c",
             "import importlib.util,sys\n"
             "s=importlib.util.spec_from_file_location('g',sys.argv[1])\n"
             "g=importlib.util.module_from_spec(s);s.loader.exec_module(g)\n"
             "print(g.export_payload(g.base_payload()))", str(guard)],
            capture_output=True, text=True, env=dict(os.environ, HOME=str(home)))
        secret = exp.stdout.strip()
        commit(repo, home, "base", {"base.md": "base\n"})
        base = git(repo, "rev-parse", "HEAD").stdout.strip()
        rc1, _ = run_ci(guard, repo, base, base, {"PRIVATE_TERMS": secret,
                                                  "PR_TITLE": "notes from the lab"})
        rc2, _ = run_ci(guard, repo, base, base, {"PRIVATE_TERMS": secret,
                                                  "PR_TITLE": "notes from the_lab"})
        record("CI: an excluded spelling passes, its folder spelling still FAILS",
               rc1 == 0 and rc2 != 0, f"phrase rc={rc1}, folder rc={rc2}")

    # --- 21. the workflow's shape (review rounds 1 and 2) ---------------------
    # A structural read, because the properties live in YAML no unit test runs:
    # base-branch code only, the environment-scoped secret, no fork oracle, and
    # the full-tree fallback instead of HEAD^..HEAD.
    wf = HERE.parents[3] / ".github" / "workflows" / "private-terms.yml"
    if wf.exists():
        code = "\n".join(l for l in wf.read_text().splitlines()
                         if not l.lstrip().startswith("#"))
        record("workflow: pull_request_target, never pull_request",
               "pull_request_target:" in code
               and not re.search(r"^\s*pull_request:", code, re.M))
        record("workflow: the secret is an environment secret, environment private-terms",
               "environment: private-terms" in code)
        record("workflow: fork PRs never reach the secret",
               "head.repo.full_name == github.repository" in code)
        record("workflow: the PR head is fetched as data, never checked out",
               "refs/pull/" in code and "ref: ${{ github.event.pull_request.head" not in code)
        record("workflow: no-base fallback is --tree, never HEAD^..HEAD",
               "--tree" in code and 'base="HEAD^"' not in code)
        # The tree scan refuses without it, so a workflow that stopped passing
        # PUSH_SIZE would turn every force-push scan red. The pairing is the
        # wiring, and nothing else in the repo passes that variable.
        record("workflow: the push's own commit count reaches the guard",
               "PUSH_SIZE: ${{ github.event.size }}" in code)

    # --- 22. REGRESSION (review round 3, blocker 1): `people` takes a list ----
    # The live registry holds a list under `contacts` on some clients and ONE
    # object under `contact` on others. The pre-fix loader read one key and
    # iterated it as a list: a dict yields its keys, so that person was missed,
    # and a list of keys crashed it.
    with tempfile.TemporaryDirectory() as tmp:
        home, repo = make_repo(tmp, guard, armed=False)
        reg = Path(tmp) / "clients.json"
        reg.write_text(json.dumps({"clients": [
            {"name": "Quexwell Labs", "contacts": [{"name": "Morwen Tallis"}]},
            {"name": "Brindlecap Partners",
             "contact": {"name": "Ilsa Vantorre", "role": "cto"}}]}))

        def people_from(people):
            (home / ".config" / "kipi" / "private-terms.json").write_text(json.dumps({
                "json_sources": [{"path": str(reg), "records": "clients",
                                  "keys": ["name"], "people": people}]}))

        people_from("contact")
        rc, out = commit(repo, home, "ordinary", {"f.md": "met Ilsa Vantorre today\n"})
        record("people: one {name} object under the key BLOCKS",
               rc != 0 and "BLOCK" in out, f"rc={rc}")
        git(repo, "reset", "-q", "--mixed", check=False)
        people_from(["contacts", "contact"])
        for label, body in (("list-shaped key", "met Morwen Tallis today\n"),
                            ("object-shaped key", "met Ilsa Vantorre today\n")):
            rc, out = commit(repo, home, "ordinary", {"f.md": body})
            record(f"people: a list of keys, the {label} BLOCKS (no traceback)",
                   rc != 0 and "BLOCK" in out and "Traceback" not in out, f"rc={rc}")
            git(repo, "reset", "-q", "--mixed", check=False)

    # --- 23. REGRESSION (review round 3, blocker 2): no partial list reaches CI
    # An unreadable registry warned and dropped out, and --sync-ci-secret pushed
    # the shorter list as if complete. A fake `gh` records what would be sent.
    with tempfile.TemporaryDirectory() as tmp:
        home, repo = make_repo(tmp, guard)   # client-tokens holds CLIENT
        git(repo, "remote", "add", "origin",
            "https://github.com/example-owner/example-public.git")
        fakebin = Path(tmp) / "bin"
        fakebin.mkdir()
        log = Path(tmp) / "gh.log"
        gh = fakebin / "gh"
        gh.write_text(f'#!/bin/sh\necho "$*" >> "{log}"\n'
                      'case "$*" in *"repo view"*) echo PUBLIC;; esac\nexit 0\n')
        gh.chmod(0o755)

        def sync():
            env = dict(os.environ, HOME=str(home),
                       PATH=f"{fakebin}{os.pathsep}{os.environ.get('PATH', '')}")
            env.pop("PRIVATE_TERMS", None)
            p = subprocess.run([sys.executable, str(guard), "--sync-ci-secret"],
                               cwd=repo, capture_output=True, text=True, env=env)
            pushed = log.exists() and "secret set" in log.read_text()
            return p.returncode, p.stdout + p.stderr, pushed

        kipi = home / ".config" / "kipi"
        (kipi / "private-terms.json").write_text(json.dumps({"json_sources": [
            {"path": str(Path(tmp) / "moved-away.json"), "records": "clients",
             "keys": ["name"]}]}))
        rc, out, pushed = sync()
        record("sync: an unreadable source refuses the CI secret push",
               rc == 0 and not pushed and "NOT synced" in out,
               f"rc={rc}, pushed={pushed}")
        (kipi / "private-terms.json").write_text(json.dumps({"json_sources": []}))
        rc, out, pushed = sync()
        record("sync: every source readable => the secret IS pushed (control)",
               rc == 0 and pushed, f"rc={rc}, pushed={pushed}")

    # --- 24. REGRESSION (review round 3, blocker 3): claim only what it detects
    # The BLOCK text said "client money" while no live rate produced a hit.
    with tempfile.TemporaryDirectory() as tmp:
        home, repo = make_repo(tmp, guard)
        rc, out = commit(repo, home, "ordinary", {"f.md": f"note about {CLIENT}\n"})
        record("BLOCK text names identifiers and claims no money detection",
               rc != 0 and "identifiers" in out and "money" not in out.lower(),
               f"rc={rc}")

    # --- 25. REGRESSION (review round 3, minor): an added "++" line is content -
    # Its diff line reads "+++ ...", which the pre-fix parser took for a file
    # header anywhere in the diff, so the line was never scanned.
    with tempfile.TemporaryDirectory() as tmp:
        home, repo = make_repo(tmp, guard)
        rc, out = commit(repo, home, "ordinary", {"f.md": f"++ {CLIENT} counter\n"})
        record("an added line starting with '++' is scanned and BLOCKS",
               rc != 0 and head_count(repo) == 0, f"rc={rc}")

    # --- 26. REGRESSION (PR #554 review round 1, major): no gh, no blocked push
    # The pre-push sync ran `gh` unguarded; without it subprocess raised, the
    # hook exited 1 and lefthook refused the push. PATH here holds git only.
    import shutil
    with tempfile.TemporaryDirectory() as tmp:
        home, repo = make_repo(tmp, guard)
        git(repo, "remote", "add", "origin",
            "https://github.com/example-owner/example-public.git")
        gitonly = Path(tmp) / "gitonly"
        gitonly.mkdir()
        (gitonly / "git").symlink_to(shutil.which("git"))
        env = dict(os.environ, HOME=str(home), PATH=str(gitonly))
        env.pop("PRIVATE_TERMS", None)
        p = subprocess.run([sys.executable, str(guard), "--sync-ci-secret"], cwd=repo,
                           capture_output=True, text=True, env=env)
        out = p.stdout + p.stderr
        record("sync: no gh on PATH warns and exits 0, never blocks the push",
               p.returncode == 0 and "Traceback" not in out and "not synced" in out,
               f"rc={p.returncode}")

    # --- 27. REGRESSION (PR #554 review round 2, major): over-cap zip ---------
    # A member past the inflation cap was skipped and only the compressed bytes
    # were scanned, where deflated text is invisible: a ~51 KB zip holding a name
    # inside a 50 MB member reported clean. It must refuse, locally and in CI.
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("big.txt", (b"A" * (50 * 1024 * 1024 + 1)) + f" {CLIENT}\n".encode())
    big_zip = buf.getvalue()

    def commit_bytes(repo, home, message, name, data):
        (repo / name).write_bytes(data)
        git(repo, "add", name)
        env = dict(os.environ, HOME=str(home))
        env.pop("LEFTHOOK_COMMIT_MSG_FILE", None)
        p = subprocess.run(["git", "commit", "-m", message], cwd=repo,
                           capture_output=True, text=True, env=env)
        return p.returncode, p.stdout + p.stderr

    with tempfile.TemporaryDirectory() as tmp:
        home, repo = make_repo(tmp, guard)
        rc, out = commit_bytes(repo, home, "add an archive", "a.zip", big_zip)
        record("local: a zip member over the inflation cap BLOCKS (unscannable, not clean)",
               rc != 0 and head_count(repo) == 0 and "Traceback" not in out, f"rc={rc}")
        rc, out = commit_bytes(repo, home,
                               f"add an archive\n\n{SKIP_TOKEN}: archive reviewed by hand\n",
                               "a.zip", big_zip)
        record("local: the bypass trailer still lets an intended archive through",
               rc == 0 and head_count(repo) == 1, f"rc={rc}")
    with tempfile.TemporaryDirectory() as tmp:
        home, repo = make_repo(tmp, guard, armed=False)
        commit(repo, home, "base", {"base.md": "base\n"})
        base = git(repo, "rev-parse", "HEAD").stdout.strip()
        commit_bytes(repo, home, "add an archive", "a.zip", big_zip)
        head = git(repo, "rev-parse", "HEAD").stdout.strip()
        secret = json.dumps({"terms": {"org": [CLIENT.lower()]}})
        rc, out = run_ci(guard, repo, base, head, {"PRIVATE_TERMS": secret})
        record("CI: a zip member over the inflation cap FAILS as not fully scanned",
               rc != 0 and "not fully scanned" in out
               and CLIENT.lower() not in out.lower(), f"rc={rc}")

    # --- 28. REGRESSION (PR #554 review round 3, major): UTF-16 ---------------
    # Git calls a UTF-16 file binary, and the binary read decoded only UTF-8, so
    # "Z\0o\0r\0..." held a name no hit could see: the review's reproducer printed
    # hits={} for a UTF-16LE payload. Every byte order and alignment, a BOM-less
    # file, a zip member, and a Latin Extended-A spelling (the measured range of
    # the live list) must refuse. A clean UTF-16 file is the control.
    def zip_member(data):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("notes.txt", data)
        return buf.getvalue()

    ext_name = "Zorptęch"   # synthetic, with U+0119 from Latin Extended-A
    text = f"prepared for {CLIENT} by the team\n"
    utf16_cases = [
        ("UTF-16LE, no BOM", "a.txt", text.encode("utf-16-le")),
        ("UTF-16BE, no BOM", "b.txt", text.encode("utf-16-be")),
        ("UTF-16 with a BOM", "c.txt", text.encode("utf-16")),
        ("UTF-16LE at an odd offset", "d.bin", b"\x01" + text.encode("utf-16-le")),
        ("a UTF-16 zip member", "e.zip", zip_member(text.encode("utf-16-le"))),
        ("a Latin Extended-A spelling in UTF-16LE", "f.txt",
         f"prepared for {ext_name}\n".encode("utf-16-le")),
    ]
    with tempfile.TemporaryDirectory() as tmp:
        home, repo = make_repo(tmp, guard)
        tokens = home / ".config" / "kipi" / "client-tokens"
        tokens.write_text(tokens.read_text() + f"{ext_name}\n")
        for label, name, data in utf16_cases:
            rc, out = commit_bytes(repo, home, "add a document", name, data)
            record(f"local: a name in {label} BLOCKS",
                   rc != 0 and head_count(repo) == 0 and "Traceback" not in out, f"rc={rc}")
            git(repo, "reset", "-q", "--mixed", check=False)
            (repo / name).unlink()
    with tempfile.TemporaryDirectory() as tmp:
        home, repo = make_repo(tmp, guard)
        rc, out = commit_bytes(repo, home, "add a document", "clean.txt",
                               "nothing private in here\n".encode("utf-16"))
        record("local: a clean UTF-16 file passes (control)",
               rc == 0 and head_count(repo) == 1, f"rc={rc}")
    with tempfile.TemporaryDirectory() as tmp:
        home, repo = make_repo(tmp, guard, armed=False)
        commit(repo, home, "base", {"base.md": "base\n"})
        base = git(repo, "rev-parse", "HEAD").stdout.strip()
        for _, name, data in utf16_cases[:2]:
            (repo / name).write_bytes(data)
        git(repo, "add", "-A")
        commit(repo, home, "documents")
        head = git(repo, "rev-parse", "HEAD").stdout.strip()
        secret = json.dumps({"terms": {"org": [CLIENT.lower()]}})
        rc, out = run_ci(guard, repo, base, head, {"PRIVATE_TERMS": secret})
        record("CI: a name in UTF-16LE and UTF-16BE files FAILS, term never printed",
               rc != 0 and "a.txt" in out and "b.txt" in out
               and CLIENT.lower() not in out.lower(), f"rc={rc}")

    # --- 29. REGRESSION (PR #554 review rounds 1 to 3): the bypass on main ----
    # The PR check honoured a PR-body trailer, the squash on main kept only the
    # title and commit messages, and the push scan went red on approved content.
    # Each scenario runs ONE change through both scans: the PR scan of the
    # branch, then a real `git merge --squash` committed with GitHub's
    # COMMIT_MESSAGES layout ("* " before each commit message) and the push scan
    # of main. The two verdicts must agree.
    secret = json.dumps({"terms": {"org": [CLIENT.lower()]}})
    trailer = f"{SKIP_TOKEN}: case study, permission recorded"

    def squash_scenario(commit_msgs, body):
        with tempfile.TemporaryDirectory() as tmp:
            home, repo = make_repo(tmp, guard, armed=False)
            commit(repo, home, "base", {"base.md": "base\n"})
            base = git(repo, "rev-parse", "HEAD").stdout.strip()
            git(repo, "checkout", "-q", "-b", "pr")
            for i, msg in enumerate(commit_msgs):
                commit(repo, home, msg, {f"study{i}.md": f"case study for {CLIENT}\n"})
            pr_head = git(repo, "rev-parse", "HEAD").stdout.strip()
            pr_rc, pr_out = run_ci(guard, repo, base, pr_head, {
                "PRIVATE_TERMS": secret, "PR_TITLE": "add a case study", "PR_BODY": body})
            git(repo, "checkout", "-q", base)
            git(repo, "merge", "--squash", "-q", "pr")
            msgs = git(repo, "log", "--reverse", "--format=%B%x00",
                       f"{base}..{pr_head}").stdout.split("\0")
            squash = "add a case study (#1)\n\n" + "\n".join(
                f"* {m.strip()}\n" for m in msgs if m.strip())
            commit(repo, home, squash)
            main_head = git(repo, "rev-parse", "HEAD").stdout.strip()
            push_rc, push_out = run_ci(guard, repo, base, main_head, {"PRIVATE_TERMS": secret})
            return pr_rc, push_rc, pr_out + push_out

    pr_rc, push_rc, out = squash_scenario([f"add a case study\n\n{trailer}"],
                                          f"A case study.\n\n{trailer}")
    record("bypass: commit + PR body trailer passes the PR AND the push to main",
           pr_rc == 0 and push_rc == 0 and CLIENT.lower() not in out.lower(),
           f"pr={pr_rc} push={push_rc}")
    pr_rc, push_rc, out = squash_scenario(["add a case study"], f"A case study.\n\n{trailer}")
    record("bypass: a PR body trailer alone cannot pass the PR, since main never gets it",
           pr_rc != 0 and push_rc != 0 and "no commit does" in out,
           f"pr={pr_rc} push={push_rc}")
    pr_rc, push_rc, out = squash_scenario([f"add a case study\n\n{trailer}"], "A case study.")
    record("bypass: a commit trailer alone passes the PR and the push alike",
           pr_rc == 0 and push_rc == 0, f"pr={pr_rc} push={push_rc}")

    # Control: on a multi-commit range (a rebase merge, a direct push) a range
    # diff cannot tell which commit added a line, so one commit's trailer must
    # not vouch for its sibling's content.
    with tempfile.TemporaryDirectory() as tmp:
        home, repo = make_repo(tmp, guard, armed=False)
        commit(repo, home, "base", {"base.md": "base\n"})
        base = git(repo, "rev-parse", "HEAD").stdout.strip()
        commit(repo, home, f"add a case study\n\n{trailer}", {"study.md": f"for {CLIENT}\n"})
        commit(repo, home, "more notes", {"notes.md": f"also {CLIENT}\n"})
        head = git(repo, "rev-parse", "HEAD").stdout.strip()
        rc, out = run_ci(guard, repo, base, head, {"PRIVATE_TERMS": secret})
        record("bypass: one commit's trailer does not authorise a sibling commit (control)",
               rc != 0 and "notes.md" in out, f"rc={rc}")

    # --- 30. REGRESSION (PR #559 review, major 1): the payload is not the
    # authority on what the push carried. GitHub's push event lists AT MOST 20
    # commits in `commits` and reports the real count in `size`, so the 2048-entry
    # cap could never fire: a 21-commit push left unlisted messages unscanned and
    # reported clean. The listed count is now cross-checked against the push's own
    # size, and every listed sha against git's reachable history.
    with tempfile.TemporaryDirectory() as tmp:
        home, repo = make_repo(tmp, guard, armed=False)
        commit(repo, home, "base", {"base.md": "base\n"})
        commit(repo, home, f"notes from the {CLIENT} call", {"a.md": "clean\n"})
        named = git(repo, "rev-parse", "HEAD").stdout.strip()
        commit(repo, home, "tidy", {"b.md": "clean\n"})
        head = git(repo, "rev-parse", "HEAD").stdout.strip()
        # A commit that EXISTS in the clone but is not reachable from the pushed
        # head: `git log -1 <sha>` alone cannot tell the two apart.
        git(repo, "checkout", "-q", "-b", "side", named)
        commit(repo, home, "side work", {"c.md": "clean\n"})
        side = git(repo, "rev-parse", "HEAD").stdout.strip()
        git(repo, "checkout", "-q", head)
        secret = json.dumps({"terms": {"org": [CLIENT.lower()]}})

        def tree30(pushed, size="match"):
            env = {k: v for k, v in os.environ.items()
                   if k not in ("PRIVATE_TERMS", "PUSH_COMMITS", "PUSH_SIZE")}
            env.update(HOME=str(Path(tmp) / "ci-home"), PRIVATE_TERMS=secret,
                       PUSH_COMMITS=json.dumps(pushed))
            if size is not None:
                env["PUSH_SIZE"] = str(len(pushed) if size == "match" else size)
            p = subprocess.run([sys.executable, str(guard), "--ci", "--tree", "--head", head],
                               cwd=repo, capture_output=True, text=True, env=env)
            return p.returncode, p.stdout + p.stderr

        rc, out = tree30([head], size=3)
        record("CI --tree: a payload shorter than the push's own size fails closed",
               rc != 0 and "3" in out and "Traceback" not in out, f"rc={rc}")
        rc, out = tree30([named, head])
        record("CI --tree: a complete payload still catches the named message (control)",
               rc != 0 and named[:10] in out, f"rc={rc}")
        rc, out = tree30([head], size=1)
        record("CI --tree: a complete payload of clean messages passes (control)",
               rc == 0, f"rc={rc}")
        rc, out = tree30([side, head])
        record("CI --tree: a listed commit not reachable from the pushed head fails closed",
               rc != 0 and "Traceback" not in out, f"rc={rc}")
        rc, out = tree30([head], size=None)
        record("CI --tree: a payload with no declared push size fails closed",
               rc != 0 and "Traceback" not in out, f"rc={rc}")

    # --- 31. REGRESSION (PR #559 review, major 2): an EMPTY list is not a
    # MISSING secret. `not terms` covered both, so a payload whose sources
    # expanded to zero terms printed "the secret is missing or empty" and sent
    # the operator to --sync-ci-secret, which refused for the same reason while
    # reporting "no private sources on this machine".
    with tempfile.TemporaryDirectory() as tmp:
        home, repo = make_repo(tmp, guard, armed=False)
        commit(repo, home, "base", {"base.md": "base\n"})
        base = git(repo, "rev-parse", "HEAD").stdout.strip()
        rc_missing, out_missing = run_ci(guard, repo, base, base, {})
        record("CI: a missing secret still fails, and still says missing or empty",
               rc_missing != 0 and "missing or empty" in out_missing, f"rc={rc_missing}")
        rc_empty, out_empty = run_ci(guard, repo, base, base,
                                     {"PRIVATE_TERMS": json.dumps({"terms": {"org": []}})})
        record("CI: a secret that expands to ZERO terms fails with its own diagnosis",
               rc_empty != 0 and "zero terms" in out_empty
               and "missing or empty" not in out_empty, f"rc={rc_empty}")

    with tempfile.TemporaryDirectory() as tmp:
        home, repo = make_repo(tmp, guard, armed=False)   # sources exist, yield nothing
        git(repo, "remote", "add", "origin",
            "https://github.com/example-owner/example-public.git")
        kipi = home / ".config" / "kipi"
        (kipi / "empty-tokens").write_text("# no tokens at all\n")
        (kipi / "private-terms.json").write_text(json.dumps(
            {"token_files": [str(kipi / "empty-tokens")]}))
        fakebin = Path(tmp) / "bin"
        fakebin.mkdir()
        log = Path(tmp) / "gh.log"
        gh = fakebin / "gh"
        gh.write_text(f'#!/bin/sh\necho "$*" >> "{log}"\n'
                      'case "$*" in *"repo view"*) echo PUBLIC;; esac\nexit 0\n')
        gh.chmod(0o755)
        env = dict(os.environ, HOME=str(home),
                   PATH=f"{fakebin}{os.pathsep}{os.environ.get('PATH', '')}")
        env.pop("PRIVATE_TERMS", None)
        p = subprocess.run([sys.executable, str(guard), "--sync-ci-secret"], cwd=repo,
                           capture_output=True, text=True, env=env)
        out = p.stdout + p.stderr
        pushed = log.exists() and "secret set" in log.read_text()
        record("sync: sources that yield zero terms refuse the push and name that state",
               p.returncode == 0 and not pushed and "zero terms" in out
               and "no private sources" not in out, f"rc={p.returncode}, pushed={pushed}")

    # --- 32. REGRESSION (PR #559 Codex P2): a RECOGNISED zip that cannot be read
    # through is unscannable, never clean. A CRC-corrupt first member raised
    # BadZipFile out of z.read(); the outer handler read that as "not a zip after
    # all" and fell back to raw bytes, where the LATER deflated member holding the
    # name is invisible. The guard reported clean.
    def crc_corrupt_zip():
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("first.txt", "A" * 2000)
            z.writestr("second.txt", f"prepared for {CLIENT}\n" * 50)
        raw = bytearray(buf.getvalue())
        i = raw.find(b"PK\x01\x02")             # first central-directory record
        raw[i + 16:i + 20] = b"\x00\x00\x00\x00"   # its stored CRC-32
        return bytes(raw)

    with tempfile.TemporaryDirectory() as tmp:
        home, repo = make_repo(tmp, guard)
        rc, out = commit_bytes(repo, home, "add an archive", "bad.zip", crc_corrupt_zip())
        record("local: a zip with an unreadable member BLOCKS (unscannable, not clean)",
               rc != 0 and head_count(repo) == 0 and "Traceback" not in out, f"rc={rc}")
        git(repo, "reset", "-q", "--mixed", check=False)
        (repo / "bad.zip").unlink()
        # Controls: a sound zip still passes, and a file that only LOOKS like a
        # zip still falls back to its raw bytes rather than refusing.
        rc, out = commit_bytes(repo, home, "add an archive", "ok.zip",
                               zip_bytes("nothing private in here"))
        record("local: a sound zip still passes (control)", rc == 0, f"rc={rc}")
        rc, out = commit_bytes(repo, home, "add a blob", "fake.zip",
                               b"PK\x03\x04" + f" prepared for {CLIENT}\n".encode())
        record("local: PK magic with no zip behind it still scans its raw bytes (control)",
               rc != 0 and "Traceback" not in out, f"rc={rc}")
        git(repo, "reset", "-q", "--mixed", check=False)
        (repo / "fake.zip").unlink()
        rc, out = commit_bytes(repo, home, "add a blob", "fake2.zip",
                               b"PK\x03\x04" + b"\x00 nothing private in here\n")
        record("local: PK magic with no zip behind it and nothing private passes (control)",
               rc == 0, f"rc={rc}")
    with tempfile.TemporaryDirectory() as tmp:
        home, repo = make_repo(tmp, guard, armed=False)
        commit(repo, home, "base", {"base.md": "base\n"})
        base = git(repo, "rev-parse", "HEAD").stdout.strip()
        commit_bytes(repo, home, "add an archive", "bad.zip", crc_corrupt_zip())
        head = git(repo, "rev-parse", "HEAD").stdout.strip()
        secret = json.dumps({"terms": {"org": [CLIENT.lower()]}})
        rc, out = run_ci(guard, repo, base, head, {"PRIVATE_TERMS": secret})
        record("CI: a zip with an unreadable member FAILS as not fully scanned",
               rc != 0 and "not fully scanned" in out
               and CLIENT.lower() not in out.lower(), f"rc={rc}")

    # --- 33. REGRESSION (PR #559 Codex P2): the pre-push sync never blocks a
    # push. An unwritable ~/.config/kipi raised OSError out of the digest stamp
    # AFTER gh had already refreshed the secret, so lefthook refused the push and
    # the "never blocks" promise in the docstring was false.
    def sync_with_gh(tmp, home, repo, prepare=None):
        fakebin = Path(tmp) / "bin"
        fakebin.mkdir(exist_ok=True)
        log = Path(tmp) / "gh.log"
        gh = fakebin / "gh"
        gh.write_text(f'#!/bin/sh\necho "$*" >> "{log}"\n'
                      'case "$*" in *"repo view"*) echo PUBLIC;; esac\nexit 0\n')
        gh.chmod(0o755)
        if prepare:
            prepare()
        env = dict(os.environ, HOME=str(home),
                   PATH=f"{fakebin}{os.pathsep}{os.environ.get('PATH', '')}")
        env.pop("PRIVATE_TERMS", None)
        p = subprocess.run([sys.executable, str(guard), "--sync-ci-secret"], cwd=repo,
                           capture_output=True, text=True, env=env)
        return p.returncode, p.stdout + p.stderr, (log.exists()
                                                   and "secret set" in log.read_text())

    with tempfile.TemporaryDirectory() as tmp:
        home, repo = make_repo(tmp, guard)
        git(repo, "remote", "add", "origin",
            "https://github.com/example-owner/example-public.git")
        kipi = home / ".config" / "kipi"
        try:
            rc, out, pushed = sync_with_gh(tmp, home, repo,
                                           prepare=lambda: kipi.chmod(0o500))
        finally:
            kipi.chmod(0o700)
        record("sync: an unwritable digest stamp warns and exits 0, never blocks the push",
               rc == 0 and pushed and "Traceback" not in out and "stamp" in out, f"rc={rc}")
    with tempfile.TemporaryDirectory() as tmp:
        home, repo = make_repo(tmp, guard)
        git(repo, "remote", "add", "origin",
            "https://github.com/example-owner/example-public.git")
        stamp = home / ".config" / "kipi" / "private-terms.ci-digest.example-owner_example-public"
        def unreadable():
            stamp.write_text("whatever\n")
            stamp.chmod(0o000)
        try:
            rc, out, pushed = sync_with_gh(tmp, home, repo, prepare=unreadable)
        finally:
            stamp.chmod(0o600)
        record("sync: an unreadable digest stamp warns, re-pushes and exits 0",
               rc == 0 and pushed and "Traceback" not in out and "stamp" in out, f"rc={rc}")

    # --- 34. REGRESSION (PR #559 review round 5, major): the length floor is ONE
    # value, and a term the floor swallows WHOLE is reported rather than dropped
    # in silence. `short_names_ok` documented a 3-character floor while add()
    # enforced MIN_LEN=4, so every 3-character name the registry approved was
    # discarded with nothing printed. Measured against the live registry
    # 2026-10-24: 1088 terms offered, 1 of them (a contact recorded as initials)
    # protected by no spelling at all, and the guard said `clean`.
    spec = importlib.util.spec_from_file_location("guard_under_test", guard)
    mod = importlib.util.module_from_spec(spec)
    # NO BYTECODE BESIDE THE GUARD UNDER TEST: --against points at a path this
    # suite does not own (a `git show` export, a read-only checkout), and a
    # .pyc written next to it is a side effect a test has no business having.
    was_quiet = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = was_quiet
    # DERIVED FROM THE GUARD UNDER TEST, never restated here: a copied 4 agrees
    # on the day it is written and keeps agreeing after the floor moves.
    floor = mod.MIN_LEN
    at_floor = "Q" + "z" * (floor - 1)        # exactly MIN_LEN: protected
    under_floor = "Q" + "z" * (floor - 2)     # one short: cannot be protected

    def registry_home(tmp, people, short_ok=True):
        home, repo = make_repo(tmp, guard, armed=False)
        reg = Path(tmp) / "clients.json"
        reg.write_text(json.dumps({"clients": [
            {"name": "Quexwell Labs", "slug": "quexwell-labs",
             "contacts": [{"name": p} for p in people]}]}))
        (home / ".config" / "kipi" / "private-terms.json").write_text(json.dumps({
            "json_sources": [{"path": str(reg), "records": "clients",
                              "keys": ["name", "slug"], "people": "contacts",
                              "short_names_ok": short_ok}]}))
        return home, repo

    with tempfile.TemporaryDirectory() as tmp:
        home, repo = registry_home(tmp, [under_floor])
        rc, out = commit(repo, home, "ordinary", {"f.md": "nothing private\n"})
        record("registry: a one-word name under the floor is REPORTED as unprotected",
               rc == 0 and "NOT protected" in out and "person" in out
               and under_floor.lower() not in out.lower(), f"rc={rc}")

    with tempfile.TemporaryDirectory() as tmp:
        # The LIVE shape, and the half a fix aimed only at short_names_ok misses:
        # initials pass the multi-word branch, so `short_names_ok` is never
        # consulted, and every separator spelling is still under the floor.
        home, repo = registry_home(tmp, ["A B"], short_ok=False)
        rc, out = commit(repo, home, "ordinary", {"f.md": "nothing private\n"})
        record("registry: initials whose EVERY spelling is under the floor are REPORTED",
               rc == 0 and "NOT protected" in out and "person" in out, f"rc={rc}")

    with tempfile.TemporaryDirectory() as tmp:
        # CONTROL: quiet when there is nothing to say. A line that prints on
        # every run is noise, and noise gets filtered instead of fixed.
        home, repo = registry_home(tmp, ["Morwen Tallis"])
        rc, out = commit(repo, home, "ordinary", {"f.md": "nothing private\n"})
        record("registry: nothing under the floor prints no unprotected line (control)",
               rc == 0 and "NOT protected" not in out, f"rc={rc}")

    with tempfile.TemporaryDirectory() as tmp:
        # CONTROL: the report is a WARN, never a refusal. The live registry holds
        # one such entry, so failing closed here would be red on its own
        # population from the first run, and a gate that is always red gets
        # switched off.
        home, repo = registry_home(tmp, [under_floor])
        rc, _ = commit(repo, home, "ordinary", {"f.md": f"met {under_floor} today\n"})
        record("registry: an unprotected short name does not block the commit (control)",
               rc == 0, f"rc={rc}")

    with tempfile.TemporaryDirectory() as tmp:
        # ONE floor, and it is add()'s. A one-word name of exactly MIN_LEN is
        # protected; one character shorter is reported instead of vanishing.
        home, repo = registry_home(tmp, [at_floor, under_floor])
        rc_at, _ = commit(repo, home, "ordinary", {"a.md": f"met {at_floor} today\n"})
        git(repo, "reset", "-q", "--mixed", check=False)
        rc_under, out_under = commit(repo, home, "ordinary",
                                     {"b.md": f"met {under_floor} today\n"})
        record(f"short_names_ok: a one-word name of exactly {floor} chars BLOCKS, "
               f"{floor - 1} is reported not silently dropped",
               rc_at != 0 and rc_under == 0 and "NOT protected" in out_under,
               f"rc_at={rc_at}, rc_under={rc_under}")

    # --- 35. REGRESSION (PR #559 review round 6, major): "already public" means
    # a PUBLIC REMOTE's ref, not any ref under refs/remotes -------------------
    # `git branch -r --contains` lists every ref under refs/remotes, and writing
    # one needs no network and no remote at all. Measured in this repo
    # 2026-10-24: 1110 remote-tracking refs, of which 550 sit in 51 namespaces
    # that NO configured remote fetches into. So a merge parent that was never
    # pushed anywhere could excuse its own content, on all three surfaces.
    def local_name_branch(repo, home, branch, files):
        """A branch carrying a private term, admitted under its own bypass."""
        git(repo, "checkout", "-q", "-b", branch)
        rc, _ = commit(repo, home, f"draft\n\n{SKIP_TOKEN}: on a side branch\n", files)
        sha = git(repo, "rev-parse", "HEAD").stdout.strip()
        git(repo, "checkout", "-q", "-")
        commit(repo, home, "main work", {"other.md": "other\n"})
        return rc, sha

    with tempfile.TemporaryDirectory() as tmp:
        # THE LIVE SHAPE: a hand-written ref in a namespace no remote owns.
        home, repo = make_repo(tmp, guard)
        add_public_remote(tmp, repo)
        commit(repo, home, "base", {"base.md": "base\n"})
        rc0, sha = local_name_branch(repo, home, "side",
                                     {"notes.md": f"notes on {CLIENT}\n"})
        git(repo, "update-ref", "refs/remotes/pr/1", sha)
        before = head_count(repo)
        rc, out = merge(repo, home, ["side"], "Merge branch 'side'")
        record("a ref in a namespace NO remote fetches into excuses nothing",
               rc0 == 0 and rc != 0 and head_count(repo) == before,
               f"branch rc={rc0}, merge rc={rc}")
        record("...and the refusal NAMES the namespace instead of staying silent",
               "pr" in out and "not a public remote" in out,
               f"namespace line present={('not a public remote' in out)}")

    with tempfile.TemporaryDirectory() as tmp:
        # THE REVIEWER'S FRAMING: a real, configured, pushed-to remote that is
        # not the public one. A private backup remote is never declared public.
        home, repo = make_repo(tmp, guard)
        add_public_remote(tmp, repo)
        add_remote(tmp, repo, "backup")
        commit(repo, home, "base", {"base.md": "base\n"})
        rc0, _ = local_name_branch(repo, home, "side",
                                   {"notes.md": f"notes on {CLIENT}\n"})
        git(repo, "push", "-q", "backup", "side")
        git(repo, "fetch", "-q", "backup")
        before = head_count(repo)
        rc, out = merge(repo, home, ["side"], "Merge branch 'side'")
        record("a parent pushed only to a NON-PUBLIC remote excuses nothing",
               rc0 == 0 and rc != 0 and head_count(repo) == before,
               f"branch rc={rc0}, merge rc={rc}")

    def stage_path_surface(repo):
        (repo / CLIENT.lower()).mkdir()
        (repo / CLIENT.lower() / "readme.md").write_text("nothing private\n")
        git(repo, "add", f"{CLIENT.lower()}/readme.md")

    def stage_binary_surface(repo):
        (repo / "blob.bin").write_bytes(b"\x00\x01" + CLIENT.encode() + b"\x00")
        git(repo, "add", "blob.bin")

    for surface, stage in (("a file PATH", stage_path_surface),
                           ("a BINARY blob", stage_binary_surface)):
        with tempfile.TemporaryDirectory() as tmp:
            # ALL THREE SURFACES, not just lines. staged_paths_and_binaries asked
            # the same question separately, so a fix on the line scan alone would
            # have left these two excused.
            home, repo = make_repo(tmp, guard)
            add_public_remote(tmp, repo)
            commit(repo, home, "base", {"base.md": "base\n"})
            git(repo, "checkout", "-q", "-b", "side")
            stage(repo)
            rc0, _ = commit(repo, home,
                            f"side\n\n{SKIP_TOKEN}: on a side branch\n")
            sha = git(repo, "rev-parse", "HEAD").stdout.strip()
            git(repo, "checkout", "-q", "-")
            commit(repo, home, "main work", {"other.md": "other\n"})
            git(repo, "update-ref", "refs/remotes/pr/1", sha)
            before = head_count(repo)
            rc, out = merge(repo, home, ["side"], "Merge branch 'side'")
            record(f"an unowned ref does not excuse {surface} either",
                   rc0 == 0 and rc != 0 and head_count(repo) == before,
                   f"branch rc={rc0}, merge rc={rc}")

    with tempfile.TemporaryDirectory() as tmp:
        # THE KNOB IS NOT DEAD CODE. Round 5's finding was a documented value no
        # code path could reach; shipping kipi.publicRemote untested would be the
        # same defect one round later. A remote NOT named origin, declared
        # public, excuses exactly what origin would.
        home, repo = make_repo(tmp, guard)
        add_remote(tmp, repo, "upstream")
        git(repo, "config", "--add", "kipi.publicRemote", "upstream")
        commit(repo, home, "base", {"base.md": "base\n"})
        git(repo, "checkout", "-q", "-b", "pub")
        rc0, _ = commit(repo, home,
                        f"Publish the case study\n\n{SKIP_TOKEN}: permission on file\n",
                        {"study.md": f"# Case study\n\n{CLIENT} shipped it.\n"})
        git(repo, "push", "-q", "upstream", "pub")
        git(repo, "checkout", "-q", "-")
        commit(repo, home, "diverge", {"other.md": "other\n"})
        before = head_count(repo)
        rc, out = merge(repo, home, ["pub"], "Merge branch 'pub'")
        record("a DECLARED public remote that is not origin still excuses its content",
               rc0 == 0 and rc == 0 and head_count(repo) == before + 2,
               f"branch rc={rc0}, merge rc={rc}")

    with tempfile.TemporaryDirectory() as tmp:
        # CONTROL: quiet on an ordinary merge. The namespace line prints only
        # when the verdict actually changed; a line on every merge is noise.
        home, repo = make_repo(tmp, guard)
        add_public_remote(tmp, repo)
        commit(repo, home, "base", {"base.md": "base\n"})
        git(repo, "checkout", "-q", "-b", "pub")
        commit(repo, home, "clean work", {"p.md": "clean\n"})
        git(repo, "push", "-q", "origin", "pub")
        git(repo, "checkout", "-q", "-")
        commit(repo, home, "main work", {"other.md": "other\n"})
        rc, out = merge(repo, home, ["pub"], "Merge branch 'pub'")
        record("an ordinary public merge prints no namespace line (control)",
               rc == 0 and "not a public remote" not in out, f"rc={rc}")

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
