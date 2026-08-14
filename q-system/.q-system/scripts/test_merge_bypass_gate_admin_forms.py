#!/usr/bin/env python3
"""Reproducer: `gh pr merge --admin=true` must be refused, not only bare `--admin`.

THE DEFECT (Codex major on PR #155, confirmed against gh before fixing):

    $ gh pr merge --admin=notabool 999999
    invalid argument "notabool" for "--admin" flag: strconv.ParseBool: ...
    $ gh pr merge --admin=true 999999 --squash
    GraphQL: Could not resolve to a PullRequest with the number of 999999.

The first proves gh ACCEPTS the `--admin=<value>` spelling and parses it with Go's
strconv.ParseBool. The second proves `--admin=true` clears flag parsing and reaches
the merge call. The original gate matched the token `--admin` exactly, so every
`--admin=<truthy>` form walked straight through the gate whose entire purpose is
to refuse admin merges.

WHY ITS OWN FILE. Folded into the main suite this would have been one more green
line in a run that was already green, and a case added after its fix has never been
watched fail. This file carries a REF HATCH so it can be pointed at the pre-fix
code and observed going red:

    MERGE_GATE_REF=9092c61e python3 test_merge_bypass_gate_admin_forms.py   # RED
    python3 test_merge_bypass_gate_admin_forms.py                          # GREEN

`--admin=false` is asserted ALLOW on purpose. Denying it would be a false positive
on a command that explicitly declines admin, and a gate that refuses correct
commands is one somebody switches off.
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
    """Load classify() from the working tree, or from a git ref when asked.

    The ref hatch is what lets this case be watched FAILING against the code that
    shipped the bug. Without it the assertion below is unfalsifiable decoration.
    """
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


# strconv.ParseBool truthy spellings. gh rejects anything outside ParseBool, so a
# value that is neither truthy nor falsy can never merge -- but it is still refused,
# because "the command would have failed anyway" is not a reason to hand it through.
TRUTHY = ["true", "True", "TRUE", "1", "t", "T"]
FALSY = ["false", "False", "FALSE", "0", "f", "F"]

CASES: list[tuple[str, str, str]] = [
    ("bare --admin", "gh pr merge 999 --squash --admin", "deny"),
]
for v in TRUTHY:
    CASES.append((f"--admin={v} (truthy)", f"gh pr merge 999 --squash --admin={v}", "deny"))
for v in FALSY:
    CASES.append((f"--admin={v} (falsy, must NOT be a false positive)",
                  f"gh pr merge 999 --squash --admin={v}", "allow"))
CASES += [
    ("--admin=garbage (gh would reject it; refuse anyway)",
     "gh pr merge 999 --admin=notabool", "deny"),
    ("--admin=true first, before the PR number",
     "gh pr merge --admin=true --squash 999", "deny"),
    ("--admin=true quoted inside a body stays allowed",
     "gh pr merge 9 --auto --body 'never --admin=true this'", "allow"),
    ("--auto is still allowed", "gh pr merge --auto --squash 999", "allow"),
]


def main() -> int:
    classify, label = _load_classify()
    cwd = str(REPO)
    failures = []
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
    print(f"ok  {len(CASES)}/{len(CASES)} admin-form checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
