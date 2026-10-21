#!/usr/bin/env python3
"""Contract test for the permanence claim `linear-sync.py` builds its dedup on
(ASK-1249).

WHY THIS EXISTS: the module docstring used to say Linear delete and archive
were refused by a PreToolUse guard, naming a tool prefix. Measured 2026-09-04,
that guard matched a different prefix, so the sentence asserted a protection
nobody was getting, stored where nothing checked it. The dedup design is sound
on its own; its stated justification was not.

The fix is not a better sentence. The claim the design actually rests on is
narrower and checkable from this repo: THIS FILE cannot take back what it
creates. So this test:

  1. derives every GraphQL mutation root field from linear-sync.py's source and
     fails if one of them deletes or archives (floor: the derivation must find
     issueCreate, or a regex that stopped matching reads as a clean pass);
  2. fails if linear-sync.py restates a guard's coverage again -- a literal MCP
     tool prefix or a hook credited with a block. Whether an agent is refused a
     delete belongs to that guard's own tests (ASK-1144), not to this file;
  3. fails if the docstring stops naming this test, so the claim and the check
     that holds it cannot drift apart.

NO LIVE LINEAR, NO NETWORK. The module is read as text; nothing is imported
and nothing is called.

NEGATIVE SELF-TEST, built in: check 1 is run against a planted source carrying
an `issueArchive` mutation and must flag it. Check 2 is checkable against the
pre-fix file:

  KIPI_TEST_LINEAR_SYNC_REF=origin/main  -> the restated-claim case must FAIL
  (unset)                                -> everything passes
"""
import os
import pathlib
import re
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
_REF = os.environ.get("KIPI_TEST_LINEAR_SYNC_REF", "").strip()

FAILURES = []
PASSES = []

# A root field whose name carries one of these removes or hides a Linear object.
REMOVING_FIELD_RE = re.compile(r"delete|archive|trash|remove|purge", re.I)

# `mutation`, optional operation name, optional variable list, then the first
# field inside the selection set. Anchored on the `{` right after the variable
# list so prose that merely says "mutation" never matches.
MUTATION_ROOT_RE = re.compile(r"\bmutation\s*(?:\w+\s*)?(?:\([^)]*\))?\s*\{\s*(\w+)")

# The shapes the pre-ASK-1249 text used to credit a guard with a block.
RESTATED_GUARD_RE = re.compile(r"mcp__\w*__|destructive-op|hook-blocked", re.I)


def ok(msg):
    PASSES.append(msg)
    print(f"  PASS {msg}")


def fail(msg):
    FAILURES.append(msg)
    print(f"  FAIL {msg}")


def read_target_source() -> str:
    """linear-sync.py from the working tree, or from a git ref for the self-test.
    Read-only `git show`; the working tree is never touched."""
    if not _REF:
        return (HERE / "linear-sync.py").read_text()
    blob = subprocess.run(
        ["git", "-C", str(HERE.parents[2]), "show",
         f"{_REF}:q-system/.q-system/scripts/linear-sync.py"],
        capture_output=True, text=True)
    if blob.returncode != 0:
        print(f"FAIL: cannot read linear-sync.py at ref {_REF}: {blob.stderr.strip()}")
        sys.exit(1)
    print(f"module under test: ref {_REF} ({len(blob.stdout.splitlines())} lines)")
    return blob.stdout


def mutation_roots(source: str) -> list:
    return MUTATION_ROOT_RE.findall(source)


def module_docstring(source: str) -> str:
    match = re.match(r'\s*(?:#![^\n]*\n)?\s*"""(.*?)"""', source, re.S)
    return match.group(1) if match else ""


def check_derivation_can_fail():
    planted = 'X = """\nmutation($id: String!) {\n  issueArchive(id: $id) { success }\n}\n"""'
    flagged = [f for f in mutation_roots(planted) if REMOVING_FIELD_RE.search(f)]
    if flagged == ["issueArchive"]:
        ok("the derivation flags a planted issueArchive mutation")
    else:
        fail(f"the derivation missed a planted issueArchive mutation, got {flagged}; "
             "check 1 below cannot fail and proves nothing")


def check_no_removing_mutation(source: str):
    roots = mutation_roots(source)
    if "issueCreate" not in roots:
        fail(f"derivation floor: issueCreate not found among mutations {roots}; the "
             "regex no longer reads this file, so an empty result would pass silently")
        return
    removing = [f for f in roots if REMOVING_FIELD_RE.search(f)]
    if removing:
        fail(f"linear-sync.py sends a removing mutation {removing}; the docstring's "
             "claim that this file cannot take back a create is now false")
    else:
        ok(f"no delete or archive among {len(roots)} derived mutations {sorted(set(roots))}")


def check_no_restated_guard(source: str):
    hits = sorted({m.group(0) for m in RESTATED_GUARD_RE.finditer(source)})
    if hits:
        fail(f"linear-sync.py restates a guard's coverage {hits}; that claim belongs "
             "to the guard's own tests (ASK-1144) and was false here once already")
    else:
        ok("linear-sync.py credits no guard with a block")


def check_docstring_names_this_test(source: str):
    if pathlib.Path(__file__).name in module_docstring(source):
        ok("the module docstring names the test that holds its permanence claim")
    else:
        fail(f"the module docstring does not name {pathlib.Path(__file__).name}, so "
             "its permanence claim has no visible check behind it")


def main():
    source = read_target_source()
    check_derivation_can_fail()
    check_no_removing_mutation(source)
    check_no_restated_guard(source)
    check_docstring_names_this_test(source)
    print(f"\n== {len(PASSES)} passed, {len(FAILURES)} failed")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
