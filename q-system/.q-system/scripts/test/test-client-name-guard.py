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

    failed = [n for n, ok in results if not ok]
    print()
    if failed:
        print(f"client-name-guard self-test: {len(failed)} FAILED")
        return 1
    print(f"client-name-guard self-test: all {len(results)} cases passed")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--against", type=Path, default=GUARD,
                    help="guard implementation to test (for the negative self-test)")
    sys.exit(main(ap.parse_args().against))
