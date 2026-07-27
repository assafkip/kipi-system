#!/usr/bin/env python3
"""The ONE mapping from an autonomous-worker branch name to its Linear issue id.

`linear-worker.sh:192` mints `sana/$(lowercase ISSUE)` for every autonomous
Linear run, so the branch -- not the PR body, which is prose an agent writes --
is the reliable carrier of the issue id.

Two things need that mapping, and they must not be allowed to disagree:

  producer  `issue_runner.py::cmd_close` stamps `linear_issue_id` onto the
            receipt, so a closeout run on a Linear branch is attributable to
            the Linear issue it closed.
  reader    `q-system/.q-system/scripts/pr-receipt-gate.py` refuses to let a PR
            merge when its branch maps to an id no receipt carries.

Scar (ASK-210, review round 3): the gate shipped with its own private copy of
this regex while the producer wrote no Linear id at all. The gate therefore
blocked 100% of the population it targeted, and the remediation it printed --
a complete, correct kipi-dsse closeout -- could not clear it. A convention with
two implementations is a convention with two meanings. This module is the one.

It lives in the plugin rather than in `q-system/.q-system/scripts/` because
`plugins/*/` is what `kipi update` propagates to instances; a fleet instance
running kipi-dsse gets the producer and this module together.
"""

from __future__ import annotations

import re
import subprocess
from typing import Optional

# A trailing slug is allowed (`sana/ask-210-receipt-gate`); the number is the id.
BRANCH_RE = re.compile(r"^sana/ask-(?P<num>\d+)(?:[-_/].*)?$", re.IGNORECASE)


def issue_id_for_branch(branch: Optional[str]) -> Optional[str]:
    """`ASK-<n>` for an autonomous-worker branch, else None (not Linear work).

    None is "this branch carries no Linear issue", NOT "lookup failed" -- human
    and chore branches legitimately map to nothing.
    """
    if not branch:
        return None
    match = BRANCH_RE.match(branch.strip())
    if not match:
        return None
    # The raw digits, not int(): a Linear identifier is the literal token, and
    # normalising would make ASK-007 and ASK-7 the same id when Linear says
    # they are not.
    return f"ASK-{match.group('num')}"


def current_branch(cwd=None) -> Optional[str]:
    """The checked-out branch name, or None on detached HEAD / not a git dir.

    Detached HEAD returns None rather than the literal "HEAD" so a caller
    cannot mistake the sentinel for a branch name.
    """
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(cwd) if cwd is not None else None,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    name = out.stdout.strip()
    if not name or name == "HEAD":
        return None
    return name
