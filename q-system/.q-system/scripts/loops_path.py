#!/usr/bin/env python3
"""One place that knows where open-loops.json lives.

Scar (ASK Consulting, found 2026-08-08): a warm inbound from a prospect's Head
of Product sat unanswered for 46 days. It was not forgotten by a human. It was
recorded correctly, as L-2026-06-08-001 in `q-consult/output/open-loops.json`,
and then read by nobody, because four readers resolved three different paths
and none of them was the file with the data in it:

    writer   loop-tracker.py        QROOT/output/open-loops.json
    hook     session-start.py       QROOT/output/open-loops.json
    display  statusline.sh          QROOT/output/  AND  QROOT/memory/
    fleet    fleet-board-refresh.py QROOT/memory/open-loops.json

`load_open_loops()` returned None for nine consecutive weeks and every reader
treated that exactly like "no open loops". Two other warm leads were in the same
file. Nobody was told about any of them.

Two rules, and the second is the one that actually failed:

1. ONE resolver. Readers ask this module; they do not build paths.
2. MISSING IS NOT EMPTY. `resolve()` returns a status, and a caller that cannot
   find the file must say so out loud. A monitor that renders "cannot read" and
   "nothing to report" identically is not a monitor, it is a blindfold with a
   green light on it.

Search order is deliberate: the instance content directory first, because that
is where the writer has actually been putting the file in practice, then the
two historical locations, so an instance that already migrated keeps working.
"""
from __future__ import annotations

import os
from pathlib import Path

# Relative to QROOT's PARENT (the repo root), then relative to QROOT itself.
# The first hit wins, so order is the migration order, not preference.
CANDIDATES = (
    ("../q-consult/output/open-loops.json", "instance-output"),
    ("output/open-loops.json", "qroot-output"),
    ("memory/open-loops.json", "qroot-memory"),
)

FOUND = "found"
MISSING = "missing"


def candidate_paths(qroot) -> list[Path]:
    """Every place the file could legitimately be, in search order."""
    qroot = Path(qroot)
    return [(qroot / rel).resolve() for rel, _ in CANDIDATES]


def resolve(qroot) -> tuple[Path | None, str]:
    """(path, status). status is FOUND or MISSING -- never a silent None."""
    for path in candidate_paths(qroot):
        if path.exists():
            return path, FOUND
    return None, MISSING


def describe_missing(qroot) -> str:
    """What a reader should SAY when it cannot find the file.

    Deliberately not silent and deliberately not 'no open loops'. Collapsing
    those two is the whole defect.
    """
    tried = "\n".join(f"    {p}" for p in candidate_paths(qroot))
    return ("open-loops.json NOT FOUND. This is not the same as having no open "
            "loops: the loop ledger cannot be read at all, so any follow-up "
            "recorded in it is invisible right now. Looked in:\n" + tried)


def load(qroot):
    """(loops, status). Callers branch on status; they never guess from [].

    A malformed file is MISSING too. A ledger that cannot be parsed tells you
    nothing, and pretending it said "empty" is the same lie in a new costume.
    """
    import json

    path, status = resolve(qroot)
    if status != FOUND:
        return [], MISSING
    try:
        with open(path) as fh:
            data = json.load(fh)
    except (ValueError, OSError):
        return [], MISSING
    loops = data.get("loops", []) if isinstance(data, dict) else data
    return loops, FOUND


def open_loops(qroot):
    """(open loops only, status)."""
    loops, status = load(qroot)
    return [l for l in loops if l.get("status") == "open"], status


if __name__ == "__main__":
    root = os.environ.get("QROOT") or Path(__file__).resolve().parents[2]
    found, st = resolve(root)
    loops, _ = open_loops(root)
    print(f"qroot:  {root}")
    print(f"status: {st}")
    print(f"path:   {found}")
    if st == FOUND:
        print(f"open:   {len(loops)}")
        for l in loops:
            print(f"   {l.get('id')}  {l.get('target')}  opened {l.get('opened')}")
    else:
        print(describe_missing(root))
