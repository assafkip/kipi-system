#!/usr/bin/env python3
"""Reproducer: a wrapper or a compact separator must not hide a merge or a push.

THE DEFECT (Codex round 4 on PR #155, filed MINOR, measured here as a full bypass):

    true;gh pr merge 155 --admin         ALLOW
    bash -c 'gh pr merge 155 --admin'    ALLOW
    sudo gh pr merge 155 --admin         ALLOW
    nohup gh pr merge 155 --admin        ALLOW
    true;git push origin main            ALLOW

Two independent causes, both fail-OPEN:

1. `shlex.split` does NOT treat `;` as a separator. `true;gh pr merge --admin`
   tokenized as ['true;gh', 'pr', 'merge', '--admin'], so the segment splitter
   never saw two commands and the first token was never `gh`. ONE CHARACTER
   defeated the entire gate. Fixed by tokenizing with `punctuation_chars=True`,
   which is the shlex mode that emits operators as their own tokens.

2. The trigger asked whether token 0 was `gh` / `git`. Any wrapper (`sudo`,
   `nohup`, `timeout 5`, `bash -c`) moves the real command off position 0 and the
   trigger went quiet. Fixed by scanning for the tool token ANYWHERE, then
   demanding position 0 for the safe shape: being unable to see the arguments is
   now a refusal rather than a pass.

Round 3 inverted the gh ARGUMENT check to an allowlist. Round 4 is the same
inversion applied one layer out, to the question of whether this is a gh command
at all. Both had the same failure direction, which is the thing worth
remembering: every part of a gate needs to fail closed, not just the part that
looked like the gate.

REF HATCH (a TAG, not a branch sha: PR #155 was SQUASH-merged, so every
pre-fix commit is unreachable from main and dies with the branch)
-- watch it fail against the code that shipped the hole:

    MERGE_GATE_REF=pre-fix/ask-791-round3 python3 test_merge_bypass_gate_wrappers.py   # RED
    python3 test_merge_bypass_gate_wrappers.py                          # GREEN
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


CASES: list[tuple[str, str, str]] = [
    # --- compact separators: no whitespace around the operator ---
    ("semicolon, no spaces, merge", "true;gh pr merge 155 --admin", "deny"),
    ("semicolon, no spaces, push", "true;git push origin main", "deny"),
    ("double semicolon", "true;;gh pr merge 155 --admin", "deny"),
    ("ampersand background", "true&gh pr merge 155 --admin", "deny"),
    ("pipe, no spaces", "echo x|gh pr merge 155 --admin", "deny"),
    ("spaced && still works (it always did)",
     "echo x && gh pr merge 155 --admin", "deny"),

    # --- wrappers that move the real command off position 0 ---
    ("sudo", "sudo gh pr merge 155 --admin", "deny"),
    ("nohup", "nohup gh pr merge 155 --admin", "deny"),
    ("timeout with its numeric argument", "timeout 5 gh pr merge 155 --admin", "deny"),
    ("nice", "nice gh pr merge 155 --admin", "deny"),
    ("command builtin", "command gh pr merge 155 --admin", "deny"),
    ("wrapper on a push", "sudo git push origin main", "deny"),
    # A wrapper is refused even on the otherwise-safe shape: it is not the plain
    # form, and nobody sudos gh.
    ("wrapper on the safe shape is still not the safe shape",
     "sudo gh pr merge 155 --auto --squash", "deny"),

    # THE WRAPPER LIST IS ITSELF A DENYLIST, so an unknown wrapper is the next
    # bypass. What closes that class is scanning for the `gh` token ANYWHERE and
    # then demanding position 0 -- a wrapper nobody enumerated still cannot hide a
    # merge. Mutation showed the scan was otherwise unobservable (wrapper
    # stripping covered every enumerated case), which is exactly how a
    # load-bearing branch gets deleted by a future cleanup.
    ("an UNKNOWN wrapper cannot hide a merge",
     "myrunner gh pr merge 155 --admin", "deny"),
    ("an unknown wrapper cannot hide even the safe shape",
     "some-future-wrapper --flag gh pr merge 155 --auto --squash", "deny"),
    ("an absolute path to gh is still gh",
     "/opt/homebrew/bin/gh pr merge --auto --squash 155", "allow"),

    # --- shell -c payloads: a whole command inside one quoted token ---
    ("bash -c merge", "bash -c 'gh pr merge 155 --admin'", "deny"),
    ("sh -c merge", "sh -c 'gh pr merge 155 --admin'", "deny"),
    ("zsh -c push", "zsh -c 'git push origin main'", "deny"),
    ("bash -c with a compact separator inside",
     "bash -c 'true;gh pr merge 155 --admin'", "deny"),
    ("wrapper around a shell -c", "sudo bash -c 'gh pr merge 155 --admin'", "deny"),

    # --- the safe path and ordinary commands must survive all of the above ---
    ("safe shape, plain", "gh pr merge --auto --squash 155", "allow"),
    ("safe shape after a separator",
     "git fetch origin;gh pr merge --auto --squash 155", "allow"),
    ("safe shape after &&", "git fetch && gh pr merge --auto --squash 155", "allow"),
    ("feature push after a separator", "true;git push -u origin sana/feature", "allow"),
    ("ordinary chained commands", "echo done && git status", "allow"),
    ("bash -c around something harmless", "bash -c 'echo hello'", "allow"),
    ("pr list mentioning merge", "gh pr list --search merge", "allow"),
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
    print(f"ok  {len(CASES)}/{len(CASES)} wrapper/separator checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
