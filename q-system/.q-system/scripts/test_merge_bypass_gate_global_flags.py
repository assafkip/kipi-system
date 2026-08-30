#!/usr/bin/env python3
"""Reproducer: a gh GLOBAL FLAG must not be able to smuggle a merge past the gate.

THE DEFECT (Codex major on PR #155 round 3, plus one this probe found itself):

    gh -R owner/repo pr merge 155 --admin          ALLOW   reported
    gh --repo owner/repo pr merge 155 --admin      ALLOW   same class
    gh --hostname github.com pr merge 155 --admin  ALLOW   never reported
    GH_REPO=other/repo gh pr merge --auto --squash ALLOW   never reported

The round-2 gate located the subcommand by filtering non-dash tokens and reading
the first two. Any global flag that takes a SEPARATE value leaves that value in
the positional stream, so `pr merge` slid out of positions 0 and 1 and the merge
check never fired. The `=` spellings happened to work, which is what made the hole
look like one flag rather than a class.

WHY THE FIX IS AN ALLOWLIST AND NOT THREE MORE PATTERNS. Three spellings in three
review rounds against gh's argument grammar -- which this repo neither owns nor can
enumerate -- is the signal to invert the rule instead of extending the list. A
denylist fails OPEN on the shape nobody thought of; an allowlist fails CLOSED. The
cases below therefore assert the PROPERTY (anything but the safe shape is refused)
rather than a list of known-bad spellings, so a grammar feature invented next year
is covered by construction.

REF HATCH (a TAG, not a branch sha: PR #155 was SQUASH-merged, so every
pre-fix commit is unreachable from main and dies with the branch)
-- watch it fail against the code that shipped the hole:

    MERGE_GATE_REF=pre-fix/ask-791-round2 python3 test_merge_bypass_gate_global_flags.py   # RED
    python3 test_merge_bypass_gate_global_flags.py                          # GREEN
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REL = "q-system/.q-system/scripts/merge-bypass-gate.py"
HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]


def _load_classify():
    ref = os.environ.get("MERGE_GATE_REF", "").strip()
    if ref:
        src = subprocess.run(["git", "-C", str(REPO), "show", f"{ref}:{REL}"],
                             capture_output=True, text=True)
        if src.returncode != 0:
            print(f"FAIL: cannot read {REL} at ref {ref!r}: {src.stderr.strip()}")
            sys.exit(2)
        tmp = Path(tempfile.mkdtemp()) / "gate_at_ref.py"
        tmp.write_text(src.stdout)
        target, label = tmp, f"ref {ref}"
    else:
        target, label = REPO / REL, "working tree"
    spec = importlib.util.spec_from_file_location("gate_under_test", target)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.classify, label


# Every global-flag spelling, with and without the admin flag. The admin flag is
# incidental here: the POINT is that a global flag must not make a merge
# unrecognisable, so the no-admin rows matter just as much.
CASES: list[tuple[str, str, str]] = [
    ("-R shorthand", "gh -R owner/repo pr merge 155 --squash --admin", "deny"),
    ("--repo separate value", "gh --repo owner/repo pr merge 155 --admin", "deny"),
    ("--repo= joined value", "gh --repo=owner/repo pr merge 155 --admin", "deny"),
    ("--hostname separate value", "gh --hostname github.com pr merge 155 --admin", "deny"),
    ("-R with no admin flag at all is still not the safe shape",
     "gh -R owner/repo pr merge 155 --auto --squash", "deny"),
    ("env prefix can retarget the repo without changing one argument",
     "GH_REPO=other/repo gh pr merge 155 --auto --squash", "deny"),
    ("GH_HOST prefix, same class",
     "GH_HOST=ghe.example.com gh pr merge 155 --auto --squash", "deny"),
    ("a global flag this gate has never heard of is refused by construction",
     "gh --some-future-global x pr merge 155 --auto --squash", "deny"),
    # --auto is the whole reason the safe shape is safe: it is the only merge that
    # lets GitHub hold the PR until the required checks pass.
    ("merge without --auto", "gh pr merge 155 --squash", "deny"),

    # The safe shape still works, in the orderings real callers use.
    # linear-worker.sh runs `gh pr merge --auto --squash "$pr"`.
    ("safe shape, worker ordering", "gh pr merge --auto --squash 155", "allow"),
    ("safe shape, ref first", "gh pr merge 155 --auto --squash", "allow"),
    ("safe shape, short method flag", "gh pr merge 155 --auto -s", "allow"),
    ("safe shape with delete-branch", "gh pr merge --auto -d --squash 155", "allow"),
    ("safe shape with a PR url",
     "gh pr merge https://github.com/o/r/pull/155 --auto --squash", "allow"),

    # Non-merge gh commands must stay out of the way entirely.
    ("pr list mentioning merge", "gh pr list --search merge", "allow"),
    ("pr view", "gh pr view 155", "allow"),
    ("api call", "gh api repos/o/r/commits/abc/status", "allow"),
]


# The decision alone under-tests this gate. Several branches deny the SAME command
# for different reasons -- a global-flag command is refused both by the subcommand
# check and, one step later, by the unknown-argument check. Mutation showed that
# removing the subcommand check changed no verdict, only the explanation. The
# explanation is what teaches the operator which shape to use, so it is asserted
# here and the branch becomes observable instead of silently redundant.
REASON_CASES: list[tuple[str, str, str]] = [
    ("-R is explained as a subcommand shift, not as an unknown argument",
     "gh -R owner/repo pr merge 155 --auto --squash",
     "not the plain `gh pr merge` form"),
    ("an unknown flag is named in the refusal",
     "gh pr merge 155 --auto --squash --admin",
     "unrecognised argument"),
    # UPDATED 2026-08-30 (ASK-1179), and it was red for TWO reasons stacked.
    # The outer one was a NameError that crashed the classifier on this exact
    # command. Fixing that exposed this one, which had never actually run: the
    # case pinned the pre-d666594d refusal wording ("does not defer to the
    # required checks"), while d666594d deliberately moved the deferral target
    # from a required check that may not exist to a local green receipt.
    #
    # The VERDICT never changed -- this form is still denied -- so only the
    # explanation is re-pinned, and it is re-pinned to a specific string rather
    # than relaxed to "any deny", because the explanation is what tells the
    # operator which shape to use.
    ("a merge without --auto is refused and names the receipt it wants",
     "gh pr merge 155 --squash",
     "no green receipt"),
    ("an env prefix is explained as a retarget",
     "GH_REPO=other/repo gh pr merge 155 --auto --squash",
     "an environment prefix"),
]


def main() -> int:
    classify, label = _load_classify()
    cwd = str(REPO)
    failures = []
    for name, command, want_in_reason in REASON_CASES:
        got, reason = classify(command, cwd)
        if got != "deny" or want_in_reason not in reason:
            failures.append(f"{name}\n      command: {command}\n"
                            f"      want deny mentioning {want_in_reason!r}\n"
                            f"      got {got}: {reason[:90]}")
    for name, command, want in CASES:
        got, reason = classify(command, cwd)
        if got != want:
            failures.append(f"{name}\n      command: {command}\n"
                            f"      want {want}, got {got}  {reason[:70]}")
    print(f"target: {label}")
    if failures:
        print(f"FAIL {len(failures)}/{len(CASES)}")
        for f in failures:
            print("    " + f)
        return 1
    print(f"ok  {len(CASES) + len(REASON_CASES)} global-flag checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
