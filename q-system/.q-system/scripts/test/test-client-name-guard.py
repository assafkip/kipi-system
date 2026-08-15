#!/usr/bin/env python3
"""Paired test for client-name-guard.py (ASK-747).

WHY THIS FILE EXISTS. The guard shipped with no test at all, and its own
introducing commit was the defect: that message DOCUMENTED the bypass token, the
old `if SKIP in text` read the mention as an invocation, both hook stages printed
`bypassed`, and the guard never scanned the commit that introduced it. A guard
any commit can switch off by talking about it is not a gate.

DRIVEN AS A SUBPROCESS, NOT BY IMPORTING AND MONKEYPATCHING. TOKENS_FILE is
resolved from Path.home() at import time, so a test that patched the module
constant would be testing a shape the hook never runs. Every case below sets a
real HOME with a real token list, stages real content in a real git repo, and
runs the real argv the lefthook stages use (lefthook.yml: `--staged` in
pre-commit, `--message {1}` in commit-msg).

NEGATIVE SELF-TEST: run with --against <path-to-pre-fix-guard> to point the same
cases at the pre-fix blob. The four cases marked PRE_FIX_REGRESSION must FAIL
there. A case that passes against both versions is not measuring this fix.
"""

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
GUARD = HERE.parent / "client-name-guard.py"

# A synthetic client token. NOT a real client name: this repo is public, which is
# the entire premise of the guard under test, and validate-separation Gate 1.2
# refuses a shipped file that names a live one.
CLIENT = "Zorptech"
SKIP_TOKEN = "client-name-guard-skip"

results = []


def record(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))


def run_guard(guard, repo, home, argv, msg_file=None):
    """Run the guard exactly as a lefthook stage does. Returns (rc, stdout)."""
    env = dict(os.environ, HOME=str(home))
    env.pop("LEFTHOOK_COMMIT_MSG_FILE", None)
    if msg_file is not None:
        env["LEFTHOOK_COMMIT_MSG_FILE"] = str(msg_file)
    p = subprocess.run([sys.executable, str(guard)] + argv, cwd=repo,
                       capture_output=True, text=True, env=env)
    return p.returncode, p.stdout + p.stderr


def make_env(tmp):
    """A HOME carrying an armed token list, and an initialised git repo."""
    home = Path(tmp) / "home"
    (home / ".config" / "kipi").mkdir(parents=True)
    (home / ".config" / "kipi" / "client-tokens").write_text(
        f"# one token per line\n{CLIENT}\n")
    repo = Path(tmp) / "repo"
    repo.mkdir()
    for cmd in (["init", "-q"], ["config", "user.email", "t@t"],
                ["config", "user.name", "t"]):
        subprocess.run(["git"] + cmd, cwd=repo, check=True,
                       capture_output=True)
    return home, repo


def stage(repo, name, content):
    (repo / name).write_text(content)
    subprocess.run(["git", "add", name], cwd=repo, check=True,
                   capture_output=True)


def main(guard):
    print(f"client-name-guard self-test against: {guard}\n")

    # --- 1. PRE_FIX_REGRESSION: a message that MENTIONS the token is SCANNED ---
    # The acceptance case from the DoR, and the guard's own origin story.
    with tempfile.TemporaryDirectory() as tmp:
        home, repo = make_env(tmp)
        msg = repo / "MSG"
        msg.write_text(
            f"Add the bypass guard\n\n"
            f"Authors can bypass this with the {SKIP_TOKEN} token when a case\n"
            f"study has recorded permission. Rolled out for {CLIENT}.\n")
        rc, out = run_guard(guard, repo, home, ["--message", str(msg)])
        record("prose mentioning the token is still SCANNED and BLOCKS",
               rc == 1 and CLIENT.lower() in out.lower(),
               f"rc={rc} {out.strip().splitlines()[:1]}")

    # --- 2. a real trailer bypass still works -------------------------------
    # Guards the fix against going permanently strict: a gate with no usable
    # intentional path gets deleted, not obeyed.
    with tempfile.TemporaryDirectory() as tmp:
        home, repo = make_env(tmp)
        msg = repo / "MSG"
        msg.write_text(
            f"Publish the case study\n\n"
            f"Permission recorded 2026-08-01.\n\n"
            f"{SKIP_TOKEN}: case study, permission on file\n"
            f"About {CLIENT} specifically.\n")
        rc, out = run_guard(guard, repo, home, ["--message", str(msg)])
        record("a trailer line DOES bypass", rc == 0 and "bypass" in out.lower(),
               f"rc={rc}")

    # --- 3. the bare token alone on a line is also a valid trailer ----------
    with tempfile.TemporaryDirectory() as tmp:
        home, repo = make_env(tmp)
        msg = repo / "MSG"
        msg.write_text(f"Publish\n\nAbout {CLIENT}.\n\n{SKIP_TOKEN}\n")
        rc, _ = run_guard(guard, repo, home, ["--message", str(msg)])
        record("the token alone on its own line is a valid trailer", rc == 0,
               f"rc={rc}")

    # --- 4. PRE_FIX_REGRESSION: a git COMMENT line cannot authorise ---------
    # Git strips '#' lines from the recorded message, so a bypass claimed there
    # would leave no audit trail at all.
    with tempfile.TemporaryDirectory() as tmp:
        home, repo = make_env(tmp)
        msg = repo / "MSG"
        msg.write_text(
            f"Add a note about {CLIENT}\n\n"
            f"# On branch main\n# {SKIP_TOKEN}\n")
        rc, _ = run_guard(guard, repo, home, ["--message", str(msg)])
        record("a token in a stripped '#' comment does NOT bypass", rc == 1,
               f"rc={rc}")

    # --- 5. PRE_FIX_REGRESSION: --staged never reads the bypass from the DIFF -
    # THE SELF-BLINDNESS. The file that defines the token is the guard itself, so
    # under the old rule any commit touching it disarmed the staged scan.
    with tempfile.TemporaryDirectory() as tmp:
        home, repo = make_env(tmp)
        stage(repo, "guardlike.py",
              f'SKIP = "{SKIP_TOKEN}"\nOWNER = "{CLIENT}"\n')
        (Path(repo) / ".git" / "COMMIT_EDITMSG").write_text("ordinary commit\n")
        rc, out = run_guard(guard, repo, home, ["--staged"])
        record("token in the DIFF does not disarm the staged scan",
               rc == 1 and CLIENT.lower() in out.lower(), f"rc={rc}")

    # --- 6. PRE_FIX_REGRESSION: the guard scans ITS OWN file ----------------
    # DoR acceptance: plant a client name in client-name-guard.py itself.
    with tempfile.TemporaryDirectory() as tmp:
        home, repo = make_env(tmp)
        planted = GUARD.read_text() + f'\n# engagement notes for {CLIENT}\n'
        stage(repo, "client-name-guard.py", planted)
        (Path(repo) / ".git" / "COMMIT_EDITMSG").write_text("edit the guard\n")
        rc, out = run_guard(guard, repo, home, ["--staged"])
        record("a client name planted in client-name-guard.py itself BLOCKS",
               rc == 1 and CLIENT.lower() in out.lower(), f"rc={rc}")

    # --- 7. a genuine staged bypass, authorised from the message ------------
    with tempfile.TemporaryDirectory() as tmp:
        home, repo = make_env(tmp)
        stage(repo, "study.md", f"# Case study\n\n{CLIENT} shipped it.\n")
        msg = repo / "MSG"
        msg.write_text(f"Publish case study\n\n{SKIP_TOKEN}: permission on file\n")
        rc, _ = run_guard(guard, repo, home, ["--staged"], msg_file=msg)
        record("a trailer in the message authorises the STAGED stage too",
               rc == 0, f"rc={rc}")

    # --- 8. clean content passes, absent token list warns and passes --------
    with tempfile.TemporaryDirectory() as tmp:
        home, repo = make_env(tmp)
        stage(repo, "ok.md", "nothing sensitive here\n")
        (Path(repo) / ".git" / "COMMIT_EDITMSG").write_text("ordinary\n")
        rc, _ = run_guard(guard, repo, home, ["--staged"])
        record("clean staged content passes", rc == 0, f"rc={rc}")

    with tempfile.TemporaryDirectory() as tmp:
        _, repo = make_env(tmp)
        bare = Path(tmp) / "barehome"
        bare.mkdir()
        stage(repo, "x.md", f"{CLIENT}\n")
        (Path(repo) / ".git" / "COMMIT_EDITMSG").write_text("ordinary\n")
        rc, out = run_guard(guard, repo, bare, ["--staged"])
        record("no token list => WARN and pass, never block",
               rc == 0 and "no token list" in out, f"rc={rc}")

    failed = [n for n, ok, _ in results if not ok]
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
