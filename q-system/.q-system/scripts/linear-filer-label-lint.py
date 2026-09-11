#!/usr/bin/env python3
"""Pairs with `.claude/rules/automated-filer-marking.md`: a file that files Linear
issues must SAY which kind of filer it is (ASK-882).

WHAT THIS GATE ACTUALLY DECIDES, AND WHAT IT REFUSES TO DECIDE

The rule this pairs with originally shipped with an explicit note that no gate
could exist here, because catching a future filer "would mean statically deciding
'is this call site creating a Linear issue without a human', which is a judgment
a regex loses". That reasoning is correct and this script does not overturn it.

So the gate is split along `skill-hook-pairing.md`'s own decision rule:

  DETERMINISTIC (this script)  does this file construct a Linear issueCreate?
  JUDGMENT      (the author)   is a human deciding that issue should exist?

A regex can see the first perfectly. It cannot see the second, so the second is
not guessed -- it is DECLARED, once, in the file, by the person who knows. The
gate's only demand is that the declaration exists. It never infers a posture and
it never rewrites one.

That is why a compliant file has exactly two ways to pass, and both are explicit:

  1. It references the triage label (`needs-triage`). It marks its own output,
     which is the reference implementation in `alert-to-linear.py`.
  2. It carries a posture marker naming itself human-driven, WITH a reason:
         # linear-filer: human-in-the-loop -- <why a person decides each issue>

WHY A MARKER AND NOT AN ALLOWLIST OF FILENAMES

An allowlist answers "is this file exempt" in a place the next author never
opens, and it goes stale silently the moment a human-driven script grows a
scheduled path. The marker sits on the code that does the filing, so a script
that changes posture has to move its own line to keep passing.

MEASURED BEFORE IT WAS WRITTEN (this is why it is not stricter)

Run across this repo 2026-08-16: 8 files construct `issueCreate`, and only ONE
referenced `needs-triage`. A gate demanding the label outright would have been
red on 7 files the day it landed -- unsatisfiable for its own population, which
is how a gate gets switched off and then protects nothing. Demanding a DECLARED
posture is satisfiable by every one of them and still blocks the case that
matters: a NEW filer that thought about neither.

HONEST BOUNDARY -- read this before trusting the gate's silence

- It matches a SHAPE (`issueCreate` in the text), not a behaviour. A filer that
  reaches Linear through some future helper without that string is invisible here.
- It cannot verify a posture marker is TRUE. `# linear-filer: human-in-the-loop`
  on a nightly sweep passes this gate and is a lie the gate cannot see. It
  removes ambiguity, not the possibility of being wrong.
- It checks that the label is REFERENCED, never that it is attached to the
  create payload on every code path. Referencing `needs-triage` while omitting it
  from one branch passes.
- Tests and fixtures are skipped on purpose (they construct the mutation to
  assert on it), so a real filer disguised as a test file is not seen.

Exit codes follow the PostToolUse contract: 2 blocks and feeds stderr back, 0
passes. Any internal error exits 0 -- a broken linter must never wedge every
edit in the repo.
"""
from __future__ import annotations

import json
import os
import re
import sys

EXIT_PASS = 0
EXIT_BLOCK = 2

# The label an automated filer attaches. Must equal alert-to-linear.py's
# TRIAGE_LABEL and linear-triage-health.py's; test_triage_label_constant_matches
# already pins those two to each other, and this file's test pins it to them.
TRIAGE_LABEL = "needs-triage"

# The shape that says "this file creates Linear issues". Linear's mutation name
# is stable API surface, so matching it is matching the thing itself rather than
# a naming convention someone may rename.
FILER_PATTERN = re.compile(r"\bissueCreate\b")

# The explicit posture declaration. A reason is REQUIRED -- a bare marker is a
# mute exemption, and the point of the marker is that it says something.
# The reason's first character may not itself be a separator. Without that the
# alternation backtracks: on a bare `-- ` the separator matches ONE dash and the
# SECOND dash satisfies "a non-space reason", so a mute marker passed. Caught by
# test_a_bare_posture_marker_without_a_reason_is_still_blocked before it shipped.
HUMAN_MARKER = re.compile(
    r"linear-filer:\s*human-in-the-loop\s*[-:]+\s*([^\s\-:].*)", re.IGNORECASE)

# Last-resort per-file bypass, one marker, no stacking (skill-hook-pairing.md).
SKIP_MARKER = "linear-filer-lint-skip"

SCANNED_SUFFIXES = (".py", ".sh")

# Test files construct the mutation in order to ASSERT on it. Gating them would
# make the reference implementation's own suite unwritable.
TEST_HINTS = ("/tests/", "/test/", "test_", "test-", "_test.", "-test.")


def is_test_path(path: str) -> bool:
    """True for a fixture/suite path, which this gate deliberately ignores."""
    norm = path.replace(os.sep, "/")
    base = norm.rsplit("/", 1)[-1]
    if any(hint in norm for hint in ("/tests/", "/test/")):
        return True
    return any(base.startswith(h) or h in base
               for h in ("test_", "test-", "_test.", "-test."))


def in_scope(path: str) -> bool:
    """Only source files this repo actually writes filers in."""
    return bool(path) and path.endswith(SCANNED_SUFFIXES) and not is_test_path(path)


def creates_linear_issues(text: str) -> bool:
    """Does this file construct a Linear issue-create mutation?"""
    return bool(FILER_PATTERN.search(text))


def declares_posture(text: str) -> tuple:
    """(ok, how). The two accepted declarations, checked in no priority order.

    Returns the reason string for a human-in-the-loop marker so a caller can
    show it; an empty reason is treated as no declaration at all.
    """
    if SKIP_MARKER in text:
        return True, "bypass marker"
    match = HUMAN_MARKER.search(text)
    if match and match.group(1).strip():
        return True, "human-in-the-loop: " + match.group(1).strip()[:60]
    if TRIAGE_LABEL in text:
        return True, "marks its output with " + TRIAGE_LABEL
    return False, ""


def message(path: str) -> str:
    """The block text. It teaches the fix, because a gate that only says no
    gets worked around rather than satisfied."""
    return (
        f"linear-filer-label-lint: {path} creates Linear issues "
        f"(constructs `issueCreate`) but never declares whether a human decides "
        f"they should exist.\n\n"
        f"Automated inflow has to be a filterable set -- inflow here is automated "
        f"and outflow is manual, so an unmarked filer is indistinguishable from "
        f"backlog nobody can drain. Pick ONE and put it in the file:\n\n"
        f"  1. It files WITHOUT a human deciding each issue -> attach the label:\n"
        f"       label_ids = _label_ids(ln, team_id, [OWNER_LABEL, TRIAGE_LABEL])\n"
        f"       if label_ids:\n"
        f"           payload[\"labelIds\"] = label_ids\n"
        f"     (worked reference: q-system/.q-system/scripts/alert-to-linear.py)\n\n"
        f"  2. A human decides each issue -> declare it, with a reason:\n"
        f"       # linear-filer: human-in-the-loop -- <why a person decides each one>\n\n"
        f"Rule: .claude/rules/automated-filer-marking.md\n"
        f"Last resort, one file only: {SKIP_MARKER}"
    )


def check_text(path: str, text: str) -> tuple:
    """(exit_code, note). Pure, so the test drives this and not argv."""
    if not in_scope(path):
        return EXIT_PASS, "not a scanned path"
    if not creates_linear_issues(text):
        return EXIT_PASS, "not a filer"
    ok, how = declares_posture(text)
    if ok:
        return EXIT_PASS, how
    return EXIT_BLOCK, "undeclared filer"


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        # No parsable hook payload is not a violation. Fail open.
        return EXIT_PASS

    path = (payload.get("tool_input") or {}).get("file_path") or ""
    if not in_scope(path):
        return EXIT_PASS

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            text = handle.read()
    except OSError:
        # The file may have been moved between the write and this hook. Not a
        # violation, and a linter must never block on its own read failure.
        return EXIT_PASS

    code, _ = check_text(path, text)
    if code == EXIT_BLOCK:
        print(message(path), file=sys.stderr)
    return code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # never wedge every edit in the repo
        print(f"linear-filer-label-lint: internal error, passing ({exc})",
              file=sys.stderr)
        sys.exit(EXIT_PASS)
