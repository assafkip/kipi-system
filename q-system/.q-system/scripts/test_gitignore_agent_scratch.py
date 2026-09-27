#!/usr/bin/env python3
"""The loop's agent-scratch files at the repo root must be un-stageable (ASK-922).

why this shape: the autonomous loop writes two kinds of transient file at the repo
root -- the refusal sentinels (`.sana-needs-scope`, `.sana-blocked-capability`) and
the per-issue PR body it feeds to `gh pr create` (`.pr-body-ask-<n>.md`). PR #141
closed the sentinel half after one was swept into a commit by `git add -A`; the
PR-body half was left uncovered (spillover sp-b2a5e5be), so the same `git add -A`
still commits it.

The assertion is made against the SHIPPED `.gitignore` in this checkout, resolved
through `git rev-parse --show-toplevel`, not a synthetic copy written by the test.
A copy would only prove the pattern I typed agrees with the pattern I typed; the
defect is in the file the repo actually ships, so that is the file consulted.

why the filenames are DERIVED and not typed (ASK-2133, from the PR #228 review):
the first version of this file hardcoded `.pr-body-ask-700.md`. No production
script emits that name, so the literal was a second source of truth for a value
`.gitignore` already owns: it agreed on the day it was written and would have gone
on asserting the old contract after the pattern moved. `.gitignore` documents its
own coupling -- each scratch stanza's comment ends "Asserted by <test>" -- so the
patterns this file guards are read back out of that attribution at run time, and
the sample paths are the patterns' own globs filled in. Rename the pattern and the
test follows it; delete it and the floor below fails instead of quietly asserting
nothing.

NEGATIVE SELF-TEST: the DoR asks for an anchored pattern (`/.pr-body-*.md`) rather
than a bare glob, because a bare glob would also swallow a legitimately-tracked
`.pr-body-*.md` anywhere in the tree. Anchoring is therefore a stated contract and
is NOT derived: `test_pattern_is_anchored_to_the_repo_root` asserts the leading `/`
itself, so un-anchoring the pattern goes RED rather than being read as the new
truth. A fix that ignores the name at every depth fails that test.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(subprocess.run(
    ["git", "-C", str(Path(__file__).resolve().parent), "rev-parse", "--show-toplevel"],
    capture_output=True, text=True, check=True).stdout.strip())

GITIGNORE = REPO / ".gitignore"

# This file's own name, as `.gitignore` spells it in its "Asserted by" back-reference.
SELF = Path(__file__).name

# The sibling test that owns the refusal-sentinel stanza. Those lines sit directly
# above the PR-body one, which is the whole reason this file re-checks them: an edit
# to one stanza can undo the other. Derived from the same back-reference so a
# renamed sentinel is followed rather than missed.
SENTINEL_OWNER = "test-worker-refusal.sh"

# Fills the `*` in a derived pattern. Only the glob hole is ours; the name and the
# extension come from `.gitignore`. `ask-700` is the issue whose run put a real
# `.pr-body-ask-700.md` on disk, so the sample keeps the shape the loop writes.
GLOB_FILL = "ask-700"


def _attributed_patterns(owner):
    """Every `.gitignore` pattern whose own comment stanza names `owner`.

    A stanza is a run of comment lines plus the pattern lines directly under it. A
    blank line ends a stanza, and so does a comment line that follows a pattern --
    without that second rule the PR-body stanza (which starts with a bare `#`
    immediately after the sentinel patterns) would inherit the sentinel stanza's
    attribution and both sets would collapse into one.
    """
    found = []
    stanza = []
    prev_was_pattern = False
    for raw in GITIGNORE.read_text().splitlines():
        line = raw.strip()
        if not line:
            stanza = []
            prev_was_pattern = False
        elif line.startswith("#"):
            if prev_was_pattern:
                stanza = []
            stanza.append(line)
            prev_was_pattern = False
        else:
            if any(owner in comment for comment in stanza):
                found.append(line)
            prev_was_pattern = True
    return found


def _sample_path(pattern, prefix=""):
    """A concrete path the pattern claims, optionally under a subdirectory."""
    rel = pattern[1:] if pattern.startswith("/") else pattern
    return f"{prefix}{rel.replace('*', GLOB_FILL)}"


OWNED = _attributed_patterns(SELF)
SENTINELS = _attributed_patterns(SENTINEL_OWNER)


def _check_ignore(relpath):
    """(exit code, -v output). check-ignore does not require the path to exist."""
    p = subprocess.run(["git", "-C", str(REPO), "check-ignore", "-v", "--", relpath],
                       capture_output=True, text=True)
    return p.returncode, p.stdout.strip()


def test_the_derivation_has_a_floor():
    """An empty parse would turn every assertion below into a silent no-op.

    This is the drift detector the hardcoded literal could not be: if the PR-body
    stanza is deleted, renamed away from its back-reference, or split by a blank
    line from the pattern it documents, the suite fails here instead of passing
    while guarding nothing.
    """
    assert OWNED, (
        f"no pattern in {GITIGNORE} is attributed to `{SELF}`. Either the anchored "
        "PR-body ignore was removed, or its comment stanza lost the "
        f"'Asserted by {SELF}' back-reference this test derives from. Both mean the "
        "agent scratch is unguarded, which is what this file exists to catch.")
    assert SENTINELS, (
        f"no pattern in {GITIGNORE} is attributed to `{SENTINEL_OWNER}`, so the "
        "refusal-sentinel stanza this one sits next to cannot be re-checked.")


def test_pr_body_scratch_is_ignored():
    """RED before the .gitignore edit: exit 1, no output."""
    for pattern in OWNED:
        scratch = _sample_path(pattern)
        rc, out = _check_ignore(scratch)
        assert rc == 0, (
            f"`{scratch}` is not ignored, so a broad `git add -A` in an agent worktree "
            "stages it and the loop commits its own PR-body scratch. Add an anchored "
            f"`{pattern}` next to the sentinel entries in .gitignore.")
        assert ".gitignore" in out, f"expected .gitignore to be the source: {out!r}"


def test_the_sentinels_it_sits_next_to_are_still_ignored():
    """PR #141's fix must survive this change; an edit near it could undo it."""
    for pattern in SENTINELS:
        name = _sample_path(pattern)
        rc, out = _check_ignore(name)
        assert rc == 0, f"`{name}` stopped being ignored: {out!r}"


def test_pattern_is_anchored_to_the_repo_root():
    """A bare `.pr-body-*.md` glob would ignore the name at every depth.

    The scratch file only ever lands at the root -- that is where the loop writes it
    and where `gh pr create` is run -- so a tree-wide ignore buys nothing and could
    silently hide a real file someone puts under a subdirectory later.

    The leading `/` is asserted rather than derived on purpose. Reading anchoring out
    of the pattern would make un-anchoring it self-approving: the derivation would
    simply stop expecting an anchor and the suite would stay green.
    """
    for pattern in OWNED:
        assert pattern.startswith("/"), (
            f"`{pattern}` is not anchored to the repo root, so it ignores that name at "
            "every depth and can hide a real file added under a subdirectory later.")
        nested = _sample_path(pattern, prefix="q-system/.q-system/scripts/")
        rc, out = _check_ignore(nested)
        assert rc != 0, (
            f"`{nested}` is ignored too, so the pattern is not anchored to the repo "
            f"root: {out!r}")


def test_no_scratch_file_is_already_tracked():
    """An ignore does nothing for a path git is already tracking."""
    for pattern in OWNED:
        tracked = subprocess.run(
            ["git", "-C", str(REPO), "ls-files", "--", pattern.lstrip("/")],
            capture_output=True, text=True, check=True).stdout.strip()
        assert not tracked, (
            f"scratch files matching `{pattern}` are already committed, the ignore "
            f"will not cover them:\n{tracked}")


def test_a_real_root_file_is_not_ignored():
    """Guards the opposite bug: a pattern broad enough to swallow the repo."""
    rc, out = _check_ignore("README.md")
    assert rc != 0, f"README.md became ignored: {out!r}"


if __name__ == "__main__":
    # The capability-gate manifest runner is `python3 <file>` (capability-gate.py:127),
    # and a pytest module with no __main__ collects nothing under it and exits 0 --
    # reported coverage that never ran (sp-bbdcf57b). This file runs itself.
    raise SystemExit(subprocess.call(
        [sys.executable, "-m", "pytest", "-q", os.path.abspath(__file__)]))
