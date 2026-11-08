#!/usr/bin/env python3
"""pr-closing-keyword-check.py (ASK-4079): a PR body that would close another open PR
on merge is refused. Scar: 2026-11-08 22:57Z, merging #671 closed the live #664
because its body said "the WIP release closed #664"."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHECK = HERE.parent / "pr-closing-keyword-check.py"
FAILS = []


def check(name, got, want):
    if got == want:
        print(f"  ok: {name}")
    else:
        FAILS.append(name)
        print(f"  FAIL: {name}\n     got  {got!r}\n     want {want!r}")


def run(body, commits="", own=671, open_prs="664 670", check_path=CHECK):
    with tempfile.TemporaryDirectory() as d:
        b = Path(d) / "body.md"; b.write_text(body)
        c = Path(d) / "commits.txt"; c.write_text(commits)
        env = dict(os.environ, KIPI_PR_KEYWORD_OPEN_PRS=open_prs)
        r = subprocess.run([sys.executable, str(check_path), "--repo", "assafkip/kipi-system",
                            "--pr", str(own), "--body-file", str(b), "--commits-file", str(c)],
                           capture_output=True, text=True, env=env)
        return r.returncode, r.stdout


print("== pr-closing-keyword-check")
rc, out = run("At 21:58:58Z the WIP release closed #664 as kind no-dor.")
check("the scar body is refused: 'closed #664' would close the open PR", (rc, "open PR #664" in out), (1, True))
for phrase in ("Fixes #670", "resolves: #664", "This closes assafkip/kipi-system#664", "fixed #670."):
    check(f"refused: {phrase!r}", run(phrase)[0], 1)
check("a closing keyword in a commit message is refused too",
      run("clean body", commits="fix(x): y\n\nThis closes #664\n")[0], 1)
for phrase in ("Fixes ASK-4057.", "PR 664 was shut by the release", "closed PR #664 earlier",
               "see #664 for context", "Closes #671", "closes otherorg/other#664",
               "fixes #12 (an issue, not a PR)"):
    check(f"allowed: {phrase!r}", run(phrase)[0], 0)
check("a failed lookup fails closed (exit 2), never reads as allowed",
      run("closes #999", open_prs="LOOKUP-FAILS")[0], 2)
# Negative control: a check that never looks at the keyword lets the scar through.
with tempfile.TemporaryDirectory() as d:
    mut = Path(d) / "check-mut.py"
    src = CHECK.read_text().replace("r\"(?i)\\b(close[sd]?|fix(?:e[sd])?|resolve[sd]?)\\b",
                                    "r\"(?i)\\b(nevermatchthis)\\b")
    mut.write_text(src)
    check("negative control: the mutant without the keyword pattern differs from the check",
          src != CHECK.read_text(), True)
    check("negative control: that mutant lets the scar body through, so the first check can fail",
          run("the WIP release closed #664", check_path=mut)[0], 0)

print()
if FAILS:
    print(f"FAILED: {len(FAILS)}")
    sys.exit(1)
print("all pr-closing-keyword checks passed")
