#!/usr/bin/env python3
"""Describe how an instance's copy of a synced file is ahead of the skeleton's.

Called by kipi-update.sh's instance_ahead_scan for one file the rsync would
overwrite whose instance bytes are not any blob the skeleton ever shipped for
that path. The scan decides WHETHER a file is ahead (fleet_authored_blob, git
history); this script only says HOW, for the log line:

    .py    -> "+defs: name, name" (defs and classes the instance has and the
              skeleton lacks) or, when the names are identical, the hunk count
    other  -> "N hunks" from a unified diff

Pure: no git, no writes. On 2026-09-06 the three instance-ahead hits were an
engine (extra modules), a gate script (five extra defs, founder_typed_text
among them) and a calibrated word list (two removed entries): the first two
are the def line, the third is the hunk count, which is why both exist.

usage: kipi-update-instance-ahead.py <instance_file> <skeleton_file>
"""
import ast
import difflib
import sys


def top_level_names(text):
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
    return names


def hunk_count(instance_text, skeleton_text):
    diff = difflib.unified_diff(
        skeleton_text.splitlines(keepends=True),
        instance_text.splitlines(keepends=True),
        n=0,
    )
    return sum(1 for line in diff if line.startswith("@@"))


def describe(instance_path, skeleton_path):
    with open(instance_path, encoding="utf-8", errors="replace") as fh:
        instance_text = fh.read()
    with open(skeleton_path, encoding="utf-8", errors="replace") as fh:
        skeleton_text = fh.read()
    hunks = hunk_count(instance_text, skeleton_text)
    if instance_path.endswith(".py"):
        mine = top_level_names(instance_text)
        theirs = top_level_names(skeleton_text)
        if mine is not None and theirs is not None:
            extra = sorted(mine - theirs)
            if extra:
                return "+defs: " + ", ".join(extra)
    return f"{hunks} hunk{'' if hunks == 1 else 's'}"


def main(argv):
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    print(describe(argv[1], argv[2]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
