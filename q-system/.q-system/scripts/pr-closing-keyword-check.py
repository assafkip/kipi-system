#!/usr/bin/env python3
"""Refuse a PR whose body or commit messages would close ANOTHER open PR on merge (ASK-4079).

WHY. 2026-11-08 22:57:18Z: merging #671 closed PR #664, a live lane (ASK-4013),
because #671's body said "the WIP release closed #664". GitHub reads close,
closes, closed, fix, fixes, fixed, resolve, resolves and resolved, followed by
#N, as a closing keyword, for pull requests as well as issues, and the #664
timeline names PR #671 as the closer. Every fleet PR body is written by an
agent, and agents describe other PRs in prose all the time.

WHAT IT REFUSES. A closing keyword followed by `#N` or `owner/repo#N` (this
repo) where N is not this PR and N is an OPEN pull request. A GitHub issue
reference stays allowed: closing an issue on merge is what the keyword is for
(heartbeat-red issues, for one). Linear ids (ASK-123) are not GitHub references.

Usage (verify.yml, pull_request events):
    pr-closing-keyword-check.py --repo owner/name --pr N --body-file F --commits-file C
--commits-file holds the commit messages, one after another. Lookups go through
`gh api`; KIPI_PR_KEYWORD_OPEN_PRS ("664 670") replaces them in tests only.
Exit 0 clean, 1 refused, 2 could not check (a lookup failed: fail closed).
"""
import argparse
import os
import re
import subprocess
import sys

KEYWORD_RX = re.compile(
    r"(?i)\b(close[sd]?|fix(?:e[sd])?|resolve[sd]?)\b\s*:?\s+"
    r"(?:(?P<repo>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+))?#(?P<num>\d+)\b")


def references(text: str, own: int, repo: str) -> list:
    """(keyword, number) for each closing reference in this repo to a number not own."""
    out = []
    for m in KEYWORD_RX.finditer(text or ""):
        ref_repo = m.group("repo")
        if ref_repo and ref_repo.lower() != repo.lower():
            continue
        num = int(m.group("num"))
        if num != own:
            out.append((m.group(0), num))
    return out


def open_pr(repo: str, num: int):
    """True if #num is an open PR, False if it is not (an issue, or a closed PR),
    None if the lookup failed."""
    fixture = os.environ.get("KIPI_PR_KEYWORD_OPEN_PRS")
    if fixture is not None:
        if fixture == "LOOKUP-FAILS":
            return None
        return str(num) in fixture.split()
    try:
        res = subprocess.run(["gh", "api", f"repos/{repo}/pulls/{num}", "--jq", ".state"],
                             capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if res.returncode == 0:
        return res.stdout.strip() == "open"
    if "Not Found" in (res.stderr + res.stdout) or "404" in res.stderr:
        return False  # not a PR: an issue reference, which may close on purpose
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--pr", required=True, type=int)
    ap.add_argument("--body-file", required=True)
    ap.add_argument("--commits-file")
    a = ap.parse_args()
    texts = [("the PR body", open(a.body_file, errors="replace").read())]
    if a.commits_file:
        texts.append(("a commit message", open(a.commits_file, errors="replace").read()))
    bad, unknown = [], []
    for where, text in texts:
        for phrase, num in references(text, a.pr, a.repo):
            state = open_pr(a.repo, num)
            if state is None:
                unknown.append(f"{where}: '{phrase}' (could not look up #{num})")
            elif state:
                bad.append(f"{where}: '{phrase}' would close open PR #{num} when this merges")
    for line in bad:
        print(f"REFUSED: {line}")
    for line in unknown:
        print(f"UNCHECKED: {line}")
    if bad:
        print("Reword it without the keyword (for example 'PR 664 was shut'), then save the body; "
              "this check runs again on the edit.")
        return 1
    if unknown:
        return 2
    print("ok: no closing keyword points at another open PR")
    return 0


if __name__ == "__main__":
    sys.exit(main())
