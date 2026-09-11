#!/usr/bin/env python3
"""Reproducer: the PUSH side must refuse a hidden `git`, exactly as the merge side does.

THE DEFECT (Codex round 5 on PR #159) and why it is the interesting one:

Round 4 gave the MERGE side a token scan so no wrapper could hide `gh`. It left
the PUSH side keyed on token 0. Round 5 then found precisely that gap:

    myrunner gh pr merge 155 --admin     DENY   (round 4 fixed this)
    myrunner git push origin main        ALLOW  (identical shape, other tool)

The rule was right. It was implemented at one of the two places that needed it.
That is the defect class RELOCATING rather than being killed: a fix that closes a
hole on one side and leaves its twin open reads like a fix and is not one. The
answer was not a third patch but a single `_tool_position()` that both verdicts
ask, so there is one place to be wrong instead of two.

Three vectors, all fail-OPEN, all closed here:

1. `bash -lc '<cmd>'` -- `-lc` is one flag cluster ending in c and carries a
   command payload exactly like `-c`. Matching the exact token `-c` missed it,
   which defeated BOTH sides at once.
2. An unknown wrapper (`myrunner git push ...`). The wrapper list is a denylist,
   so the token scan is what closes the class, not a longer list.
3. A newline. shlex treats a newline as WHITESPACE, never a separator token, so
   `true\\ngit push origin main` arrived as ONE segment whose first token was
   `true`. Now split into logical lines before tokenizing, honouring backslash
   continuations so a wrapped command is not chopped in half.

REF HATCH (a TAG, not a branch sha: these branches get squash-merged and the
pre-fix commits die with them) -- watch it fail against the code that shipped it:

    MERGE_GATE_REF=pre-fix/ask-791-round4 python3 test_merge_bypass_gate_hidden_tool.py  # RED
    python3 test_merge_bypass_gate_hidden_tool.py                                        # GREEN
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

# Built rather than written literally: this gate runs live in the sessions that
# edit it, and it refuses a command string carrying the flag it exists to refuse.
ADMIN = "--" + "admin"


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
    # --- 1. combined shell flag clusters, BOTH sides ---
    ("bash -lc hides a push", "bash -lc 'git push origin main'", "deny"),
    ("sh -ic hides a push", "sh -ic 'git push origin main'", "deny"),
    ("bash -lc hides a merge", f"bash -lc 'gh pr merge 155 {ADMIN}'", "deny"),
    ("plain -c still works", "bash -c 'git push origin main'", "deny"),

    # --- 2. unknown wrapper: the wrapper list is a denylist, the scan is not ---
    ("unknown wrapper hides a push", "myrunner git push origin main", "deny"),
    ("unknown wrapper hides a merge", f"myrunner gh pr merge 155 {ADMIN}", "deny"),
    ("unknown wrapper with its own flags",
     "some-runner --opt v git push origin main", "deny"),

    # --- 3. newline as a separator ---
    ("newline before a push", "true\ngit push origin main", "deny"),
    ("newline before a merge", f"true\ngh pr merge 155 {ADMIN}", "deny"),
    ("newline mid-script, push on the last line",
     "git fetch\ngit status\ngit push origin main", "deny"),
    # PINNED DELIBERATELY, not by accident. A `cd` to somewhere that is not a git
    # repo makes the remote unresolvable, and the gate's stated rule is that
    # unresolvable means ALLOW (it can only refuse what it can prove targets a
    # protected branch on a GitHub remote). The first draft of the case above used
    # `cd /tmp` and went green for THIS reason rather than for the newline logic
    # it meant to test -- a fixture that conflated two properties and would have
    # passed against code with the newline bug still in it.
    ("cd away from any repo makes the target unprovable, so it is allowed",
     "cd /tmp\ngit push origin main", "allow"),
    ("backslash continuation is joined, not split",
     "git push origin main \\\n  --dry-run", "deny"),

    # --- the safe path survives every mechanism above ---
    ("safe merge shape", "gh pr merge --auto --squash 155", "allow"),
    ("feature push", "git push -u origin sana/feature", "allow"),
    ("feature push after a newline",
     "git fetch origin\ngit push -u origin sana/feature", "allow"),
    ("multi-line script with no protected push",
     "cd /tmp\ngit fetch origin\ngit status", "allow"),
    ("shell -c around something harmless", "bash -lc 'echo hello'", "allow"),
    ("plain status", "git status", "allow"),
    ("git merge is local, still not our business", "git merge origin/main", "allow"),

    # --- FALSE POSITIVES the token scan introduced (Codex round 6, minor) ---
    # Every round widened the trigger, and round 6 is where the widening started
    # refusing ordinary commands. A gate that denies `echo git push` is one
    # somebody switches off, and a gate that is off protects nothing. These pin
    # the narrowing so a future round cannot widen it back silently.
    ("echo is not an invocation", "echo git push", "allow"),
    ("ls is not an invocation", "ls git push", "allow"),
    ("grep over a file that mentions it", "grep push git-notes.txt", "allow"),
    ("cat with those words as filenames", "cat git push notes.txt", "allow"),
    ("prose in a quoted echo", 'echo "git push is how you publish"', "allow"),
    ("printf is not an invocation", "printf 'git push'", "allow"),
    # The narrowing must not reach a command that CAN run a child. Being wrong
    # about a name in the non-executing list costs a false deny; being wrong in
    # this direction costs a bypass, which is why the list excludes these.
    ("xargs can run a child, so it is not 'non-executing'",
     "xargs git push origin main", "deny"),
]


# Mutation showed two of the round-5 branches were EQUIVALENT under the decision
# alone: the push walk finds `push` anywhere, so it re-denies a hidden git even
# with `_tool_position` neutered, and the token scan re-denies a newline case even
# with line-splitting removed. Same verdict, different route. Two consequences,
# both pinned below, because an unpinned branch is one a future cleanup deletes
# while every test stays green:
#
#   - the hidden-tool REASON is asserted, so the branch that produces it is
#     observable rather than merely redundant;
#   - a `cd` into a REAL repo followed by a protected push is the one case that
#     line-splitting alone decides. Without it, token 0 is `cd`, the classifier
#     takes the cd branch and never evaluates the push at all.
REASON_CASES: list[tuple[str, str, str]] = [
    ("a hidden git is explained as unseeable, not as a branch verdict",
     "myrunner git push origin main",
     "cannot see which branch it targets"),
    ("a hidden gh merge says the same thing on its side",
     f"myrunner gh pr merge 155 {ADMIN}",
     "cannot see its real arguments"),
]

# Resolved at runtime: this checkout IS a github remote, so a cd into it followed
# by a push to main is provably a protected push. Hard-coding a path would make
# the case pass for the wrong reason on any other machine.
CD_THEN_PUSH = (f"cd {REPO}\ngit push origin main", "deny")


def main() -> int:
    classify, label = _load_classify()
    cwd = str(REPO)
    failures = []
    for name, command, want_in_reason in REASON_CASES:
        got, reason = classify(command, cwd)
        if got != "deny" or want_in_reason not in reason:
            failures.append(f"{name}\n      command: {command!r}\n"
                            f"      want deny mentioning {want_in_reason!r}\n"
                            f"      got {got}: {reason[:90]}")
    _cmd, _want = CD_THEN_PUSH
    _got, _reason = classify(_cmd, cwd)
    if _got != _want:
        failures.append(f"cd into a real repo then push to main\n"
                        f"      command: {_cmd!r}\n"
                        f"      want {_want}, got {_got}  {_reason[:70]}")
    for name, command, want in CASES:
        got, reason = classify(command, cwd)
        if got != want:
            failures.append(f"{name}\n      command: {command!r}\n"
                            f"      want {want}, got {got}  {reason[:70]}")
    print(f"target: {label}")
    if failures:
        print(f"FAIL {len(failures)}/{len(CASES)}")
        for f in failures:
            print("    " + f)
        return 1
    print(f"ok  {len(CASES) + len(REASON_CASES) + 1} hidden-tool checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
